# 运维手册

## 1. 机器人离线

自查顺序：**NapCat 进程 → QQ 登录态 → WS 连接 → bot 进程 → 网络**。

- 各平台自启：systemd（Ubuntu）/ Windows 服务或计划任务（Windows）/ 手动（macOS 开发机）；
- 日志：前台日志或平台服务日志；
- NapCat 掉线时优先检查其 WebUI（默认 6099）。

## 2. 小号被风控 / 封禁（换号流程）

1. 停 bot；
2. NapCat 登出旧号 → 扫码登录新号；
3. 把新号邀请进群；
4. 转让 / 更新管理员：`uv run python scripts/manage.py admins transfer <新号>`（或群内命令）；
5. 上线公告。**代码与数据零改动。**

## 3. 数据库损坏

1. 停 bot；
2. `uv run python scripts/restore.py <最近备份>`；
3. `uv run python scripts/doctor.py` 验证；
4. 启动 bot。损失窗口 ≤ 每日备份间隔（默认 24h）。

## 4. 服务器迁移 / 丢失

新机器按 `docs/deploy-*.md` 部署 + `import_handover.py` 导入最近备份 / 交接包。

## 5. 备份策略（默认）

- 每日 03:00 自动备份（bot 内置调度），滚动保留 30 天 + 每月 1 份；
- 建议每月手动同步一份备份到社团网盘（异地副本）。

## 6. 协议端失效

切换备选协议端（LLOneBot / Lagrange），仅需改连接方式；平台差异按 `docs/platform-notes.md` 逐项核查。
