import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

load_dotenv()

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: Any = None) -> Any:
    return os.getenv(name, default)


class AdapterSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    merlin_api_url: str = "www.getmerlin.in"
    merlin_path: str = "/arcane/api/v2/thread/unified"
    firebase_auth_host: str = "identitytoolkit.googleapis.com"
    firebase_auth_path: str = "/v1/accounts:signInWithPassword"
    firebase_refresh_host: str = "securetoken.googleapis.com"
    firebase_refresh_path: str = "/v1/token"
    firebase_api_key: str = "AIzaSyAvCgtQ4XbmlQGIynDT-v_M8eLaXrKmtiM"
    merlin_email: str | None = None
    merlin_password: str | None = None
    merlin_version: str = "iframe-merlin-7.5.19"
    adapter_api_key: str = "sk-123"
    log_level_name: str = "INFO"
    log_to_file: bool = True
    project_dir: Path = PROJECT_DIR
    log_file_path: Path = Field(default_factory=lambda: PROJECT_DIR / "logs" / "adapter.log")
    log_max_bytes: int = 1_048_576
    log_backup_count: int = 3
    token_refresh_buffer_seconds: int = 60
    auth_request_timeout_seconds: float = 20
    merlin_request_timeout_seconds: float = 45
    tool_prompt_max_messages: int = 5
    tool_description_max_chars: int = 160
    tool_message_max_chars: int = 1200
    tool_system_max_chars: int | None = None
    tool_tool_result_max_chars: int | None = None
    tool_tool_arguments_max_chars: int | None = None
    tool_parameter_description_max_chars: int | None = None

    @field_validator("log_level_name", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> str:
        return str(value or "INFO").upper()

    @field_validator("log_to_file", mode="before")
    @classmethod
    def _parse_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @field_validator("auth_request_timeout_seconds", "merlin_request_timeout_seconds")
    @classmethod
    def _clamp_timeout(cls, value: float) -> float:
        return max(value, 1.0)

    @field_validator(
        "tool_description_max_chars",
        "tool_message_max_chars",
        "tool_system_max_chars",
        "tool_tool_result_max_chars",
        "tool_tool_arguments_max_chars",
        "tool_parameter_description_max_chars",
        mode="after",
    )
    @classmethod
    def _clamp_non_negative_optional(cls, value: int | None) -> int | None:
        return max(value, 0) if value is not None else None

    @field_validator("tool_prompt_max_messages", "log_max_bytes", "log_backup_count", "token_refresh_buffer_seconds")
    @classmethod
    def _clamp_positive_int(cls, value: int) -> int:
        return max(value, 1)

    @model_validator(mode="after")
    def _fill_dependent_defaults(self) -> "AdapterSettings":
        if self.tool_system_max_chars is None:
            self.tool_system_max_chars = max(self.tool_message_max_chars, 12000)
        if self.tool_tool_result_max_chars is None:
            self.tool_tool_result_max_chars = max(self.tool_message_max_chars, 6000)
        if self.tool_tool_arguments_max_chars is None:
            self.tool_tool_arguments_max_chars = max(self.tool_message_max_chars, 4000)
        if self.tool_parameter_description_max_chars is None:
            self.tool_parameter_description_max_chars = max(self.tool_description_max_chars, 300)
        return self


SETTINGS = AdapterSettings.model_validate(
    {
        "firebase_api_key": _env("MERLIN_FIREBASE_API_KEY", AdapterSettings.model_fields["firebase_api_key"].default),
        "merlin_email": _env("MERLIN_EMAIL"),
        "merlin_password": _env("MERLIN_PASSWORD"),
        "merlin_version": _env("MERLIN_VERSION", AdapterSettings.model_fields["merlin_version"].default),
        "adapter_api_key": _env("ADAPTER_API_KEY", AdapterSettings.model_fields["adapter_api_key"].default),
        "log_level_name": _env("LOG_LEVEL", AdapterSettings.model_fields["log_level_name"].default),
        "log_to_file": _env("LOG_TO_FILE", AdapterSettings.model_fields["log_to_file"].default),
        "auth_request_timeout_seconds": _env(
            "AUTH_REQUEST_TIMEOUT_SECONDS",
            AdapterSettings.model_fields["auth_request_timeout_seconds"].default,
        ),
        "merlin_request_timeout_seconds": _env(
            "MERLIN_REQUEST_TIMEOUT_SECONDS",
            AdapterSettings.model_fields["merlin_request_timeout_seconds"].default,
        ),
        "tool_prompt_max_messages": _env(
            "TOOL_PROMPT_MAX_MESSAGES",
            AdapterSettings.model_fields["tool_prompt_max_messages"].default,
        ),
        "tool_description_max_chars": _env(
            "TOOL_DESCRIPTION_MAX_CHARS",
            AdapterSettings.model_fields["tool_description_max_chars"].default,
        ),
        "tool_message_max_chars": _env(
            "TOOL_MESSAGE_MAX_CHARS",
            AdapterSettings.model_fields["tool_message_max_chars"].default,
        ),
        "tool_system_max_chars": _env("TOOL_SYSTEM_MAX_CHARS"),
        "tool_tool_result_max_chars": _env("TOOL_TOOL_RESULT_MAX_CHARS"),
        "tool_tool_arguments_max_chars": _env("TOOL_TOOL_ARGUMENTS_MAX_CHARS"),
        "tool_parameter_description_max_chars": _env("TOOL_PARAMETER_DESCRIPTION_MAX_CHARS"),
    }
)

MERLIN_API_URL = SETTINGS.merlin_api_url
MERLIN_PATH = SETTINGS.merlin_path
FIREBASE_AUTH_HOST = SETTINGS.firebase_auth_host
FIREBASE_AUTH_PATH = SETTINGS.firebase_auth_path
FIREBASE_REFRESH_HOST = SETTINGS.firebase_refresh_host
FIREBASE_REFRESH_PATH = SETTINGS.firebase_refresh_path
FIREBASE_API_KEY = SETTINGS.firebase_api_key
MERLIN_EMAIL = SETTINGS.merlin_email
MERLIN_PASSWORD = SETTINGS.merlin_password
MERLIN_VERSION = SETTINGS.merlin_version
ADAPTER_API_KEY = SETTINGS.adapter_api_key
LOG_LEVEL_NAME = SETTINGS.log_level_name
LOG_TO_FILE = SETTINGS.log_to_file
LOG_FILE_PATH = SETTINGS.log_file_path
LOG_MAX_BYTES = SETTINGS.log_max_bytes
LOG_BACKUP_COUNT = SETTINGS.log_backup_count
TOKEN_REFRESH_BUFFER_SECONDS = SETTINGS.token_refresh_buffer_seconds
AUTH_REQUEST_TIMEOUT_SECONDS = SETTINGS.auth_request_timeout_seconds
MERLIN_REQUEST_TIMEOUT_SECONDS = SETTINGS.merlin_request_timeout_seconds
TOOL_PROMPT_MAX_MESSAGES = SETTINGS.tool_prompt_max_messages
TOOL_DESCRIPTION_MAX_CHARS = SETTINGS.tool_description_max_chars
TOOL_MESSAGE_MAX_CHARS = SETTINGS.tool_message_max_chars
TOOL_SYSTEM_MAX_CHARS = SETTINGS.tool_system_max_chars
TOOL_TOOL_RESULT_MAX_CHARS = SETTINGS.tool_tool_result_max_chars
TOOL_TOOL_ARGUMENTS_MAX_CHARS = SETTINGS.tool_tool_arguments_max_chars
TOOL_PARAMETER_DESCRIPTION_MAX_CHARS = SETTINGS.tool_parameter_description_max_chars
