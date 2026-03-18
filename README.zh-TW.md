# merlinai-adapter-server

這是一個 OpenAI 相容的 FastAPI adapter，會把聊天請求轉送到 Merlin，處理 Firebase 驗證登入流程，並把 Merlin 回應轉回 OpenAI 風格的 payload。

**語言：** [English](README.md) | 繁體中文

## 專案概覽

`merlinai-adapter-server` 提供簡潔的 OpenAI 風格介面，讓需要 `/v1/chat/completions` 與 `/v1/models` 的 client 可以直接接 Merlin。

它會處理：

- adapter API key 驗證
- Merlin 登入與 token refresh
- prompt 與 payload 轉換
- 串流與非串流回應
- OpenAI `tool_calls` 相容層

## 主要功能

- 支援 OpenAI 相容的 `POST /v1/chat/completions`
- 支援 OpenAI 相容的 `GET /v1/models`
- 支援串流與非串流回應
- 自動取得與刷新 Merlin bearer token
- 透過 `Authorization: Bearer <ADAPTER_API_KEY>` 保護 adapter 入口
- 將 Merlin 輸出轉為 OpenAI `tool_calls` 的工具呼叫相容層
- 當必須產生工具呼叫但上游未提供時，回傳嚴格的 `422`
- 支援 request/response payload debug logging
- 可用本機或 Docker 方式部署

## 快速開始

### 需求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Merlin 帳號

### 安裝依賴

```bash
uv sync
```

### 建立環境變數

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

接著修改 `.env`，填入你的 Merlin 帳號密碼與 adapter API key。

### 本機執行

```bash
uv run python main.py
```

服務會啟動在 `http://0.0.0.0:8000`。

### 呼叫範例

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-123" \
  -d '{
    "model": "claude-4.6-sonnet",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
```

## Docker

建置並啟動服務：

```bash
docker compose up --build -d
```

查看 logs：

```bash
docker compose logs -f
```

停止服務：

```bash
docker compose down
```

容器會把 API 開在 `http://localhost:8000`。

## API 端點

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/v1/chat/completions` | 接收 OpenAI 風格 chat completion 請求，並回傳 OpenAI 風格回應。 |
| `GET` | `/v1/models` | 回傳 adapter 對外公布的 Merlin-backed 模型清單。 |

完整 request/response 範例可參考 [API reference](docs/api-reference.md)。

## 支援模型

- `gpt-5.4`
- `grok-4.1-fast`
- `gemini-3.1-flash-lite`
- `gemini-3.1-pro`
- `claude-4.6-sonnet`
- `claude-4.6-opus`
- `glm-5`
- `minimax-m2.5`

## 環境設定

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `MERLIN_EMAIL` | Yes | None | Merlin 登入信箱。 |
| `MERLIN_PASSWORD` | Yes | None | Merlin 登入密碼。 |
| `ADAPTER_API_KEY` | No | `sk-123` | 進入 adapter 時要求的 `Authorization` API key。 |
| `MERLIN_FIREBASE_API_KEY` | No | 內建預設值 | 用於 Merlin 登入的 Firebase Web API key。 |
| `MERLIN_VERSION` | No | `iframe-merlin-7.5.19` | 轉發到上游時使用的 Merlin version header。 |
| `LOG_LEVEL` | No | `INFO` | logger 層級。設為 `DEBUG` 可查看 payload trace。 |
| `LOG_TO_FILE` | No | `true` | 開啟時會把 logs 寫入 `logs/adapter.log`。 |
| `AUTH_REQUEST_TIMEOUT_SECONDS` | No | `20` | Firebase 登入與 refresh request timeout。 |
| `MERLIN_REQUEST_TIMEOUT_SECONDS` | No | `45` | Merlin upstream request timeout。 |
| `TOOL_PROMPT_MAX_MESSAGES` | No | `5` | tool prompt 中保留的非 system 訊息數上限。 |
| `TOOL_DESCRIPTION_MAX_CHARS` | No | `160` | tool description 裁切上限。 |
| `TOOL_MESSAGE_MAX_CHARS` | No | `1200` | 一般訊息裁切上限。 |
| `TOOL_SYSTEM_MAX_CHARS` | No | `12000` minimum | system message 裁切上限。 |
| `TOOL_TOOL_RESULT_MAX_CHARS` | No | `6000` minimum | tool result 序列化後的裁切上限。 |
| `TOOL_TOOL_ARGUMENTS_MAX_CHARS` | No | `4000` minimum | assistant tool arguments 裁切上限。 |
| `TOOL_PARAMETER_DESCRIPTION_MAX_CHARS` | No | `300` minimum | tool parameter description 裁切上限。 |

## 除錯

把 `LOG_LEVEL=DEBUG` 打開後，可以檢查 adapter 收到的 request、轉發給 Merlin 的 payload、structured payload parsing 過程，以及最後回給 client 的 OpenAI response。

如果只想輸出到 console，可以設定：

```text
LOG_TO_FILE=false
```

常用輔助腳本：

- `uv run python scripts/build_log_report.py --log logs/adapter.log --out logs/report.md`
- `uv run python scripts/compare_tool_transport_modes.py`

## 延伸文件

- [API reference](docs/api-reference.md)
- [Architecture flow](docs/architecture-flow.md)
- [Development notes](docs/development-notes.md)
- [Troubleshooting](docs/troubleshooting.md)
- [English README](README.md)
