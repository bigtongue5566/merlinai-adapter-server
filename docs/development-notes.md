# Development Notes

This document collects implementation-heavy details that do not belong on the project homepage.

For setup and usage, see the [root README](../README.md). For internal request flow and module ownership, see [Architecture Flow](architecture-flow.md).

## Tool-Calling Transport Strategy

When the incoming OpenAI-style request includes `tools`, the adapter switches into a stricter compatibility mode designed to improve Merlin's chance of returning usable tool calls.

Current behavior:

- `metadata.mcpConfig.isEnabled` is forced to `false`
- `metadata.webAccess` is forced to `true`
- Tool schema is preserved in prompt JSON instead of relying on Merlin-side MCP injection
- The adapter asks Merlin for a structured payload that can be converted into OpenAI `tool_calls`

The goal is to avoid false-success responses where a client required tool usage but Merlin only returned natural-language content.

## Structured Payload Parsing

Tool-call data can arrive from more than one place:

- event-level tool call information in Merlin SSE output
- structured JSON payload blocks embedded in generated content
- repaired JSON reconstructed from malformed payloads

`tool_payload_parser.py` is responsible for:

- locating `<OPENAI_TOOL_PAYLOAD>...</OPENAI_TOOL_PAYLOAD>` blocks
- repairing malformed JSON when possible
- extracting tool calls
- filtering calls against the allowed tool list
- resolving whether the final result should be treated as `message` content or `tool_calls`

## Repair Behavior

The adapter can issue follow-up attempts in two cases.

### `repair`

Used when Merlin returns a malformed structured payload that looks recoverable. The retry prompt asks for a cleaner, parseable payload instead of silently accepting broken output.

### `agentic_repair`

Used only in narrower tool-calling cases, typically when `tool_choice=auto` suggests the model should still be interacting with tools but instead ends early with a plain assistant message.

This retry is intended as a recovery path, not a guaranteed second pass for every tool request.

## Logging and Debug Reference

Set:

```text
LOG_LEVEL=DEBUG
```

Useful debug events include:

- `incoming_chat_request`
- `tool_prompt_metrics`
- `non_tool_prompt_metrics`
- `outgoing_merlin_payload`
- `merlin_raw_response`
- `merlin_attempt_summary`
- `structured_payload_resolution`
- `agentic_repair_skipped`
- `outgoing_openai_response`
- `streamed_openai_response_summary`

Correlation behavior:

- every request gets a `request_id`
- retries also carry an `attempt` value such as `initial`, `repair`, or `agentic_repair`
- File logging writes to `logs/adapter.log` when `LOG_TO_FILE=true`

If you want console-only logging:

```text
LOG_TO_FILE=false
```

## Helper Scripts

### Build a Markdown report from adapter logs

```bash
uv run python scripts/build_log_report.py --log logs/adapter.log --out logs/report.md
```

### Compare tool transport modes

```bash
uv run python scripts/compare_tool_transport_modes.py
```

## Finding the Firebase API Key

If you need to inspect or replace `MERLIN_FIREBASE_API_KEY`, the most direct approach is to observe Merlin Web login traffic:

1. Open `https://extension.getmerlin.in`
2. Open browser DevTools and switch to the Network panel
3. Perform the login flow
4. Inspect the request to `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=...`

## Related Docs

- [API reference](api-reference.md)
- [Project README](../README.md)
- [Traditional Chinese README](../README.zh-TW.md)
- [Architecture Flow](architecture-flow.md)
- [Troubleshooting](troubleshooting.md)
