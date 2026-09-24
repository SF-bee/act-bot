# Ubuntu 部署（22.04 / 24.04）— 生产环境（推荐）

> 结构：协议端（NapCat）+ 业务层（本仓库）。
> 业务层步骤与各平台相同；**NapCat 环节按本文档执行，不要照搬其他平台**。

## 0. 准备

- Ubuntu 22.04 / 24.04，2C2G 起；固定公网 IP 更利于账号稳定；
- 安装 `git` 与 [uv](https://docs.astral.sh/uv/)；
- （可选）Docker + Compose（方式 A 使用）。

## 1. 方式 A（推荐）：Docker Compose

> TODO（实施时完善）：以 napcat-docker 官方文档为准，把 compose 模板固化到 `deploy/docker/`。

1. 部署 NapCat 容器（Linux amd64 / arm64 镜像），挂载持久化数据卷；
2. WebUI（6099）仅内网访问（安全组 / ufw 限制，切勿裸奔公网）；
3. 部署业务层（本仓库）：可直接跑在宿主机，也可独立容器；
4. `.env` 的 `ONEBOT_ACCESS_TOKEN` 与 NapCat 侧配置保持一致。

## 2. 方式 B：原生

1. NapCat 一键脚本（支持 Ubuntu 20+，含 TUI / CLI 选项）：

   ```bash
   curl -o napcat.sh \
     https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh \
     && bash napcat.sh
   ```

   按提示完成安装与扫码登录（测试号 / 正式小号）。

2. 业务层：

   ```bash
   cd /opt/act-bot        # 或任意目录
   uv sync
   cp .env.example .env && vi .env
   uv run python scripts/doctor.py
   uv run python scripts/bootstrap_admin.py
   ```

3. 自启（systemd，模板 `deploy/linux/`，实施时补全）：`napcat.service` + `act-bot.service`。

## 3. 防火墙与安全

- 仅开放必要端口；NapCat WebUI（6099）不暴露公网；
- 业务层 8080 端口仅对协议端所在网络开放（同机部署时绑 `127.0.0.1`）。

## 4. 验收

```bash
uv run python scripts/smoke_protocol.py --url ws://127.0.0.1:3001 --token <token>
```

然后按 `docs/acceptance.md` 逐项打勾。
