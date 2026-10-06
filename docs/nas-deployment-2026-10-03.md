# NAS 模型清單部署驗證（2026-10-03）

本次 NAS 部署已完成，最終狀態為 `DEPLOYMENT_VERIFIED`。2026-10-03 23:25（Asia/Taipei）從獨立 Windows 電腦核對 [正式模型 API](https://ai.mh-tech.me/v1/models)：認證請求回傳 HTTP 200，23 個模型 ID 與所有容量均符合本次更新；未認證的模型及聊天請求均回傳 HTTP 401。

模型由 17 個增加至 23 個，新增 `claude-opus-5.5`、`claude-sonnet-5.5`、`gpt-6-luna`、`gpt-6-sol`、`gpt-6.1-sol`、`grok-4.7`。容量與來源核對見 [模型上限表](model-limits-2026-10-03.md) 及 [本機驗證紀錄](model-validation-2026-10-03.md)。

## 部署與備份

| 項目 | 結果 |
| --- | --- |
| NAS 專案 | `/volume2/docker2/merlinai-adapter-server` |
| 容器／Compose service | `merlinai-adapter-server` |
| 正式 API | `https://ai.mh-tech.me/v1/models` |
| 上版來源 | 已驗證的本機工作目錄，含尚未提交的模型更新 |
| 本機基準 commit | `5953a30e1a3a6ddd95be0770e25734eb98722b71` |
| 原版備份 | `/volume2/docker2/merlinai-adapter-backups/20261003-model-catalog` |
| 候選 image | `merlinai-adapter-candidate:20261003-model-catalog` |
| 回復 image | `merlinai-adapter-rollback:20261003-model-catalog` |
| 正式容器 image ID | `sha256:c9587f1a5c0a4d25c7310ad91c0374dd9130532f9553f8f7fbbb83ce296e8794` |
| 容器狀態 | `running`，`restart_count=0` |

本次以原 NAS image 的既有依賴環境建立候選版本，覆蓋本次驗證的應用程式來源。發布包的 71 個檔案與 NAS 專案逐一核對 SHA-256，正式 image 的 25 個執行檔案也逐一核對通過。NAS 舊版的 26 個基準檔案在上版前已確認一致。

發布包 SHA-256：`55aa5a4f3d5e1f26215e854f9a0fccd6bb8a2fff1e1712bf6acf71a930d5c657`。

原始 `.env` 與 `docker-compose.yml` 已備份並以位元組比對確認保持一致。正式服務保留 `emulated` 工具模式、`merlin-extension-8.2.3` 及 `/arcane/api/v2/extension/chat` 傳輸。

## 實際驗證

- NAS 候選 image 的既有單元／合約測試：81／81 通過。
- 候選版本的 GPT 6 Luna、Claude Sonnet 5.5 一般聊天與串流：4／4 通過。
- 正式公開 API 的新增 6 個模型一般聊天與串流：12／12 通過，本次最終驗收沒有觸發重試。
- 候選與正式服務的 Qwen 3.8 Max：指定工具、接收實際工具結果、再串流回答的完整回合通過；請求 `max_tokens=8192` 依既有相容行為調整為 131072。
- NAS 內部與獨立 Windows 用戶端均核對 23 個模型的完整清單、容量及 API key 認證。
- 正式容器最後 200 行日誌未見 traceback 或 HTTP 5xx。

| 新增模型 | 傳送 max_tokens | 一般聊天 | 聊天串流 |
| --- | ---: | --- | --- |
| `claude-opus-5.5` | 128000 | 通過 | 通過 |
| `claude-sonnet-5.5` | 128000 | 通過 | 通過 |
| `gpt-6-luna` | 128000 | 通過 | 通過 |
| `gpt-6-sol` | 128000 | 通過 | 通過 |
| `gpt-6.1-sol` | 128000 | 通過 | 通過 |
| `grok-4.7` | 500000 | 通過 | 通過 |

聊天驗證包含回覆 schema、模型 ID、usage 與 finish reason；串流另核對 chunk schema、無 SSE error，且以 `[DONE]` 正常結束。Grok 使用簡單算式 `7 + 8 = 15` 核對內容，其他模型使用固定測試字串。

最初兩次公開驗收因 Grok 未回覆隨機測試字串而失敗，均已自動回復原版。恢復原版後也重現 Grok 對隨機字串的拒答及一次 504；改用算式的最終驗收則兩種模式都通過。前三次驗收與診斷紀錄均保留，最終結果不代表上游日後不會拒答或逾時。

本次未在 NAS 重測其他 17 個模型的全部真實聊天回覆，也未驗證 OpenCode 檔案操作。短回覆測試不代表已驗證填滿 context 或實際產生到最大 output；Qwen 工具回合通過也不代表所有模型的工具相容性。

## 本機證據

所有詳細結果位於 `logs/nas-deploy-20261003/`，不納入 Git，未包含 NAS 密碼或 API key：

- `status.txt`、`container-status.txt`
- `manifest.json`、`release.sha256`
- `offline-tests.log`、`candidate-verification.json`
- `production-image-verification.json`、`production-source-verification.json`
- `production-local.json`、`production-public.json`
- `production-public-attempt1.json`、`production-public-attempt2.json`、`production-public-attempt3.json`
- `client-verification.json`、`container-log-verification.json`
- `grok-public-diagnosis.json`、`grok-arithmetic-verifier-check.json`

Docker 免 sudo 設定另見 [NAS 權限紀錄](nas-docker-permissions.md)。
