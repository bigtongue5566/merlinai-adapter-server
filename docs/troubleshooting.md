# Troubleshooting

This guide covers the most common startup, authentication, upstream, and tool-calling issues for `merlinai-adapter-server`.

For setup and examples, see the [root README](../README.md). For request flow details, see [Architecture flow](architecture-flow.md). For tool-mode internals, see [Development notes](development-notes.md).

## First Checks

Before debugging deeper issues, verify:

- the server is running on the expected port
- `.env` exists and contains your Merlin credentials
- the client sends `Authorization: Bearer <ADAPTER_API_KEY>`
- the selected `model` exists in `GET /v1/models`
- `LOG_LEVEL=DEBUG` is enabled when you need request tracing

## Authentication Problems

### `401 Invalid or missing adapter API key`

Cause:

- the incoming `Authorization` header does not match `Bearer <ADAPTER_API_KEY>`

Checks:

- confirm the header is present
- confirm `ADAPTER_API_KEY` in `.env`
- restart the adapter after changing `.env`

### `500 Missing MERLIN_EMAIL or MERLIN_PASSWORD environment variables`

Cause:

- required Merlin credentials are absent

Checks:

- verify `MERLIN_EMAIL` and `MERLIN_PASSWORD` in `.env`
- make sure the process is loading the correct `.env`
- restart the process after edits

### `502 Firebase auth failed` or `502 Firebase auth error`

Cause:

- Merlin sign-in was rejected
- `MERLIN_FIREBASE_API_KEY` is invalid or stale
- Merlin credentials are incorrect

Checks:

- confirm the Merlin account credentials
- inspect whether the Firebase API key still works
- review the exact error body in the response or debug logs

### `504 Firebase auth request timed out`

Cause:

- timeout while reaching Firebase during sign-in or token refresh

Checks:

- verify outbound network access
- retry the request
- increase `AUTH_REQUEST_TIMEOUT_SECONDS` if the environment is consistently slow

## Merlin Upstream Problems

### `502 Merlin request failed`

Cause:

- connection failure while sending the upstream request

Checks:

- inspect network reachability from the host
- confirm Merlin is accessible from the runtime environment
- turn on `LOG_LEVEL=DEBUG` and inspect `outgoing_merlin_payload`

### `504 Merlin request timed out` or `504 Merlin event stream timed out`

Cause:

- Merlin did not respond in time, or the event stream stalled

Checks:

- retry the request
- increase `MERLIN_REQUEST_TIMEOUT_SECONDS`
- compare behavior across models to rule out model-specific slowness

### Upstream Merlin status passthrough

Behavior:

- if Merlin returns a non-200 HTTP response, the adapter can forward the upstream status code and error body

Checks:

- inspect the response body returned by the adapter
- inspect debug logs for the forwarded payload and upstream response summary

## Request Validation Problems

### `400 No user message content found`

Cause:

- the adapter could not extract usable text from the request's user messages

Checks:

- include at least one `messages` item with `role: "user"`
- provide user content as a string or a supported content-part structure
- avoid sending empty content arrays or arrays without text-bearing fields

## Tool-Calling Problems

### `422 Tool calling was required, but upstream did not return a valid tool call payload`

Cause:

- the request required tool use, but Merlin responded with plain text or malformed structured output

Checks:

- verify the request includes a valid `tools` array
- confirm `tool_choice` matches the intended behavior
- inspect `structured_payload_resolution` in debug logs
- compare event-level tool calls with payload-level tool calls

### `422 Specific tool call was required (...)`

Cause:

- the request required a named function, but the returned tool call did not match or was not usable

Checks:

- verify the function name in `tool_choice`
- verify the same function name appears in `tools`
- confirm the tool schema is not being over-trimmed by prompt compaction settings

### Tool mode is enabled but output still looks like plain text

Possible reasons:

- Merlin returned content instead of structured tool payload
- payload JSON was malformed beyond repair
- the tool call was filtered out because it was not in the allowed list

Checks:

- inspect `merlin_raw_response`
- inspect `structured_payload_resolution`
- inspect `merlin_attempt_summary`
- review the final `outgoing_openai_response`

## Logging and Diagnostics

### Enable debug logging

```text
LOG_LEVEL=DEBUG
```

Useful debug events:

- `incoming_chat_request`
- `tool_prompt_metrics`
- `non_tool_prompt_metrics`
- `outgoing_merlin_payload`
- `merlin_raw_response`
- `merlin_attempt_summary`
- `structured_payload_resolution`
- `outgoing_openai_response`
- `streamed_openai_response_summary`

### Console-only logging

```text
LOG_TO_FILE=false
```

### Log file location

- `logs/adapter.log`

### Helper scripts

Build a Markdown summary from logs:

```bash
uv run python scripts/build_log_report.py --log logs/adapter.log --out logs/report.md
```

Compare tool transport modes:

```bash
uv run python scripts/compare_tool_transport_modes.py
```

## If You Need More Detail

- [API reference](api-reference.md)
- [Architecture flow](architecture-flow.md)
- [Development notes](development-notes.md)
- [Project README](../README.md)
