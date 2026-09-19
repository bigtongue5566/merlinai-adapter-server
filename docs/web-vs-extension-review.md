# 網頁版與 extension 方案比較

研究日期：2026-09-17。結合官方網頁前端、已安裝的 extension 8.2.3、使用者提供的 HAR，以及本次隔離連線測試。

> 目前狀態：以下研究建議是在遷移前提出；依使用者後續決定，正式 adapter
> 現在採用原生 extension chat transport，且不註冊 extension 內建工具。最新
> 實作與驗證以 [extension API 評估](extension-api-migration-review.md) 為準。

## 遷移前建議

**以目前專案的相容層和最小修改範圍來看，先對齊網頁版比較適合。** 現有 adapter 的端點和 payload 已經接近網頁版；新版 extension 的聊天協定則需要較完整的遷移。

這個建議來自程式結構與本次有限測試，不表示網頁版具有較高的長期成功率。網頁方案仍使用目前的提示詞工具相容層，沒有因此解決上下文裁切、tool_choice 驗證、SSE 錯誤處理或原先的工具輸出不穩定。

新版 extension 可以直接傳 messages 和工具 schema，仍是值得研究的後續路線；但本次最小自訂工具探測遇到上游錯誤，尚未通過工具回合，現在不適合直接替換正式 transport。

## 官方實作核對

重新讀取 [Merlin Chat](https://www.getmerlin.in/chat)，確認仍引用相同的聊天 transport bundle：

- `43896-9461226a344ac30a.js`
- SHA-256：`b93f3613cb6d5396dea675cbb32245e52c4c0dae3a3f5582586f68ddd715b424`

其中的網頁聊天程式直接使用 `x-merlin-version: web-merlin`、`/v2/thread/unified`，並送出 message、chatId、mode、metadata 等欄位。這與現有 adapter 的請求結構相近。

網頁實作也有工具呼叫與工具結果事件的顯示處理，但這只證明網頁能接收這些事件，不能據此認定它允許任意 client 自訂 tools schema。新版 extension 的送出程式則明確包含 `params.tools`。

| 項目 | 網頁版路線 | 新版 extension 路線 |
| --- | --- | --- |
| 聊天端點 | `/arcane/api/v2/thread/unified` | `/arcane/api/v2/extension/chat` |
| 版本 header | `web-merlin` | `merlin-extension-8.2.3` |
| 主要輸入 | message + chatId + metadata | messages + params + metadata |
| 現有程式可沿用程度 | 高；現有 payload、聊天及工具相容層可沿用 | 需更新 payload、SSE parser 和回覆組裝 |
| 自訂工具 | 本次仍用提示詞 JSON 相容層；未確認網頁端點的通用自訂工具介面 | 程式可直接送 params.tools，但本次自訂工具探測失敗 |
| token usage | 現有 adapter 尚未實作真實 usage 映射 | 最小文字探測確實收到 usage 事件 |
| 角色與歷史 | adapter 目前仍將歷史序列化成單一 prompt | 可直接傳 messages；多輪工具尚待驗證 |
| 維護成本判斷 | 短期修改較小 | 初期修改較多；通過驗證後可能減少文字工具修復邏輯 |

## 隔離實測

### 網頁設定：8/8 通過

在獨立程序調整下列 header；使用既有 Firebase 驗證、現有 `/v2/thread/unified` payload 與工具相容層，沒有改寫正式設定：

```text
x-merlin-version: web-merlin
Origin: https://www.getmerlin.in
Referer: https://www.getmerlin.in/chat
```

其中 web-merlin 由官方程式確認；Origin/Referer 是本次模擬同源網頁呼叫所採用的設定，未取得網頁版 HAR 逐項比對。

| 模型 | 一般聊天 | 聊天串流 | required 工具呼叫 | 工具串流 |
| --- | --- | --- | --- | --- |
| gpt-5.6-luna | 通過 | 通過 | 通過 | 通過 |
| claude-sonnet-5 | 通過 | 通過 | 通過 | 通過 |

測試經 FastAPI TestClient 呼叫真實 Merlin 上游，檢查 schema、指定回覆文字、工具名稱／參數及 SSE 結束。工具成功指既有提示詞相容層產生正確呼叫描述，不是已驗證網頁原生工具協定。

先前相同兩模型、相同四種模式使用 extension 8.2.3 header 的首輪是 7/8，失敗個案複測通過。這些執行不在同一時刻、沒有隨機化或足夠重複次數，不能以 8/8 對 7/8 宣稱網頁版更穩定或更快。

### 新版 extension 最小探測：文字成功，自訂工具失敗

直接呼叫 `/v2/extension/chat`，使用既有帳號 token、官方 extension header 和 chrome-extension Origin；模型 gpt-5.6-luna，max_tokens=1000。

| metadata.isMCPEnabled | 純文字請求 | 自訂 echo_probe 工具請求 |
| --- | --- | --- |
| false | HTTP 200；預期文字、usage、DONE 均收到 | HTTP 200，但 SSE 為 error，沒有 tool_calls |
| true | HTTP 200；預期文字、usage、DONE 均收到 | HTTP 200，但 SSE 為 error，沒有 tool_calls |

錯誤事件表示上游 internal error。工具請求沒有成功，所以未執行後續工具結果 round trip；未執行瀏覽器或第三方服務工具，也沒有發送 telemetry 或 sync-session。

這只是最小協定探測，不是完整官方 extension 重播：使用合成提示、一個自訂 echo 工具，以及不同於 HAR 的輸出上限。尚未確認根因，不能推定新版 API 完全不支援自訂工具，也不能把它與網頁 adapter 的 8 個案例當成相同條件的效能比較。

這項結果也驗證了 error 事件必須被正確處理：HTTP 200 並不保證聊天成功。

## 對專案的具體建議

1. **先做網頁設定一致化**：若採用此方案，一併處理版本 header、Origin、Referer，保留 `/v2/thread/unified`；不要只依擴充套件版號維護網頁 transport。現有帳密取得 token 的路徑在本次網頁測試有效，暫無證據要求更換登入流程。
2. **先修 adapter 自己的行為**：完整執行 tool_choice、保留重要上下文、辨識錯誤／不完整串流，加入離線回歸測試。換 header 不會自動修正這些問題。
3. **extension 作為獨立驗證項目**：先釐清自訂工具 error，再驗證完整多輪工具流程、usage 與不同模型；通過後再決定要不要遷移。修改範圍見 [extension API 評估](extension-api-migration-review.md)。

目前沒有證據足以比較兩條路線的長期費用、成功率、輸出品質或限流政策；不作這些優勢宣稱。

## 產物與目前狀態

本次只增加研究文件及 Git 忽略的測試產物。正式設定仍是 `merlin-extension-8.2.3`，Origin/Referer 仍為 extension 網站，端點仍是 `/v2/thread/unified`。

（遷移前記錄）上段描述的是研究當時的工作區狀態。後續依使用者決定，adapter
已改用 `/arcane/api/v2/extension/chat` 的原生訊息格式；目前實作狀態與最新
文字 smoke 結果請看 [extension API 評估](extension-api-migration-review.md)。

本機證據：

- `logs/web-profile-smoke.json`：8 項網頁設定測試與實際 header profile。
- `logs/extension-native-probe.json`：MCP false 的文字／工具結果。
- `logs/extension-native-probe-mcp-enabled.json`：MCP true 的文字／工具結果。
- `logs/probe_extension_chat.py`：隔離探測腳本，執行會消耗帳號額度。
