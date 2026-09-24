# config/ 说明

本目录放**业务配置**（与代码分离、与凭据分离）。

- `config.example.toml` —— 模板（入库，供参考/复制）。
- `config.toml` —— 真实配置（复制模板后修改），**不入库**（见 `.gitignore`）。

三层配置原则（单一来源）：

| 层 | 位置 | 放什么 | 入库? |
| --- | --- | --- | --- |
| 部署层 | `.env`（仓库根） | 监听地址、token、数据目录、时区、初始管理员 | ✗（`.env.example` 入库） |
| 业务层 | `config/config.toml` | 功能开关、限速、备份策略 | ✗（`.example` 入库） |
| 运行层 | 数据库（`data/act.db`） | 管理员、群开关、部门、活动、资料 | 随备份 / 交接包迁移 |

注意：

- 命令前缀等 NoneBot 自身设置放在 `.env`（`COMMAND_START`），不要写进本文件；
- 不要把任何 QQ 号、密码、token 写进 `config.toml` —— 那是 `.env` 或数据库的事。
