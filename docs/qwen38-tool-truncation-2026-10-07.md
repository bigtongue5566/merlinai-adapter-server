# Qwen 3.8 Max 工具呼叫除錯（2026-10-07）

後續已加入本機續寫方案，見 [Qwen 續寫驗證](qwen38-continuation-2026-10-07.md)。
下方保留初次調查結果；較小工具參數的草稿退回，與後續請模型補完原回應是不同方案。

## 結論

已用 OpenCode 2.0.24 與原始雨夜便利店提示詞重現失敗。Qwen 能呼叫讀取工具，
但 Merlin 在寫檔 JSON 尚未完成時就送出正常 DONE，造成工具參數無法驗證。
目前證據指向上游長輸出被提前結束，沒有耗盡 adapter 設定的 131072 輸出預算。
尚未取得 Merlin 伺服器內部的截斷原因，也未完整解決或部署 NAS。

使用者提示詞保持原文，SHA-256：
`9a60c4499055745812975984a1554837dff96d91a5b560a984ac408bff792cc3`。
OpenCode context 設定維持 1000000。

## 使用者工作階段

檢查 `ses_eecc0f7a2ffd7UrPsgo9TrbmOS` 的匯出檔：

- `<tool_call>image_generate</tool_name>` 僅出現在工作階段標題。
- 實際完成的工具是 `read`，讀取空目錄；沒有 `image_generate` 執行紀錄。
- 後續沒有寫檔工具結果，工作階段最後被中斷。
- 同時段 NAS 日誌顯示，讀取後的寫檔回應反覆出現 invalid JSON；一次協定更正後仍失敗，OpenCode 持續重試。

因此不能將標題當成模型曾執行圖像工具的證據。

## 本機重現與串流核對

測試皆在 Git 忽略的隔離專案進行，未修改使用者 Desktop 專案。

`logs/opencode-scene-e2e-qwen38-v2-debug-a1`：

- `read` 成功：output=145、reasoning=116。
- 下一步 `write` 回應 1419 字元，JSON decoder 報 `Unterminated string`。
- 回應在 JavaScript 檔案內容字串中間結束，沒有關閉字串、外層物件或結尾標記。
- output=666、reasoning=212，遠低於 max_tokens=131072。

`logs/opencode-scene-e2e-qwen38-v2-frames-a2` 額外核對原始 SSE framing：

- 確認送出的 `params.max_tokens=131072`、`params.tools=[]`。
- 失敗回應的原始 text 欄位與 adapter 組裝的答案都是 1441 字元。
- content 欄位沒有另一份遺漏的答案；DONE 的 content 僅是一個空白。
- 上游確實送出 usage、turnUsage、DONE，並非 adapter 因 socket EOF 或 token 上限提前停止。
- 單次更正和 OpenCode 重試繼續產生類似的截斷回應。
- 240 秒隔離測試結束時只完成 read，沒有檔案，protocol_passed=false。

多份回應的 output 減 reasoning 約為 453–456。
這是本次路由的觀測值，不能當成模型官方最大輸出或保證固定的服務限制。

## 長輸出對照

不提供呼叫端工具，要求輸出包含 1 到 400 的完整 JSON 陣列。
所有測試都在陣列中途結束，未通過完整陣列驗證。

| 測試 | 結果 |
| --- | --- |
| extension 8.2.3，max_tokens=131072 | 截斷 |
| 省略空 tools 欄位 | 截斷 |
| 省略 max_tokens | 截斷 |
| isMCPEnabled=false | 截斷 |
| 額外傳 max_output_tokens=131072 | 截斷 |
| 官方已安裝 extension 8.3.0 header | 截斷 |
| 額外傳 max_completion_tokens=131072 | 截斷 |
| 8.3.0 原始碼使用的 max_tokens=10000 | 截斷 |
| 官方非串流 /extension/chat/completions 路徑 | 截斷 |

因此未將上述變更套用到正式 transport，也未改模型上限或 default header。
非串流對照僅收到 content，沒有足以判定 finish reason 的資料。

證據：`logs/qwen-limit-controls.json`、`logs/qwen-83-controls.json`、
`logs/qwen-completions-control.json`。診斷只保留答案及 token 計數，不保留原始推理文字。

## 分步寫檔草稿

探測中的 Qwen 內部指示草稿要求較小的完整工具回合，並讓協定更正要求縮小寫檔增量。
仍保留嚴格 JSON、工具名稱、schema 與 tool_choice 驗證；max_tokens 與 context 不變。

`logs/opencode-scene-e2e-qwen38-v2-checkpoints-b1/report.json`：

- 成功完成 read、write、write，建立並更新 index.html。
- 檔案內容只有 197 bytes 的 HTML loader，尚未建立 main.js 或完成場景。
- 後續請求達到本次診斷的 120 秒整體時限，收到 SSE 504，OpenCode 開始重試。
- 在 440.3 秒停止隔離測試；exit=1，protocol_passed=false。

這只證明較小的工具回合能通過，不能宣稱場景端到端成功或問題已修復。
另一個續寫截斷 JSON 的探測也未取得完成的續寫片段，未加入正式程式。
只有完整驗證通過的回應才能成為工具呼叫。

分步限制沒有通過完整場景測試，因此已從正式程式退回。草稿保留在
`logs/qwen38-short-checkpoint-candidate`，目前 Qwen 正式提示詞與本次除錯前相同。

84 項本機回歸測試通過。上述是未提交的本機調查，NAS 尚未更新。
