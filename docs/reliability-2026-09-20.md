# 請求可靠性改造（2026-09-20）

此改造保留 OpenAI 相容介面及 Merlin extension transport，把格式恢復、預算、取消與使用量分開管理。
原始使用者提示詞不變；尚未驗證的 Merlin 推理參數仍不接受。

## 已實作

- `emulated_recovery.py`：型別化協定錯誤、最多一次模型更正。只處理完整收到上游結束事件、
  非空、有輸出 usage、未耗盡預算的格式／schema 錯誤；不執行工具、不自動修 JSON。
- `merlin_client.py`：串流與非串流共用相同驗證／更正流程；更正前不釋出任何工具。
  每次更正使用 `原請求上限 - 第一次實際輸出`，不偷偷增加原請求輸出 allowance。
- `request_budget.py`：整體時限、解析後 SSE 資料量上限、可中止的 socket 讀取。
  串流消費者中斷時會取消上游，尚未開始迭代的連線也可關閉。
- `response_usage.py`：統一 token 欄位解析，合計更正前後 input/output，提供可用的 reasoning 明細。
  reasoning 已包含在 output，不能重複計入 total；不把布林值當 token 數。
- 一般完成流程不再保留 raw reasoning event 與 SSE JSON 的雙份副本，僅保留事件長度／數量摘要。
  DEBUG 的 caller payload 仍可能含專案資料；不是全面去敏感資料的日誌模式。
- adapter 指令要求先寫小型可运行骨架、再逐步擴充，且只能輸出文字協定。
  這是軟性工作流程指示，不是硬性推理 token 限制。
- 上游錯誤工具名稱可能包含整份程式碼，API 錯誤現在只回固定診斷，不再把該內容全部回顯。

## 設定

| 設定 | 預設 | 行為 |
| --- | ---: | --- |
| `COMPLETION_TIMEOUT_SECONDS` | 600 | 原請求與更正共用的整體時限（秒） |
| `COMPLETION_MAX_BYTES` | 16777216 | 已解析 SSE 資料量上限（bytes），包含更正 |
| `EMULATED_CORRECTION_ATTEMPTS` | 1 | 只接受 0 或 1，0 停用 |

socket 閒置讀取仍受 `MERLIN_REQUEST_TIMEOUT_SECONDS` 約束。整體計時在完成請求的 transport
階段開始；Firebase 登入／刷新仍有獨立 timeout，返回後會再次檢查剩餘時間。
輸出用量未提供時不進行更正，避免以未知消耗量開啟額外請求。
取消處理針對串流路徑；非串流呼叫仍受時限管理，未宣稱已完成全面 async transport 改造。

## 模型上限

[17 個模型上限表](model-limits-2026-09-20.md)及 [JSON 快照](model-limits-2026-09-20.json)
來自 models.dev 的原廠 provider 紀錄。GLM 5.3／Flash 是 131072，**不代表已驗證 Merlin 可用到此上限**。

Adapter 現在由 `models_catalog.py` 的 `MODEL_MAX_OUTPUT_TOKENS` 統一設定 17 個模型上限。
未指定／null 使用該模型上限；明確指定不超過上限的值原樣傳遞，超限在連線前回 422。
未知模型保留 10000 預設及原有明確值透傳。更正與預算耗盡診斷使用同一個有效上限。
OpenCode 的 32000 預設上限需由呼叫端調整，因此新增隔離驗證腳本：

```powershell
$env:COMPLETION_TIMEOUT_SECONDS='1200'
.venv\Scripts\python.exe scripts/run_opencode_task.py --tag glm-large --model glm-5.3 --max-output-tokens 131072 --context-tokens 1000000 --timeout 1200 --prompt-file path/to/original-prompt.txt
```

此腳本只改子程序環境／內嵌設定，使用空白隔離 Git 專案。它會真的呼叫 Merlin 並讓 OpenCode
執行允許的工具，消耗帳號配額；`logs/` 可包含原始提示詞、模型程式碼、工具輸入及本機路徑。
不保存原始推理文字，也不改全域 OpenCode 設定。`protocol_passed` 只代表協定完整，
不能代替場景內容、語法與實際瀏覽器驗證。

## 驗證紀錄

離線測試涵蓋更正成功／再次失敗、共享預算、未知工具、tool_choice、多區塊、缺 usage、
EOF／上游錯誤、串流／非串流一致性、大小上限、阻塞 socket deadline 與 ASGI 取消。
目前 69 項通過，Python 編譯、CLI help、模型快照比對及 diff whitespace 檢查通過。

合成 10001 個 SSE 事件的 `tracemalloc` 局部比較：舊 raw collection 峰值 15892473 bytes，
新 summary collection 4247112 bytes，下降 73.3%。輸入、gateway/parser 相同，
分別執行舊 `_read_event_stream` 與新 `_read_response`；輸入 buffer 在開始追蹤前建立。
此測量只比較回應收集的 Python 配置峰值，不是服務 RSS、併發容量或真實模型效能基準。
紀錄：`logs/response-memory-comparison.json`。

真實上游 Luna、Sonnet：聊天、聊天串流、工具、工具串流共 8/8 通過，
紀錄在 `logs/reliability-smoke-20260920.json`。這是協定 smoke，不是完整場景驗收。

原始場景提示詞文字 SHA-256：
`9a60c4499055745812975984a1554837dff96d91a5b560a984ac408bff792cc3`。

| 測試 | 輸出上限 | 結果 |
| --- | ---: | --- |
| `glm53-recovery-b1` | 32000 | 第二輪 reasoning=31997、空白回答，290.31 秒失敗 |
| `glm53-recovery-b2` | 32000 | 更正成功並進入多輪寫檔；程序中斷、無最終報告，不算通過 |
| `glm53-recovery-64k-b3` | 65536 | 多輪寫檔，留下 16852-byte HTML；程序中斷、無最終報告，不算通過 |
| `glm53-final-64k-c1` | 65536 | 223.30 秒；read/write 成功建立 2076-byte 骨架，後續上游工具名稱混入程式碼，拒絕執行 |
| `glm53-final-128k-c2` | 131072 | 605.36 秒正常結束，19 個 OpenCode 請求全部完成；產生 21673-byte HTML，最終 JavaScript 語法檢查通過 |

例如 b2 第二輪未包協定標記，原輸出 5936 tokens；更正回合 1612 tokens、reasoning=58，
產生合法工具呼叫並交由 OpenCode 執行。這證明更正流程有實際收益，但不代表完整任務穩定成功。
64K 完整測試失敗原因是上游錯誤工具事件，並非 token 耗盡；單純拉高預算不足以修復該失敗。

131072 測試共 23 次上游請求，包含 **4 次協定更正，全數成功**；每個 OpenCode 請求仍最多更正一次。
42 次工具操作中 40 次成功；2 次 bash 操作被隔離測試權限拒絕，模型收到錯誤後繼續，
最後使用允許的方式完成語法檢查並正常回答。這不是 adapter 放寬工具權限的結果。

上游 usage 合計 input=834056、output=114969、reasoning=94402、cached=777600。
這些是逐次上游回報的加總，包含更正與重複上下文，不是已核對帳單。
**最高單輪 output 只有 25111**：雖然每個呼叫端請求已確認送出 `max_tokens=131072`，
不能由這次成功推斷「必須提高上限才成功」，也不能證明 Merlin 能實際產生完整 131072 tokens。
流程分段、模型非確定性及協定更正均可能影響結果；未做固定種子的單變量成功率比較。

最終輸出：`logs/opencode-scene-e2e-glm53-final-128k-c2/project/index.html`。
SHA-256：`4afa71d63aa332ba1460a9efec4ccdd3ae9dbb3003b462dc8823b07991f58a95`。
`report.json` 為完整 OpenCode 紀錄，`static-check.json` 記錄最終 HTML 的獨立 `node --check` 結果。
未做瀏覽器畫面／互動驗收，也未多次重跑確認穩定成功率。因此結論是：
**此配置下已有一次完整 OpenCode 產檔及語法檢查成功，尚非穩定性或視覺品質保證。**
此版本未部署 NAS、未更動全域 OpenCode 設定。
