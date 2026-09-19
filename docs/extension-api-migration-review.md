# 新版 extension API 差異與修改範圍

> 目前狀態：adapter 已切換到原生 extension chat transport；下方前半段是
> 遷移前的證據與限制，最新實作及驗證記錄在文件末尾。

核對日期：2026-09-17。（遷移前記錄）範圍為使用者提供的 HAR、已安裝的官方 extension 8.2.3 原始程式，以及當時的 adapter；當時尚未包含端點遷移實作或新版端點的實際請求測試。

後續的隔離端點探測與路線建議，另見 [網頁版與 extension 比較](web-vs-extension-review.md)；本文件保留原先的協定分析與待驗證範圍。

## 結論

新版 extension 的聊天協定與目前 adapter 有實質差異。值得優先驗證直接傳遞 messages 和工具定義的路徑，因為它可能降低目前依賴提示詞產生工具 JSON 的需求；但尚未量測其工具成功率，也不能宣稱已解決現有模型的 422 問題。

這是一次聊天 transport 與回覆轉換的修改，對外仍可保留 `/v1/chat/completions`、`/v1/models`。不能只更換 `MERLIN_PATH`。

## 證據與限制

### HAR 直接確認

- 共 4 個請求，均回傳 HTTP 200：2 個 telemetry、1 個 chat、1 個 sync-session。
- 聊天端點為 `https://www.getmerlin.in/arcane/api/v2/extension/chat`。
- `x-merlin-version` 為 `merlin-extension-8.2.3`。
- `Origin` 為 `chrome-extension://camppjleccjaphfdbohjdohecfnoikec`，沒有 Referer。
- 範例模型為 `gpt-5.6-luna`，直接傳送 5 筆 `messages`；有 system、user、assistant，文字內容同時有字串與文字區塊陣列形式。
- `params.tools` 包含 12 個 function 工具，`params.max_tokens=10000`。
- `metadata.isMCPEnabled=true`。
- 回應 Content-Type 為 `text/event-stream`，記錄大小 2856 bytes；`_eventSourceMessages` 有 9 筆時間及事件名稱紀錄，但沒有事件 data，`response.content` 也没有 text。

因此 HAR 足以確認這次請求的路徑與 payload，不能單獨證明工具呼叫、usage 或錯誤事件的實際回應內容。它也沒有包含 assistant tool_calls 和 role=tool 的完整多輪樣本。

HAR 的請求 header 清單沒有 Authorization；不能據此推定新版端點不需要驗證。

### 官方 extension 原始程式補充

核對 `chunks/sidepanel-Dt2U-t-U.js`，SHA-256：
`6d6d2b4fbf07fd321dac3eebdcdf3a3493ffc27723d6937963635a2df5f836cc`。

- HTTP request interceptor 會取得 session 並加入 `Authorization: Bearer <accessToken>`。
- runIteration 直接送出 model、messages、params.tools、params.max_tokens、metadata.isMCPEnabled。
- SSE parser 會以空行切分事件，讀取 `event:` 和 `data:`，處理 `INIT_MESSAGE_CONTENT`、`tool_calls`、`usage`、`error`；message 資料另支援文字、reasoning 與 DONE。
- usage 處理程式讀取 tokens 的 input、output、cached、reasoning，以及 context_window。
- 工具事件進入 extension 本機的工具執行流程；這不代表 adapter 需要執行瀏覽器或第三方服務工具。

上述是程式支援的協定，不代表所有模型每次都會送出這些事件。

## 差異表

| 項目 | 現有 adapter | 新版 extension／HAR | 修改影響 |
| --- | --- | --- | --- |
| 路徑 | `/v2/thread/unified` | `/v2/extension/chat` | 新 transport 路徑與相容驗證 |
| Header | 新版本值已更新；Origin/Referer 仍為 extension 網站 | chrome-extension Origin、沒有 Referer | 核對伺服器實際需要的 headers；不必複製瀏覽器自動加入的所有標頭 |
| 對話 | 拼成單一 `message.content` prompt，含字數與歷史裁切 | 原始 `messages[]` | 保留角色、內容與工具回合，建立明確的序列化契約 |
| 工具 | 工具 schema 寫進 prompt，解析 `<OPENAI_TOOL_PAYLOAD>` 等文字 | `params.tools` | 接收呼叫端提供的工具 schema，評估直接工具回覆路徑 |
| 輸出長度 | request schema 已新增 max_tokens，但 transport 尚未使用 | 範例為 `params.max_tokens=10000` | 保留新增欄位並接上上游映射；不能假設所有參數均受支援 |
| Metadata | `mcpConfig.isEnabled=false`、`webAccess=true` 等舊結構 | `isMCPEnabled=true` | 不直接套用舊結構；另測 true/false 與自訂工具的行為 |
| SSE | 逐行只讀 `data:`，預期物件中的 data.text/content | 使用事件名稱及不同資料形狀 | 更新事件 framing、分派、結束及錯誤狀態 |
| 工具串流 | 整段文字完成並解析後再輸出 | 有獨立工具事件 | 依實際事件粒度轉成 OpenAI tool_calls chunks，保留 ID／index |
| Usage | 固定為 0 | extension parser 能讀取 token 資料 | 有資料才映射 usage；先確認欄位語意及缺值處理 |

## 已在本機重現的相容性問題

以官方 parser 所處理的事件形式建立合成 SSE，包含 text、陣列形狀的 tool_calls、usage、error。現有 `MerlinGateway._read_event_stream()` 只收集到文字，工具數為 0；再交給現有一般聊天 response builder，產生 `finish_reason=stop`、usage 全為 0。

這是離線合成測試，不是 HAR 內的真實回應。它證明僅換 URL 存在具體不相容性，無法推算新版實際請求的成功率。

## 建議修改範圍

| 模組 | 工作內容 |
| --- | --- |
| `config.py`、`merlin_client.py` 的 headers／transport | 建立 extension chat 路徑，核對驗證、Origin、timeout、token refresh 與錯誤回傳 |
| `schemas.py` | 新增 extension request/event 模型；保留 messages、tool_calls、tool_call_id 與需要支援的生成參數 |
| `merlin_client.py` 的 payload builder | 直接序列化對話；將呼叫端工具放到 params.tools，避免先轉成單一提示字串 |
| SSE parser（可自 merlin_client.py 抽出） | 支援跨讀取區塊、空行 framing、多行 data、event 名稱、工具陣列、usage、error、DONE 與不完整結束 |
| `openai_response_builder.py` | 組裝工具呼叫、實際 usage 與 finish_reason；驗證 tool_choice、工具名稱與參數 |
| `app.py` | 調整工具串流路徑，將新版結構化事件轉為對外回覆 |
| `tool_prompt.py`、`tool_payload_parser.py`、`structured_output.py` | 待新版工具流程驗證後，再決定哪些文字修復邏輯保留給舊 transport；不要讓新舊協定的判斷混用 |
| 測試、README、開發文件 | 新增離線協定 fixture、多輪工具回歸案例及真實端點 smoke check，記錄相容限制 |

既有 adapter API key、模型清單及 Firebase token manager 可作為保留基礎；新版路徑是否能直接使用現有 token，仍需實際驗證。

## 先驗證，再決定的項目

1. **真實 SSE data**：取得最小文字與自訂工具呼叫樣本，確認 payload、呼叫 ID、工具參數、usage、DONE、error。現有 HAR 沒有保留這些資料。
2. **tool_choice 契約**：HAR 與 extension 的這條送出程式沒有指定 tool_choice，尚未證實新端點支援 none、required 或指定函式。對外相容層仍須強制驗證，不能直接假設轉傳即生效。
3. **多輪工具**：驗證 assistant tool_calls → 呼叫端執行 → role=tool → 最終回覆的 round trip；adapter 只轉接呼叫與結果。
4. **MCP 旗標**：釐清 isMCPEnabled 與自訂工具是否相依。HAR 的 true 是該 extension 工作階段的值，不宜直接成為所有 adapter 請求的固定設定。
5. **一般聊天與錯誤處理**：無工具、串流中斷、錯誤事件、401 refresh、429、timeout 都要測；先確認不同輸出限制欄位的支援程度。

HAR 的瀏覽器工具清單與 system prompt 屬於該 extension 工作階段，不應複製為 adapter 的預設工具或指令。telemetry 和 sync-session 是周邊請求，本次資料未證明它們是聊天完成的前置條件；初版遷移應先驗證 stateless chat 是否獨立運作。圖片、影片、瀏覽器操作和 Merlin 聊天歷史同步可列為後續功能。

## 建議切分

第一步做最小 protocol probe 與已去識別化的事件 fixtures，確認新端點的工具 round trip。第二步實作文字聊天與 SSE。第三步接上自訂工具、tool_choice 與 usage，跑離線回歸及代表模型實測。通過後再切换預設 transport，評估是否保留明確的舊版選項。

不建議遇到任意錯誤就自動改走舊端點：同一請求可能已在上游生成或計費，隱性重送也會讓問題難以定位。

（歷史記錄）當時僅新增評估文件；8.2.3 header 更新保留在工作區，聊天端點尚未遷移。

## 2026-09-18 工作區核對與遷移阻礙

目前 HEAD 為 `54cce21`（PR #20 merge）。比對前次工作狀態，額外發現
`OpenAIRequest.max_tokens` 與 `stream_options` 兩個欄位；兩者保留未改動。
`max_tokens` 有正整數驗證，但兩欄都還沒有接入 transport 或 response builder。
其他 tracked diff 仍為版本 header、README 與 smoke report 的既有修改。
Git 未提交差異本身無法證明編輯者身分。

本次使用現有 token manager 與原生 `/arcane/api/v2/extension/chat` 直接測試，
沒有經過舊版 prompt 相容層，也沒有執行回傳的工具。

| 核對項目 | 結果 |
| --- | --- |
| Sonnet 5、無工具、max_tokens=10000 | HTTP 200，收到指定文字、usage 與 DONE |
| Sonnet 5、自訂 echo 工具、max_tokens=10000 | HTTP 200，但 SSE error，沒有工具呼叫 |
| Luna、自訂工具移除 additionalProperties、加入 system、MCP=true | 同樣失敗，error.type=INTERNAL_SERVER_ERROR |
| Luna、將測試工具改為官方已有名稱 | 同樣失敗 |
| Luna、帶工具但要求完全不使用工具 | 同樣失敗 |
| Luna、明確 params.tool_choice=auto | 同樣失敗 |
| Luna、HAR 的官方工具 schemas，要求純文字且不呼叫工具 | 同樣失敗 |

先前 Luna 無工具測試成功；自訂工具在 MCP true/false 下都失敗。
本次證據顯示問題不只出現在單一模型、1000 token 上限或測試工具名稱。
目前仍不能判定根因是服務端問題，或尚未確認的 extension 工作階段／請求條件；
不能據此宣稱新 endpoint 永久不支援自訂工具。

原生工具請求未成功，因此尚無法驗證完整 tool-result round trip。
HTTP 200 和 DONE 都不能取代 error 檢查。本次未切換預設 transport，避免已知工具回歸，
也沒有把錯誤自動改走舊 endpoint。後續需先取得同帳號、同端點成功的原生工具回應，
再完成上述遷移與驗證。

去除憑證的本機測試摘要位於 gitignored `logs/extension-native-probe-sonnet.json`、
`logs/extension-tool-diagnosis.json`、`logs/extension-official-tools-probe.json`。
HAR 與任何驗證憑證未加入版本控制。

## 2026-09-18 遷移結果

使用者確認官方 extension 的工具功能正常，但 adapter 不需要那些內建工具，
因此沒有把 `read_content`、`screenshot`、`scroll`、MCP 或其他 extension tool
註冊到 adapter。新版 transport 現在已切換為 `/arcane/api/v2/extension/chat`，
並保留呼叫端原本的 `messages[]`。user 與 tool 的純文字會轉成 extension 使用的
`[{"type":"text","text":"..."}]` content part；其他角色與 content part 會保留。

核對出的兩個必要條件如下：

1. 即使 `params.tools` 為空，`metadata.isMCPEnabled` 仍必須為 `true`；這只是
   extension session capability flag，不會注入任何工具。
2. user message 使用純字串會造成上游 `INTERNAL_SERVER_ERROR`；轉為原生
   text part 後即可正常回覆。

目前 `max_tokens` 會映射到 `params.max_tokens`（預設 10000）。
`stream_options.include_usage` 由 adapter 處理，使用者要求時會在最後送出
OpenAI usage chunk，不把未確認的參數塞進 Merlin extension payload。

`params.tools` 預設是空陣列，且不會放入官方 extension 的瀏覽器或 MCP 工具。
呼叫端若明確提供自己的 OpenAI function schema，adapter 才會原樣轉送；這些
schema 不等同於 extension 內建工具，且本次不把它們當成已驗證的 extension
整合能力。

原生 SSE parser 已支援 event 名稱、跨行 data、text、reasoning、tool_calls、
usage、DONE、error 與未完成 EOF；HTTP 200 搭配 error event 不會被當作成功。
串流錯誤會輸出 OpenAI 風格 error event，且不送成功的 finish chunk 或 `[DONE]`。

本機回歸測試：`python -m unittest discover -s tests -v`，9 tests passed。
真實上游 smoke：`gpt-5.6-luna` 與 `claude-sonnet-5` 的 chat 與 chat-stream
均通過（4/4），報告為 gitignored `logs/extension-migration-smoke-final-2models.json`。
這次 smoke 僅測文字聊天，沒有傳送或執行 extension 內建工具。

補充測試顯示目前 Merlin extension endpoint 對 adapter 自行提供的
`echo_probe` schema 回傳 `INTERNAL_SERVER_ERROR`；因此沒有把自訂工具列為
已通過功能，也沒有將官方 extension 工具偷偷加入作為繞過方式。
