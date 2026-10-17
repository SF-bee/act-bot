# ACT Bot

> ACT 动漫社 QQ 群机器人。
> 面向社团长期运营的跨平台业务层：功能、权限、统计、风控、定时任务和数据都由本项目管理；QQ 登录和消息收发交给独立的 OneBot 协议端。

项目的核心原则是：**账号、协议端和操作系统都可以更换，代码与数据可以继续交接。**

## 这是什么

ACT Bot 由两部分组成：

```text
QQ 群成员
    │
    ▼
协议端（NapCat 等，负责 QQ 登录和收发消息）
    │  OneBot v11 反向 WebSocket
    ▼
业务层（本仓库：NoneBot2 + SQLite）
    ├─ 插件：欢迎、聊天、统计、风控、推送、管理
    ├─ 数据：data/act.db
    └─ 运维：备份、恢复、交接、自检
```

业务层不保存 QQ 登录态，也不依赖某个特定协议端。协议端主动连接业务层：
`ws://<业务层地址>:<端口>/onebot/v11/ws`。

> **聊天互动不是 LLM。** 当前实现是基于关键词、概率、冷却和连续 @ 状态的确定性规则，不会调用外部 AI 服务。

## 能力概览

| 能力 | 用法/触发方式 | 说明 |
| --- | --- | --- |
| 帮助与系统 | `/帮助`、`/ping`、`/版本` | 自动汇总插件命令；管理员看到额外的管理命令 |
| 入群欢迎 | 群成员加入 | 自动 @ 新人并发送可配置欢迎语，支持全局和群级开关 |
| 聊天互动 | @ 机器人或命中关键词 | 支持概率回复、冷却、连续 @ 分档和群级规则；默认关闭 |
| 活跃统计 | `/统计` | 支持今天、昨天、本周、上周、本月、近 N 天和趋势；管理员可看额外指标 |
| 群互动 · 签到 | `/签到`、`/签到榜` | 成员每日打卡，记录连续天数与累计次数；支持本月/累计排行榜；默认关闭 |
| 群管理与风控 | 自动规则、`/mod`、`/warn`、`/mute` 等 | 敏感词、URL/号码模式、刷屏、复读、@全体；支持撤回、警告、禁言、踢出和灰度模式 |
| 定时推送 | `config/config.toml` 的 `[[push]]` | 按天/周推送到群或管理员，可试发 |
| 掉线提醒 | 协议端重新上线 | 汇总掉线时刻、在线时长和离线时长后私聊管理员 |
| 权限与审计 | `/权限`、`/audit` | 管理员、群级功能开关和管理操作均有记录 |
| 数据保护 | 自动/手动备份 | SQLite 数据库每日备份，支持恢复和换届交接 |

完整命令清单见 [`docs/commands.md`](docs/commands.md)，风控细节见 [`docs/moderation.md`](docs/moderation.md)。

## 平台支持

这里的“支持”分为业务层和协议端，不要混为一谈：

| 平台 | 业务层 | 协议端 | 推荐用途 |
| --- | --- | --- | --- |
| macOS Apple Silicon | ✅ | ⚠️ 通过 Docker/本地方案联调 | 开发 |
| Ubuntu 22.04 / 24.04 | ✅ | ✅ | 生产（推荐） |
| Windows 10 / 11 | ✅ | ✅ | 接管、备用部署 |

协议端在不同平台的安装、自启和挂载方式并不相同。请先阅读
[`docs/platform-notes.md`](docs/platform-notes.md)，再选择对应部署文档：

- [`docs/deploy-macos-dev.md`](docs/deploy-macos-dev.md)：macOS 开发与联调
- [`docs/deploy-ubuntu.md`](docs/deploy-ubuntu.md)：Ubuntu 生产
- [`docs/deploy-windows.md`](docs/deploy-windows.md)：Windows 部署
- [`deploy/docker/`](deploy/docker/)：Docker Compose 模板

## 快速开始

### 1. 准备环境

需要：

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- 一个兼容 OneBot v11 的协议端（真实 QQ 联调时）

### 2. 安装业务层

```bash
git clone <repository-url>
cd act-bot
uv sync
```

复制配置模板：

```bash
cp .env.example .env
cp config/config.example.toml config/config.toml
```

至少在 `.env` 中设置：

```dotenv
ACTBOT_BOOTSTRAP_ADMIN_QQ=你的管理员QQ
ONEBOT_ACCESS_TOKEN=请设置一个随机token
```

配置原则：

| 配置 | 文件 | 内容 |
| --- | --- | --- |
| 部署配置 | `.env` | 地址、端口、token、数据目录、时区 |
| 业务配置 | `config/config.toml` | 功能开关、欢迎语、限速、备份、推送、风控 |
| 运行时数据 | `data/` | 管理员、群设置、规则、统计和备份 |

不要把真实 `.env`、`config/config.toml`、QQ 号或 token 提交到仓库。

### 3. 自检并初始化管理员

```bash
uv run python scripts/doctor.py
uv run python scripts/bootstrap_admin.py
```

`bootstrap_admin.py` 使用 `.env` 中的 `ACTBOT_BOOTSTRAP_ADMIN_QQ` 写入首个
owner。已有 owner 时不要重复执行；换届请使用：

```bash
uv run python scripts/manage.py admins transfer <新管理员QQ>
```

### 4. 启动

```bash
uv run python bot.py
```

默认监听 `127.0.0.1:8080`。协议端需要连接：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

如果协议端位于另一台机器或 Docker 容器，调整 `.env` 中的 `HOST`、端口映射、
WebSocket 地址和 `ONEBOT_ACCESS_TOKEN`，两端 token 必须一致。

### 5. 不接真实 QQ 的验证

```bash
uv run python scripts/smoke_fake.py
uv run pytest -q
```

接入真实协议端后，可运行：

```bash
uv run python scripts/smoke_protocol.py --url ws://... --token ...
```

部署完成后按 [`docs/acceptance.md`](docs/acceptance.md) 验收。

## 常用命令

### 普通成员

| 命令 | 作用 |
| --- | --- |
| `/帮助` / `/help` | 查看可用命令 |
| `/统计` / `/stats` | 查看本群活跃统计 |
| `/签到` / `/checkin` | 群内打卡，查看连续天数与累计次数 |
| `/签到榜` / `/checkin_rank` | 查看本群签到排行（本月/累计） |
| `/版本` / `/version` | 查看版本和功能状态 |
| `/权限` / `/op` | 查看自己的角色和管理员名单 |
| `/ping` | 检查连通性 |

### 管理员

| 命令 | 作用 |
| --- | --- |
| `/config [-g 群号]` | 查看或修改群级功能开关 |
| `/audit [n]` | 查看管理操作审计 |
| `/use <群号>` | 私聊管理时绑定默认群 |
| `/welcome` | 查看欢迎状态和预览 |
| `/chat ...` | 管理聊天规则 |
| `/mod ...` | 管理风控规则和状态 |
| `/push` / `/push test <名称>` | 查看或试发定时推送 |
| `/warn` `/mute` `/unmute` `/kick` `/recall` | 手动处置群成员或消息 |

管理员命令对普通成员静默拒绝；私聊管理群时使用 `/use <群号>` 或命令参数
`-g <群号>`。`-s` 可让处置静默执行但仍写入审计。完整规则见
[`docs/commands.md`](docs/commands.md)。

## 配置功能

常用业务配置位于 [`config/config.example.toml`](config/config.example.toml)：

- `[features]`：全局功能开关（`welcome`、`chat`、`stats`、`moderation`、`checkin`）
- `[persona]`：机器人名称、身份和称呼
- `[welcome]`：欢迎语与是否 @ 新人
- `[chat]`：回复概率、冷却和连续 @ 行为
- `[stats]`：落库间隔、趋势天数、管理员日报
- `[checkin]`：签到文案模板、榜单人数与缺省范围
- `[backup]`：每日备份时间和保留周期
- `[alert]`：协议端掉线提醒
- `[moderation]`：敏感词、刷屏、复读、处置方式和灰度模式
- `[[push]]`：定时推送任务，可配置多个

修改 `.env` 或 `config/config.toml` 后需要重启业务层；配置不会热加载。
功能还可能被管理员通过 `/config <功能> on|off` 在单个群内关闭。

## 运维

### 常用脚本

| 脚本 | 用途 |
| --- | --- |
| `scripts/doctor.py` | 检查 Python、依赖、路径、时区和数据库 |
| `scripts/backup.py` | 手动备份数据库 |
| `scripts/restore.py <备份文件> [--yes] [--force]` | 停止 bot 后恢复数据库（会先校验备份与占用） |
| `scripts/manage.py` | 离线管理管理员 |
| `scripts/export_handover.py` | 导出换届交接包（不含凭据） |
| `scripts/import_handover.py <交接包>` | 导入交接包 |
| `scripts/smoke_fake.py` | Fake OneBot 端到端测试 |
| `scripts/smoke_events.py` | 事件中枢冒烟测试 |

### 默认备份策略

业务层默认每天 `03:00` 备份，按自然日保留最近 30 天每日副本（同一天多份只留最新）
和 6 个月月度副本。
生产环境仍建议把备份复制到异地存储。数据库损坏或迁移前，先停止 bot，再执行恢复。
更多故障处理见 [`docs/ops.md`](docs/ops.md)。

### 服务化部署

仓库提供以下模板：

- Ubuntu：[`deploy/linux/`](deploy/linux/)
- Windows：[`deploy/windows/`](deploy/windows/)
- macOS：[`deploy/macos/`](deploy/macos/)
- Docker：[`deploy/docker/`](deploy/docker/)

部署总览见 [`docs/deploy.md`](docs/deploy.md)。

## 开发

代码和测试均使用 Python：

```bash
uv sync
uv run pytest -q
uv run python scripts/doctor.py
uv run python scripts/smoke_fake.py
```

目录结构：

```text
act-bot/
├── bot.py                 # 根启动入口
├── src/
│   ├── core/              # 配置、数据库、权限、调度、备份、OneBot 等
│   ├── models/            # 数据模型
│   └── plugins/           # 各业务插件
├── scripts/               # 运维和冒烟脚本
├── config/                # 业务配置模板
├── data/                  # SQLite、附件和备份（运行时目录）
├── deploy/                # 各平台服务与容器模板
├── docs/                  # 设计、部署、契约、运维和交接文档
└── tests/                 # 单元测试与 Fake OneBot 测试
```

新增命令或插件前请阅读 [`docs/commands.md`](docs/commands.md)：
命令前缀必须非空；普通成员命令使用中文并可提供英文别名；管理命令必须显式做
管理员校验；功能开关统一通过 `/config` 管理。

## 文档索引

- [部署总览](docs/deploy.md)
- [平台差异与限制](docs/platform-notes.md)
- [命令约定与完整清单](docs/commands.md)
- [群管理与风控](docs/moderation.md)
- [定时任务与推送](docs/scheduler.md)
- [OneBot v11 接口契约](docs/onebot-contract.md)
- [运维手册](docs/ops.md)
- [换届交接](docs/handover.md)
- [常见问题](docs/faq.md)
- [设计基线](docs/design.md)

## 安全与隐私

- 公网或跨主机部署时务必设置 `ONEBOT_ACCESS_TOKEN`，并限制协议端 WebUI 暴露范围。
- 凭据只放 `.env`；运行数据、管理员名单和 QQ 号只放数据库或本地配置。
- 统计只保存聚合结果，不保存每条消息正文，也不落库每个人的发言明细。
- 风控功能需要协议端账号拥有相应群管理权限；启用前先用 `dry_run = true` 验证规则。
- 更换 QQ 账号不需要修改代码；停 bot、切换协议端登录态，再按运维文档更新管理员即可。

---

维护者与接班人请把“代码、数据、凭据、协议端”分开管理。换届时优先阅读
[`docs/handover.md`](docs/handover.md)，并定期进行一次完整的导出、恢复和验收演练。
