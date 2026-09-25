# macOS（Apple Silicon）开发环境

> 定位：**主开发环境**（业务层开发 / 运行 / 联调）。macOS 不作为生产部署承诺。

## 1. 一次性准备

- macOS 13+（Apple Silicon，arm64）
- 安装 [uv](https://docs.astral.sh/uv/)（推荐）与 git
- （可选，联调用）Docker Desktop（arm64），用于跑 Linux 容器

## 2. 起步

```bash
cd act-bot
uv sync
cp .env.example .env           # 按需修改（可先留默认）
uv run python scripts/doctor.py
```

## 3. 日常开发

```bash
uv run pytest -q                    # 单元测试（离线）
uv run python scripts/smoke_fake.py # 端到端冒烟（Fake 协议端，无需 QQ）
uv run python bot.py                # 本地启动（默认 127.0.0.1:8080）
```

## 4. 协议端（联调用）三种接法

1. **Fake OneBot（默认）**：`scripts/smoke_fake.py` 内置；离线开发全部业务功能。
2. **本地真实联调（推荐）**：Docker Desktop 跑 Linux 版 NapCat 容器（arm64 镜像）——
   直接复用模板：`docker compose -f deploy/docker/docker-compose.yml up -d napcat`
   （只起协议端；业务层仍在宿主机跑，反向 WS 指向 `ws://host.docker.internal:8080/onebot/v11/ws`）；
   ⚠️ 此时业务层**必须监听 0.0.0.0**（容器经 Docker 网关 192.168.65.254 进来，绑 127.0.0.1 会一直被拒）：
   `HOST=0.0.0.0 uv run python bot.py`（临时覆盖即可，不必改 `.env`）；
   在容器 WebUI（6099 端口）扫码登录一个**测试小号**；
   注意 macOS Docker 的 UID/GID、挂载语义与 Linux 主机不同（见 `docs/platform-notes.md`）。
3. **远程联调（可选）**：连后续 Ubuntu 测试机上的协议端（内网 / SSH 隧道；不要裸奔公网）。

本机不需要安装任何原生 NapCat（社区 Mac 安装器属于实验项，不纳入验收）。

## 5. 保活（联调别再用前台会话跑）

前台终端 / 带超时的任务跑 `bot.py`，进程一被带走，NapCat 那边就是刷屏的 `ECONNREFUSED`。
用 LaunchAgent 托管（等价于 Linux 的 systemd unit，`KeepAlive` 自动重启）：

```bash
sed -e "s#__REPO_PATH__#$PWD#g" -e "s#__HOME__#$HOME#g" \
    deploy/macos/com.actbot.dev.plist.template > ~/Library/LaunchAgents/com.actbot.dev.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.actbot.dev.plist
```

详见 `deploy/macos/README.md`（含停止、看日志、重启命令）。

## 6. 排障：真实端点连不上

- **NapCat 日志刷 `connect ECONNREFUSED ...:8080`**：业务层没起，或绑在 127.0.0.1（见上）；
- **业务层报 `[Errno 48] address already in use`**：8080 被上次残留进程占着，先 `lsof -nP -iTCP:8080 -sTCP:LISTEN` 看清是谁；
- 两侧 token 必须一致（`.env` 的 `ONEBOT_ACCESS_TOKEN` ↔ NapCat 反向 WS 的 token；本机联调可都留空）。

## 7. 注意事项

- 本机 `data/` 只用于开发调试；**生产数据不要放在开发机上直接改**；
- 提交前跑一遍 `uv run pytest -q` 与 `scripts/doctor.py`；
- 与 Windows / Ubuntu 的行为差异由三平台 CI 兜底，本地无需模拟。
