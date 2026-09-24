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
   在容器 WebUI（6099 端口）扫码登录一个**测试小号**；
   注意 macOS Docker 的 UID/GID、挂载语义与 Linux 主机不同（见 `docs/platform-notes.md`）。
3. **远程联调（可选）**：连后续 Ubuntu 测试机上的协议端（内网 / SSH 隧道；不要裸奔公网）。

本机不需要安装任何原生 NapCat（社区 Mac 安装器属于实验项，不纳入验收）。

## 5. 注意事项

- 本机 `data/` 只用于开发调试；**生产数据不要放在开发机上直接改**；
- 提交前跑一遍 `uv run pytest -q` 与 `scripts/doctor.py`；
- 与 Windows / Ubuntu 的行为差异由三平台 CI 兜底，本地无需模拟。
