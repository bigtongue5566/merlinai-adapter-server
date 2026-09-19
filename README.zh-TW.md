# merlinai-adapter-server

這是一個 OpenAI 相容的 FastAPI adapter，會把聊天請求轉送到 Merlin，處理 Firebase 驗證登入流程，並把 Merlin 回應轉回 OpenAI 風格的 payload。

**語言：** [English](README.md) | 繁體中文

## 專案概覽

`merlinai-adapter-server` 提供簡潔的 OpenAI 風格介面，讓需要 `/v1/chat/completions` 與 `/v1/models` 的 client 可以直接接 Merlin。

它會處理：

- adapter API key 驗證
- Merlin 登入與 token refresh
- 原生 extension 訊息與 payload 轉送
- 上游即時串流與非串流回應
- 結構化 extension SSE 解析與 OpenAI 回應轉換

## 主要功能

- 支援 OpenAI 相容的 `POST /v1/chat/completions`
- 支援 OpenAI 相容的 `GET /v1/models`
- 聊天請求支援 Merlin extension SSE 即時串流
- 保留完整對話；原生模式保留 content parts，模擬模式將工具歷史轉成文字紀錄
- 自動取得與刷新 Merlin bearer token
- 透過 `Authorization: Bearer <ADAPTER_API_KEY>` 保護 adapter 入口
- 明確切換 `native`／`emulated` 工具模式，不加入瀏覽器、MCP 或其他官方 extension 工具
- 模擬呼叫必須通過完整 JSON 協定、工具名稱與參數 schema 驗證
- 支援 request/response payload debug logging
- 可用本機或 Docker 方式部署

在 `.env` 設定 `TOOL_CALL_MODE=emulated` 並重啟，即可使用新版 extension
傳輸搭配工具模擬。原生工具先前實測失敗；模擬模式已通過 Luna／Sonnet 的
讀檔後回答完整回合。詳見[工具模式說明](docs/emulated-tool-calling.md)與
[OpenCode 實測](docs/opencode-validation-2026-09-19.md)。

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
    "model": "claude-sonnet-5",
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

模型清單於 2026-09-17 核對 [Merlin 官方設定](https://cdn.jsdelivr.net/gh/foyer-work/cdn-files@latest/merlin_constants.json)，僅公布未封存的文字模型（`textLLMs` 中 `archived=false`）。

## 環境設定

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `MERLIN_EMAIL` | Yes | None | Merlin 登入信箱。 |
| `MERLIN_PASSWORD` | Yes | None | Merlin 登入密碼。 |
| `ADAPTER_API_KEY` | No | `sk-123` | 進入 adapter 時要求的 `Authorization` API key。 |
| `MERLIN_FIREBASE_API_KEY` | No | 內建預設值 | 用於 Merlin 登入的 Firebase Web API key。 |
| `MERLIN_VERSION` | No | `merlin-extension-8.2.3` | 上游 `x-merlin-version` header 的值，已核對官方 extension 原始程式。 |
| `MERLIN_PATH` | No | `/arcane/api/v2/extension/chat` | 原生 Merlin extension chat endpoint。 |
| `MERLIN_ORIGIN` | No | `chrome-extension://camppjleccjaphfdbohjdohecfnoikec` | 官方 8.2.3 extension request 使用的 Origin。 |
| `LOG_LEVEL` | No | `INFO` | logger 層級。設為 `DEBUG` 可查看 payload trace。 |
| `LOG_TO_FILE` | No | `true` | 開啟時會把 logs 寫入 `logs/adapter.log`。 |
| `AUTH_REQUEST_TIMEOUT_SECONDS` | No | `20` | Firebase 登入與 refresh request timeout。 |
| `MERLIN_REQUEST_TIMEOUT_SECONDS` | No | `45` | Merlin upstream request timeout。 |
| `TOOL_CALL_MODE` | No | `native` | `native` 直接轉送工具；`emulated` 使用文字協定並驗證工具 JSON。修改後重啟。 |
| `TOOL_PROMPT_MAX_MESSAGES` | No | `5` | 歷史比較設定；正常原生 transport 不使用。 |
| `TOOL_DESCRIPTION_MAX_CHARS` | No | `160` | 歷史比較設定；正常原生 transport 不使用。 |
| `TOOL_MESSAGE_MAX_CHARS` | No | `1200` | 歷史比較設定；正常原生 transport 不使用。 |
| `TOOL_SYSTEM_MAX_CHARS` | No | `12000` minimum | 歷史比較設定；正常原生 transport 不使用。 |
| `TOOL_TOOL_RESULT_MAX_CHARS` | No | `6000` minimum | 歷史比較設定；正常原生 transport 不使用。 |
| `TOOL_TOOL_ARGUMENTS_MAX_CHARS` | No | `4000` minimum | 歷史比較設定；正常原生 transport 不使用。 |
| `TOOL_PARAMETER_DESCRIPTION_MAX_CHARS` | No | `300` minimum | 歷史比較設定；正常原生 transport 不使用。 |

`TOOL_*` prompt 壓縮設定仍保留給歷史比較與診斷輔助工具；正常的原生
extension transport 會保留呼叫端的 messages 順序，不會攤平成單一 prompt。

adapter 會設定 `metadata.isMCPEnabled=true`，因為 extension endpoint 即使
`params.tools` 為空也要求這個 session flag；這不會加入 extension 工具。
已核對的 extension header、測試結果與協定範圍，請參考
[Extension compatibility](docs/extension-compatibility.md)。修改 `MERLIN_VERSION` 後需重啟 adapter。

## 除錯

把 `LOG_LEVEL=DEBUG` 打開後，可以檢查 adapter 收到的 request、轉發給 Merlin 的 payload、原生 SSE event，以及最後回給 client 的 OpenAI response。

如果只想輸出到 console，可以設定：

```text
LOG_TO_FILE=false
```

常用輔助腳本：

- `uv run python scripts/build_log_report.py --log logs/adapter.log --out logs/report.md`

## 延伸文件

- [API reference](docs/api-reference.md)
- [Architecture flow](docs/architecture-flow.md)
- [Development notes](docs/development-notes.md)
- [Troubleshooting](docs/troubleshooting.md)
- [English README](README.md)
