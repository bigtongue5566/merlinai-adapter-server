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
| `tools` | `array` | No | Enables tool-calling compatibility mode when present. |
| `tool_choice` | `string` or `object` | No | Supports plain values such as `auto`, `required`, or a function selector object. |

### Message shape

Each item in `messages` supports:

- `role`: required
- `name`: optional
- `tool_call_id`: optional
- `tool_calls`: optional
- `content`: optional string or content-part array

Supported content-part patterns currently include:

- plain string content
- `{ "text": "..." }`
- `{ "input_text": "..." }`
- `{ "type": "text", "content": "..." }`

If no usable user message text is found, the adapter returns `400`.

### Tool choice forms

Accepted forms include:

```json
"auto"
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

When `tools` is present, the adapter switches into tool JSON mode and attempts to translate Merlin output into OpenAI `tool_calls`.

### Basic example

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-123" \
  -d '{
    "model": "claude-4.6-sonnet",
    "messages": [
      {"role": "system", "content": "Answer briefly."},
      {"role": "user", "content": "Explain what this adapter does."}
    ],
    "stream": false
  }'
```

### Tool-calling example

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-123" \
  -d '{
    "model": "gpt-5.4",
    "messages": [
      {"role": "user", "content": "What is the weather in Taipei?"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "Get current weather for a city",
          "parameters": {
            "type": "object",
            "properties": {
              "city": {"type": "string"}
            },
            "required": ["city"]
          }
        }
      }
    ],
    "tool_choice": "required",
    "stream": false
  }'
```

### Non-streaming response shape

Successful responses use OpenAI-style payloads:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "claude-4.6-sonnet",
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
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
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
2. either a content chunk or one or more `tool_calls` chunks
3. a final chunk with `finish_reason`
4. `data: [DONE]`

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
      "id": "gpt-5.4",
      "object": "model",
      "created": 1710000000,
      "owned_by": "merlin"
    }
  ]
}
```

Published model IDs:

- `gpt-5.4`
- `grok-4.1-fast`
- `gemini-3.1-flash-lite`
- `gemini-3.1-pro`
- `claude-4.6-sonnet`
- `claude-4.6-opus`
- `glm-5`
- `minimax-m2.5`

## Error Behavior

Common status codes returned by the adapter:

| Status | Typical cause |
| --- | --- |
| `400` | No usable user message content was found. |
| `401` | Missing or invalid adapter API key. |
| `422` | Tool calling was required, but no valid tool call payload was produced. |
| `500` | Required Merlin credentials are missing from the environment. |
| `502` | Firebase or Merlin upstream request failed. |
| `504` | Firebase or Merlin upstream request timed out. |

Upstream Merlin errors may also be passed through using the upstream HTTP status code and body.

## Related Docs

- [Project README](../README.md)
- [Architecture flow](architecture-flow.md)
- [Development notes](development-notes.md)
- [Troubleshooting](troubleshooting.md)
