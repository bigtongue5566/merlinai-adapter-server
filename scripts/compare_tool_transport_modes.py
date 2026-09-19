from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import BaseModel

from merlinai_adapter_server.schemas import build_function_tool_payload


class WeatherInputSchema(BaseModel):
    location: str
    unit: Literal["celsius", "fahrenheit"] | None = None


TEST_TOOLS = [
    build_function_tool_payload(
        name="get_current_weather",
        description="Get the current weather in a given location",
        input_schema=WeatherInputSchema,
    )
]

TEST_USER_MESSAGE = (
    "What is the weather like in Tokyo? "
    "Use the get_current_weather tool and do not answer directly."
)

RETIREMENT_MESSAGE = (
    "This historical comparison is retired: the adapter now accepts only the native "
    "Merlin extension payload and does not send legacy tool/prompt transport requests."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Merlin tool transport modes")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument(
        "--tool-choice",
        nargs="+",
        default=["required", "auto"],
        help="Tool choice values to test",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=Path("logs") / "tool_transport_compare.json",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=Path("logs") / "tool_transport_compare.md",
    )
    args = parser.parse_args()

    print(RETIREMENT_MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
