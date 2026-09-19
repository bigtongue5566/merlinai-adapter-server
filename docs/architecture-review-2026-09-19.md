# 架構與提示詞改善評估（2026-09-19）

範圍：目前工作區的 extension transport 遷移；本次由主代理分析與驗收，
由 luna-worker 分工修改程式、回歸測試與使用文件。不加入官方 extension 工具。

## 本次決策

優先修正協定契約與測試覆蓋。原生 transport 已直接送出 `messages[]`，
因此修改 `tool_prompt.py` 的舊提示詞，不會改善目前一般聊天路徑。
本次沒有加入預設 system prompt、工具 JSON 指示或隱性重試。

## 具體發現與處理

| 發現 | 影響 | 本次處理 |
| --- | --- | --- |
| gateway 同時接受舊 `user_message` 與新 `messages`，卻使用相同新版 endpoint | 歷史比較腳本可能送出錯誤協定，產生難以解讀的上游錯誤 | 正常 gateway 僅接受原生 payload；停用舊版網路比較 CLI，於送出請求前明確提示 |
| `tool_choice` 被接受但沒有落實 | `none` 仍可能送工具；`required` 或指定函式可能得到違反要求的成功回應 | 共用原生請求政策：`none` 不送工具；尚未支援的 required／指定函式在連線前回 422 |
| 使用舊 normalizer 過濾未宣告的工具，並嘗試修復 arguments | 錯誤事件可能消失，或改變上游原始資料，最後回成功 | 原生事件使用嚴格驗證；錯誤或未宣告工具明確失敗，不對原生 arguments 做 JSON repair |
| `app.py` 保留永遠不會走到的舊串流分支 | 正常與歷史流程混在一起，容易在維護時誤接 | 簡化為原生串流與非串流兩條入口 |
| 非串流失敗時 attempt context 沒有 finally 清理 | 直接呼叫 client 時，後續 log 可能帶有前次標記 | 在 finally 清理 attempt context |
| 舊測試主要驗證 helper，缺少完整 API 錯誤回合 | helper 通過仍可能有錯誤的 HTTP／SSE 完成行為 | 增加真實 parser 與 response builder 經 FastAPI 路由的離線驗收 |
| 部分文件仍把舊 prompt／repair 描述為現行行為 | 使用者容易調整已不生效的設定或誤判工具能力 | 同步 API、架構、開發與排錯文件 |

`required` 與指定函式回 422 是相容性收斂，呼叫端應移除強制選擇，或在可接受
模型自行選擇時使用 `auto`。這不代表已修復 Merlin 自訂工具能力；實際上游工具
呼叫仍未通過驗證。此處僅驗證呼叫格式與 arguments 為合法 JSON 物件，
不驗證完整工具參數 JSON Schema，也不執行工具。

## 提示詞策略

- 保留呼叫端的 system／developer／user／assistant 角色與先後順序。
- 保留完整歷史及 content parts，僅做 extension 必要的文字格式轉換。
- 不以固定字數裁切 system 指示或工具結果，也不把全部角色壓成一段 user prompt。
- 聊天中出現看似工具 JSON 的文字仍是文字，不能因此變成可執行工具呼叫。
- 若之後要比較提示詞品質，先建立固定任務集與評分規則，在同模型、同輸出
  限制下做 A/B。這次驗收證明傳輸與契約正確性，不宣稱回答品質或長期穩定性提升。

## 後續優先項目

1. 串流目前仍保留完整文字、raw events 與 raw chunks，可能重複占用記憶體；
   下一步可將完整 trace 改為明確開啟且設上限，預設只保留摘要。需搭配長輸出測量。
2. 網路使用同步 HTTP 與 threadpool；若實際併發量增加，再衡量連線池、取消
   傳播及並行上限。沒有壓測證據前不整批改成 async。
3. 目前缺少 usage 時非串流回覆使用零值，應再定義「未取得」與「實際為零」
   的公開表示方式；不要把這些數字直接當作帳務資料。
4. 推理文字雖有解析，尚未對外提供專門欄位；圖片等 content parts 的保留亦
   不代表已驗證多模態。需各自增加明確能力測試。

## 驗證範圍

後續完整 17 模型驗證見 [驗證紀錄](verification-2026-09-19.md)：首輪 28/34，
Minimax 複測恢復；Gemini 3.8 Flash 與 Qwen 3.8 Max 持續收到上游 error。
下列兩模型的早期 smoke 結果不代表全部模型均正常。

離線測試使用合成 SSE，驗證完整 HTTP 路由、真實 framing/parser、回應組裝、
多輪長歷史保留、usage、未完成 EOF、error 與工具選擇契約。真實上游 smoke
另用兩模型的文字與文字串流；不執行瀏覽器工具，也不把合成工具事件當作上游
工具可用證明。

真實上游結果：

- 修改前基準：`gpt-5.6-luna`、`claude-sonnet-5` 的聊天與串流 4/4 通過。
- 修改後驗證：同兩模型聊天與串流 4/4 通過。
- 額外多輪測試：同兩模型能依 system 指示，只回覆前文保存的指定代碼，2/2 通過。
- 本機去憑證報告：`logs/architecture-baseline-20260919.json`、
  `logs/architecture-final-20260919.json`、`logs/architecture-multiturn-20260919.json`。
  `logs/` 保持 Git ignored；這些測試不是已部署服務驗證，也不是效能基準。

離線驗收：`python -m unittest discover -s tests -v` 共 29 項通過；
`python -m compileall -q main.py merlinai_adapter_server scripts tests` 與
`git diff --check` 通過。退役比較 CLI 回傳預期的 exit code 2，不送出上游請求。
