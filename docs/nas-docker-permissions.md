# Synology NAS：sudo 免密碼與 Docker 免 sudo

2026-10-03 已設定並實際驗證：`mark12433` 已加入 `docker` 群組；`/var/run/docker.sock` 為 `root:docker`、權限 `660`。以全新 SSH 連線直接執行 `docker version` 與 `docker ps` 成功，沒有使用 sudo；daemon 版本為 24.0.2。

現有 daemon 設定已備份，並保存 `"group": "docker"`；其他 JSON 選項維持原值，Docker 的 `--validate` 檢查通過。備份位於 `/volume2/homes/mark12433/merlinai-update-20261003-model-catalog/docker-daemon-backup-20261003/dockerd.json.before`，只有 root 可讀。

本次沒有重啟 ContainerManager；現在的 socket 權限已生效，儲存的 `group` 設定供 daemon 下次啟動使用。尚未以 ContainerManager 重啟實測設定的延續性。

Docker 群組可完整控制 root 執行的 Docker daemon，權限等同 root。[Docker 官方說明](https://docs.docker.com/engine/install/linux-postinstall/)

## sudo 免密碼：已完成

2026-10-03 23:48（Asia/Taipei）以全新 SSH 連線核對，`mark12433` 執行 sudo 指令、`sudo -v` 與 `sudo -l` 均無需密碼。驗證使用 `-k -n` 略過既有認證快取，且不允許互動提示；執行 `id -u` 實際取得 root UID 0。

規則位於 `/etc/sudoers.d/zzzz-merlinai-mark12433-nopasswd`，擁有者為 root，權限 `0440`：

```sudoers
Defaults:mark12433 verifypw=never
mark12433 ALL=(ALL:ALL) NOPASSWD: ALL
```

這讓該帳號的所有 sudo 指令可免密碼執行。`verifypw=never` 限定此帳號，讓 `sudo -v` 也免密碼；只有 `NOPASSWD` 指令規則時，其他原有群組規則仍可能使 `sudo -v` 要求密碼。[sudo 官方手冊原始碼](https://github.com/sudo-project/sudo/blob/main/docs/sudoers.mdoc.in)

NAS 沒有 visudo，設定過程以已安裝的 sudo policy parser 檢查，並在非 root 子程序中實際核對免密碼指令、驗證與權限查詢；若檢查失敗，腳本會回復修改。原 `/etc/sudoers` 保持原內容，備份位於 `/volume2/homes/mark12433/merlinai-update-20261003-model-catalog/sudoers-backup-20261003/sudoers.before`，只有 root 可讀。

可在新的 SSH 連線自行核對：

```bash
sudo -k -n id -u
sudo -k -n -v
sudo -k -n -l
docker ps
```

第一個指令應回傳 `0`；其他指令應直接成功，沒有密碼提示。

## 首次建立群組與授權

首次仍需由管理員執行：

```bash
sudo /usr/syno/sbin/synogroup --add docker mark12433
sudo chgrp docker /var/run/docker.sock
sudo chmod 660 /var/run/docker.sock
```

登出 SSH 並重新登入後驗證：

```bash
id -nG
/usr/local/bin/docker ps
```

初次核對時 `docker` 群組不存在，所以使用 `--add` 建立並加入帳號。現在群組已存在，不需重跑建立指令；新增其他帳號時需保留其原有成員，因為 Synology 的 `--member` 會取代整份成員名單。[Synology 官方 CLI 管理手冊](https://global.download.synology.com/download/Document/Software/DeveloperGuide/Firmware/DSM/All/enu/Synology_DiskStation_Administration_CLI_Guide.pdf)

## Docker 重啟後維持設定

上述 socket 群組修改只作用於目前的 socket。這台 NAS 的 Docker 24.0.2 由 ContainerManager 啟動，執行參數指定的設定檔為：

```text
/var/packages/ContainerManager/etc/dockerd.json
```

本次已由管理員備份設定檔，再在現有 JSON 中設定：

```json
"group": "docker"
```

Docker 的 `group` 設定指定新建 Unix socket 的群組。[Docker daemon 官方文件](https://docs.docker.com/reference/cli/dockerd/)

JSON 與 daemon 設定驗證已通過。日後需實際驗證 ContainerManager 重啟時，應安排維護時段，因為這項操作涉及其他 NAS 容器。

Docker socket 存取權與 NAS 專案檔案的寫入權是分開的。這次部署的專案原始碼與備份目錄由 root 擁有，部署腳本仍透過 sudo 取得管理員權限；依本次新增規則，`mark12433` 不需再次輸入密碼。

本機驗證紀錄位於 `logs/nas-deploy-20261003/` 的 `docker-permissions-result.json`、`docker-access-verification.json`、`sudo-permissions-result.json` 與 `sudo-access-verification.json`；`logs/` 不納入 Git，紀錄不含密碼或完整 daemon 設定。第一次 sudo 指令已免密碼、但 `sudo -v` 仍要求密碼的診斷，另保存在名稱含 `initial` 的紀錄中。
