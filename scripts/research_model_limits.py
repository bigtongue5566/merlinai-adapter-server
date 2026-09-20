"""Extract first-party limits from a downloaded models.dev snapshot, never configure runtime."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from merlinai_adapter_server.models_catalog import SUPPORTED_MODELS


def source_model(model):
    providers = {"claude-": "anthropic", "deepseek-": "deepseek", "gemini-": "google",
                 "glm-": "zai", "gpt-": "openai", "grok-": "xai", "kimi-": "moonshotai"}
    if model == "minimax-m3":
        return "minimax", "MiniMax-M3"
    if model == "qwen-3.8-max":
        return "alibaba", "qwen3.8-max"
    for prefix, provider in providers.items():
        if model.startswith(prefix):
            return provider, model
    raise ValueError(f"No reviewed provider mapping for {model}")


def extract(data):
    rows = []
    for model in SUPPORTED_MODELS:
        provider, upstream = source_model(model)
        entry = data.get(provider, {}).get("models", {}).get(upstream)
        if not entry:
            raise ValueError(f"Missing exact source: {provider}/{upstream}; refusing a fuzzy match")
        limit = entry.get("limit", {})
        if any(type(limit.get(key)) is not int or limit[key] <= 0 for key in ("context", "output")):
            raise ValueError(f"Missing positive limits for {provider}/{upstream}")
        rows.append({"adapter_model": model, "provider": provider, "provider_model": upstream,
                     "limit": limit, "merlin_limit_verified": False})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    report = {"source": "https://models.dev/api.json", "retrieved_at": None,
              "extracted_at": datetime.now(timezone.utc).isoformat(),
              "source_sha256": hashlib.sha256(raw).hexdigest(),
              "selection": "Exact first-party provider records; not verified Merlin limits.",
              "models": extract(json.loads(raw))}
    with args.out.open("x", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write("\n")
    print(f"Extracted {len(report['models'])} models to {args.out}")


if __name__ == "__main__":
    main()
