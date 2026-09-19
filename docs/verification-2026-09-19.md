# Extension adapter 驗證紀錄（2026-09-19）

結論：離線 29 項測試通過；17 個模型的聊天／串流首輪通過 28/34。
Minimax 的兩項逾時在複測恢復，綜合本次結果有 15/17 個模型通過兩種模式；
Gemini 3.8 Flash 與 Qwen 3.8 Max 持續收到上游錯誤，不能宣稱全部模型正常。

## 環境與範圍

- 驗證對象：本機未提交工作區，基於 `54cce21`，包含 extension 遷移與架構修正。
- 請求版本：`merlin-extension-8.2.3`；endpoint：`/arcane/api/v2/extension/chat`。
- 路徑：FastAPI `TestClient` → adapter → 真實 Merlin 上游，沒有 mock 上游。
- 一般 smoke：要求回覆 `MERLIN_SMOKE_OK`，`max_tokens=1000`，兩個並行 worker。
- 串流另檢查回應 schema、model／ID、assistant role、完成原因、usage chunk、
  回覆標記及 `[DONE]`。只檢查 usage 存在，沒有驗證帳務數字準確性。
- 所有真實請求均未攜帶工具；沒有新增或執行 extension 瀏覽器／MCP 工具。
- 這是本機程式與真實上游的功能驗證，未驗證已部署服務、持續負載或長期穩定性。

## 模型矩陣

以下為首輪結果；逾時與複測保留各自紀錄，不覆蓋失敗樣本。

| 模型 | 聊天 | 串流 | 複測／診斷 |
| --- | --- | --- | --- |
| `claude-opus-5` | 通過 | 通過 | — |
| `claude-sonnet-5` | 通過 | 通過 | 多輪通過 |
| `deepseek-v4-flash` | 通過 | 通過 | — |
| `deepseek-v4-pro` | 通過 | 通過 | — |
| `gemini-3.1-flash-lite` | 通過 | 通過 | — |
| `gemini-3.8-flash` | HTTP 502 | HTTP 200，未成功完成 | 兩模式再測仍失敗；原始 SSE 有上游 error |
| `glm-5.3` | 通過 | 通過 | — |
| `glm-5.3-flash` | 通過 | 通過 | — |
| `gpt-5.5` | 通過 | 通過 | — |
| `gpt-5.6-luna` | 通過 | 通過 | 多輪通過 |
| `gpt-5.6-sol` | 通過 | 通過 | — |
| `gpt-5.6-terra` | 通過 | 通過 | — |
| `gpt-6-astra` | 通過 | 通過 | — |
| `grok-4.6` | 通過 | 通過 | — |
| `kimi-k3` | 通過 | 通過 | 串流約 34.92 秒，僅單次觀測 |
| `minimax-m3` | HTTP 504，約 45 秒 | HTTP 504，約 45 秒 | 後續兩輪的兩模式均通過 |
| `qwen-3.8-max` | HTTP 502 | HTTP 200，未成功完成 | 原始 SSE 複測仍有上游 error |

### Gemini／Qwen

直接經 gateway 檢查原始 SSE，兩模型在 `max_tokens=1000` 與 `10000` 均為：

- 上游 HTTP 200。
- `event: error`，錯誤類型 `INTERNAL_SERVER_ERROR`。
- 後續仍有 `event: message`，內含 `eventType: DONE`。

因此 HTTP 200 或上游 DONE 都不足以代表成功。adapter 將已發生的 error
視為失敗，沒有再對客戶端送出成功的 `[DONE]`。首輪 smoke 的
`Missing SSE terminator` 是失敗摘要，並非證明資料傳輸遭截斷。
以上排除了僅因本次 1,000 輸出上限造成錯誤的解釋，尚不能區分供應商故障、
帳號限制或這兩個模型需要不同請求條件。

### Minimax

先以僅限測試程序的 90 秒 timeout 重測，兩模式約 2.05／2.06 秒通過；
再恢復預設 45 秒，兩模式約 2.22／2.25 秒通過。較符合暫時性逾時，
沒有證據顯示必須放寬 timeout；未修改 `.env` 或正式預設值。

## 其他驗證

- `python -m unittest discover -s tests -v`：29/29 通過，涵蓋 parser、原生請求、
  HTTP／SSE 錯誤處理、工具契約及歷史保留。
- `python -m compileall -q main.py merlinai_adapter_server scripts tests`：通過。
- `git diff --check`：通過。
- `/v1/models`、聊天 API 未授權請求回 401；模型清單與 catalog 一致且無重複；
  缺少必要欄位回 422。
- `gpt-5.6-luna` 與 `claude-sonnet-5` 的四訊息多輪測試：2/2 通過，
  能依 system 指示回覆先前保存的代碼。
- 後續 [OpenCode 實測](opencode-validation-2026-09-19.md)：Luna／Sonnet 的
  文字與多輪 4/4 通過，`read` 自訂工具 0/2，均收到上游 SSE error；
  原生 function calling 尚無成功證據。之後加入的 `emulated` 模式已通過兩模型
  OpenCode 讀檔後回答完整回合 2/2；詳見同份 OpenCode 紀錄的更新段落。
  多模態與長時間壓測仍未驗證。

## 可重跑命令與本機證據

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q main.py merlinai_adapter_server scripts tests
.venv\Scripts\python.exe scripts/smoke_test_models.py --modes chat chat-stream --workers 2 --out logs/verification-all-models-20260919.json
```

真實 smoke 會使用帳號配額，結果可能隨上游狀態變動。這次報告存於 Git ignored
的 `logs/`，不包含憑證或完整上游回應：

- `verification-all-models-20260919.json`：首輪 28/34。
- `verification-gemini-recheck-20260919.json`：Gemini 再測 0/2。
- `verification-failed-models-native-20260919.json`：Gemini／Qwen 原始事件類型與錯誤識別。
- `verification-minimax-90s-20260919.json`：90 秒設定複測 2/2。
- `verification-minimax-default-20260919.json`：預設 45 秒複測 2/2。
- `architecture-multiturn-20260919.json`：本次重跑多輪 2/2。
