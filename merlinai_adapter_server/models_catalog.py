from datetime import datetime
from typing import Any, Dict

from .schemas import OpenAIModel, OpenAIModelsResponse

SUPPORTED_MODELS = (
    "claude-4.6-sonnet",
    "claude-4.8-opus",
    "deepseek-v4-pro",
    "gemini-3.5-flash",
    "glm-5.1",
    "gpt-5.5",
    "grok-4.3",
    "kimi-k2.6",
    "minimax-m2.7",
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
