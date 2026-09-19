# OpenCode 實測（2026-09-19）

後續 GLM 格式修正：離線 48/48、GLM／Luna／Sonnet 的 OpenCode 完整讀檔回合
3/3 通過；長程式碼實際回覆在串流及非串流重放保持逐字一致。
範圍與限制見 [GLM 問題紀錄](glm-opencode-format-fix-2026-09-19.md)。

初次驗收：新增 `TOOL_CALL_MODE=emulated` 後，OpenCode 1.18.13 的 Luna／Sonnet
讀檔後回答完整回合 2/2 通過；一般聊天與多輪對話重新驗證 4/4 通過。
原生工具模式的 0/2 失敗保留於下方，並未因此修復原生工具能力。

## 工具模擬模式驗收

| 模型 | OpenCode 讀檔→工具結果→最終回答 | 一般聊天／多輪 | required 工具 API（非串流／串流） |
| --- | --- | --- | --- |
| `gpt-5.6-luna` | 通過，8.92 秒 | 2/2 通過 | 非串流通過；串流首輪失敗，複測通過 |
| `claude-sonnet-5` | 通過，11.39 秒 | 2/2 通過 | 2/2 通過 |

兩個成功 OpenCode 工具回合均有真實 `read` completed 事件；下一次 API 請求
包含 `system,user,assistant,tool`，最後回答與檔案隨機代碼相符。代碼未出現在
初始 prompt。兩輪皆有正確 finish、usage 與 DONE，沒有 error。
執行權限只開放該測試檔，未開放改檔、shell 或其他工具。

工具模擬首輪測試遇到 OpenCode 的路徑權限比對不符：模型已產生合法呼叫，
但 `read` 被測試程式自行設定的規則擋住。補上同一檔案的 Windows 原生與
相對路徑表示後，上表兩個完整回合通過。原失敗報告仍保留，沒有當作成功。

required API 首輪為 3/4；Luna 串流只記錄到 `Missing SSE terminator`，當時的
腳本未保留實際 error 原因，因此不能斷定是上游或模型格式問題。改進腳本
錯誤摘要後，僅複測該項 1/1 通過。這些結果證明可完成樣本，不代表工具
格式與工具選擇每次都可靠。

真實證據（Git ignored）：

- `logs/opencode-emulated-read-20260919.json`：首輪測試路徑權限失敗 0/2。
- `logs/opencode-emulated-read-final-20260919.json`：完整工具回合 2/2。
- `logs/opencode-emulated-chat-20260919.json`：一般聊天與多輪 4/4。
- `logs/emulated-tools-api-20260919.json`：required API 首輪 3/4。
- `logs/emulated-tools-luna-recheck-20260919.json`：Luna 串流複測 1/1。

實作與使用方式見 [工具模擬模式](emulated-tool-calling.md)。工具回合會暫存
上游回覆，完整驗證後才送出工具或文字 chunk；原生模式及無工具聊天保留
原本即時串流。沒有自動 fallback、JSON repair 或隱性重試。

最終離線回歸 43/43 通過；Python 編譯與 `git diff --check` 通過。涵蓋兩模式、
參數 schema、required／指定工具、歷史保留、多工具 ID／index、截斷及錯誤串流。

以下各節保留新增工具模擬前的原生模式測試。

## 環境與設定

- 本機工作區基於 `54cce21`，包含尚未提交的 extension transport 與架構修正。
- 使用使用者指定的 `%USERPROFILE%\.config\opencode\opencode.jsonc`。
  其中 `merlinai-dev` 與 `merlinai` 仍各列 9 個舊清單模型，未直接修改全域檔案。
- 測試用 `OPENCODE_CONFIG_CONTENT` 暫時補上兩個新模型 ID、目前 adapter 的
  認證資訊及本機隨機 loopback port；使用 `@ai-sdk/openai-compatible`。
  金鑰只在子程序環境中，不寫入測試設定檔或報告。
- 路徑：OpenCode CLI → 真實本機 HTTP/SSE → 工作區 FastAPI → 真實 Merlin。
  沒有 mock，也沒有連到已部署的 `ai.mh-tech.me`。
- 使用 `--pure` 關閉外掛；禁止分享、自動更新與其他工具。這是最小相容性測試，
  不代表已驗證使用者預設 build agent、外掛組合或所有模型。
- 純文字 agent 不攜帶工具；工具 agent 僅允許 `read` 讀取隨機生成的 fixture，
  禁止其他工具。沒有加入 Merlin extension 內建工具。

設定方式依據 OpenCode 官方文件：
[設定合併與程序內覆寫](https://opencode.ai/docs/config/)、
[agent 權限](https://opencode.ai/docs/agents/)、
[自訂 provider](https://opencode.ai/docs/providers/)。

## 結果

| 模型 | 串流聊天 | 同 session 多輪記憶 | `read` 工具回合 |
| --- | --- | --- | --- |
| `gpt-5.6-luna` | 通過，4.52 秒 | 通過，4.88 秒 | 失敗，3.09 秒 |
| `claude-sonnet-5` | 通過，6.86 秒 | 通過，4.81 秒 | 失敗，2.77 秒 |

時間是單次 CLI 執行觀測，含啟動成本，不是效能基準。

四個文字回合均取得指定的精確輸出、至少一個文字 delta、一個 usage chunk、
`finish_reason=stop`、`[DONE]`，OpenCode 以 exit code 0 完成且沒有 error event。
多輪回合以相同 session ID 繼續，請求保留 `system,user,assistant,user`，
能回覆第一輪的隨機代碼；第二輪 prompt 未重複該代碼。

兩個工具回合的 HTTP 皆為 200，但請求攜帶 `tools=[read]` 與
`tool_choice=auto` 後，收到以下串流錯誤：

```json
{"error":{"message":"Merlin returned an upstream SSE error","type":"upstream_error","code":502}}
```

沒有文字、工具 delta、usage、成功 finish 或 `[DONE]`。OpenCode 都產生
`UnknownError` 並以 exit code 1 結束；沒有執行讀檔，也沒有進入工具結果回傳
的下一輪。本次證實失敗會傳到 OpenCode，沒有被 HTTP 200 掩蓋；仍不能僅由
此錯誤區分上游工具限制與請求契約不符，也不能宣稱所有模型都不支援工具。

## 重跑

實測會使用 Merlin 帳號配額。需先安裝 OpenCode，並備妥專案 `.env`。

```powershell
.venv\Scripts\python.exe scripts/smoke_test_opencode.py --config "$env:USERPROFILE\.config\opencode\opencode.jsonc" --tool-call-mode native --out logs/opencode-smoke.json
```

上方命令明確重跑原生模式，改為 `--tool-call-mode emulated` 可測模擬模式。
省略此選項時使用 `.env` 的模式。預設測兩模型，各執行文字、多輪、讀檔三回合。
僅驗證文字可加 `--modes chat`；
僅重測工具可加 `--modes read`。任一回合失敗、超時、缺少完整 SSE 結尾或
預期輸出不符，測試程序回 exit code 1。工具回合必須真的完成 `read`、送出
tool role 歷史並答對 fixture，才算通過。

腳本於結束時關閉測試 server 並刪除 fixture，保留去憑證的測試結果。
OpenCode 本身仍會保留本機 smoke sessions；未改寫其全域 provider 設定。

本次本機證據（Git ignored）：

- `logs/opencode-chat-luna-20260919.json`：文字與多輪 2/2。
- `logs/opencode-sonnet-20260919.json`：文字與多輪 2/2，工具 0/1。
- `logs/opencode-read-luna-20260919.json`：工具 0/1。

另外重跑既有離線測試 29/29 通過。17 模型的一般 API 測試為前次獨立結果，
見 [完整 API 驗證紀錄](verification-2026-09-19.md)，本次未重跑全模型。
