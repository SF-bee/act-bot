# 平台差异备忘（必读）

> **前置声明：NapCat 在 macOS / Ubuntu / Windows 上不存在统一的部署方式。**
> 业务层（本仓库）跨平台；协议端（QQ 接入）逐平台单独部署，以下是差异总表。

## 1. 支持矩阵（协议端）

| 平台 | 协议端部署方式（各不相同） | 级别 | 已知限制 |
| --- | --- | --- | --- |
| Ubuntu 22.04 / 24.04 | ① 官方一键脚本（Shell 无头，支持 Ubuntu 20+，含 TUI / CLI / Docker 选项）② Docker 镜像（Linux amd64 / arm64） | ✅ 生产（推荐） | 无需图形环境 |
| Windows 10 / 11 | ① Shell + QQ 客户端（Win10 用 `launcher-win10.bat`）② "一键版"（内置 QQ、免安装，仅 AMD64）③ NapCatQQ-Desktop（GUI） | ✅ 接管环境 | Framework / LiteLoader 官方已不推荐；自启用服务 / 计划任务 |
| macOS（Apple Silicon） | ① Docker Desktop 跑 Linux 容器（arm64，联调用）② 社区安装器（实验） | ⚠️ 非生产；仅开发 / 联调 | 与 Linux 的 UID/GID、挂载语义不同 |

## 2. "禁止假设"清单

1. 不假设脚本 / 安装包跨平台通用（Ubuntu 脚本 ≠ Windows 一键版 ≠ macOS 安装器）；
2. 不假设 Docker 行为一致（Windows 需 Docker Desktop + WSL2；镜像仅 Linux 容器；`UID/GID` 参数在 Windows 不适用；挂载属主、换行符、自启方式均有差异）；
3. 不假设 QQ 客户端依赖一致（Linux 无头；Windows 需安装或使用内置一键版；macOS 社区方案）；
4. 不假设自启机制一致（systemd / Windows 服务 / 手动托管）；
5. 不假设路径、编码、权限行为一致（统一走业务层跨平台规范，见下）。

## 3. Docker 平台差异速查（Ubuntu vs Windows vs macOS）

| 差异点 | Ubuntu | Windows | macOS |
| --- | --- | --- | --- |
| 容器类型 | 原生 Linux 容器 | WSL2 内 Linux 容器 | 虚拟机内 Linux 容器 |
| UID/GID 参数 | 使用 `$(id -u)` | 不适用（用官方简化命令） | 语义不同（Docker Desktop 接管） |
| 数据卷 | bind mount 正常 | 经 WSL2 挂载，属主多为 root；注意 CRLF | 经虚拟机映射 |
| 自启 | docker 服务自启 | Docker Desktop 需常驻 | Docker Desktop 需常驻 |
| 网络 | host 网络可用（本设计不用） | 统一端口映射 | 统一端口映射 |

## 4. 业务层跨平台规则（CI 守护）

1. 路径只用 `pathlib`；数据目录来自 `ACTBOT_DATA_DIR`；禁止硬编码路径；
2. 文本 I/O 显式 `utf-8`；行尾由 `.gitattributes` 管理；
3. 不使用 fork / chmod / 符号链接依赖 / 高级信号；
4. 调度用 APScheduler（不依赖 cron / 计划任务也能工作）；
5. 时区用 `zoneinfo` + `tzdata`（Windows 必装）；
6. 数据库 SQLite 不放网络盘 / 网盘同步目录；
7. 子进程禁止 `shell=True` 拼接；
8. **事件循环**：业务代码不得依赖 uvloop（Windows 无此包）。uvicorn 在 macOS / Linux 上可能自动启用 uvloop——CI 三平台矩阵同时覆盖"有 / 无 uvloop"两种环境，两边都必须全绿；
9. 全部业务代码须在 macOS / Ubuntu / Windows 三平台 CI 通过。

## 5. 参考

- 接口契约：`docs/onebot-contract.md`
- 各平台部署：`docs/deploy-macos-dev.md` / `deploy-ubuntu.md` / `deploy-windows.md`
