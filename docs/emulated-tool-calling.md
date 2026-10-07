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
- `auto`（含省略／null）容許無標記的非空普通最終文字，保留原文字與空白，
  回 `finish_reason=stop`，不建立工具呼叫。仍須上游正常 DONE。
- 純文字相容路徑不接受疑似協定標記、JSON／工具結構，或輸出 token 已達上限的
  無標記回答；不會把損壞的呼叫改成文字成功。required／指定工具仍要求合法呼叫。
- 容許單一完整區塊前後有解說文字；區塊外文字不會變成工具或回答。
- 若有開始標記、JSON 已完整結束且後面只有空白，容許省略結尾文字標記。
  不補 JSON 括號、不補字串、不修復參數。JSON 字串內的標記視為普通內容。
- 未能完整續寫的截斷 JSON、結構化回覆缺少開始標記、重複 JSON key、多個區塊、非有限數字、混合回答與呼叫、
  空呼叫清單、未宣告名稱及不符合 `tool_choice` 的回覆。
- 使用 `jsonschema` 驗證 arguments，包含 required、型別、enum、巢狀結構、
  additionalProperties 等條件；支援本地 `#/$defs/...` 引用，禁止遠端 schema
  引用及下載。`format` 依 jsonschema 預設作為註記，不額外驗證。
- 不使用舊版 JSON repair、不猜參數、不忽略錯誤呼叫。非空、未耗盡預算且有完整 usage 的
  格式／schema 錯誤可交回模型更正一次；更正仍須通過完整驗證，並共享原始輸出預算與時限。
  未宣告工具、tool_choice 違反、多個區塊、上游錯誤、空白回應不進行更正。
- 回應不合法時非串流回 502；串流送 error，沒有成功 finish 或 `[DONE]`。

Qwen 3.8 Max 的上游有時在工具 JSON 中途送出 DONE。對仍可由追加文字完成的
JSON 前綴，adapter 保留原對話、工具 schema 與已收到的文字，另請模型續寫缺少的
後綴。續寫時只改 adapter 自己的兩段輸出指示，避免完整 envelope 規則與後綴規則
衝突。每個模型產生的片段必須是正常 DONE 的完整上游回應；adapter 原字拼接，
直到整份 JSON、工具名稱、schema 和 tool_choice 全部通過，才釋出呼叫。

不會補括號、修正跳脫或猜測檔案內容。新片段若引入錯誤 JSON，整片丟棄，請模型
重寫一次；有效進展後下一片可再獲一次重寫機會，但所有請求都計入續寫次數上限。
未宣告工具、tool_choice 違反、多個 envelope、傳輸失敗、空片段及缺少 output usage
直接失敗。普通無工具對話不啟用自動續寫，因為正常 DONE 的純文字未必能辨識是否截斷。

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

usage 包含模擬協定文字產生的 token；更正／續寫成功時合計全部請求，包括被丟棄的片段。
上游有提供推理計數時，另輸出 `completion_tokens_details.reasoning_tokens`；每次計數必須都存在才合計此欄位。
推理已包含於 completion_tokens，不能再加一次。這些計數不能當作已核對的帳單。
格式驗證失敗會記錄 model、文字長度、是否有標記、max_tokens、output_tokens 與
reasoning_tokens、錯誤種類；這項 warning 不包含提示詞、檔案內容或工具結果。
空文字與沒有完整回覆且用滿上游輸出預算分別報錯，不再一概說缺少標記。
budget 診斷依上游 usage 判斷，並不代表 adapter 能控制 Merlin 的思考強度。

`reasoning_effort`、`thinking`、`reasoning` 的非 null 設定會在上游請求前回 422，
說明 Merlin extension 傳輸尚未確認支援，避免默默忽略。null 視為未設定。
使用者原始 messages 與 OpenCode 全域設定不變；adapter 內部新增短步驟與先寫可运行骨架的指示。
不自動提高 max_tokens。GLM 大上限測試與 models.dev 目錄上限見 [模型上限](model-limits-2026-09-20.md)。

`EMULATED_CORRECTION_ATTEMPTS=0` 可停用更正，預設 1。更正最多使用
原請求剩餘輸出預算，沒有另一個固定上限；低於 256 不更正。Qwen 剩餘預算須至少 16385。
`EMULATED_CONTINUATION_ATTEMPTS=8` 控制 Qwen 續寫請求數，範圍 0–16；0 停用。
兩個選項都設 0 可停用全部協定恢復。續寫也使用原請求的剩餘 output 預算、共同時限
和共同 SSE 資料量上限；合併文字最多 65536 字元。每片約 300 答案 tokens 只是內部
指示的目標，不會取代模型自己的 max_tokens 設定。候選片段尚未驗證時不會執行工具。
拒絕回應超過 65536 字元時不重送內容。`COMPLETION_TIMEOUT_SECONDS=600` 限制整個請求，
`COMPLETION_MAX_BYTES=16777216` 限制已解析 SSE 資料量；串流斷線會中止上游讀取。

## 驗證與重跑

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -q
.venv\Scripts\python.exe scripts/smoke_test_opencode.py --config "$env:USERPROFILE\.config\opencode\opencode.jsonc" --tool-call-mode emulated --out logs/opencode-emulated.json
.venv\Scripts\python.exe scripts/smoke_test_models.py --models gpt-5.6-luna claude-sonnet-5 --modes tool tool-stream --workers 1 --out logs/emulated-tools-api.json
```

最後一個命令使用 `.env` 的模式；兩個真實 smoke 腳本都會使用帳號配額。
完整實測結果見 [OpenCode 驗證紀錄](opencode-validation-2026-09-19.md)。

Qwen3.8 Max 使用單一工具封包：`{"type":"tool_call","name":"read","arguments":{"filePath":"notes.txt"}}`，仍包在相同標記內並完整驗證 JSON、schema 與 tool_choice。既有批次封包仍可驗證，其他模型的協定不變。
# Gemini 3.8 transport compatibility

When no native tools are supplied, Gemini 3.8 Flash requires the upstream `params.tools` field to be omitted instead of an empty array. The adapter applies this exception while retaining text-emulated tool schemas and the model-specific token budget. Nonempty native tool lists are preserved.
