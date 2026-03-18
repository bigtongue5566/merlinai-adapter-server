# merlinai-adapter-server

OpenAI-compatible FastAPI adapter that forwards chat requests to Merlin, manages Firebase-backed Merlin authentication, and converts Merlin responses back into OpenAI-style payloads.

**Languages:** English | [繁體中文](README.zh-TW.md)

## Overview

`merlinai-adapter-server` exposes a small OpenAI-style surface for clients that expect `/v1/chat/completions` and `/v1/models`.

It handles:

- adapter API key validation
- Merlin login and token refresh
- prompt and payload transformation
- streaming and non-streaming responses
- tool-calling compatibility with OpenAI `tool_calls`

## Key Features

- OpenAI-compatible `POST /v1/chat/completions`
- OpenAI-compatible `GET /v1/models`
- Streaming and non-streaming response support
- Automatic Merlin bearer token acquisition and refresh
- Adapter-level API key protection via `Authorization: Bearer <ADAPTER_API_KEY>`
- Tool-calling compatibility layer that maps Merlin output to OpenAI `tool_calls`
- Strict `422` responses when required tool calls are not produced
- Debug logging for request/response payload inspection
- Local and Docker-based deployment options

## Quick Start

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A Merlin account

### Install dependencies

```bash
uv sync
```

### Create environment variables

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

Update `.env` with your Merlin credentials and adapter API key.

### Run locally

```bash
uv run python main.py
```

The server starts on `http://0.0.0.0:8000`.

### Example request

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-123" \
  -d '{
    "model": "claude-4.6-sonnet",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'
```

## Docker

Build and start the service:

```bash
docker compose up --build -d
```

View logs:

```bash
docker compose logs -f
```

Stop the service:

```bash
docker compose down
```

The container publishes the API on `http://localhost:8000`.

## API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/v1/chat/completions` | Accepts OpenAI-style chat completion requests and returns OpenAI-style responses. |
| `GET` | `/v1/models` | Returns the adapter's published Merlin-backed model list. |

For request and response examples, see [API reference](docs/api-reference.md).

## Supported Models

- `gpt-5.4`
- `grok-4.1-fast`
- `gemini-3.1-flash-lite`
- `gemini-3.1-pro`
- `claude-4.6-sonnet`
- `claude-4.6-opus`
- `glm-5`
- `minimax-m2.5`

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `MERLIN_EMAIL` | Yes | None | Merlin login email. |
| `MERLIN_PASSWORD` | Yes | None | Merlin login password. |
| `ADAPTER_API_KEY` | No | `sk-123` | API key expected in the incoming `Authorization` header. |
| `MERLIN_FIREBASE_API_KEY` | No | Built-in value | Firebase Web API key used for Merlin sign-in. |
| `MERLIN_VERSION` | No | `iframe-merlin-7.5.19` | Merlin version header sent upstream. |
| `LOG_LEVEL` | No | `INFO` | Logger level. Set to `DEBUG` for payload tracing. |
| `LOG_TO_FILE` | No | `true` | Writes logs to `logs/adapter.log` when enabled. |
| `AUTH_REQUEST_TIMEOUT_SECONDS` | No | `20` | Timeout for Firebase sign-in and refresh requests. |
| `MERLIN_REQUEST_TIMEOUT_SECONDS` | No | `45` | Timeout for Merlin upstream requests. |
| `TOOL_PROMPT_MAX_MESSAGES` | No | `5` | Maximum number of non-system messages retained in tool prompts. |
| `TOOL_DESCRIPTION_MAX_CHARS` | No | `160` | Maximum tool description length in prompt compaction. |
| `TOOL_MESSAGE_MAX_CHARS` | No | `1200` | Maximum general message length in tool prompt compaction. |
| `TOOL_SYSTEM_MAX_CHARS` | No | `12000` minimum | Maximum system message length in tool prompt compaction. |
| `TOOL_TOOL_RESULT_MAX_CHARS` | No | `6000` minimum | Maximum serialized tool result length in tool prompt compaction. |
| `TOOL_TOOL_ARGUMENTS_MAX_CHARS` | No | `4000` minimum | Maximum serialized assistant tool argument length. |
| `TOOL_PARAMETER_DESCRIPTION_MAX_CHARS` | No | `300` minimum | Maximum tool parameter description length. |

## Debugging

Use `LOG_LEVEL=DEBUG` to inspect the adapter's incoming request, forwarded Merlin payload, structured payload parsing, and outgoing OpenAI response.

If you only want console output, set:

```text
LOG_TO_FILE=false
```

Useful helpers:

- `uv run python scripts/build_log_report.py --log logs/adapter.log --out logs/report.md`
- `uv run python scripts/compare_tool_transport_modes.py`

## Documentation

- [API reference](docs/api-reference.md)
- [Architecture flow](docs/architecture-flow.md)
- [Development notes](docs/development-notes.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Traditional Chinese README](README.zh-TW.md)
