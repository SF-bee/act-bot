# ACT Bot

> ACT 动漫社 QQ 群机器人 —— 可跨届传承的社团线上基础设施。
>
> **原则：账号是可替换的，项目和数据才是 ACT 的资产。**

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
