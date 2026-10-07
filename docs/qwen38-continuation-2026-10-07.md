# Qwen 3.8 Max 截斷回應續寫（2026-10-07）

Merlin 提前結束工具 JSON 時，adapter 現在能保留完整原前綴，請 Qwen 追加缺少的
後綴，再驗證整份回應。已用真正的 OpenCode、原雨夜便利店提示詞，恢復被截斷的
write 和 3 個 edit 呼叫；不代表每次續寫都能成功，也不代表完整場景已驗證完成。
NAS 尚未更新。

## 處理方式

- 僅適用 Qwen 3.8 Max 的 emulated tools；普通無工具文字對話不自動續寫。
- 上游必須正常 DONE，原回應須有明確 envelope 開始標記，且 JSON 錯誤須符合
  仍可追加完成的前綴。已能確認損壞的跳脫、控制字元或重複 key 不當成單純截斷；
  尚未閉合物件的重複 key 仍須等完整 JSON 驗證才會被偵測並拒絕。
- 保留呼叫端對話、工具 schema 與 tool_choice；替換 adapter 自己的格式指示，
  要求只輸出後綴，避免舊規則要求模型重送整個 envelope。
- 在開放的 JSON 字串中，續寫要保留跳脫。串接採原始文字，不裁重複段落、不猜補符號。
- 錯誤片段整片丟棄，原前綴不變；該前綴最多請模型重寫一次。有效進展後可再處理下一片。
- 完整 JSON、工具名稱、schema、tool_choice 全通過後才釋出唯一呼叫。
- 預設最多 8 次續寫，設定 `EMULATED_CONTINUATION_ATTEMPTS=0` 可停用，最高 16。
  所有片段和重寫均共享原請求剩餘 output 預算、600 秒預設時限及 SSE 資料量上限；
  不給新一份 131072 預算，不修改使用者提示詞。
- 初次回應及每一片都須有有效的 output usage；未知用量不能視為零再授予預算。
- 每片約 300 答案 tokens 是指示目標；上游 max_tokens 仍為模型上限扣除累計 output。
  檔案建立回合保留最小可執行 scaffold 的檢查點，剩餘功能由後續工具回合完成。

## 已取得的實測證據

`logs/qwen-continue-v2-array.json`：對被截斷的 1–400 JSON 陣列續寫三次，原字拼接後
恰好等於完整 400 個整數的陣列。證明普通對話請求也可用追加 assistant 歷史的方式續寫，
但普通串流無法可靠自動辨識截斷，因此未啟用自動續寫。

`logs/qwen-continue-v3-context.json`、`logs/qwen-continue-v5-context.json`：
保留原場景對話與工具規格，在已取得兩個有效片段的前綴後，用修正過的結尾指示完成
write 呼叫。4816 字元協定回應解出 4444 字元 HTML，JavaScript 模組 `node --check`
通過。沒有更改已收到的前綴。

`logs/qwen-continue-v6-context.json`：直接要求補完最初的整份檔案，360 秒沒有取得
答案片段，達整體時限。不能把一次成功視為穩定成功率。

`logs/qwen-continue-v7-context.json`、`logs/qwen-continue-v8-context.json`：
每次只要求一個片段，能持續取得合法前綴。補回檔案 checkpoint 指示後，從保留的前綴
完成 8508 字元的合法 write 回應。這些是捕獲的真實截斷樣本與真實上游續寫測試，
尚不是完整 OpenCode 任務成功證據。

`logs/opencode-scene-e2e-qwen38-v2-continuation-c3/`：真正 OpenCode v2 使用完整原提示詞，
觀察到 read、write、4 次 edit 皆為 completed，沒有工具錯誤。當中 write 與 3 次 edit
各經一次續寫補成完整 JSON 後執行；另一次 edit 的初次回應已完整。具體上游配對：

- write：`upstream-2.json`（1436 字元）與 `upstream-3.json`（973 字元）。
- edit：`upstream-4.json`（1235）與 `upstream-5.json`（179）。
- edit：`upstream-6.json`（1139）與 `upstream-7.json`（808）。
- edit：`upstream-9.json`（1050）與 `upstream-10.json`（675）。

產出 `project/index.html`（5890 bytes），抽出的 JavaScript 模組 `node --check` 通過。
觀察紀錄持續至約 210 秒；接續的一個 edit 仍在續寫，程序後來已不存在且沒有最終
`report.json`。將這輪記為中斷、部分成功，不推定其退出原因、不計為完整場景成功，
也未進行畫面品質驗證。保留的 `partial-report.json` 明確標示沒有整個任務的完成結果。

## 本機回歸

新增端點測試涵蓋串流／非串流的多片續写、跳脫與 Unicode 邊界、片段丟棄後重寫、
工具名稱／指定工具限制、未知 usage、低剩餘預算、次數上限、關閉續寫和傳輸未 DONE。
另一組測試確認先更正再續寫也計入初次請求的用量，以及反覆壞片段不釋出呼叫。
補上初次回應未知／負 output 用量不觸發續寫的端點測試後，全套 98 tests 通過，
Python compileall 和 git diff --check 通過。

原提示詞 SHA-256：
`9a60c4499055745812975984a1554837dff96d91a5b560a984ac408bff792cc3`。
此雜湊核對的是實際送出的 UTF-8 提示詞文字；Windows 寫入的 `prompt.txt` 使用 CRLF，
檔案位元組雜湊不同，但讀回後的提示詞文字與來源完全一致。
初次 model max_tokens=131072、OpenCode context=1000000；兩者保持原模型設定。
