# Pi / Codex 如何處理推理預算與工具錯誤

研究日期：2026-09-20。此文件是原始碼研究與 adapter 修復設計，**不是已完成的修復或成功率報告**。
沿用原始雨夜便利店提示詞；不要求使用者改寫任務。

後續已依此設計實作有界更正、取消與 usage 改造；目前實作與實測狀態以
[可靠性改造紀錄](reliability-2026-09-20.md)為準。下文保留研究當時的設計與推論。

## 來源與範圍

本次讀取官方公開儲存庫，固定在以下 commit，避免日後 main 分支變動：

- Pi：`3c75b2747965e8d69ad9e17cbe788b2e33bf4d99`。原 `badlogic/pi-mono` 網址目前重新導向
  [earendil-works/pi](https://github.com/earendil-works/pi/tree/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99)。
- Codex：[`595cc91e8cbb1c2ca822d0311dcf12709410c582`](https://github.com/openai/codex/tree/595cc91e8cbb1c2ca822d0311dcf12709410c582)。

本機唯讀研究副本在 `logs/harness-research/`，不納入版本控制。本次未執行這兩個 harness
連接 Merlin 的端到端測試。Codex 公開 CLI 原始碼也不能代表桌面版所有內部行為。

## 對本專案的結論

現有實測包含兩種獨立失敗，不能用一種重試政策處理：

| 失敗 | 現有證據 | 優先處理方向 |
| --- | --- | --- |
| 推理吃完共用輸出預算 | output=32000，reasoning 接近 32000，回答空白 | 驗證上游 reasoning effort／數值預算能力，保留清楚錯誤；原樣重送沒有可靠收益證據 |
| 已產生工具意圖但協定不合法 | 推理只有數十至數百 token，卻有缺括號、錯誤參數層級、損壞標記 | 嚴格拒絕執行，將具體協定錯誤交回模型，有限次重新產生並再次驗證 |

Pi 和 Codex 提供最直接的啟發是：**錯誤要回到 agent 的決策迴圈；不必每次都終止整個任務。**
但兩者通常持有原生工具呼叫與識別碼；我們是文字模擬工具的 adapter，不能直接照搬為假造工具結果。

## 1. Pi：預算分配依供應商能力決定

Pi 的共用預算工具定義 `MIN_ANSWER_TOKENS=1024`，可在共用輸出上限內壓低推理預算，
為回答保留空間；各推理等級也有數值預算對應。未指定輸出上限時，基礎選項從模型資訊取上限，
並依剩餘上下文調整，而非所有模型固定使用 32000。

來源：[simple-options.ts](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/ai/src/api/simple-options.ts#L55)。

這不是任意 API 都有效的保證。OpenAI-compatible provider 只有設定了已知的
`thinkingTokenBudgetField` 或相容能力時，才傳送數值限制；預設不送。
對 Z.ai 的分支則使用 `thinking`、`clear_thinking:false` 與支援時的 `reasoning_effort`。
**推理強度 low 和硬性 token 預算不是同一回事。**

來源：[供應商參數映射](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/ai/src/api/openai-completions.ts#L870)、
[數值預算只在支援時送出](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/ai/src/api/openai-completions.ts#L973)、
[預算測試](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/ai/test/openai-completions-thinking-token-budget.test.ts#L98)。

Pi 的 Z.ai provider 直接使用 `api.z.ai`，不是 Merlin extension endpoint。
因此不能把 Pi 支援 GLM 的參數等同於 Merlin 已支援轉送。
來源：[zai.ts](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/ai/src/providers/zai.ts#L6)。

Adapter 應採用明確的路由能力設定；在 Merlin 有契約或可靠實測前，不開放看似成功、實際可能無效的參數。
也不應為模仿 Pi 而偷偷提高呼叫者的 `max_tokens`。

## 2. 工具錯誤回報給模型，而不是直接結束

Pi 在工具不存在、參數 schema 不符時，產生 `isError` 工具結果，讓下一輪模型修正。
遇到 `stopReason=length` 且已有工具呼叫，即使參數看起來合法，也不執行：
它會回報輸出遭截斷、要求重新提出完整呼叫。

來源：[agent loop](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/agent/src/agent-loop.ts#L217)、
[截斷呼叫處理](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/agent/src/agent-loop.ts#L434)、
[工具驗證](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/agent/src/agent-loop.ts#L664)。

Codex 的參數解析使用嚴格的 `serde_json::from_str`，解析失敗轉為
`FunctionCallError::RespondToModel`。工具派送中的部分可恢復錯誤，也會記入對話、要求下一輪處理；
它區分可交回模型的錯誤和真正 fatal error。

來源：[嚴格 JSON 解析](https://github.com/openai/codex/blob/595cc91e8cbb1c2ca822d0311dcf12709410c582/codex-rs/core/src/tools/handlers/mod.rs#L85)、
[回報模型並繼續](https://github.com/openai/codex/blob/595cc91e8cbb1c2ca822d0311dcf12709410c582/codex-rs/core/src/stream_events_utils.rs#L386)。

相對地，目前 adapter 的文字協定解析失敗會直接讓 OpenCode 收到錯誤，沒有更正機會。
在只有權限修改 adapter 的範圍內，可在尚未向 OpenCode 釋出任何工具前，於 adapter 內部提供一次更正機會。

建議第一版限制：

1. 只處理完整收到上游結束事件、有非空回答、且未偵測到預算耗盡的文字協定格式錯誤。
2. 保留原始使用者提示詞、工具 schema、工具選擇限制與歷史；加入 adapter 協定錯誤說明，要求重新產生完整 envelope。
3. 最多一次更正；不在已輸出工具、網路中斷、上游錯誤、未知工具或權限限制失敗後自動重送。
4. 更正結果仍須通過原有 JSON、工具名稱、參數 schema 與 tool_choice 驗證；不猜測參數、不執行部分呼叫。
5. 不向 OpenCode 假造工具呼叫、呼叫 ID、成功結果；這是 adapter 協定更正，不是工具已經執行。
6. 更正請求與原請求共享明確的整體時間／token 限制；回報合計 usage，記錄嘗試次數，保留取消能力。

以上是待實作與驗證的設計。先前一次更正實驗在 45 秒逾時，**不足以判定所有有限更正流程無效**。
但也不能因為其他 harness 採用此模式，就宣稱 Merlin 上已成功。

## 3. Pi 確實會修 JSON，但不宜直接複製

Pi 有修補字串中非法跳脫／控制字元的 `repairJson`，也使用 `partial-json` 解析不完整 JSON。
OpenAI-compatible provider 在工具參數處理中使用這些函式，不只是 UI 顯示；之後還有 schema 驗證與型別轉換。

來源：[json-parse.ts](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/ai/src/utils/json-parse.ts#L28)、
[provider 工具解析](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/ai/src/api/openai-completions.ts#L449)、
[參數驗證](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/ai/src/utils/validation.ts#L317)。

我們的 Merlin 文字模擬協定沒有同等可靠的原生工具邊界與 `finish_reason=length` 契約。
補好括號後，`write` 的 content 可能只是被截斷但仍通過字串 schema 的程式碼。
因此較合適的是借用 Codex 的嚴格解析與回報錯誤，讓模型重新產生，不直接導入寬鬆 JSON 修補。

## 4. 保存推理狀態，不等於把推理文字展示給使用者

Pi 的 provider 轉換會保留供應商支援的 thinking/signature、reasoning details；
Codex 的 Responses 請求包含 `reasoning.encrypted_content`，用於保留模型所需的推理項目。

來源：[Pi 訊息轉換](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/ai/src/api/openai-completions.ts#L1297)、
[Codex Responses 請求](https://github.com/openai/codex/blob/595cc91e8cbb1c2ca822d0311dcf12709410c582/codex-rs/core/src/client.rs#L932)。

目前 adapter 未把 Merlin reasoning delta 作為下一輪供應商推理狀態傳回。
這是值得查證的多回合差異，但不是已證實根因：第一輪同樣可能耗盡預算，
且已檢視的 Merlin 官方擴充套件也沒有把這些 delta 放入 assistant 歷史。
先確認上游接受何種欄位或 opaque state，再設計傳遞；不可把原始推理文字塞進 system prompt 代替正式契約。

## 5. 縮短上下文與重試各有用途

Pi 的 `isRecoverableLength` 要求實際輸出少於原定輸出上限，才符合該種壓縮後重試的判定。
單看這個分支，32000/32000 並不符合；不能把壓縮上下文視為本案預算耗盡的通用修復。

來源：[overflow.ts](https://github.com/earendil-works/pi/blob/3c75b2747965e8d69ad9e17cbe788b2e33bf4d99/packages/ai/src/utils/overflow.ts#L170)。

Codex 對 `response.incomplete` 讀取未完成原因，回報 stream error，而不是當成成功。
其傳輸重試另外判定錯誤是否可重試、計算退避與次數；這不等於推理用光後可無限接續。

來源：[未完成回應](https://github.com/openai/codex/blob/595cc91e8cbb1c2ca822d0311dcf12709410c582/codex-rs/codex-api/src/sse/responses.rs#L479)、
[重試政策](https://github.com/openai/codex/blob/595cc91e8cbb1c2ca822d0311dcf12709410c582/codex-rs/core/src/responses_retry.rs#L50)。

## 修復順序與驗收

1. **先補有限的協定更正流程**：針對非空且未耗盡預算的格式錯誤，證明不釋出無效呼叫、
   不重複執行、不無限重試，且串流與非串流行為一致。搭配通用的短步驟 adapter 指令再評估。
2. **增加使用量可見性**：目前 `_openai_usage` 只轉換 input/output/total；可另傳 reasoning token 明細，
   區分模型在思考、輸出工具參數、或真正截斷。這是觀測改善，不宣稱能停止過度推理。
3. **查證 Merlin 推理控制與狀態傳遞契約**：數值限制、effort、原生工具、推理狀態各自驗證，
   不能用 HTTP 200 或另一家 API 的文件當成支援證明。
4. **以原始任務驗收**：先離線測試錯誤分類與更正界限，再用相同提示詞做真實 OpenCode 多回合測試。
   要有工具實際執行、場景檔案、程式檢查及正常最終回答；重跑確認穩定性，並記錄總 token／耗時。

若修好格式更正後仍只得到空白、推理耗盡的回應，應維持明確失敗並保留診斷；
此時才評估有明確推理控制契約的其他上游路由，而不是持續疊加「少想一點」的提示詞。

相關：[GLM 5.3 實測與診斷紀錄](glm53-reasoning-research-2026-09-20.md)。
