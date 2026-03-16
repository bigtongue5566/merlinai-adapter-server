import json
import sys
from typing import Any

from loguru import logger

from .config import LOG_BACKUP_COUNT, LOG_FILE_PATH, LOG_LEVEL_NAME, LOG_MAX_BYTES, LOG_TO_FILE
from .request_logging import get_attempt, get_request_id


def configure_logger() -> None:
    logger.remove()
    console_format = (
        "<green>[proxy]</green> "
        "<cyan>{time:YYYY-MM-DD HH:mm:ss}</cyan> "
        "<level>{level: <8}</level> "
        "<level>{message}</level>"
    )
    file_format = "[proxy] {time:YYYY-MM-DDTHH:mm:ssZZ} {level} {message}"
    logger.add(
        sys.stderr,
        level=LOG_LEVEL_NAME,
        colorize=True,
        format=console_format,
        backtrace=False,
        diagnose=False,
    )

    if LOG_TO_FILE:
        LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            LOG_FILE_PATH,
            level=LOG_LEVEL_NAME,
            format=file_format,
            rotation=LOG_MAX_BYTES,
            retention=LOG_BACKUP_COUNT,
            encoding="utf-8",
            backtrace=False,
            diagnose=False,
        )


def log_debug_payload(label: str, payload: Any) -> None:
    if isinstance(payload, dict):
        request_id = get_request_id()
        attempt = get_attempt()
        payload = dict(payload)
        if request_id and "request_id" not in payload:
            payload["request_id"] = request_id
        if attempt and "attempt" not in payload:
            payload["attempt"] = attempt
    logger.opt(lazy=True).debug(
        "{label}:\n{body}",
        label=lambda: label,
        body=lambda: json.dumps(payload, ensure_ascii=False, indent=2, default=str),
    )
