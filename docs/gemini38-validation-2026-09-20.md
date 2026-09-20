# Gemini 3.8 Flash 實測（2026-09-20）

## 已定位並修正：空工具陣列

後续隔離測試推翻了「模型路由本身不可用」的推測：相同訊息 `Reply exactly OK.`，保持 max_tokens=65536 與 metadata.isMCPEnabled=true，只省略 params.tools=[] 就正常回覆 OK。
保留空工具陣列時，65536、32768、8192、甚至省略 max_tokens 都失敗；單獨關閉 MCP 也失敗。因此不是輸出上限過高或 MCP 旗標造成。
原始 SSE error 的 type 是 INTERNAL_SERVER_ERROR；HTTP 本身為 200。使用者提供的成功 HAR 使用相同模型與 endpoint，但有非空工具清單，與此結果一致。

adapter 現在僅針對 gemini-3.8-flash 省略空工具欄位，保留實際 native 工具清單、模型預算和 MCP 設定。
修正後 `logs/gemini38-emptytools-fix-controls.json`：聊天、串流聊天、工具、串流工具全部通過，均使用 65536。81 項回歸測試通過。
原雨夜便利店覆驗 `logs/opencode-scene-e2e-gemini38-emptytools-i1/report.json`：109.63 秒，16 次上游回應均有內容，已能執行多輪工具與產檔，但後續長內容工具 JSON 及一次更正仍不合法，任務未完成。此剩餘協定生成問題與先前空工具欄位觸發的 INTERNAL_SERVER_ERROR 不同；不可將部分 dist 產物當成完成場景。
隔離測試紀錄：`logs/gemini-diagnostic-matrix.json`、`logs/gemini-diagnostic-flags.json`。HAR 含私人資訊，不納入專案紀錄。

下方保留先前失敗紀錄，當時尚未隔離出空工具欄位差異；不應再据此認定 Gemini 一般對話不可用。

## 最新覆驗 h1

Qwen 雨夜便利店完成後，以目前 adapter 重跑相同原始提示詞；自動讀取 Gemini output=65536、context=1048576。
`logs/opencode-scene-e2e-gemini38-current-h1/report.json`：4.14 秒失敗，第一個上游請求即 SSE error，零工具呼叫、零檔案、無回答或 usage。提示詞 hash 與下方相同。

這次短請求對照也使用各模型的正常上限，沒有沿用早期 1000：
`logs/gemini38-modelbudget-controls-h1.json` 中 Gemini 65536 的聊天與串流皆失敗（1.20／1.33 秒），Luna 128000 的相同兩項測試皆成功（1.64／1.88 秒）。
因此目前尚無 Gemini 成功產生場景的證據；錯誤發生在工具 JSON 驗證之前，無法歸因為 JSON 格式或推理预算耗盡。Merlin 未提供足夠資訊確定根因，不應以 Qwen 的低預算邊界推論 Gemini。沒有修改程式、原提示詞或 NAS。

## 前次測試

使用本機目前 adapter、emulated 模式、真正的 OpenCode build agent，
原始雨夜便利店提示詞不變。隔離專案輸出上限 65536、context 設定 1048576。
提示詞 SHA-256：`9a60c4499055745812975984a1554837dff96d91a5b560a984ac408bff792cc3`。

| 測試 | max_tokens | 結果 |
| --- | ---: | --- |
| Gemini 3.8 Flash／原始 OpenCode 場景 | 65536 | 4.22 秒失敗，上游 SSE error；無工具、無檔案、無回答及 usage |
| Gemini 3.8 Flash／簡短聊天 | 1000 | 1.33 秒失敗，HTTP 502／上游 SSE error |
| Gemini 3.8 Flash／簡短聊天串流 | 1000 | 1.17 秒失敗，上游 SSE error，未發送成功 DONE |
| GPT 5.6 Luna／相同簡短聊天對照 | 1000 | 1.91 秒成功 |
| GPT 5.6 Luna／相同聊天串流對照 | 1000 | 1.69 秒成功 |

短請求沒有場景工具 schema；失敗因此不是只出現在複雜提示詞或 65536 上限。
目前證據指向 Merlin 的 Gemini 模型路由／供應商端失敗，並非 adapter JSON 更正失敗，
也没有 usage 證據顯示推理預算耗盡。Luna 對照成功表示這不是本次所有請求都失效。
上游錯誤沒有提供足以確定更深層原因的資訊；不能斷言是特定配額、停機或模型不存在。

沒有調整原提示詞、切換場景測試模型、修補生成檔案或部署 NAS。
原始紀錄：`logs/opencode-scene-e2e-gemini38-flash-current-d1/report.json`、
`logs/opencode-scene-e2e-gemini38-flash-current-d1/upstream-1.json`、
`logs/gemini38-current-controls.json`。
