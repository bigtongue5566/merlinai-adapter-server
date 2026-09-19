# NAS 更新紀錄（2026-09-19）

狀態：**部署完成並驗證成功**。使用者完成 sudo 驗證後，NAS 流程於 2026-09-19
13:15（Asia/Taipei）產生 `DEPLOYMENT_VERIFIED`；後續經 SSH 讀回結果，
並從本機重新連線公開 API 驗證認證與模型清單。

- SSH：`mark12433@192.168.1.2`，金鑰登入成功。
- NAS：Synology，現有專案 `/volume2/docker2/merlinai-adapter-server`。
- 現有 Compose：`merlinai-adapter-server`，host/container port `8000:8000`。
- 更新前 `.env` 使用 `merlin-extension-8.0.11`。
- 公開入口 `https://ai.mh-tech.me/v1/models` 未認證請求回 401。
- 更新包：48 個檔案，來源為目前未提交工作區；不含 `.env`、Compose、Git、logs。
- SHA-256：`8576f2a9bba571e401f4c0691bb55d8bb3e88ecba91e28a44aa1bb1423d75562`。
- 本機離線驗證：43/43 通過。

## 最終驗收

- NAS 候選映像建置及離線測試通過，才進入正式切換。
- 正式 container：`merlinai-adapter-server`，`running`，restart count `0`。
- 映像 ID：`sha256:6afd2c14aa309e91455d7af3c15c7f09fc79b4d28264d9353897a20010ad2c68`。
- 生效設定：`TOOL_CALL_MODE=emulated`、`merlin-extension-8.2.3`、
  `/arcane/api/v2/extension/chat`。
- 候選容器：17 模型清單、未認證拒絕、一般聊天、required 工具→呼叫端結果→
  串流最終回答全部通過。
- 正式容器本機：17 模型清單與未認證拒絕通過。
- 正式公開入口 `https://ai.mh-tech.me`：上述四項完整功能驗證全部通過，
  聊天與工具回合使用 `claude-sonnet-5`。
- 本機另行存取公開網址：認證後取得精確的 17 模型清單；未認證回 401。
- 部署原始碼比對 manifest：48/48 一致，沒有 hash 差異。

這次驗證涵蓋實際 NAS 容器與公開入口，未做所有模型工具回合或長時間壓測。
本機先前的模型格式偶發失敗仍見 OpenCode 驗證紀錄，不宣稱每次呼叫均成功。

## 執行

```powershell
ssh -t mark12433@192.168.1.2 'sudo /bin/sh /volume2/homes/mark12433/merlinai-update-20260919-emulated-a1/deploy.sh'
```

密碼只在終端輸入，不寫入腳本或紀錄。使用者帳號沒有 Docker socket 權限，
`sudo -n true` 回報需要密碼，因此必須由使用者完成這一步。

腳本先核對既有 container 的 Compose 工作目錄與掛載，再備份原始碼、設定與
舊映像。新映像先執行離線測試與隔離容器真實 API 測試，通過才切換正式服務。
更新 `.env` 僅涉及 extension 版本、endpoint、Origin 與 `TOOL_CALL_MODE=emulated`，
保留 NAS 帳密、API key、原 Compose 及 port mapping。

切換後檢查本機模型清單，再經公開網址檢查認證、模型清單、一般聊天，以及
required 工具→呼叫端結果→串流最終回答。通過後才同步更新部署目錄原始碼。
任何中途失敗都會留下 status；切換開始後若失敗，腳本會嘗試還原原設定與映像。

## 證據位置

準備目錄：`/volume2/homes/mark12433/merlinai-update-20260919-emulated-a1`

- `status.txt`：最後階段；只有 `DEPLOYMENT_VERIFIED` 表示完整流程通過。
- `build.log`、`offline-tests.log`：建置及測試結果。
- `candidate-verification.json`：候選容器 API 驗證。
- `production-local.json`：正式容器本機驗證。
- `production-public.json`：正式公開網址功能驗證。
- `container-status.txt`：映像 ID、執行狀態及 restart count。
- `manifest.json`：更新包檔案清單與個別 hash。

備份目錄：`/volume2/docker2/merlinai-adapter-backups/20260919-emulated-a1`。
設定備份含原有憑證，存於 root 限制目錄，不回傳到對話。
