# 普通回答與輸出預算的相容修正

範圍只限 adapter 原始碼、測試及文件。使用者提示詞、`build_emulated_messages`
的協定提示詞、OpenCode 設定與既有場景產物均未修改。

## 行為

- 模擬模式的 auto／省略／null 工具選擇，允許無標記的非空普通最終回答，
  保留文字與空白，回 stop；必須先收到上游正常 DONE。
- 疑似 JSON、工具呼叫或協定標記不走純文字相容路徑。required／指定工具
  仍須成功驗證工具呼叫；不修補損壞 JSON、不自動重試。
- 沒有回答文字時回明確錯誤。若不完整回覆的 usage 顯示 output 達 max_tokens，
  回報輸出預算耗盡，包含上游 output／reasoning 計數。完整合法 envelope
  不會僅因 token 達上限而被拒絕；參數或工具驗證錯誤也不會被預算訊息掩蓋。
- 非 null 的 reasoning_effort／thinking／reasoning 在發出上游請求前回 422，
  明確說明 Merlin extension 支援尚未確認，不再默默忽略；null 視為未設定。

此修正不會強制模型使用工具、不會改寫任務，也不會自動提高 token 上限。
它無法保證模型停止過度推理，或修復模型生成的網頁程式碼。

## 驗證

- 55 項離線測試通過，涵蓋串流／非串流、完整工具往返、純文字保留、錯誤／EOF、
  可疑結構、工具選擇約束、輸出預算、無 usage、推理設定的請求前拒絕。
- 實際 GLM 普通文字回覆重放：兩種模式都原樣送回，沒有產生工具呼叫。
- 實際 GLM 空輸出與 32000／31997 token 記錄重放：兩種模式都報預算耗盡，
  不送成功結尾或工具呼叫。
- 先前長程式碼記錄重放：完整寫檔參數保持逐字一致；不合法 JSON 仍被拒絕。
- AST 比對確認協定提示詞函式與 HEAD 一致。
- 真實 OpenCode + GLM 5.3 使用未修改的原始完整提示詞，447.36 秒後上游正常
  DONE，但仍無文字，output=32000、reasoning=31995。OpenCode 現在收到正確的
  `output token budget exhausted` 錯誤，不再收到缺少 envelope 的誤導訊息。
  未逾時、沒有工具呼叫或檔案產出，不能宣稱場景任務已成功。
  工作階段：`ses_f45b04a29ffemQKMzwwm4G00va`；提示詞 SHA-256 仍為
  `9a60c4499055745812975984a1554837dff96d91a5b560a984ac408bff792cc3`。

本機記錄：`logs/project-only-fix-verification.json`、
`logs/glm-recording-verification.json`。
真實複測：`logs/opencode-scene-e2e-glm53-project-fix-original/report.json`。
