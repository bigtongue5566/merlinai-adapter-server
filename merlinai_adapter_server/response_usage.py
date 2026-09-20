"""One token-accounting contract for diagnostics, retries and OpenAI responses."""

from typing import Any


def token_counts(usage: Any) -> dict[str, int]:
    raw = usage.get("tokens", usage) if isinstance(usage, dict) else {}
    if not isinstance(raw, dict):
        return {}
    result = {}
    for name, alias in (("input", "prompt"), ("output", "completion"), ("reasoning", "reasoning")):
        value = raw.get(name, raw.get(alias))
        if type(value) is int and value >= 0:
            result[name] = value
    return result


def sum_usage(attempts: list[dict | None]) -> dict | None:
    if not any(isinstance(usage, dict) for usage in attempts):
        return None
    counts = [token_counts(usage) for usage in attempts]
    totals = {key: sum(count.get(key, 0) for count in counts) for key in ("input", "output")}
    # Never claim complete reasoning accounting if an attempt omitted it.
    if all("reasoning" in count for count in counts):
        totals["reasoning"] = sum(count["reasoning"] for count in counts)
    return {"tokens": totals}


def openai_usage(usage: Any) -> dict:
    counts = token_counts(usage)
    prompt, completion = counts.get("input", 0), counts.get("output", 0)
    result = {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}
    if "reasoning" in counts:
        result["completion_tokens_details"] = {"reasoning_tokens": counts["reasoning"]}
    return result
