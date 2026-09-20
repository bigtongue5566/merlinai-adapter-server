# GLM 5.3 推理預算與工具協定研究

## 結論與保留範圍

**尚未找到能完成原始場景任務的可靠修復。** 本輪 10 次真實 OpenCode 測試均未完成，
沒有產出場景檔案。單步提示有時把第一次工具選擇的推理降至數十／數百 token，
但可能在下一回合再次耗盡預算，或產生錯誤工具格式。

已撤回本輪未成功的正式程式變更：純 JSON／單一工具格式、GLM 專用提示詞與
相應實驗測試均未留在正式 API。原本已通過測試的普通回答相容、預算耗盡診斷、
未確認推理參數的 422 拒絕仍保留。**沒有放寬 JSON、工具名稱或參數驗證，
沒有改模型、自動提高 max_tokens、加入自動重試或部署至 NAS。**

本輪保留的成果是此研究紀錄及 `scripts/probe_glm_reasoning.py` 診斷工具。
正式協定提示詞函式恢復為本輪開始前的版本；失敗候選原始碼留在本機
`logs/glm-reasoning-experimental/`，不屬於可用修復。

## 可確認的原因與未知部分

1. 預算耗盡確實發生在上游。正常收到 DONE，但 output=32000、reasoning 接近 32000，
   回答文字為空。這不是 adapter 沒找到已有的 JSON，也不是網路逾時。
2. 明確限制本回合工作範圍能影響推理，但不是硬性預算控制。提示詞中的
   「少於 200／1000 reasoning tokens」是模型指示，不能視為已套用服務端限制。
3. 控制住第一步不代表多回合任務成功。a6 完成目錄讀取後，第二輪仍有 31998 個
   reasoning tokens、零回答；a7 第二輪降到 355，但待辦工具 JSON 少一個括號。
4. 工具格式是另一個問題。曾觀察到原始上游文字中的括號錯誤、參數沒有放進
   arguments、結尾標記損壞，以及上游 tool_calls 中混入 XML 的錯誤工具名稱。
   這些輸出不應被 adapter 猜測修補後執行。
5. 簡短的 `Reply exactly OK.` 請求，上游報 input=3483；MCP 開／關都是如此。
   這提示上游有額外上下文或計量行為，但**沒有上游實作證據，不能斷言隱藏指令
   衝突就是推理迴圈的唯一根因**。

## 原廠 API 與 Merlin 的差別

[Z.ai GLM 5.3 文件](https://docs.z.ai/guides/llm/glm-5.3)列明必須開啟推理，
可用 `reasoning_effort=low/high/max`，預設 max；直接 API 不支援
`thinking.type=disabled`。[官方聊天模板](https://huggingface.co/zai-org/GLM-5.3/blob/main/chat_template.jinja)
也有 reasoning effort 對應的系統文字。這些是原廠介面，不能直接推定 Merlin 會轉送。

本機官方 Merlin 8.2.3 擴充套件的 `runIteration` 只傳
`params: {tools, max_tokens}`，未找到 reasoning_effort、reasoningEffort、
thinkingBudget 或 thinkingConfig 設定。來源為 `chunks/sidepanel-Dt2U-t-U.js`，
SHA-256 `6d6d2b4fbf07fd321dac3eebdcdf3a3493ffc27723d6937963635a2df5f836cc`。

實驗結果：

| 實驗 | 結果 | 可下的結論 |
| --- | --- | --- |
| 相同完整提示詞、4000 token 控制組 | output=4000、reasoning=3998，零回答 | 此設定仍耗盡預算 |
| 在 params 加 reasoning_effort=low | output=4000、reasoning=4000，零回答 | 未證實此參數可解決問題；HTTP 200 不是採用參數的證據 |
| 系統文字加 Reasoning Effort: Low | output=4000、reasoning=4000，零回答 | 模板文字不能直接當成 API 控制 |
| 短文字請求加 thinking=disabled | 仍回 OK，reasoning=10，和控制組相同 | 沒有關閉推理，行為也不同於原廠直接 API 的拒絕 |
| GLM 原生工具、MCP=true | INTERNAL_SERVER_ERROR | 目前不能以原生工具取代文字模擬 |
| GLM 原生工具、MCP=false | 相同 INTERNAL_SERVER_ERROR | 改旗標沒有修復 |
| 原始錯誤 JSON 交回模型更正的診斷 | 45.44 秒請求逾時 | 此次更正未成功；單次逾時不足以否定有界更正流程 |

4000 token 對照是有界診斷，不是完整 OpenCode 任務；`low` 本身也不是固定 token 上限。
所以結果不證明此欄位一定遭忽略，只證明尚未建立可依賴的有效性。

## 相同原始提示詞的真實 OpenCode 測試

全部使用 `merlinai/glm-5.3`、build agent、隔離空白 Git 專案、原有 32000 output
token 上限。只更動 adapter 實驗候選；沒有附加使用者任務指示、修改原場景提示詞，
也沒有人工建立場景檔案。提示詞文字（UTF-8、LF 換行）的 SHA-256 全部相同：

`9a60c4499055745812975984a1554837dff96d91a5b560a984ac408bff792cc3`

| 本機紀錄標籤 | 秒數 | 觀察 |
| --- | ---: | --- |
| glm53-action-cycle-a1 | 260.31 | 泛用短步驟提醒仍用完 32000；reasoning=31992 |
| glm53-checkpoint-a2 | 6.19 | reasoning=91；工具 JSON 多一個括號 |
| glm53-checkpoint-a3 | 24.16 | 上游產生混有 XML 的錯誤工具名稱；無完整 usage |
| glm53-checkpoint-a4 | 5.14 | reasoning=80；command 放在 arguments 外 |
| glm53-checkpoint-a5 | 5.22 | reasoning=72；JSON 後接損壞的結尾標記 |
| glm53-json-checkpoint-a6 | 395.38 | 第一輪 read 成功，reasoning=79；第二輪 reasoning=31998，耗盡預算 |
| glm53-json-incremental-a7 | 17.22 | 第一輪 read 成功；兩輪 reasoning=95／355；第二輪待辦 JSON 缺括號 |
| glm53-compact-a8 | 476.41 | 簡化成單一工具 JSON 仍用完 32000；reasoning=31989 |
| glm53-compact-prefix-a9 | 6.20 | reasoning=123；Windows 路徑未跳脫且參數層級錯誤 |
| glm53-single-step-a10 | 7.17 | 明確 client 分步指示仍回錯誤工具名稱；無完整 usage |

每組完整紀錄位於 `logs/opencode-scene-e2e-<標籤>/`，包括 `report.json`、
`upstream-N.json`、`cli.jsonl` 與 `prompt.txt`。這些為模型的非確定性樣本，
**不能將不同候選的一次結果當成受控成功率比較**。本輪成功完成場景數是 0/10。

其他本機證據：`logs/glm-budget-*.json`、`logs/glm-transport-diagnostics.json`、
`logs/glm-transport-mcp-off.json`。原始紀錄可能有專案路徑／模型產生的內容，
`logs/` 維持不納入版本控制。

## 真正修復的驗收路徑

後續更新：新的分步指令與有界更正版本，已在 131072 請求上限下完成一次原始 OpenCode 任務
及語法檢查；該輪最高實際輸出只有 25111，尚不能把成功歸因於提高上限。
本文件上方 0/10 是較早提示詞候選的歷史結果。最新完整結果見
[可靠性改造與驗證](reliability-2026-09-20.md)。

後續已讀取 Pi 與 Codex 官方原始碼，整理成
[harness 比較與修復設計](harness-comparison-2026-09-20.md)。需要區分「已有內容但格式錯誤」
與「只有推理、零回答」：前者可在 adapter 內研究一次有界的協定更正，維持嚴格驗證，
不必等待上游改版；後者沒有可更正的工具內容，仍需查證上游預算控制。
其他 harness 的做法是設計依據，不是本專案已修復的證據。

若繼續使用 Merlin，優先需要確認其 GLM 路由是否能轉送、驗證推理強度設定，
並修正／確認 GLM 原生工具介面的支援。只有上游明確契約與實測吻合後，才應
把該參數加入正式 adapter；不能因為 HTTP 200 就移除目前的 422 保護。

若改接支援原廠推理控制的 GLM 端點，可明確使用 low 或 high，再實測此任務；
這需要新的服務憑證與路由選擇，**本輪未切換，也未宣稱可保證成功**。
單純加大 max_tokens 只是提高成本與等待上限，無法保證終止反覆規劃。

正式修復至少應通過：相同原始提示詞、完整多回合工具執行、實際檔案產出、
程式檢查與正常最終回答。之後再重跑確認不是單次偶然成功。
目前只有縮短部分回合與安全拒絕錯誤輸出的證據，尚未達成這項驗收。

## 可重跑的診斷工具

```powershell
.venv\Scripts\python.exe scripts\probe_glm_reasoning.py --request-json logs\request.json --variant baseline --max-tokens 4000 --out logs\glm-baseline-new.json
.venv\Scripts\python.exe scripts\probe_glm_reasoning.py --request-json logs\request.json --variant effort-low --max-tokens 4000 --out logs\glm-low-new.json
```

`request.json` 應為待測的 OpenAI 請求；訊息與完整工具 schema 保留原樣。
`--adapter-instruction` 可指定額外 adapter 系統指令檔，不修改呼叫端訊息。
另有 `thinking-disabled`、`native` 診斷分支；不會讓正式 API 接受未確認的參數。
所有分支都只接收模型回應，**不執行工具**，也不會改寫 OpenCode 或 NAS 設定。
預設只存使用量、長度、雜湊、工具名稱與錯誤；`--save-content` 才保存回答文字，
永不保存原始推理。時間限制在收到串流事件時檢查；等待網路讀取另受 socket timeout 限制。

完成回復後，55 項離線測試通過，Python 編譯與診斷工具 CLI 檢查通過。
新診斷工具也以獨立的 `Reply exactly OK.` 短請求通過真實傳輸檢查，
報告為 `logs/glm-probe-cli-smoke.json`；這不是場景任務測試。
這些驗證保護既有協定，不代表 GLM 場景實測已通過。
