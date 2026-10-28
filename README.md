# merlinai-adapter-server

OpenAI-compatible FastAPI adapter that forwards chat requests to Merlin, manages Firebase-backed Merlin authentication, and converts Merlin responses back into OpenAI-style payloads.

**Languages:** English | [繁體中文](README.zh-TW.md)

## Overview

`merlinai-adapter-server` exposes a small OpenAI-style surface for clients that expect `/v1/chat/completions` and `/v1/models`.

It handles:

- adapter API key validation
- Merlin login and token refresh
- Merlin Web request forwarding, with an optional extension transport
- live upstream streaming and non-streaming responses
- structured Merlin SSE parsing and OpenAI response conversion

## Key Features

- OpenAI-compatible `POST /v1/chat/completions`
- OpenAI-compatible `GET /v1/models`
- Merlin Web SSE streaming for chat requests
- Full conversation history; native content parts and explicit tool-history encoding in emulated mode
- Automatic Merlin bearer token acquisition and refresh
- Adapter-level API key protection via `Authorization: Bearer <ADAPTER_API_KEY>`
- Validated emulated tools on Web; optional extension native mode; no official tools are added
- Emulated calls require complete protocol JSON, declared names, and valid schema arguments
- Debug logging for request/response payload inspection
- Local and Docker-based deployment options

Web is the default (`MERLIN_TRANSPORT=web`) and always uses validated emulated
tools. It serializes the complete message history into the Web request. Set
`MERLIN_TRANSPORT=extension` to restore the extension path. See
[Web transport behavior and limits](docs/web-transport.md).

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
    "model": "claude-sonnet-5",
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

- `claude-haiku-5.5`
- `claude-opus-5.5`
- `claude-sonnet-5.5`
- `deepseek-v4-flash`
- `deepseek-v4-pro`
- `gemini-3.1-flash-lite`
- `gemini-3.8-flash`
- `gemini-4-argon`
- `glm-5.3`
- `glm-5.3-flash`
- `gpt-6-astra`
- `gpt-6-luna`
- `gpt-6-sol`
- `gpt-6.1-sol`
- `grok-4.7`
- `kimi-k3`
- `minimax-m3`
- `qwen-3.8-max`

Model list verified on 2026-10-28 against [Merlin's official configuration](https://cdn.jsdelivr.net/gh/foyer-work/cdn-files@latest/merlin_constants.json): 18 active text models (`textLLMs` with `archived=false`) are published.

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `MERLIN_EMAIL` | Yes | None | Merlin login email. |
| `MERLIN_PASSWORD` | Yes | None | Merlin login password. |
| `ADAPTER_API_KEY` | No | `sk-123` | API key expected in the incoming `Authorization` header. |
| `MERLIN_FIREBASE_API_KEY` | No | Built-in value | Firebase Web API key used for Merlin sign-in. |
| `MERLIN_TRANSPORT` | No | `web` | `web` uses the official Web profile and emulated tools; `extension` restores the legacy transport. |
| `MERLIN_VERSION` | No | `merlin-extension-8.2.3` | Extension-only version header. Web uses `web-merlin`. |
| `MERLIN_PATH` | No | `/arcane/api/v2/extension/chat` | Extension-only endpoint. Web uses `/arcane/api/v2/thread/unified`. |
| `MERLIN_ORIGIN` | No | `chrome-extension://camppjleccjaphfdbohjdohecfnoikec` | Extension-only Origin. Web uses `https://www.getmerlin.in`. |
| `LOG_LEVEL` | No | `INFO` | Logger level. Set to `DEBUG` for payload tracing. |
| `LOG_TO_FILE` | No | `true` | Writes logs to `logs/adapter.log` when enabled. |
| `AUTH_REQUEST_TIMEOUT_SECONDS` | No | `20` | Timeout for Firebase sign-in and refresh requests. |
| `MERLIN_REQUEST_TIMEOUT_SECONDS` | No | `45` | Timeout for Merlin upstream requests. |
| `TOOL_CALL_MODE` | No | `native` | Applies to extension. Web always uses `emulated`; the example environment selects it explicitly. |
| `COMPLETION_TIMEOUT_SECONDS` | No | `600` | Overall completion deadline, including correction and continuation; separate from socket inactivity timeout. |
| `COMPLETION_MAX_BYTES` | No | `16777216` | Maximum parsed SSE data bytes per completion, including correction and continuation. |
| `EMULATED_CORRECTION_ATTEMPTS` | No | `1` | One bounded protocol regeneration, or `0` to disable. Never retries transport failures. |
| `EMULATED_CONTINUATION_ATTEMPTS` | No | `8` | Qwen emulated tools: up to 8 suffix requests for truncated JSON; `0` disables, maximum 16. Shares the original limits. |
| `TOOL_PROMPT_MAX_MESSAGES` | No | `5` | Legacy comparison setting; unused by the normal native transport. |
| `TOOL_DESCRIPTION_MAX_CHARS` | No | `160` | Legacy comparison setting; unused by the normal native transport. |
| `TOOL_MESSAGE_MAX_CHARS` | No | `1200` | Legacy comparison setting; unused by the normal native transport. |
| `TOOL_SYSTEM_MAX_CHARS` | No | `12000` minimum | Legacy comparison setting; unused by the normal native transport. |
| `TOOL_TOOL_RESULT_MAX_CHARS` | No | `6000` minimum | Legacy comparison setting; unused by the normal native transport. |
| `TOOL_TOOL_ARGUMENTS_MAX_CHARS` | No | `4000` minimum | Legacy comparison setting; unused by the normal native transport. |
| `TOOL_PARAMETER_DESCRIPTION_MAX_CHARS` | No | `300` minimum | Legacy comparison setting; unused by the normal native transport. |

The `TOOL_*` prompt-compaction settings are retained for historical comparison
and diagnostic helpers. They are not used by the normal extension transport,
which preserves the caller's message sequence.

When extension is selected, the adapter sends `metadata.isMCPEnabled=true` because that endpoint
requires that session flag even when `params.tools` is empty. It does not add
extension tools. For the verified extension header, test results, and protocol scope, see
[Extension compatibility](docs/extension-compatibility.md). Restart the adapter
after changing `MERLIN_VERSION`.

## Debugging

Use `LOG_LEVEL=DEBUG` to inspect the adapter's incoming request, forwarded Merlin payload, native SSE events, and outgoing OpenAI response.

If you only want console output, set:

```text
LOG_TO_FILE=false
```

Useful helper:

- `uv run python scripts/build_log_report.py --log logs/adapter.log --out logs/report.md`

## Documentation

- [API reference](docs/api-reference.md)
- [Architecture flow](docs/architecture-flow.md)
- [Development notes](docs/development-notes.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Traditional Chinese README](README.zh-TW.md)

Model output limits and verification: [model limits](docs/model-limits-2026-10-28.md), [catalog update and live results](docs/model-validation-2026-10-28.md), [reliability implementation and live results](docs/reliability-2026-09-20.md).
