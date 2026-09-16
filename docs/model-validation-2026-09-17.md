# Merlin 模型更新與功能測試（2026-09-17）

模型清單由 9 個更新為 17 個；新增 15 個現行模型，移除原清單中 7 個已封存項目，保留 `deepseek-v4-pro` 與 `gpt-5.5`。

資料來源：[Merlin 官方模型設定](https://cdn.jsdelivr.net/gh/foyer-work/cdn-files@latest/merlin_constants.json)，由 [Merlin Chat](https://www.getmerlin.in/chat) 前端的 `MerlinConstants` 查詢引用。以 `textLLMs` 的 `archived=false` 為準。前端 JavaScript 內嵌 enum 仍是舊版本，因此沒有用它作為最終清單。

## 結果

- 首輪 17 模型 × 4 種模式：**62／68 通過**。
- 對 5 個出現異常的模型複測 chat、tool、tool-stream：**11／15 通過**。複測包含新的失敗，不能視為所有問題已恢復。
- API key 驗證、模型清單、請求格式驗證、Python 編譯與 Git whitespace 檢查通過。
- 三份公開文件的模型 ID 與官方未封存清單完全一致。
- 這是少量實際請求的功能抽測，不能據此估算長期成功率。

| 模型 | 一般聊天 | 聊天串流 | 工具呼叫 | 工具串流 | 複測結果 |
| --- | --- | --- | --- | --- | --- |
| `claude-opus-5` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `claude-sonnet-5` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `deepseek-v4-flash` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `deepseek-v4-pro` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `gemini-3.1-flash-lite` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `gemini-3.8-flash` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `glm-5.3` | 預期文字未出現 | 通過 | 通過 | 通過 | chat: 通過；tool: HTTP 422；tool-stream: 通過 |
| `glm-5.3-flash` | 通過 | 通過 | 通過 | HTTP 422 | chat: 通過；tool: HTTP 422；tool-stream: HTTP 422 |
| `gpt-5.5` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `gpt-5.6-luna` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `gpt-5.6-sol` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `gpt-5.6-terra` | 通過 | 通過 | HTTP 422 | HTTP 422 | chat: 預期文字未出現；tool: 通過；tool-stream: 通過 |
| `gpt-6-astra` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `grok-4.6` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `kimi-k3` | 通過 | 通過 | 通過 | 通過 | 未重測 |
| `minimax-m3` | 預期文字未出現 | 通過 | 通過 | 通過 | chat: 通過；tool: 通過；tool-stream: 通過 |
| `qwen-3.8-max` | 通過 | 通過 | HTTP 422 | 通過 | chat: 通過；tool: 通過；tool-stream: 通過 |

## 異常判讀

`HTTP 422` 表示工具呼叫為 required，但經現有修復重試後仍沒有可用的工具 JSON。Terra 診斷中，上游直接表示 `echo_probe` 不存在於此聊天，沒有產生工具呼叫；adapter 因而拒絕把純文字當成工具成功。Terra 後續工具複測可通過，GLM 5.3／5.3 Flash 則仍出現工具失敗，顯示相容性不穩定。Qwen 的工具失敗在複測中未重現。

「預期文字未出現」表示 HTTP 200 的內容沒有包含指定的 `MERLIN_SMOKE_OK`；這是回覆內容檢查失敗，不等同於網路中斷。GLM 5.3、MiniMax M3 在首輪發生，複測聊天通過；Terra 在複測聊天出現同類失敗。

本次只更新模型清單與文件，並新增驗證腳本；沒有變更既有工具提示、解析或重試策略。需要工具呼叫時，可先使用本輪四種模式均通過的 `gpt-5.6-sol`、`gpt-6-astra` 或 Claude 5；此測試不保證後續每次成功。

## 測試方法與重現

使用 FastAPI `TestClient` 經 adapter 呼叫真實 Merlin 上游，載入既有 `.env`，沒有 mock 回覆。檢查回覆 schema、模型欄位、測試字串、SSE `[DONE]` 與 finish reason，以及工具名稱、JSON 參數及 call ID。工具僅產生呼叫描述，不執行外部工具。未驗證已部署的服務、反向代理或真實網路上的首 token 延遲。

```bash
uv run python scripts/smoke_test_models.py --modes chat chat-stream tool tool-stream --workers 3 --out logs/model-refresh/all-models.json
uv run python scripts/smoke_test_models.py --models glm-5.3 glm-5.3-flash gpt-5.6-terra minimax-m3 qwen-3.8-max --modes chat tool tool-stream --workers 2 --out logs/model-refresh/recheck.json
```

會使用 Merlin 帳號額度。腳本遇到任何失敗會以 exit code 1 結束，不會用重測覆蓋首輪結果。

本機詳細紀錄（`logs/` 不納入 Git）：

- 首輪：`logs/model-refresh/all-models.json`
- 複測：`logs/model-refresh/recheck.json`
- 工具診斷：`logs/model-refresh/tool-diagnostics.json`
- 官方設定快照：`logs/model-refresh/merlin_constants.json`

官方設定快照 SHA-256：`d7963532680db4de3d06a5537e58a7cd26df54138786a5e65ec83d9aade7df6c`。
