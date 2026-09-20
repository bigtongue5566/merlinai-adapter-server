# Qwen3.8 Max 實測（2026-09-20）

## 後續修正與覆驗

### 雨夜便利店覆驗 g1

補強單次工具呼叫的結尾範例（字串結尾後兩個右大括號），並消除單次呼叫與批次呼叫的指示矛盾後，以原提示詞重跑：
`logs/opencode-scene-e2e-qwen38-braces-g1/report.json`。
模型 Qwen3.8 Max，max_tokens=131072，自動讀取模型設定，提示詞 hash 不變。
421.36 秒完成，exit 0，14 次請求協定全部通過；13 次工具操作中 12 次成功，1 次 shell 權限拒絕後自行恢復。
產出 index.html（400 bytes）與 main.js（18308 bytes），獨立 `node --check` 通過；80 項本機回歸測試通過。
這是一次端到端成功證據，尚不代表穩定成功率。

原始產物缺少 OrbitControls 相依的 three import map，因此保留 project 原檔，在同次紀錄的 preview 目錄另外補上 import map，供 HTTP 預覽。未使用瀏覽器目視驗證，不能把協定成功當成畫面品質驗證。未修改使用者提示詞或部署 NAS。

下方為初次失敗紀錄；後續控制實驗已縮小原因，不能以低預算測試判定路由不可用。
相同簡短訊息在 max_tokens=8192、16384 時出現 SSE error；16385、32767、32768、131072 可正常回覆。
16384/16385 邊界已重複驗證。這是 Merlin 路由的觀測結果，尚未證實其內部推理預留機制。

adapter、協定更正、smoke 與 OpenCode 測試預設統一讀取 MODEL_LIMITS。
更正不再有固定 8192 或 32768 上限，而是原請求預算扣除已用 output tokens。
Qwen 明確指定低於 16385 時回 422，不偷偷提高使用者指定值。
工具協定採 Qwen 專用單次呼叫格式，仍嚴格驗證 JSON 與工具參數，不猜補括號。

最新版驗證：

- 80 項本機測試通過，包含全部 17 個模型的更正預算。
- `logs/qwen38-modelbudget-controls.json`：聊天、串流聊天、工具、串流工具 4/4 通過，全部使用 131072。
- 原提示詞 SHA-256 不變。`logs/opencode-scene-e2e-qwen38-modelbudget-f3/report.json`：251.33 秒，成功 read/write/edit，產出 5258 bytes 的 index.html，但後續 edit 及一次更正仍缺外層 JSON 結尾括號，任務失敗。這不是完整場景交付。
- 較早單次呼叫候選版 f2 曾成功產出 20405 bytes HTML，但其更正預算政策不同，不能代替最新版完整通過證據。

本次已修正各模型預算設定與低預算 SSE 問題；長內容工具 JSON 的穩定性仍待改善。未部署 NAS。

## 初次失敗紀錄

使用目前本機 adapter、emulated 模式、真正的 OpenCode build agent。
原始雨夜便利店提示詞不變，SHA-256：
`9a60c4499055745812975984a1554837dff96d91a5b560a984ac408bff792cc3`。
模型 `qwen-3.8-max`，輸出上限 131072、context 設定 1000000，隔離空白 Git 專案。

結果：46.24 秒後失敗，沒有產檔。

1. 第一次上游回應合法，output=116、reasoning=45；OpenCode 成功執行 read，讀取目錄。
2. 第二次 output=1379、reasoning=239，產生 3563 字元工具內容，但 JSON 不合法，因此未釋出工具。
3. adapter 進行一次協定更正，Merlin 回上游 SSE error，沒有回答或 usage；任務明確失敗。

這次沒有推理預算耗盡證據。adapter 沒有猜補參數、執行錯誤呼叫或回傳成功 DONE。

簡短聊天對照（max_tokens=1000、不帶工具）：

| 模式 | 秒數 | 結果 |
| --- | ---: | --- |
| 非串流 | 2.81 | HTTP 502 |
| 串流 | 2.45 | Merlin 上游 SSE error |

因此上游錯誤不只出現在原場景或高輸出上限；但原場景最初兩次請求確實有回應，
不能把此結果描述成 Qwen 路由完全不可用。詳細供應商原因未取得。
本次未更改 adapter、原提示詞、全域設定或 NAS。

完整紀錄：`logs/opencode-scene-e2e-qwen38-max-current-e1/report.json`、
該目錄下 `upstream-1.json` 至 `upstream-3.json`，及 `logs/qwen38-current-controls.json`。
