# deploy/linux/

## 业务层自启：`act-bot.service`

```bash
cd /opt/act-bot
sudo cp deploy/linux/act-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now act-bot
systemctl status act-bot
journalctl -u act-bot -f
```

单元里默认约定：仓库在 `/opt/act-bot`，运行账号 `actbot`，虚拟环境 `/opt/act-bot/.venv`。
与实际情况不一致就改这三处（**不要**把 QQ 号 / token 写进 unit，它们来自 `.env`）。

## 协议端（NapCat）自启

**本目录不提供 napcat.service**，因为 NapCat 的自启方式取决于部署路线，强行给一份模板反而误导：

| 路线 | 自启方式 |
| --- | --- |
| 官方一键脚本（原生） | 安装时选择，脚本自带 systemd 服务；`systemctl status napcat` 查看 |
| Docker Compose | `deploy/docker/docker-compose.yml` 已写 `restart: unless-stopped`，无需自建 unit |

## 防火墙（ufw 示例）

```bash
sudo ufw allow 22/tcp                 # SSH
# 8080 只对协议端所在网络开放；同机部署时 .env 用 HOST=127.0.0.1，无需开端口
# 6099（NapCat WebUI）绝不对外开放，需要时用 SSH 隧道：ssh -L 6099:127.0.0.1:6099 <user>@<host>
```
