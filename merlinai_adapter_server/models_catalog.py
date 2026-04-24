from datetime import datetime
from typing import Any, Dict

from .schemas import OpenAIModel, OpenAIModelsResponse

SUPPORTED_MODELS = (
    "gpt-5.4",
    "grok-4.1-fast",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro",
    "claude-4.6-sonnet",
    "claude-4.6-opus",
    "glm-5",
    "minimax-m2.5",
)


def build_models_response() -> Dict[str, Any]:
    created = int(datetime.now().timestamp())
    response = OpenAIModelsResponse(
        data=[
            OpenAIModel(
                id=model,
                created=created,
            )
            for model in SUPPORTED_MODELS
        ],
    )
    return response.model_dump()
