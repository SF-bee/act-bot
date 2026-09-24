# 部署总览

> 三层：**业务层（跨平台）** 与 **协议端（平台相关）** 分开部署；先读 `docs/platform-notes.md`。

## 选择你的平台

| 场景 | 文档 |
| --- | --- |
| 开发（macOS Apple Silicon） | `deploy-macos-dev.md` |
| 生产（Ubuntu 22.04 / 24.04，推荐） | `deploy-ubuntu.md` |
| 接管（Windows 10 / 11） | `deploy-windows.md` |

## 部署 = 两件事

1. **协议端**：按平台各自的方式装 NapCat（三平台方式互不相同，见对应文档）；
2. **业务层**：本仓库 + `.env` + `data/`（三种平台步骤一致）：

```bash
uv sync                                            # 安装依赖
cp .env.example .env                               # 填配置（含 ONEBOT_ACCESS_TOKEN 等）
cp config/config.example.toml config/config.toml   # 按需修改业务配置
uv run python scripts/doctor.py                    # 环境自检
uv run python scripts/bootstrap_admin.py           # 首次部署：写 owner 管理员
uv run python bot.py                               # 启动（或按平台配置自启）
```

## 首次联调与验收

- `uv run python scripts/smoke_fake.py`（离线冒烟，任何平台）；
- 协议端接入后：`uv run python scripts/smoke_protocol.py --url ws://... --token ...`；
- 按 `docs/acceptance.md` 逐项打勾。

## 注意

- NapCat 在各平台的部署方式**互不相同**，不要照搬（见 `platform-notes.md` 的"禁止假设"清单）；
- 公网环境务必设置 `ONEBOT_ACCESS_TOKEN`，并保护协议端 WebUI 端口（如 6099）。
