# ACT Bot 技术方案设计（v0.3 · 双契约版）

- 日期：2026-09-24 ｜ 整理：尤莉娅 ｜ 状态：已批准，P0 实施中（本文件为仓库设计基线）
- v0.3 变更：**"业务代码跨平台"与"协议端平台限制"分离设计（双契约）**；主开发平台明确为 **macOS（Apple Silicon）**；正式部署目标 Ubuntu；Windows 必须支持；**不假设 NapCat 在三平台具有相同部署方式**。
- r2（2026-09-24 22:01）：**开发环境正式定为 macOS（Apple Silicon，本机直接开发）**；补充 macOS 本地联调方案（Docker Desktop + Linux 版 NapCat 容器）；新增"已定 / 待定"决策状态。
- 核心原则：**账号是可替换的，项目和数据才是 ACT 的资产。**（延伸：协议端可替换、操作系统可替换，业务层对所有平台一视同仁。）

## 0. 一句话结论

业务代码（ACT Bot）与 QQ 协议接入端（NapCat 等）**彻底分离、分别设计**：业务层 100% 跨平台（macOS Apple Silicon 主开发 / Ubuntu 生产 / Windows 支持），只依赖一份固化的 **OneBot v11 接口契约**；协议端是**平台相关且可替换**的独立组件——三平台部署方式互不相同、各自建档，业务代码对其零感知。

## 1. 设计总则：两层分离（双契约）

| 维度 | 业务层（ACT Bot 业务代码） | 协议端（QQ 接入层） |
| --- | --- | --- |
| 内容 | 插件逻辑、权限、数据、调度、备份 | QQ 登录、消息收发（NapCat 等） |
| 平台属性 | **完全跨平台**，三平台行为一致 | **平台相关**，三平台部署方式互不相同 |
| 接口 | 只认 **OneBot v11 契约子集**（WebSocket） | 实现该子集 |
| 验证 | CI 三平台矩阵 + 规则守护测试 | 每平台一份部署文档 + 验收清单 |
| 替换 | 换平台/换系统零改动 | 换平台需按对应文档重装；换实现 = 换连接地址 |

**接口契约**：业务层把用到的 OneBot v11 能力（事件 + API）固化为 `docs/onebot-contract.md`（实现阶段编写，MVP 用到多少写多少）：
- 事件：群消息、私聊消息（如需）、群成员进/退群事件、元事件（心跳）；
- API 起始清单（示例）：`send_group_msg`、`get_group_member_info`、`set_group_ban`、`set_group_kick`、`delete_msg`、`get_msg`。
- 业务代码只依赖该子集；Fake OneBot（测试用模拟器）实现同一子集；换协议端只要求子集兼容。

**配套铁律：**
1. 业务代码**禁止**出现 `sys.platform` / `os.name` 分支，禁止任何 NapCat/平台专属细节；
2. 平台差异只允许存在于：协议端安装方式、部署方式（自启/服务）、部署文档；
3. 同一份代码 + 同一份数据，在三个平台行为一致。

## 2. 协议端平台支持矩阵（独立章节 ★）

> **前置声明：NapCat 在 macOS / Ubuntu / Windows 上不存在统一的部署方式。** 以下三套方案互相独立，安装、启动、自启、维护方式全部分开处理。

| 平台 | 部署方式（各不相同） | 支持级别 | 已知限制 |
| --- | --- | --- | --- |
| **Ubuntu 22.04/24.04** | ① 官方一键脚本（Shell 无头；支持 Ubuntu 20+，含 TUI/CLI/Docker 选项）② Docker 镜像（Linux amd64/arm64） | ✅ 生产（推荐） | 无需图形环境；低内存占用 |
| **Windows 10/11** | ① Shell + QQ 客户端（Win10 专用 `launcher-win10.bat`）② "一键版"（内置 QQ、免安装，**仅 AMD64**）③ NapCatQQ-Desktop（GUI 管理） | ✅ 完整支持（接管环境） | Framework/LiteLoader 路线官方已不推荐；自启需服务/计划任务 |
| **macOS（Apple Silicon）** | ① 开发联调：Docker Desktop 跑 Linux 容器（arm64）② 社区维护的 Mac 安装器（实验） | ⚠️ 非生产；仅开发/联调 | 与 Linux 的 UID/GID、挂载语义不同；原生安装器不纳入验收 |
| 备选协议端 | LLOneBot / Lagrange.Core | 备选 | 平台矩阵需逐平台单独核查，同样不假设一致 |

**"禁止假设"清单（写入 `docs/platform-notes.md`）：**
1. 不假设脚本/安装包跨平台通用（Ubuntu 脚本 ≠ Windows 一键版 ≠ macOS 安装器）；
2. 不假设 Docker 行为一致（Windows 需 Docker Desktop + WSL2；镜像仅 Linux 容器；`UID/GID` 参数在 Windows 不适用；挂载属主、换行符、自启方式均有差异）；
3. 不假设 QQ 客户端依赖一致（Linux 无头；Windows 需安装或使用内置一键版；macOS 社区方案）；
4. 不假设自启机制一致（systemd / Windows 服务或计划任务 / 手动托管）；
5. 不假设路径、编码、权限行为一致（统一走业务层跨平台规范）。

## 3. 整体架构（含契约边界）

```
       业务侧（跨平台，三 OS 行为一致）               协议侧（平台相关，可替换）
┌─────────────────────────────────────┐   ┌────────────────────────────────────┐
│  ACT Bot（NoneBot2 / Python）        │   │  NapCat（QQ 接入）                   │
│  plugins ─ core ─ models             │   │  Ubuntu：官方脚本 / Docker           │
│  data/（SQLite + 附件 + 备份）         │   │  Windows：Shell+QQ / 一键版 / GUI    │
│  scripts/（全部 Python）              │   │  macOS：社区安装器（实验）             │
└───────────────┬─────────────────────┘   └──────────────┬─────────────────────┘
                │        OneBot v11 契约（反向 WebSocket + token）               │
                └──────────────────────────────────────────────────────────────┘
```

部署拓扑（任一平台）：

```
QQ 群成员 → 腾讯 QQ 服务 → [协议端 NapCat] ←OneBot WS→ [ACT Bot + data/] → 备份/交接
                                （平台相关）      （跨平台）
```

## 4. 项目目录结构

```
act-bot/
├─ README.md                     # 支持矩阵（业务层/协议端分开标注）+ 快速开始
├─ pyproject.toml
├─ .gitattributes                # 行尾策略（代码 LF / .bat CRLF）
├─ .env.example                  # 部署配置模板（入库；真实 .env 不入库）
├─ .gitignore
├─ src/
│  ├─ bot.py                     # 启动入口（跨平台）
│  ├─ core/                      # config / db / permissions / scheduler / backup / paths
│  ├─ models/
│  └─ plugins/                   # 每功能一个目录
│     ├─ help/ about/ departments/ welcome/ events/
│     ├─ signups/ broadcast/ archive/ group_admin/
├─ config/                       # config.example.toml + README
├─ data/                         # ★ 运行数据（.gitignore；可经 DATA_DIR 外置）
│  ├─ act.db  ├─ uploads/  └─ backups/
├─ scripts/                      # 全部 Python（跨平台）
│  ├─ backup.py  restore.py  export_handover.py  import_handover.py
│  ├─ bootstrap_admin.py  manage.py  doctor.py  smoke_protocol.py
├─ deploy/                       # 按平台拆分
│  ├─ docker/    ├─ linux/    ├─ windows/    └─ macos/
├─ docs/
│  ├─ design.md                  # 本方案
│  ├─ onebot-contract.md         # ★ 接口契约（业务层只依赖它）
│  ├─ deploy.md                  # 部署总览
│  ├─ deploy-ubuntu.md           # Ubuntu（含协议端部署）
│  ├─ deploy-windows.md          # Windows（含协议端部署）
│  ├─ deploy-macos-dev.md        # macOS 开发
│  ├─ platform-notes.md          # ★ 协议端平台差异 + 禁止假设清单
│  ├─ acceptance.md              # 三平台验收清单
│  ├─ handover.md  ops.md  faq.md  generations.md
└─ tests/
```

## 5. 数据库设计（SQLite）

单文件、零运维、拷贝即备份；三平台行为一致；社团量级绰绰有余。

| 表 | 用途 | 关键字段 |
| --- | --- | --- |
| `meta` | 元信息 | schema_version、initialized_at |
| `admins` | 管理员（权限唯一来源） | qq、role(owner/admin)、note、created_by |
| `groups` | 接入的群与开关 | group_id、name、features、welcome_on、active |
| `departments` | 部门 | name、description、contact、sort_order |
| `events` | 社活 | title、desc、location、start/end、报名开关、deadline、status |
| `event_signups` | 报名 | event_id、qq、note、status（唯一键 event+qq） |
| `announcements` | 通知/广播 | title、content、target_groups、status、sent_at |
| `archive_items` | 历届作品/资料 | title、category、year、authors、file_path/url、tags |
| `settings` | 运行时可改配置 | key、value(JSON)、updated_by |
| `audit_log` | 审计 | qq、action、detail、created_at |

注意：WAL 模式；DB 不放网络盘/同步盘；备份用 `.backup` API。

## 6. 配置方案（三层分离）

| 层 | 位置 | 内容 | 入库? |
| --- | --- | --- | --- |
| 部署层 | `.env` | NapCat 连接地址/token、`DATA_DIR`、时区、初始管理员（仅首次） | ✗（.example 入库） |
| 业务层 | `config/config.toml` | 功能开关、命令前缀、欢迎语默认值、广播限速 | ✗（.example 入库） |
| 运行层 | 数据库 | 管理员、群开关、部门、活动、资料 | 随 data/ 迁移 |

**管理员权限（不写死 QQ）**：owner/admin 两级存 `admins` 表；命令管理（`/权限 添加|移除|转让`）；冷启动 `bootstrap_admin.py`；离线兜底 `manage.py`。

## 7. 部署方案总览

| 平台 | 业务层 | 协议端 | 文档 |
| --- | --- | --- | --- |
| Ubuntu 22.04/24.04（生产） | Docker Compose 或原生（venv + systemd） | 官方一键脚本 或 Docker | `deploy-ubuntu.md` |
| Windows 10/11（接管） | 原生（venv + 服务/计划任务）或 Docker Desktop | Shell+QQ / 一键版 / Desktop | `deploy-windows.md` |
| macOS（主开发） | 本地直接运行 | Fake / 本地 Docker 容器（联调）/ 远程端点（可选） | `deploy-macos-dev.md` |

- Docker Compose 是推荐方式但**非硬依赖**；原生方案同等文档化。
- 平台差异只进"协议端部署"章节与 `platform-notes.md`，业务层文档不含平台分支。

## 8. 迁移与交接方案

- **日常备份（跨平台）**：每日 03:00 由 bot 内置调度器（APScheduler）执行：`.backup` → `data/backups/`（滚动 30 天 + 每月留存）；每周打包 uploads；`integrity_check` 自检；可选叠加系统级定时器（systemd timer / Windows 计划任务）。
- **换届流程**（`docs/handover.md`）：交接包（`export_handover.py`）→ 新号部署（任选平台）→ `import_handover.py` → 管理员 → 验收清单 → 上线；换届前"陌生机器全流程演练"。
- **资产归属**：仓库、服务器放社团组织账号。

## 9. 故障预案

| 场景 | 处理 |
| --- | --- |
| 机器人离线 | NapCat 进程 → 登录态 → WS → bot 进程 → 网络；按平台的自启机制自动重启（见各自 deploy 文档） |
| 小号风控/封禁 | 换号：停 bot → 登出 → 新号扫码 → 重新拉群 → 改管理员 → 公告；代码与数据零改动 |
| 数据库损坏 | 停服 → `restore.py` → 校验 → 启动；≤24h 窗口；月度异地副本 |
| 服务器丢失/换平台 | 新机器从零部署（任意平台）+ 导入备份 |
| 协议端失效 | 切 LLOneBot/Lagrange（OneBot 同层替换）；平台差异按 platform-notes 逐项核查 |

## 10. macOS（Apple Silicon）开发工作流（★ 正式开发环境）

> 决策（r2 · 2026-09-24）：**开发环境 = macOS（Apple Silicon，本机直接开发）**；全套工具链原生运行在 Mac 上，不依赖虚拟机/远程 SSH。

- **业务层本地全支持**：`uv sync → python scripts/doctor.py → pytest → 运行`（Python、SQLite、NoneBot2 在 macOS arm64 原生运行）。
- **协议端（联调用）三种接法：**
  1. **Fake OneBot（默认）**：本地模拟器，离线开发全部功能——契约测试的主战场。
  2. **本地真实联调（推荐）：Docker Desktop 跑 Linux 版 NapCat 容器**——把"官方支持的 Linux 部署"放进 Mac 的 Docker（arm64 原生镜像）；配测试小号 + 测试群，需要真机联调时启动；注意 macOS 下 UID/GID、挂载语义与 Linux 主机不同（以官方文档为准）。
  3. **远程联调（可选）**：后续有 Ubuntu 测试机后，连它的测试实例（内网/SSH 隧道）。
- **实验项（可选、不承诺）**：本机跑社区 Mac 安装器——标注"实验"，不纳入验收。
- **macOS 验收 = 业务层测试全绿 + 用 Fake 或本地容器完成一轮端到端联调。**

## 11. 平台相关依赖清单（两张表）

**表 A：业务层依赖（要求三平台完全一致，CI 验证）**

| 类别 | 依赖 | 注意 |
| --- | --- | --- |
| 运行时 | Python 3.10+（建议 3.11/3.12） | macOS 用 uv/brew；Windows python.org/winget |
| 框架 | nonebot2 + nonebot-adapter-onebot | — |
| 数据 | SQLAlchemy 2.x + aiosqlite | 不基于网络盘 |
| 调度 | APScheduler | 备份不依赖系统 cron |
| 时区 | tzdata | Windows 必装 |
| 事件循环 | asyncio 默认 | 明确不启用 uvloop |
| 测试 | pytest + pytest-asyncio | CI 三平台矩阵 |

**表 B：协议端依赖（平台相关，按平台建档）**

| 平台 | 协议端获取方式 | 自启方式 |
| --- | --- | --- |
| Ubuntu | 官方脚本 / Docker 镜像 | systemd / Docker restart 策略 |
| Windows | Shell+QQ / 一键版 / Desktop | Windows 服务（NSSM/WinSW）或计划任务 |
| macOS | Docker Desktop（Linux 容器，联调用）或社区安装器（实验） | 手动（仅开发） |

## 12. 跨平台测试策略

1. **CI 三平台矩阵**：ubuntu / windows / macos 全量跑 pytest；
2. **契约测试（核心）**：Fake OneBot 实现 OneBot 子集，全部集成测试离线运行，不依赖真实 QQ 与 NapCat；
3. **规则守护测试**：扫描禁模式（`/home/`、`C:\`、`uvloop`、`shell=True`、`chmod`、`fork`、`sys.platform`），违规即 CI 失败；
4. **doctor.py**：环境自检（Python/依赖/data 可写/时区/DB 完整性），三平台通用；
5. **smoke_protocol.py**：连上真实协议端后验证契约子集能力（部署验收用）；
6. **备份/恢复往返测试**（三平台 CI）；
7. **三平台验收清单**（`acceptance.md`，纳入交接流程）。

## 13. README 支持平台说明（草案，按"两层"分列）

| 维度 | macOS (Apple Silicon) | Ubuntu 22.04/24.04 | Windows 10/11 |
| --- | --- | --- | --- |
| 业务层 | ✅ 开发 / 运行 | ✅ 生产（推荐） | ✅ 支持 |
| 协议端 | ⚠️ 开发联调：Fake / 本地 Docker 容器（远程可选） | ✅ 官方脚本 / Docker | ✅ Shell / 一键版 / Desktop |
| 定位 | 开发环境（正式） | 生产环境 | 接管环境 |

> 一句话：**业务代码不绑定操作系统；协议端按平台单独部署，互不假设。**

## 14. MVP 功能边界（不变）

包含（9 项）：入群欢迎 / 社团简介 / 部门查询 / 社活通知 / 活动报名 / 管理员广播 / 历届作品资料查询 / 基础群管理 / 帮助菜单。
明确不做（本期）：AI 对话、微信端、Web 管理台、积分等级、自动入群审核。

## 15. 开发顺序（更新）

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| P0 地基 | 骨架 + **契约固化（onebot-contract.md）+ Fake OneBot + 三平台 CI** + 配置 + 数据库 + 权限 + 跨平台脚本 + doctor | 收发消息（Fake 端到端；条件允许时真实端点联调）；CI 三平台全绿 |
| P1 内容 | 帮助 / 简介 / 部门查询 | 新人可自助查询 |
| P2 管理 | 广播 + 群管理 + 审计 | 管理员全流程可用 |
| P3 活动 | 社活通知 + 活动报名（含名单导出） | 建→报→导出闭环 |
| P4 档案 | 入群欢迎 + 资料查询 + 导入工具 | 资料可检索 |
| P5 交接 | 三平台验收清单 + 陌生机器演练 + 交接包测试 | 新负责人独立完成 |

## 16. 决策状态

**已定（2026-09-24）：**
- 开发环境 = **macOS（Apple Silicon，本机直接开发）**；
- 部署目标 = Ubuntu（生产）；Windows 必须支持（接管环境）；
- 技术栈 = NapCat + OneBot v11 + NoneBot2 + SQLite（双契约分离设计）。

**待定（拍板项）：**

1. 生产机来源：Ubuntu 服务器（推荐）/ 家里旧电脑 / 学校资源；
2. 社团组织账号：建议社团专属 GitHub Org；
3. 小号：建议 1 主 + 1 备；
4. 多群范围：主群 + 部门群结构；
5. 资料库：首批内容、录入负责人与量级；
6. 补充项：Windows 接管环境倾向"原生"还是"Docker Desktop"？（P5 前定即可）
