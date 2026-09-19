# Development Notes

This document collects implementation-heavy details that do not belong on the project homepage.

For setup and usage, see the [root README](../README.md). For internal request flow and module ownership, see [Architecture Flow](architecture-flow.md).

## Native Extension Transport

The default `TOOL_CALL_MODE=native` path preserves the caller's system, developer, assistant,
user, and tool messages. It does not flatten history into a generated prompt,
add hidden instructions, register Merlin browser/MCP tools, or retry with a
repair prompt. This keeps the adapter's behavior predictable and leaves
conversation policy with the caller.

`tool_choice` policy is intentionally narrow: omitted, `null`, and `auto`
forward caller-supplied schemas; only the literal string `none` sends an empty
`params.tools` list. `required`, named selectors, and invalid selectors return
`422` before network I/O because this upstream capability is not verified.

Caller-supplied tool schemas are forwarded for compatibility, but live Merlin
support remains unverified. Native tool events are accepted only when they
have a non-empty `id`, a declared `name`, and valid JSON object arguments.
Malformed or undeclared events fail with `502`; ordinary text is never repaired
into a tool call.

## Emulated Tool Mode

The explicit `TOOL_CALL_MODE=emulated` path is implemented in `emulated_tools.py`.
It adds a strict output protocol only when caller tools are enabled, translates
tool history into full text records, and validates the completed JSON and
parameter schemas before exposing calls. It reuses the extension gateway and
OpenAI response builders, with no JSON repair, hidden retry, or mode fallback.
See [tool mode behavior](emulated-tool-calling.md).

## Legacy Comparison Modules

The prompt compaction, structured-output repair, and comparison helpers in
`tool_prompt.py`, `tool_payload_parser.py`, and related modules are retained
only for historical diagnostics. They are not called by the normal extension
transport. The old comparison CLI is retired before any upstream network
request, so it must not be used as a health check or as a fallback path.

## Logging and Debug Reference

Set:

```text
LOG_LEVEL=DEBUG
```

Useful debug events include:

- `incoming_chat_request`
- `outgoing_merlin_payload`
- `merlin_raw_response`
- `merlin_attempt_summary`
- `outgoing_openai_response`
- `streamed_openai_response_summary`

Correlation behavior:

- every request gets a `request_id`
- the native transport does not issue hidden repair or agentic retries
- File logging writes to `logs/adapter.log` when `LOG_TO_FILE=true`

If you want console-only logging:

```text
LOG_TO_FILE=false
```

## Helper Scripts

### Verify the model catalog and live chat functionality

Merlin's web model selector loads `textLLMs` from
[`merlin_constants.json`](https://cdn.jsdelivr.net/gh/foyer-work/cdn-files@latest/merlin_constants.json).
Use entries with `archived=false` when updating `models_catalog.py` and the three
published lists in the READMEs and API reference. The model enum embedded in the
web JavaScript bundle can lag behind this configuration.

Run a short chat against every published model:

```bash
uv run python scripts/smoke_test_models.py
```

Run text chat and SSE chat:

```bash
uv run python scripts/smoke_test_models.py --modes chat chat-stream --out logs/model-smoke.json
```

To limit the run, use `--models gpt-5.6-luna` and/or `--modes chat`.
These checks use FastAPI's in-process HTTP test client with **real Merlin upstream
requests**, the credentials in `.env`, and account query quota. They check API
authentication, request validation, catalog consistency, response schemas,
expected reply content, usage, and SSE termination. Tool schemas are not part
of the normal health check because their live upstream behavior is unverified.
They do not execute a requested tool or verify a deployed server or proxy. Reports contain
statuses and timings, with no credentials or upstream response bodies. A failed
case produces a nonzero exit code. This is a smoke check, not a reliability benchmark.

### Build a Markdown report from adapter logs

```bash
uv run python scripts/build_log_report.py --log logs/adapter.log --out logs/report.md
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
