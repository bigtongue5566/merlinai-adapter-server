# Merlin 模型清單更新與驗證（2026-10-03）

模型清單由 17 個更新為 23 個。依 [Merlin 官方設定](https://cdn.jsdelivr.net/gh/foyer-work/cdn-files@latest/merlin_constants.json) 的 `textLLMs` 中 `archived=false` 選取，原有 17 個模型仍在現行清單，新增：

- `claude-opus-5.5`
- `claude-sonnet-5.5`
- `gpt-6-luna`
- `gpt-6-sol`
- `gpt-6.1-sol`
- `grok-4.7`

`MODEL_LIMITS`、`/v1/models`、中英文 README、API reference 與研究腳本已同步。容量依本次下載的 [models.dev API](https://models.dev/api.json) 原廠 provider 精確紀錄更新，Claude 5.5 使用明確的原廠拼字映射。完整容量及差異見 [模型上限表](model-limits-2026-10-03.md) 與 [機器可讀快照](model-limits-2026-10-03.json)。

## 驗證結果

- 既有本機單元／合約測試：**81／81 通過**，涵蓋各模型容量發布、預設輸出預算、串流／非串流、native／emulated 傳輸及超額請求拒絕。
- 新增 6 個模型 × 一般聊天／聊天串流：**12／12 真實上游測試通過**。
- 容量變動的 4 個模型 × 一般聊天／聊天串流：**8／8 真實上游測試通過**。
- 官方現行清單、adapter 回傳清單及三份公開文件的 23 個 ID 完全一致，沒有重複或封存模型。
- API key 驗證、請求格式驗證、公開容量與來源 SHA-256 核對通過。

| 模型 | 本次範圍 | 傳送 max_tokens | 一般聊天 | 聊天串流 |
| --- | --- | ---: | --- | --- |
| `claude-opus-5.5` | 新增模型 | 128,000 | 通過 | 通過 |
| `claude-sonnet-5.5` | 新增模型 | 128,000 | 通過 | 通過 |
| `gpt-6-luna` | 新增模型 | 128,000 | 通過 | 通過 |
| `gpt-6-sol` | 新增模型 | 128,000 | 通過 | 通過 |
| `gpt-6.1-sol` | 新增模型 | 128,000 | 通過 | 通過 |
| `grok-4.7` | 新增模型 | 500,000 | 通過 | 通過 |
| `deepseek-v4-flash` | Output 更新 | 393,216 | 通過 | 通過 |
| `deepseek-v4-pro` | Output 更新 | 393,216 | 通過 | 通過 |
| `kimi-k3` | Output 更新 | 1,048,576 | 通過 | 通過 |
| `minimax-m3` | Context 更新 | 512,000 | 通過 | 通過 |

## 測試方法與範圍

使用本機 FastAPI `TestClient` 經 adapter 呼叫真實 Merlin 上游，載入既有 `.env`，沒有 mock 聊天回覆。測試模式設定為 `emulated`，本次請求沒有工具；驗證 HTTP 狀態、回覆 schema、模型 ID、`MERLIN_SMOKE_OK`、usage 與 finish reason。串流另驗證每個 chunk、沒有 SSE error 且以 `[DONE]` 正常結束。

這是新模型與容量變動模型的少量聊天抽測，沒有重測其他 13 個模型的真實上游回覆、工具呼叫或 OpenCode 檔案操作。上游接受這些 `max_tokens` 的短回覆，不代表已驗證能實際產生到最大 output 或填滿 context。

本次完成本機程式與文件更新；這份紀錄不構成已部署服務的驗證。

## 重現

```bash
uv run python -m unittest discover -s tests -q
uv run python scripts/smoke_test_models.py --models claude-opus-5.5 claude-sonnet-5.5 gpt-6-luna gpt-6-sol gpt-6.1-sol grok-4.7 --modes chat chat-stream --workers 2 --out logs/model-catalog-2026-10-03/new-models-smoke.json
uv run python scripts/smoke_test_models.py --models deepseek-v4-flash deepseek-v4-pro kimi-k3 minimax-m3 --modes chat chat-stream --workers 2 --out logs/model-catalog-2026-10-03/changed-limits-smoke.json
```

本次使用既有 `.venv/Scripts/python.exe` 執行；真實上游測試會使用 Merlin 帳號額度，腳本遇到任何失敗會以 exit code 1 結束。

本機詳細紀錄（`logs/` 不納入 Git）：

- 新增模型實測：`logs/model-catalog-2026-10-03/new-models-smoke.json`
- 容量變動模型實測：`logs/model-catalog-2026-10-03/changed-limits-smoke.json`
- 清單及來源一致性核對：`logs/model-catalog-2026-10-03/catalog-verification.json`
- Merlin 官方設定快照：`logs/model-catalog-2026-10-03/merlin_constants.json`
- 容量來源完整快照：`logs/models-dev-2026-10-03.json`

Merlin 官方設定 SHA-256：`81d68044a8b7bea02622bbbe388c2f18fb9784bdb147bf6f0febd3a955f5aa41`。

models.dev SHA-256：`0c8a1d4e6374b5a5765c76da38aa5d32fdbd3200a53ba28ea2b3a82ac490aa7b`。
