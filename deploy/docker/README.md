# Docker 部署模板（协议端 + 业务层）

> 状态：模板已固化；`docker compose config` 语法校验通过。**镜像构建与端到端联调需在目标机器按 `docs/acceptance.md` 实测。**
> 凭据全部来自 `.env`（不入库）；本目录不含任何 QQ 号 / token / 机器绝对路径。

## 1. 前置

- Linux 生产机：Docker Engine + Compose v2（`docker compose version`）；
- macOS / Windows：Docker Desktop（Windows 需 WSL2 后端）；Docker Desktop 必须常驻，否则容器不随开机自启；
- 仓库根已有 `.env`（`cp .env.example .env` 后填写，至少设置 `ONEBOT_ACCESS_TOKEN` 与 `ACTBOT_BOOTSTRAP_ADMIN_QQ`）。

## 2. 首次部署

```bash
cd <仓库根>
uv sync                                  # 首次先在宿主机构建 .venv（可选，仅为了跑脚本）
cp .env.example .env && vi .env           # 填凭据（ONEBOT_ACCESS_TOKEN 必须设置）

# 首次初始化业务数据（建库 + 迁移 + 写入 owner 管理员）
docker compose -f deploy/docker/docker-compose.yml run --rm act-bot python scripts/doctor.py
docker compose -f deploy/docker/docker-compose.yml run --rm act-bot python scripts/bootstrap_admin.py

# Linux 宿主：带上 UID/GID；Windows / macOS 去掉这两个变量
NAPCAT_UID=$(id -u) NAPCAT_GID=$(id -g) docker compose -f deploy/docker/docker-compose.yml up -d --build
```

数据落盘位置：`deploy/docker/runtime/`（业务库 `act-bot-data/`、NapCat 配置与登录态 `napcat/` `ntqq/`）。**该目录不入库，也是换届交接要备份的对象。**

## 3. 协议端登录与连线

0. **免扫码（推荐）**：在 `deploy/docker/.env` 里设 `NAPCAT_QQ=<机器人QQ号>`——compose 会作为 `ACCOUNT` 传给容器，镜像 entrypoint 执行 `qq -q $ACCOUNT` 走快速登录（实测重建容器后直接 `正在快速登录`，无需扫码）。留空则走下面的扫码流程。
1. 取 WebUI 登录 token：`docker compose -f deploy/docker/docker-compose.yml logs act-napcat | head -50`
2. 隧道访问 WebUI（**不要**把 6099 暴露公网）：
   ```bash
   ssh -L 6099:127.0.0.1:6099 <user>@<生产机>
   # 浏览器打开 http://127.0.0.1:6099/webui ，用测试小号扫码
   ```
3. 在 WebUI → 网络配置里添加**反向 WebSocket**（契约见 `docs/onebot-contract.md`）：
   - URL：`ws://act-bot:8080/onebot/v11/ws`（NapCat 在容器内 → 用服务名；NapCat 在宿主机时用 `ws://127.0.0.1:8080/onebot/v11/ws`）
   - Token：与 `.env` 的 `ONEBOT_ACCESS_TOKEN` **完全一致**；
   - 握手头由 NapCat 侧自动携带 `X-Self-ID`，无需额外配置。
4. 断线重连由协议端负责（NapCat 会自动重连），业务层只等待接入。

## 4. 验收

```bash
# 正向 WS 契约冒烟（3001 绑定在 127.0.0.1，故在宿主机执行）
uv run python scripts/smoke_protocol.py --url ws://127.0.0.1:3001
# 群内发 /ping 应回 pong；随后按 docs/acceptance.md 逐项打勾
```

## 5. 排障

- **`docker build` 拉不到基础镜像 / `failed to resolve ... registry-1.docker.io: EOF`**：
  属网络问题（非仓库问题）。给 Docker 配置镜像加速器，或在能访问的机器上预拉
  `python:3.13-slim` 与 `ghcr.io/astral-sh/uv:latest` 后再构建。
  > 本机（开发 Mac）实测：Docker Hub 连接不稳定，镜像构建未能本地验证；`docker compose config` 校验通过。
- **每次重建容器都要重新扫码**：`NAPCAT_QQ` 没设（= 没走 `-q` 快速登录），或 `runtime/ntqq` 数据目录被清掉；
- **容器起来但协议端 403 / 连不上**：核对 `ONEBOT_ACCESS_TOKEN` 两边一致、
  NapCat 反向 WS 地址用的是 `ws://act-bot:8080/onebot/v11/ws`（同一 compose 网络内）。

## 6. 平台差异（详见 docs/platform-notes.md）

| 差异点 | Ubuntu | Windows（Docker Desktop） | macOS（Docker Desktop） |
| --- | --- | --- | --- |
| 容器类型 | 原生 Linux 容器 | WSL2 内 Linux 容器 | 虚拟机内 Linux 容器 |
| `NAPCAT_UID/GID` | 用 `$(id -u)` / `$(id -g)` | 不适用，保持默认 | 语义不同，保持默认 |
| 自启 | docker 服务 + `restart: unless-stopped` | Docker Desktop 需常驻 + 容器 restart | 同 Windows |
| 挂载属主 | 正常 | 经 WSL2，多为 root，注意 CRLF | 经虚拟机映射 |

## 7. 常用运维

```bash
C=deploy/docker/docker-compose.yml
docker compose -f $C ps                       # 状态
docker compose -f $C logs -f act-bot          # 业务层日志
docker compose -f $C exec act-bot python scripts/backup.py   # 手动备份
docker compose -f $C restart act-bot          # 改完 .env 后重启业务层
docker compose -f $C down                     # 停止（数据在 runtime/ 不会丢）
```

> 只想要协议端、业务层仍跑在宿主机（macOS 联调常见）：
> `docker compose -f deploy/docker/docker-compose.yml up -d napcat`，
> 此时 NapCat 反向 WS 指向 `ws://host.docker.internal:8080/onebot/v11/ws`（macOS / Windows）或 `ws://172.17.0.1:8080/...`（Linux）。
