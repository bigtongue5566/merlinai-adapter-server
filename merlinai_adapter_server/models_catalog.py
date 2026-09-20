from datetime import datetime
from typing import Any, Dict

from .schemas import ModelLimits, OpenAIModel, OpenAIModelsResponse

# Active textLLMs (archived=false), verified 2026-09-17 against Merlin's
# https://cdn.jsdelivr.net/gh/foyer-work/cdn-files@latest/merlin_constants.json
# Configured capacities from the first-party models.dev snapshot (2026-09-20).
# These are adapter metadata/policy, not verified Merlin transport capabilities.
MODEL_LIMITS = {
    'claude-opus-5': ModelLimits(context=1_000_000, output=128_000),
    'claude-sonnet-5': ModelLimits(context=1_000_000, output=128_000),
    'deepseek-v4-flash': ModelLimits(context=1_000_000, output=384_000),
    'deepseek-v4-pro': ModelLimits(context=1_000_000, output=384_000),
    'gemini-3.1-flash-lite': ModelLimits(context=1_048_576, output=65_536),
    'gemini-3.8-flash': ModelLimits(context=1_048_576, output=65_536),
    'glm-5.3': ModelLimits(context=1_000_000, output=131_072),
    'glm-5.3-flash': ModelLimits(context=1_000_000, output=131_072),
    'gpt-5.5': ModelLimits(context=1_050_000, input=922_000, output=128_000),
    'gpt-5.6-luna': ModelLimits(context=1_050_000, input=922_000, output=128_000),
    'gpt-5.6-sol': ModelLimits(context=1_050_000, input=922_000, output=128_000),
    'gpt-5.6-terra': ModelLimits(context=1_050_000, input=922_000, output=128_000),
    'gpt-6-astra': ModelLimits(context=1_050_000, input=922_000, output=128_000),
    'grok-4.6': ModelLimits(context=500_000, output=500_000),
    'kimi-k3': ModelLimits(context=1_048_576, output=131_072),
    'minimax-m3': ModelLimits(context=1_048_576, output=512_000),
    'qwen-3.8-max': ModelLimits(context=1_000_000, output=131_072),
}
MODEL_MAX_OUTPUT_TOKENS = {model: limits.output for model, limits in MODEL_LIMITS.items()}
SUPPORTED_MODELS = tuple(MODEL_LIMITS)
UNKNOWN_MODEL_DEFAULT_MAX_TOKENS = 10_000
# Merlin Qwen route: repeated 2026-09-20 probes reject 16384 and accept 16385.
# This is transport compatibility, not the number of answer tokens required.
MODEL_MIN_OUTPUT_TOKENS = {"qwen-3.8-max": 16_385}


def resolve_max_tokens(model: str, requested: int | None) -> int:
    """Use model defaults for omitted or transport-incompatible client budgets."""
    from fastapi import HTTPException

    ceiling = MODEL_MAX_OUTPUT_TOKENS.get(model)
    if requested is None:
        return ceiling if ceiling is not None else UNKNOWN_MODEL_DEFAULT_MAX_TOKENS
    if type(requested) is not int or requested <= 0:
        raise HTTPException(422, "max_tokens must be a positive integer")
    minimum = MODEL_MIN_OUTPUT_TOKENS.get(model, 1)
    if requested < minimum:
        # Some clients supply a small generic budget even for reasoning models.
        # Use this model's configured default instead of rejecting those requests.
        return ceiling if ceiling is not None else minimum
    if ceiling is not None and requested > ceiling:
        raise HTTPException(422, f"max_tokens exceeds the configured output limit for {model}: {ceiling}")
    return requested



def build_models_response() -> Dict[str, Any]:
    created = int(datetime.now().timestamp())
    response = OpenAIModelsResponse(
        data=[
            OpenAIModel(
                id=model,
                created=created,
                limit=MODEL_LIMITS[model],
            )
            for model in SUPPORTED_MODELS
        ],
    )
    return response.model_dump(exclude_none=True)
