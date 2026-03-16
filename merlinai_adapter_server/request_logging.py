from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
_attempt_var: ContextVar[Optional[str]] = ContextVar("attempt", default=None)


def set_request_log_context(*, request_id: str, attempt: Optional[str] = None) -> None:
    _request_id_var.set(request_id)
    _attempt_var.set(attempt)


def set_attempt_context(attempt: Optional[str]) -> None:
    _attempt_var.set(attempt)


def clear_request_log_context() -> None:
    _request_id_var.set(None)
    _attempt_var.set(None)


def get_request_id() -> Optional[str]:
    return _request_id_var.get()


def get_attempt() -> Optional[str]:
    return _attempt_var.get()
