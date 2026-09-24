# Windows 部署（10 / 11）— 接管环境

> 结构：协议端（NapCat）+ 业务层（本仓库）。
> **Windows 的协议端部署与 Ubuntu / macOS 完全不同**，不要照搬 Linux 教程。

## 0. 准备

- Windows 10 / 11；
- 安装 Python 3.10+ 与 [uv](https://docs.astral.sh/uv/)、git；
- 一台常开、不休眠的设备（电源计划设为"从不睡眠"）。

## 1. 协议端（三选一）

1. **Shell + QQ 客户端（推荐）**：安装并保持 QQ 最新；下载 `NapCat.Shell.zip` 解压后双击
   `launcher.bat`（Win10 用 `launcher-win10.bat`）启动；
2. **一键版**（无需安装 QQ，仅 AMD64）：下载 `NapCat.Shell.Windows.OneKey.zip`，运行
   `NapCatInstaller.exe` 后用 `napcat.bat` 启动；
3. **NapCatQQ-Desktop**（可视化）：适合不熟悉命令行的同学。

> 注意：Framework / LiteLoader 路线官方已不推荐。

## 2. 业务层

```powershell
cd act-bot
uv sync
copy .env.example .env      # 填配置（含 ONEBOT_ACCESS_TOKEN）
uv run python scripts\doctor.py
uv run python scripts\bootstrap_admin.py
uv run python bot.py
```

## 3. 自启（二选一）

- NSSM / WinSW 把 `uv run python bot.py` 注册为 Windows 服务（推荐）；
- "任务计划程序"登录时启动（简单但不够稳）。

（模板见 `deploy/windows/`，实施时补全。）

## 4. 平台注意（详见 `docs/platform-notes.md`）

- 不要照搬 Linux 的 `UID/GID` 等参数（Docker 路线的差异见 platform-notes）；
- 防火墙仅放行必要端口；
- 控制台编码：建议用 Windows Terminal；业务层已统一 UTF-8 处理。

## 5. 验收

按 `docs/acceptance.md` 逐项打勾（含 `smoke_fake` 与真实端点冒烟）。
