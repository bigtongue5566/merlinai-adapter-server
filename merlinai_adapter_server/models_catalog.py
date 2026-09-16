from datetime import datetime
from typing import Any, Dict

from .schemas import OpenAIModel, OpenAIModelsResponse

# Active textLLMs (archived=false), verified 2026-09-17 against Merlin's
# https://cdn.jsdelivr.net/gh/foyer-work/cdn-files@latest/merlin_constants.json
SUPPORTED_MODELS = (
    "claude-opus-5",
    "claude-sonnet-5",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "glm-5.3",
    "glm-5.3-flash",
    "gpt-5.5",
    "gpt-5.6-luna",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-6-astra",
    "grok-4.6",
    "kimi-k3",
    "minimax-m3",
    "qwen-3.8-max",
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
