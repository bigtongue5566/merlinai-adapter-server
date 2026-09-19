# 工具模擬模式

工具模擬沿用新版 `/arcane/api/v2/extension/chat` 傳輸，將呼叫端的工具規格
放進提示詞，驗證模型輸出的 JSON，再轉成 OpenAI `tool_calls` 交由呼叫端執行。
adapter 不執行工具，也不加入 Merlin extension 的瀏覽器或 MCP 工具。

## 啟用與切換

在 `.env` 設定並重新啟動 adapter：

```dotenv
TOOL_CALL_MODE=emulated
```

`native` 是程式預設值，直接把工具交給 Merlin；`emulated` 使用文字協定。
不接受其他值，不會在原生失敗時偷偷改模式或自動重送請求。
本機工作區的 `.env` 已設為 `emulated`；部署環境需另行設定並重新啟動。

沒有工具或 `tool_choice=none` 時，不加入工具輸出協定，也不把模型的 JSON
文字解析成工具呼叫。若前文含工具回合，仍轉成帶有 call ID 的文字紀錄，
讓模型理解先前結果。

## 工具選擇

| `tool_choice` | `native` | `emulated` |
| --- | --- | --- |
| 省略／`null`／`auto` | 轉送呼叫端工具 | 可選擇工具呼叫或最終回答 |
| `none` | 不提供工具 | 不提供工具、不解析工具 JSON |
| `required` | 請求回 422 | 必須產生至少一個合法工具呼叫 |
| 指定 function 物件 | 請求回 422 | 只能呼叫指定且已宣告的工具 |

`required` 未提供工具、指定未宣告名稱、重複工具名稱、非 function 工具、
不合法參數 schema 或不支援的選擇方式會在上游請求前回 422。
不使用非標準 `function:name` 字串，請使用 OpenAI function 選擇物件。

## 協定與檢查

提示詞要求模型輸出單一完整 `<OPENAI_TOOL_PAYLOAD>` 區塊，內含以下其中一種 JSON：

```json
{"type":"tool_calls","tool_calls":[{"name":"read","arguments":{"filePath":"notes.txt"}}]}
```

```json
{"type":"message","content":"最終回答"}
```

- 僅解析明確啟用模擬模式且帶有工具的請求。
- 容許單一完整區塊前後有解說文字；區塊外文字不會變成工具或回答。
- 若有開始標記、JSON 已完整結束且後面只有空白，容許省略結尾文字標記。
  不補 JSON 括號、不補字串、不修復參數。JSON 字串內的標記視為普通內容。
- 拒絕截斷 JSON、缺少開始標記、重複 JSON key、多個區塊、非有限數字、混合回答與呼叫、
  空呼叫清單、未宣告名稱及不符合 `tool_choice` 的回覆。
- 使用 `jsonschema` 驗證 arguments，包含 required、型別、enum、巢狀結構、
  additionalProperties 等條件；支援本地 `#/$defs/...` 引用，禁止遠端 schema
  引用及下載。`format` 依 jsonschema 預設作為註記，不額外驗證。
- 不使用舊版 JSON repair、不猜參數、不忽略錯誤呼叫，也不自動重試。
- 回應不合法時非串流回 502；串流送 error，沒有成功 finish 或 `[DONE]`。

收到合法呼叫後，adapter 建立唯一 call ID。呼叫端執行工具，再送回 assistant
工具呼叫歷史及 `role=tool` 結果。下一輪將工具呼叫改成 assistant 文字紀錄，
將工具結果改成 user 文字紀錄，包含原始 call ID、工具名稱（若有）及完整內容。
一般 system／developer／user／assistant 訊息維持原順序，不做舊版字數裁切。
有工具時另在末尾加入 system 格式提醒，避免 agent 的回覆風格要求蓋過工具協定，
提醒長程式碼使用正確 JSON 跳脫與分步呼叫。
這些工具紀錄只是傳輸表示，不改寫呼叫端的原始 messages。

這是文字工具協定。工具結果中的圖片等內容會作為 JSON 資料表示，並非已驗證
的多模態工具支援。格式正確不保證工具選擇或參數在任務語意上正確；實際
執行權限仍由 OpenCode 等呼叫端管理。

## 串流行為

一般無工具聊天繼續即時串流。工具模擬回合先送 assistant role，接著暫存
整份上游文字，直到上游正常 DONE 且完整 JSON／參數驗證通過，才送出工具
或最終文字 chunk、finish、可選 usage 與 `[DONE]`。因此工具回合的內容不是
逐 token 即時顯示；截斷或後續出錯的 JSON 不會提前變成可執行呼叫。

usage 保留上游數值，包含模擬協定文字產生的 token；不能當作已核對的帳單。
格式驗證失敗會記錄 model、文字長度、是否有標記、max_tokens、output_tokens 與
錯誤種類；這項 warning 不包含提示詞、檔案內容或工具結果。

## 驗證與重跑

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -q
.venv\Scripts\python.exe scripts/smoke_test_opencode.py --config "$env:USERPROFILE\.config\opencode\opencode.jsonc" --tool-call-mode emulated --out logs/opencode-emulated.json
.venv\Scripts\python.exe scripts/smoke_test_models.py --models gpt-5.6-luna claude-sonnet-5 --modes tool tool-stream --workers 1 --out logs/emulated-tools-api.json
```

最後一個命令使用 `.env` 的模式；兩個真實 smoke 腳本都會使用帳號配額。
完整實測結果見 [OpenCode 驗證紀錄](opencode-validation-2026-09-19.md)。
