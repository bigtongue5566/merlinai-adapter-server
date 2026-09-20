"""Bound a logical completion, including correction attempts and streaming reads."""

import socket
import time
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event, Lock, Timer

from fastapi import HTTPException


active_deadline: ContextVar[float | None] = ContextVar("merlin_deadline", default=None)


class RequestBudget:
    def __init__(self, seconds: float, max_bytes: int):
        self.deadline = time.monotonic() + seconds
        self.max_bytes = max_bytes
        self.bytes_read = 0
        self._cancelled = Event()
        self._expired = Event()
        self._lock = Lock()
        self._interrupt = None

    def remaining(self) -> float:
        if self._cancelled.is_set():
            raise HTTPException(499, "Client disconnected from the completion")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or self._expired.is_set():
            raise HTTPException(504, "Merlin completion exceeded its overall time limit")
        return remaining

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            interrupt = self._interrupt
        if interrupt is not None:
            interrupt()

    def observe(self, raw_chunk: str) -> None:
        self.remaining()
        self.bytes_read += len(raw_chunk.encode("utf-8"))
        if self.bytes_read > self.max_bytes:
            raise HTTPException(502, "Merlin completion exceeded its response size limit")

    @contextmanager
    def opening(self):
        self.remaining()
        token = active_deadline.set(self.deadline)
        try:
            yield
            self.remaining()
        finally:
            active_deadline.reset(token)

    @contextmanager
    def reading(self, conn, response=None):
        # Closing from another thread alone may not interrupt a blocking read;
        # shutdown the socket first. No response bodies or credentials are kept.
        sock = conn.sock
        if sock is None and response is not None:
            # HTTPConnection detaches a Connection: close socket after headers;
            # HTTPResponse still owns it while the body is being read.
            sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        def interrupt():
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            conn.close()

        def expire():
            self._expired.set()
            interrupt()

        timer = Timer(self.remaining(), expire)
        timer.daemon = True
        with self._lock:
            self._interrupt = interrupt
        timer.start()
        try:
            self.remaining()
            yield
            self.remaining()
        except Exception:
            self.remaining()  # An interrupted read reports the actual deadline cause.
            raise
        finally:
            timer.cancel()
            with self._lock:
                self._interrupt = None


class ManagedStream:
    """Own a pre-opened connection even if iteration never starts."""

    def __init__(self, iterator, conn, budget: RequestBudget):
        self.iterator, self.conn, self.budget = iterator, conn, budget

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.iterator)

    def close(self):
        self.budget.cancel()
        self.conn.close()
        # ASGI cancellation can arrive while a worker is inside next(). The
        # interrupted read will unwind the generator's own finally block.
        if not self.iterator.gi_running:
            self.iterator.close()
