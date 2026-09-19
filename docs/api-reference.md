# API Reference

This adapter exposes a small OpenAI-compatible API surface.

Base URL examples:

- Local: `http://localhost:8000`
- Docker Compose: `http://localhost:8000`

All requests must include:

```text
Authorization: Bearer <ADAPTER_API_KEY>
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/chat/completions` | Run a Merlin-backed chat completion request using OpenAI-style request fields. |
| `GET` | `/v1/models` | Return the adapter's published model list. |

## `POST /v1/chat/completions`

### Request body

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `model` | `string` | Yes | Must be one of the published model IDs. |
| `messages` | `array` | Yes | OpenAI-style message list. |
| `stream` | `boolean` | No | Defaults to `false`. |
| `tools` | `array` | No | Caller function schemas: forwarded in native mode, encoded in a prompt in emulated mode. No official extension tools are added. |
| `tool_choice` | `string` or `object` | No | `auto`/omitted/`null` permits tools; `none` disables them. `required` and a named function are supported in emulated mode only; invalid requests return `422`. |
| `max_tokens` | `integer` | No | Positive output limit; sent as `params.max_tokens`, defaulting upstream to `10000`. |
| `stream_options` | `object` | No | Supports `include_usage`; usage is emitted in the final stream chunk when enabled. |

### Message shape

Each item in `messages` supports:

- `role`: required
- `name`: optional
- `tool_call_id`: optional
- `tool_calls`: optional
- `content`: optional string or content-part array

The adapter accepts plain string content and preserves caller-provided native
content-part objects for the extension transport. Preservation does not mean
that every provider-specific part is supported by Merlin upstream; unsupported
parts may still be rejected by Merlin.

String content in `user` and `tool` messages is encoded as the extension's
`[{"type":"text","text":"..."}]` content-part form.

### Tool choice forms

The adapter recognizes these forms:

```json
"auto"
```

```json
"none"
```

```json
"required"
```

```json
{
  "type": "function",
  "function": {
    "name": "get_weather"
  }
}
```

Tool mode is configured by `TOOL_CALL_MODE` at server startup (default `native`).
There is no automatic fallback between modes. In `emulated` mode, the adapter
sends no native tools upstream, instructs the model to return a strict JSON
envelope, validates complete calls against the declared parameter schemas,
and encodes subsequent tool history as text. Required/named choices are
enforced locally. Invalid responses return `502` or an SSE error.
See [emulated tool calling](emulated-tool-calling.md) for the full contract.

In `native` mode, the adapter does not register Merlin's browser or MCP tools. Omitted or
`null` `tool_choice`, and `tool_choice: "auto"`, send caller-supplied schemas.
Only literal `tool_choice: "none"` sends an empty tool list. `required`, named-function selectors, and invalid
selectors return `422` before any network request because this upstream
capability is not verified. Native structured tool events are converted to
OpenAI `tool_calls` only when the caller supplies a matching schema and Merlin
returns a native event.

Native tool events must have `type: "function"`, a non-empty `id` and
`name`, an object of arguments (or a valid JSON-object string), and a name
declared by the caller.
Malformed or undeclared events return `502`; in streaming mode the adapter
emits `event: error` and does not emit a successful finish or `[DONE]`.
Ordinary text containing JSON is kept as text.

### Basic example

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-123" \
  -d '{
    "model": "claude-sonnet-5",
    "messages": [
      {"role": "system", "content": "Answer briefly."},
      {"role": "user", "content": "Explain what this adapter does."}
    ],
    "stream": false
  }'
```

### Non-streaming response shape

Successful responses use OpenAI-style payloads. Token values below are
illustrative; when Merlin supplies usage, the adapter maps it into these
fields:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "claude-sonnet-5",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 123,
    "completion_tokens": 8,
    "total_tokens": 131
  }
}
```

If tool calls are returned, the adapter switches the choice to:

- `message.content = null`
- `message.tool_calls = [...]`
- `finish_reason = "tool_calls"`

### Streaming response shape

When `stream=true`, the adapter emits server-sent events in OpenAI chunk style:

1. an initial assistant role chunk
2. one or more content or native `tool_calls` chunks
3. a final chunk with `finish_reason`
4. an optional usage chunk with `choices: []` when `stream_options.include_usage=true`
5. `data: [DONE]`

Regular chat requests stream Merlin extension text events through as OpenAI
`content` deltas as they arrive. A native `error` event or incomplete upstream
stream is returned as an error and never as a successful `[DONE]` completion.

Emulated tool rounds buffer the upstream response until DONE and validate the
whole envelope before emitting any content/tool deltas. They then emit the
same finish, optional usage, and DONE sequence. No partial protocol JSON or
unvalidated tool arguments are sent to the client.

## `GET /v1/models`

### Example

```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer sk-123"
```

### Response shape

```json
{
  "object": "list",
  "data": [
    {
      "id": "gpt-5.5",
      "object": "model",
      "created": 1710000000,
      "owned_by": "merlin"
    }
  ]
}
```

Published model IDs:

- `claude-opus-5`
- `claude-sonnet-5`
- `deepseek-v4-flash`
- `deepseek-v4-pro`
- `gemini-3.1-flash-lite`
- `gemini-3.8-flash`
- `glm-5.3`
- `glm-5.3-flash`
- `gpt-5.5`
- `gpt-5.6-luna`
- `gpt-5.6-sol`
- `gpt-5.6-terra`
- `gpt-6-astra`
- `grok-4.6`
- `kimi-k3`
- `minimax-m3`
- `qwen-3.8-max`

Model list verified on 2026-09-17 against [Merlin's official configuration](https://cdn.jsdelivr.net/gh/foyer-work/cdn-files@latest/merlin_constants.json). Only active text models (`textLLMs` with `archived=false`) are published.

## Error Behavior

Common status codes returned by the adapter:

| Status | Typical cause |
| --- | --- |
| `400` | Invalid request content. |
| `401` | Missing or invalid adapter API key. |
| `422` | Request field validation failed. |
| `500` | Required Merlin credentials are missing from the environment. |
| `502` | Firebase or Merlin upstream request failed. |
| `504` | Firebase or Merlin upstream request timed out. |

Upstream Merlin errors may also be passed through using the upstream HTTP status code and body.

## Related Docs

- [Project README](../README.md)
- [Architecture flow](architecture-flow.md)
- [Development notes](development-notes.md)
- [Troubleshooting](troubleshooting.md)
