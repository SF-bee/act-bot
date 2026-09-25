# ACT Bot

> ACT 动漫社 QQ 群机器人 —— 可跨届传承的社团线上基础设施。
>
> **原则：账号是可替换的，项目和数据才是 ACT 的资产。**
>
> **人设**：项目技术名是 `act-bot`（仓库 / 服务 / 日志），群里的对外身份是 **Yulia｜ACT 动漫社助理**。
> 名字、身份、别名都在 `config/config.toml` 的 `[persona]` 配置；`/help`、`/version`、入群欢迎语都自动使用它。

## 支持平台（业务层 / 协议端分开）

| 维度 | macOS (Apple Silicon) | Ubuntu 22.04 / 24.04 | Windows 10 / 11 |
| --- | --- | --- | --- |
| 业务层（本仓库） | ✅ 开发 / 运行 | ✅ 生产（推荐） | ✅ 支持 |
| 协议端（NapCat 等） | ⚠️ 开发联调（Fake / 本地 Docker 容器） | ✅ 官方脚本 / Docker | ✅ Shell / 一键版 / Desktop |
| 定位 | **开发环境** | **生产环境** | **接管环境** |

> 业务代码不绑定操作系统；协议端按平台单独部署，详见 `docs/platform-notes.md`。

## 快速开始（开发机 = macOS）

```bash
uv sync                          # 安装依赖（在 .venv 内）
cp .env.example .env             # 填写配置（至少设置管理员 QQ）
uv run python scripts/doctor.py  # 环境自检
uv run python bot.py             # 启动机器人（默认监听 127.0.0.1:8080）
```

端到端冒烟测试（**不需要真实 QQ**）：

```bash
uv run python scripts/smoke_fake.py
```

## 已实现功能

| 功能 | 触发 | 说明 |
| --- | --- | --- |
| 帮助菜单 | `/help` | 命令清单由各插件的 `PluginMetadata` 自动汇总；**普通成员与管理员看到的内容不同**（管理员多一段「管理员命令」） |
| 入群欢迎 | 有人入群（`notice.group_increase`） | 自动 @ 新人 + 欢迎语；两级开关：全局 `[features].welcome`（config.toml）、群级「群内 `/config welcome on|off`」（`/welcome` 只读，看状态与预览）；文案在 `[welcome].text`，支持占位符 `{nickname}` / `{group_name}` / `{user_id}`；同一人 60 秒内重复事件只欢迎一次 |
| 群功能开关 | `/config`、`/config <功能> on|off` | 管理员可按群开关功能（写 `groups.features`）；功能名册见 `src/core/features.py`，新增功能不用改命令 |
| 管理操作审计 | `/audit [n]` | 谁在哪个群做了什么（改配置等），管理员可查；写入见 `src/core/audit.py` |
| 事件中枢 | —（无命令） | 事件先经 `src/core/events.py` 规范化，再按群级功能开关分发；新功能用 `subscribe(...)` 注册，**不要**直接挂 OneBot 事件 |
| 连通性检查 | `/ping` | 回复 `pong` |
| 版本信息 | `/version` | 版本号 + 已开启的功能开关数 |

命令一律用英文（方便手机输入）；管理类命令仅管理员可用，非管理员静默。

**新增插件时的约定**：在 `PluginMetadata` 里填好 `usage`（一行一个命令，形如 `/cmd — 说明`）与 `extra`（`role`: `member`/`admin`、`order`: 排序权重），`/help` 会自动收录，不需要改帮助插件。

**命令分层约定**（避免两个入口改同一份状态）：**开关类操作一律走 `/config <功能> on|off`**；业务命令只负责该功能专有的展示与内容（例如 `/welcome` 只读状态与预览）。新增功能请照此分层，审计动作名统一为 `config.set`。

## 运行逻辑（改代码前先看这一节）

```
QQ 群 / 好友
   ↕  （腾讯协议，由协议端负责）
[协议端 NapCat]        独立进程或容器，持有 QQ 登录态
   ↓  反向 WebSocket（协议端作为客户端主动连过来）
[业务层 本仓库]        NoneBot2 + OneBot v11 适配器，监听 8080
   ↓  SQLite（data/act.db，版本化迁移）
```

1. **协议端**负责与腾讯通信、持有登录态；它主动连业务层 `ws://<机器人主机>:8080/onebot/v11/ws`，握手头带 `X-Self-ID`，可选 token（两边必须一致）。
2. **业务层**（本仓库，单进程）启动顺序：读 `.env` → `nonebot.init()` → 注册 OneBot v11 适配器 → 建库并跑迁移 → 启动 APScheduler → 监听 8080。
3. 群里有人发消息 → 协议端推 `message.group` 事件 → 插件的 matcher 按命令前缀（默认 `/`）匹配 → 插件执行（可读写 SQLite）→ 回复经 `send_msg` 交回协议端 → 协议端发出去。
4. 业务层**不持有** QQ 登录态、也**不主动**连协议端；所以它可以随时重启，协议端会自动重连（断几秒）。接口约定见 `docs/onebot-contract.md`。
5. 全部状态只有两处：SQLite（`data/`，路径来自 `ACTBOT_DATA_DIR`）与配置文件。业务层进程本身无状态。

## 改了东西怎么生效

| 你改了什么 | 怎么生效 |
| --- | --- |
| 业务代码（`src/`、`bot.py`） | **重启业务层**（见下表） |
| 配置（`.env`、`config/config.toml`） | 同样**重启**——设置是进程级缓存，不会热读 |
| 依赖（`pyproject.toml`） | 先 `uv sync` 再重启 |
| 数据库结构 | 在 `src/core/migrations/` 新增 `00X_描述.sql`（文件名数字即版本号），**重启时自动按序应用**，幂等可重复跑 |
| 加一个新命令 | 新建/修改 `src/plugins/<名字>/__init__.py` 里的 matcher，然后重启 |
| 协议端配置（网络、token） | 改 NapCat 侧配置后 `docker compose -f deploy/docker/docker-compose.yml restart napcat` |

重启与看日志，按部署方式：

| 部署方式 | 重启 | 看日志 |
| --- | --- | --- |
| macOS 开发机（launchd，见 `deploy/macos/`） | `launchctl kickstart -k gui/$(id -u)/com.actbot.dev` | `tail -f ~/Library/Logs/actbot-dev.log` |
| 前台调试 | Ctrl+C 后 `HOST=0.0.0.0 uv run python bot.py` | 终端 |
| Ubuntu 生产（systemd，见 `deploy/linux/`） | `sudo systemctl restart act-bot` | `journalctl -u act-bot -f` |
| Docker（业务层也在容器里，见 `deploy/docker/`） | `docker compose -f deploy/docker/docker-compose.yml up -d --build act-bot` | `docker compose -f deploy/docker/docker-compose.yml logs -f act-bot` |
| Windows（NSSM，见 `deploy/windows/`） | `Restart-Service act-bot` | `<仓库>\logs\act-bot.out.log` |

改完先自测（都不需要真实 QQ）：

```bash
uv run pytest -q                     # 单元测试
uv run python scripts/doctor.py      # 环境自检
uv run python scripts/smoke_fake.py  # Fake 协议端端到端
```

> 两个常见坑：**①** Docker 路线下业务代码在镜像里，改完必须带 `--build` 重建才生效；
> **②** 协议端跑在 Docker Desktop、业务层跑在宿主机时，业务层要 `HOST=0.0.0.0`（否则容器连不进来，日志会刷 ECONNREFUSED），详见 `docs/deploy-macos-dev.md`。

## 运行测试

```bash
uv run pytest -q
```

## 常用脚本

| 脚本 | 作用 |
| --- | --- |
| `scripts/doctor.py` | 环境自检（Python / 依赖 / 数据目录 / 时区 / 数据库） |
| `scripts/backup.py` | 手动执行一次数据库备份 |
| `scripts/restore.py <备份文件>` | 从备份恢复数据库（恢复前请先停 bot） |
| `scripts/bootstrap_admin.py` | 首次部署：写入 owner 管理员 |
| `scripts/manage.py` | 离线管理：管理员增删 / 转让（bot 不启动也能用） |
| `scripts/export_handover.py` | 导出换届交接包（数据 + 文档，不含凭据） |
| `scripts/import_handover.py <交接包>` | 导入交接包 |
| `scripts/smoke_protocol.py` | 连接真实协议端做契约冒烟（部署验收用） |
| `scripts/smoke_fake.py` | Fake OneBot 端到端自测（无需真实 QQ） |
| `scripts/smoke_events.py` | 事件中枢端到端冒烟：入群欢迎 / cooldown / 群级开关 / 审计（无需真实 QQ） |

## 目录结构

```
act-bot/
├─ bot.py            # 启动入口
├─ src/              # 业务代码（跨平台）
│  ├─ bot.py         # 启动逻辑
│  ├─ core/          # config / db / permissions / backup / scheduler
│  ├─ models/        # 数据模型
│  └─ plugins/       # 功能插件
├─ scripts/          # 运维脚本（全部 Python，跨平台）
├─ config/           # 业务配置（示例入库，真实配置不入库）
├─ data/             # 运行数据（不入库；备份 / 迁移针对的就是这里）
├─ docs/             # 文档（设计 / 契约 / 部署 / 交接 / 运维）
└─ tests/            # 测试（含 Fake OneBot）
```

## 文档

- 设计基线：`docs/design.md`
- OneBot 接口契约：`docs/onebot-contract.md`
- 平台差异备忘（必读）：`docs/platform-notes.md`
- 部署：`docs/deploy.md`（总览）｜ `docs/deploy-ubuntu.md` ｜ `docs/deploy-windows.md` ｜ `docs/deploy-macos-dev.md`
- 交接：`docs/handover.md` ｜ 运维：`docs/ops.md`

## 交接与传承

本项目设计为**可交接**：换届时导出「交接包」（数据 + 文档，**不含任何凭据**），新负责人按 `docs/handover.md` 清单完成部署与接替。动生产环境之前请先阅读。

---

_维护约定：任何 QQ 号、凭据、绝对路径都不得写入代码；社团数据都在 `data/`。_
