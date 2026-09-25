# deploy/

分平台部署资源（**已固化，不再是占位**）：

| 目录 | 内容 | 状态 |
| --- | --- | --- |
| `docker/` | `Dockerfile` + `docker-compose.yml`（napcat + act-bot）+ README | 已固化；`docker compose config` 校验通过 |
| `linux/` | `act-bot.service`（systemd）+ README（含 NapCat 自启说明、ufw 示例） | 已固化；需在目标机 `systemctl` 实测 |
| `windows/` | `install-act-bot-service.ps1`（NSSM）+ `start-act-bot.bat` + README | 已固化；需在 Windows 上实测 |
| `macos/` | `com.actbot.dev.plist.template`（LaunchAgent 保活）+ README | 已固化；已在本机实测（`kill -9` 后约 8 秒自动拉起） |

## 通用约定

- 模板里**不含** QQ 号、token、机器绝对路径；凭据一律来自仓库根 `.env`（不入库）；
- 部署路径（如 `/opt/act-bot`、`C:\act-bot`）是运维约定，可按实际修改；
- 部署完成后按 `docs/acceptance.md` 逐项打勾；
- 平台差异（尤其协议端）先读 `docs/platform-notes.md`。
