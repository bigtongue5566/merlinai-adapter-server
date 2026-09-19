# GLM OpenCode 工具回覆格式修正

## 問題與證據

使用者的 OpenCode 1.18.13 工作階段 `ses_f47e099cfffeuO5XqcwjZkMRex`，
模型 `merlinai/glm-5.3-flash`，執行雨夜便利店三維場景提示詞。
第一回合 `bash(dir)` 成功；第二回合約 104 秒後回報
`Emulated tool response is missing its complete payload envelope`。
OpenCode 此請求的 `max_tokens` 為 32000。

原始失敗的模型文字未保留，不能斷言它是哪一種格式問題。
使用者允許把同一提示詞、工具清單與目錄結果重送 Merlin。
診斷從工作階段副本擷取請求，移除額外的 Continue 訊息後重放；
不執行模型產生的工具，不更動原場景專案或原工作階段。

- 修正前重現：75.36 秒，21,720 字元，8,215 output tokens。
  標記前有解說，JSON 最後多出不完整的空欄位；即使取出區塊仍不合法。
- 加入格式提醒後：102.70 秒，27,872 字元，12,004 output tokens。
  JSON 完整，產生 write 呼叫，內含 26,916 字元、757 行檔案內容，
  但省略結尾文字標記。兩次都有上游正常 DONE，並非已證實的輸出截斷。

## 修正

1. 保留完整對話，在末尾加入工具格式提醒及長程式碼 JSON 跳脫、分步呼叫指引。
2. 使用 JSON decoder 從明確開始標記解析完整 JSON；容許區塊外解說。
3. 已完整解析 JSON 且後面沒有其他內容時，容許省略結尾文字標記。
4. 仍拒絕不完整或錯誤 JSON、多個區塊、未知工具、錯誤參數，以及上游未 DONE。
   不使用 JSON repair、不自動重試、不猜測參數。
5. 增加不含提示詞及工具內容的格式失敗診斷。

## 驗證

- 離線測試 48/48 通過。
- 將真實模型回覆按 91 字元切片，經 API 串流與非串流重放：
  錯誤 JSON 都被擋下；完整 write 參數逐字相同，長程式碼未改寫。
- OpenCode → 本機修正版 adapter → Merlin：GLM 5.3 Flash、GPT 5.6 Luna、
  Claude Sonnet 5 各完成一次 read 工具執行 → role=tool 結果 → 最終回答，3/3 通過。
- 這些結果不代表所有 GLM 長篇產生都會成功。若模型仍回傳不合法 JSON，
  adapter 會明確報錯；本次未執行或驗收模型產生的場景。

本機診斷記錄（忽略於 Git，不加入 NAS 發佈包）：
`logs/glm-scene-before-raw.json`、`logs/glm-scene-after-raw.json`、
`logs/glm-recording-verification.json`、`logs/opencode-glm-fix-read-20260919.json`。

## 完整提示詞 OpenCode 實測（後續）

應使用者要求，以原始完整提示詞另開獨立 Git 測試專案，使用 OpenCode 的
`build` agent、`merlinai/glm-5.3-flash`，連接本機修正版 adapter。
未新增提示詞指示，SHA-256 為
`9a60c4499055745812975984a1554837dff96d91a5b560a984ac408bff792cc3`。
允許專案內寫檔及常用建置命令，禁止外部目錄；未延續或修改原工作階段。

- 工作階段：`ses_f47ba9400ffeMLagxqQRnky6RM`。
- 耗時 300.50 秒，CLI exit 0，無錯誤、未逾時。
- 真實 `write` 工具執行成功，產生 25,618 bytes 的 `rainy-corner.html`。
- 第二次請求含 `assistant` 工具呼叫及 `role=tool` 結果，最終正常回答。
- 兩次串流均 HTTP 200、有 usage、有成功 finish 及 DONE，無 error。
- 產出檔與 write 工具的 content 逐字相同，內嵌 JavaScript 通過 `node --check`。
- 這證明本次完整 OpenCode 工具流程成功；未做瀏覽器渲染或美術品質驗收，
  也不是 NAS 正式服務測試。單次成功不代表後續 GLM 產生不合法 JSON 的機率為零。

完整記錄：`logs/opencode-scene-e2e-20260919-a1/report.json`；
檔案檢查：同目錄 `artifact-check.json`；產出：`project/rainy-corner.html`。

## NAS 更新狀態（尚未套用）

已準備 `20260919-glm-format-a2` 更新包；尚待 NAS 管理員執行。
更新流程先備份、建立候選容器、執行離線測試及 GLM 工具往返檢查，
再切換正式服務並驗證公開 API；失敗時還原。
不能把本機測試或更新包上傳視為正式服務已更新。
