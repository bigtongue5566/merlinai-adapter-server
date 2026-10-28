# Web 與 extension API 隔離比較（2026-10-28）

後續依使用者決定，專案已實作以 Web 為預設的可回復切換，詳見 [Web transport](web-transport.md)。以下保留切換前的隔離研究；其「尚未修改」描述指研究當時狀態。

## 結論

本次結果支持為 `gemini-4-argon` 增加可選的 Web transport；尚不足以支持所有模型全面切換。Qwen 的長輸出限制在 Web 仍可重現，不能靠換端點解決。

僅增加研究文件與 Git 忽略的本機測試產物。正式 adapter、模型 token 設定、OpenCode 設定及 NAS container 均未修改。

## 當日實測

使用相同帳號、相同合成提示與工具 schema，比較目前 extension 請求和官方 Web 請求。工具案例包含產生呼叫、提供本機隨機值、驗證模型逐字回覆該值的完整往返。

| 模型 | Web | extension |
| --- | --- | --- |
| `claude-haiku-5.5` | 算術 1/1；工具往返 1/1；長輸出回傳 300 行 | 算術 1/1；工具往返 1/1；長輸出回傳 300 行 |
| `gemini-4-argon` | 算術 3/3；工具往返 1/1；長輸出回傳 300 行 | 算術 0/3；工具 0/1；長輸出失敗，均為 SSE `INTERNAL_SERVER_ERROR` |
| `qwen-3.8-max` | 工具往返 3/3；長輸出 3 次均不足 60 行，且收到 `finishReason: length` | 工具往返 2/3；長輸出 3 次均停在第 57 行附近 |
| `grok-4.7` | 工具往返 1/1；長輸出回傳 300 行 | 工具往返 1/1；長輸出回傳 300 行 |

「300 行」表示回應行數達標。嚴格格式另要求每行句尾有句點：只有 Grok Web 的首輪完全符合，其餘 300 行案例省略句點，原始報告的 `passed` 仍為 false，不能將它們寫成完整格式測試通過。

Qwen extension 工具未通過的 1 次，是第二個請求在 45 秒 socket timeout 時無回覆。將探測 timeout 提高至 90 秒後，兩次完整往返均通過。這不足以判定 extension 工具協定有固定缺陷，也不是正式 adapter 的逾時測試。

追加控制組：Argon extension 僅省略 `params.max_tokens`，其餘請求不變；算術 0/2、工具 0/2，仍為同一上游錯誤。因此本次失敗不能單憑刪除該欄位排除。尚未取得 Merlin 伺服器端診斷，無法定位其內部根因。

## Qwen 截斷的證據

本節比較的是單次上游回應，沒有呼叫 adapter 既有的工具 JSON 續寫流程；「單次被截斷」不代表模型不能被要求繼續輸出。

- extension 實際送出 `max_tokens=131072`，三次仍停在第 57 行附近；其中複測的末行只有 `057` 或 `057 rain`。
- Web 三次均出現 `finishReason: length`，複測回應也附上官方的最大輸出長度／請求續寫提示。Web 的總行數為 59、59、53，包含提示文字及空行，並非完成相同數量的編號內容。
- 以上回應均有正常串流結束，沒有觸發探測的 150 秒總預算。單靠 HTTP 200 或 DONE 會漏掉這種內容截斷。
- 這支持「Merlin 上游對此模型另有限制」的判斷；尚不能斷言固定上限是幾個 token，或其內部如何計入 reasoning。模型公開最大輸出值不代表此端點實際會提供該額度。

## 協定核對

重新下載 [Merlin Chat](https://www.getmerlin.in/chat) 當日的公開前端程式，確認：

- transport bundle：`60786-0287f6df2a312298.js`。
- SHA-256：`0d2a6e9695af613646d4908e50bf13252fface0a40dddcae5e8ac42991d86b88`。
- Web 端點：`/arcane/api/v2/thread/unified`；版本 header：`web-merlin`。
- Web 送出 `message`、`chatId`、`mode`、`metadata` 等欄位；未在觀察到的請求中找到 caller 自訂 tools 或 `max_tokens`。
- extension 沿用目前專案的 `/arcane/api/v2/extension/chat` payload 與各模型輸出上限。

本次 Web 將完整角色與歷史序列化成單一訊息，extension 則傳送 messages 陣列。兩者測試意圖一致，但不是逐位元相同的 payload，不能將差異僅歸因於端點 URL。

兩條路徑都以 SSE 收取上游資料，檢查 error、文字及結束事件；一般聊天將串流彙整後驗證答案。這不是 OpenAI 非串流端點與 OpenCode TUI 的整合驗證。

工具測試沿用目前 adapter 的提示詞 JSON 相容協定，不是 Web 原生自訂工具。每次只執行返回合成隨機字串的本機函式，沒有模型驅動的檔案、shell 或網路工具。所有 Web 請求都使用新的對話 ID，未讀取帳號既有對話。

extension usage 事件的 `context_window` 在此次長輸出中分別回報 Haiku／Grok 100000、Qwen 39900。這是當次 Merlin 回報值，不能直接當作模型公開 context 規格，也未驗證大上下文實際容量。Web 的 usage 事件沒有同等 token 資料；後續實作時確認另一個 `turnUsage.totals` 事件有真實 input／output／reasoning，用於正式 Web 傳輸與續寫計算。

## Qwen 續寫追加實測

Qwen 確實能繼續輸出。單次長輸出被截斷，與後續能否續寫，是兩個不同的驗收項目。

使用未修改的 adapter 執行 `store_probe(text)` 合成工具測試：要求 text 為完整 150 行編號內容，不執行該工具。首個回應截斷後，既有續寫流程追加兩次，總共三個上游請求，成功組成一個通過 JSON、tool_choice 及工具 schema 驗證的呼叫。三次輸出 token 分別為 613、635、363，後續 max_tokens 依序扣減為 130459、129824，沒有重設預算。

不過內容精確驗證仍失敗：150 行中第 111 行的 `neon warm` 變成 `neonwarm`。其餘行與預期一致，沒有尾端換行。這證明現有續寫能補完工具 JSON，但語法與 schema 通過並不足以保證參數字串內容完全正確。

純文字續寫也能到達編號 300，但 extension 出現額外空白，例如 `227` 被接成 `2 27`；Web 的同一 chatId／parentId 多輪也有空白、換行遺失。因此本次不能宣稱無損續寫已通過，也不能靠直接刪補空白通用修復程式碼。

Web 純文字探測器最初未處理官方截斷提示尾端的空白，將提示一併計入行數。已修正探測器，並依原始片段長度對既存結果離線複核、僅移除確定的官方提示；複核後仍有接縫內容錯誤。修正後的探測器未再執行新的 Web 網路測試，不將此離線複核宣稱為新的上游測試成功。

現有續寫的 14 項離線回歸測試均通過，涵蓋 JSON escape、多段累積、錯誤片段替換、工具驗證及共同預算。本次未修改正式續寫程式或 NAS；下一個可靠性改善應聚焦可驗證的接縫與內容驗收，而非單純增加續寫次數。

追加證據位於相同本機目錄：`continue_qwen.py`、`continue_qwen_tool.py`、`continuation-tool.json`／`.txt`、`continuation-extension-pilot.json`／`.txt`、`continuation-web.json`／`.txt` 與 `continuation-web-footer-audit.json`／`.txt`。其中 plain-text pilot 的額外請求與格式失敗均保留，沒有改寫為成功。

## 建議的後續實作

1. 增加可選且可回復的 Web transport，先限於 Argon；維持完整歷史與工具驗證，再執行 OpenCode 原始雨夜便利店提示的端到端驗收。
2. 保留 extension 作為其他模型的既有路徑；此次 Haiku／Grok 沒有顯示必須切換的故障。
3. Qwen extension 已有工具 JSON 的有界續寫（`emulated_continuation.py`），預設最多追加 8 次，共用原請求時間／輸出預算，完整驗證後才釋出工具呼叫。這不是一般文字的通用續寫；Web 需要處理 finishReason、官方截斷提示與不同的 token 事件。後續實作已接入 turnUsage，保留原有續寫流程。不得因 DONE 就把不完整工具 JSON 視為成功，也不應無限重試。
4. 若加入 fallback，須先辨識明確錯誤；已收到部分內容或工具副作用後不得盲目重播。

本次沒有修改使用者原始雨夜便利店提示，也未重跑該完整場景。短合成工具的成功不代表大型寫檔工具已通過。測試數量有限、沒有隨機化或長期追蹤，不據此宣稱 Web 全面更穩或更快。

## 本機證據與重現

產物位於 Git 忽略的 `logs/web-api-comparison-20261028/`：

- `compare.py`：使用現有登入流程及 adapter 的工具編碼／驗證，金鑰僅留在記憶體；執行會消耗帳號額度。
- `initial.json`、`argon-repeat.json`：聊天與 Argon 重複測試。
- `extended.json`：四模型的長輸出與工具往返首輪。
- `qwen-repeat.json`：Qwen 長輸出與工具往返各追加兩次。
- `argon-omit-max-tokens.json`：省略 max_tokens 控制組。
- `chat.html` 與公開 JS bundles：當日前端協定來源。

報告僅保留 usage 的 token/context 欄位，不保留帳號方案、額度或原始 reasoning。首輪 socket timeout 45 秒，複測為 90 秒，每個請求總預算 150 秒、資料上限 4 MiB。

```powershell
.venv/Scripts/python.exe logs/web-api-comparison-20261028/compare.py --models claude-haiku-5.5 gemini-4-argon qwen-3.8-max grok-4.7 --cases long tool --out extended-rerun.json
.venv/Scripts/python.exe logs/web-api-comparison-20261028/compare.py --models gemini-4-argon --cases chat tool --routes extension-default --repeat 2 --out argon-omit-rerun.json
```

舊的 [2026-09-17 評估](web-vs-extension-review.md) 為歷史記錄，其模型、bundle 與成功次數不可替代本次結果。
