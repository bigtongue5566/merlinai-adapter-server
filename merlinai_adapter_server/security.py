from typing import Optional

from fastapi import HTTPException

from .config import ADAPTER_API_KEY


def verify_adapter_api_key(authorization: Optional[str]) -> None:
    expected_header = f"Bearer {ADAPTER_API_KEY}"
    if authorization != expected_header:
        raise HTTPException(status_code=401, detail="Invalid or missing adapter API key")
