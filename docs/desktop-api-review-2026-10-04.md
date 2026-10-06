# Merlin Desktop API 接入評估

核對日期：2026-10-04，Asia/Taipei。

## 結論

使用者提供的 `Merlin.dmg` 是 Merlin Agent 1.5.3。安裝檔內確實包含可由伺服器發送請求的桌面版聊天 API，登入沿用與目前 adapter 相同的 Firebase 專案。接入在協定上可行，但**目前專案設定的帳號被 `DESKTOP_PLAN_REQUIRED` 擋住，尚不能切換為可用服務**。

一般聊天實測為 HTTP 403；串流為 HTTP 200，但 SSE 內回傳相同方案錯誤。兩者都未產生有效聊天回覆。原生自訂工具、多輪工具結果、底層模型、usage 與輸出限制尚未完成線上驗證。

本次產出靜態協定分析與隔離 probe，未更改 adapter 執行程式或 NAS 部署。安裝檔中的 prompt、skills 和程式文字只作為分析資料；未啟動 Merlin、執行其 JavaScript，或把內建指令套用到本專案。

## 安裝檔與來源證據

| 項目 | 核對值 |
| --- | --- |
| 使用者提供的檔案 | `C:/Users/Bigtongue/Downloads/Merlin.dmg` |
| DMG 大小 | 153,498,607 bytes |
| DMG SHA-256 | `af062b2ff93811f46bdb913d1246b2e345acde6cfa561604d5d6e562f815856d` |
| Bundle ID | `com.foyer.merlin.desktop` |
| 版本／build | `1.5.3`／`1.5.3` |
| 程式封裝 | Electron `app.asar` |
| SDK | `@rune-ai/sdk`，依賴指向 `foyer-work/rune-sdk` commit `200374231ee841dfffb6e6c1939cb11fc42723fa` |

使用官方 7-Zip 26.03 可攜版讀取 DMG/HFS，只抽取 `Info.plist`、更新資訊及 `app.asar`；再以 ASAR 檔案索引定位需要的原始程式。抽出的分析檔以 ASAR 的 SHA-256 integrity 欄位核對。分析檔、工具和 probe 均位於 gitignored `logs/merlin-desktop-api-20261004/`，未將第三方完整程式或驗證憑證加入版本控制。

主要程式證據，相對於上述目錄的 `asar/`：

| 程式位置 | 證據 |
| --- | --- |
| `out/main/index.js:24` | Arcane API base URL |
| `out/main/index.js:2799` | `desktop-${app.getVersion()}` 版本標頭 |
| `out/main/index.js:2808` | Bearer token 與版本標頭的組裝 |
| `out/main/index.js:4310` | 預設模式 `merlin-lite` |
| `out/main/index.js:4316` | Desktop plan、model、daily/monthly/weekly limit 錯誤處理 |
| `out/main/index.js:5475` | 建立桌面版 relay client，401 時更新登入 token |
| `out/renderer/assets/index-DvftrPcU.js` | 模型選單：Lite、Pro、Max |
| `node_modules/@rune-ai/sdk/dist/index.js:460` | 分別指定串流與一般聊天端點 |
| `node_modules/@rune-ai/sdk/dist/index.js:477` | 一般聊天 `{status,data}` 外層解包 |
| `node_modules/@rune-ai/sdk/dist/index.js:502` | model 對應 `arcane-*` 路由設定 |
| `node_modules/@rune-ai/sdk/dist/index.js:730` | messages、生成參數及 function tools 的請求組裝 |

## 已確認的請求協定

Base URL：`https://www.getmerlin.in/arcane/api`

| 用途 | Method | Path |
| --- | --- | --- |
| 一般聊天 | POST | `/v2/desktop/chat/generate` |
| 串流聊天 | POST | `/v2/desktop/chat/completions` |

請求標頭：

```text
Authorization: Bearer <Firebase ID token>
Content-Type: application/json
x-merlin-version: desktop-1.5.3
x-rune-config: arcane-merlin-lite
```

`x-rune-config` 依 SDK 的 `arcane-` + model 名稱計算，名稱內的 `.` 換成 `-`。產品選單的三個 model ID 是 `merlin-lite`、`merlin-pro`、`merlin-max`。另有 `merlin-base` 用於內部標題流程，不列為已確認的使用者聊天選項。

最小一般聊天測試請求：

```json
{
  "model": "merlin-lite",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "What is 7 + 8? Reply with only the number.",
          "cache_control": {"type": "ephemeral"}
        }
      ]
    }
  ],
  "max_tokens": 2048
}
```

串流請求另外傳送 `stream: true`、`stream_options: {include_usage: true}`。SDK 將 function schemas 放在頂層 `tools`，並支援組裝 `tool_choice`、assistant `tool_calls` 及 tool result messages。這些是**程式協定證據**，不等同於目前帳號已通過功能驗證。

一般聊天的 SDK 預期 response 為 `{status,data}` 包住的 OpenAI 風格資料；串流 SDK 處理 chat-completion chunks。本次真實串流還觀察到 `INIT_MESSAGE_CONTENT`、`error` 和 `message` 具名事件，因此接入時必須檢查事件及資料中的錯誤，不能把 HTTP 200 視為成功。

## 現有帳號的線上測試

測試使用 adapter 現有 token manager，Firebase 登入成功；未記錄 token、密碼或帳號名稱。請求只包含上方合成數學問題，不讀取聊天歷史，不呼叫 telemetry、sync-progress 或桌面版工具。

最新測試時間：2026-10-04 00:47:59 +08:00。

| 測試 | HTTP／內容 | 結果 |
| --- | --- | --- |
| Lite，一般聊天 | 403，JSON `{status: "error", data: ...}` | `DESKTOP_PLAN_REQUIRED` |
| Lite，串流聊天 | 200，`text/event-stream` | SSE `error`：`DESKTOP_PLAN_REQUIRED`；無回覆、工具呼叫或有效完成標記 |

錯誤訊息：`This endpoint is only available on Merlin Desktop plans.`

證據檔：`logs/merlin-desktop-api-20261004/probe-lite.json`。

這證明此帳號在這兩條請求上受到 Desktop 方案限制。不能據此判定帳號的具體訂閱名稱、其他帳號的權限，或 Pro／Max 的實際可用性。登入成功也不代表有 Desktop 使用權。

已備妥的隔離測試程式：`logs/merlin-desktop-api-20261004/probe_desktop_api.py`。有權限後，可依序執行：

```powershell
& '.\.venv\Scripts\python.exe' 'logs/merlin-desktop-api-20261004/probe_desktop_api.py' --stage lite
& '.\.venv\Scripts\python.exe' 'logs/merlin-desktop-api-20261004/probe_desktop_api.py' --stage catalog
& '.\.venv\Scripts\python.exe' 'logs/merlin-desktop-api-20261004/probe_desktop_api.py' --stage tools
```

`catalog` 測 Pro／Max 的一般與串流回覆；`tools` 測 caller-defined `sum_probe` 原生工具呼叫，驗證名稱及參數後，只在本機計算 7+8，再送回工具結果並驗證最終回覆。它不執行產品內建檔案、shell 或瀏覽器工具。本次因方案限制尚未執行後兩個階段。

## 改接 adapter 的實際範圍

| 項目 | 現行 extension transport | Desktop transport 所需調整 |
| --- | --- | --- |
| 端點 | `/v2/extension/chat`，由 adapter 組裝一般／串流回覆 | 依一般／串流分別選 `generate`、`completions` |
| 登入 | Firebase ID token | 可沿用 token manager；另驗證 Desktop 方案權限與 token refresh |
| 路由 | 現有 23 個個別模型 ID | 先以 Lite／Pro／Max 建立獨立模型設定；未證明可直接搬用 23 個 ID |
| 版本／路由標頭 | `merlin-extension-8.2.3`、extension Origin | `desktop-1.5.3`、`x-rune-config` |
| 請求參數 | `params.tools`、`params.max_tokens` | 頂層 `tools`、`tool_choice`、`max_tokens` 等已觀察到的欄位 |
| 回覆 | extension 具名 SSE 解析與 OpenAI 轉換 | 一般 JSON 外層解包、OpenAI chunk 解析及具名 SSE error 處理 |
| 工具 | 有明確的 native／emulated 模式 | 原生工具需通過真實多輪驗證，才決定如何接上現有相容層 |
| 對外 API | `/v1/models`、`/v1/chat/completions` | 可保留這兩個對外介面 |

這不是只換一個 URL 的修改。取得正確帳號權限後，先通過三種模式的聊天、串流及原生工具 round trip，再實作可切換的 Desktop transport；最後才評估變更 NAS 預設。底層實際模型與 token 上限需以有效回應和實測確認，不能從模式名稱或 app prompt 推定。

## 官方公開資訊

[Merlin Agent 官方產品頁](https://www.getmerlin.in/agent) 列出包含 Desktop 的方案和模型路由功能；目前 API 回覆仍判定本專案帳號缺少 Desktop 方案。需由 Merlin 帳號設定或客服確認／開通該帳號的 Desktop 使用權，不能僅由既有 extension 可用性推定。

[官方公開 API 功能請求](https://feedback.getmerlin.in/feature-requests/p/merlin-api) 已關閉，官方在 2026-04-20 表示當時不推進公開 Merlin API。因此本次找到的是桌面產品內部使用的 API；尚無公開、穩定的第三方 API 契約可作為相容保證。
