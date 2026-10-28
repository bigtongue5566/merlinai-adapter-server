# Web transport

預設為 `MERLIN_TRANSPORT=web`。Web 使用 `/arcane/api/v2/thread/unified`、`web-merlin` header、網頁 Origin／Referer 與 request timestamp。既有 `.env` 的 extension 版本、path、Origin 不會覆蓋此 Web profile；設為 `MERLIN_TRANSPORT=extension` 並重啟可切回舊路徑。

Web 一律使用既有 emulated tool protocol，即使舊 `.env` 的 `TOOL_CALL_MODE=native` 也相同。完整 system／user／assistant／工具結果會依原順序編碼為一個訊息，每次建立新對話 ID，沒有共享的伺服器端對話狀態。這不是 Web 原生任意工具介面，不啟用官方 MCP、搜尋或網頁工具。

目前 Web 僅支援文字。圖片等非文字 content parts 會回覆 422，不會靜默捨棄。extension 仍保留原有訊息格式。

SSE 會保留至多 256 字元尾端緩衝，直到上游明確結束。收到 `finishReason=length` 時，只移除已核對的官方截斷提示，保留模型內容的空白與 JSON escape。一般文字截斷映射成 OpenAI `finish_reason=length`；錯誤或提早斷線不會回覆成功 DONE。工具 JSON 在完整驗證前不會交給呼叫端。

真實 token 用量取自 Web `turnUsage.totals` 的 input／output／reasoning；`usage` 事件裡的帳號方案、費用及額度不進入 token 計算。前一輪隔離探測只讀 usage 事件，曾誤以為 Web 無相同 token 資料，此處已依重新核對的 turnUsage 更正。

各模型的預設輸出上限與 context metadata 保留。觀察到的 Web 請求沒有 `max_tokens` 欄位，因此上限不會假裝傳給上游：adapter 依真實 output usage 檢查是否超過呼叫端的有效上限，超過則回覆錯誤；串流可能已交付部分文字，但不會發出成功結束。這無法讓上游提前停止生成或保證其費用。若沒有可驗證的 token usage，則不會授予工具重試或續寫新的預算。

Qwen 不完整工具 JSON 仍使用原有續寫：預設最多追加 8 次，與原請求共用時間、token 及大小限制，累加全部嘗試後才釋出完整工具呼叫。這不保證字串內容無損，已知實測可能在接縫遺失空白；JSON/schema 驗證無法替代生成程式碼的執行驗收。一般文字回應不會自動循環要求續寫。

本次修改沒有變更使用者的雨夜便利店提示或模型清單。隔離比較及續寫實測的背景見 [2026-10-28 比較報告](web-api-comparison-2026-10-28.md)。

## 切換前驗證（2026-10-28）

- 107 項離線回歸測試通過，含 Web wire profile、完整歷史、非文字拒絕、turnUsage、截斷尾註、錯誤／不完整串流與 Qwen 續寫的原子驗證。
- 經本機候選 OpenAI API 實測 Haiku 5.5、Gemini 4 Argon、Qwen 3.8 Max、Grok 4.7：8/8 聊天／串流、4/4 工具呼叫 → 隨機本機結果 → 串流回答，均通過，沒有重試。
- 真實 Web Qwen 長工具測試經 3 次請求，完整 JSON/schema 驗證通過，150 行精確內容比對未通過；不宣稱無損續寫。各次真實 output token 為 521、558、398，後續上限扣減為 130551、129993。
- 18 個模型 ID 與 metadata 保持一致，未驗證所有模型的實際最大 context／output，也未重跑完整雨夜便利店。

本機產物：`logs/nas-deploy-20261028-web/local-api.json`、`offline-tests.log`、`qwen-web-continuation.json`。NAS 部署狀態以同目錄的部署後回讀證據為準。
