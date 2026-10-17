# 运维手册

## 1. 机器人离线

自查顺序：**NapCat 进程 → QQ 登录态 → WS 连接 → bot 进程 → 网络**。

- 各平台自启：systemd（Ubuntu）/ Windows 服务或计划任务（Windows）/ 手动（macOS 开发机）；
- 日志：前台日志或平台服务日志；
- NapCat 掉线时优先检查其 WebUI（默认 6099）。
- 日志里 `notice.bot_offline`（“你的账号当前登录已失效”）= **腾讯回收了第三方登录态**，与业务层无关；配了 `NAPCAT_QUICK_PASSWORD` 时 NapCat 会自动密码重登，否则要扫码（`bash deploy/docker/fetch-qr.sh`）。
- 日志里业务进程 `Shutting down` → 5 秒后重连，属于**业务层重启**（launchd/systemd KeepAlive 自愈），不是掉 QQ。
- 不想盯日志：`[alert].uplink = true`（默认）时，被踢下线会被记下来，协议端重新连上后私聊管理员一条汇总（掉线时刻 / 掉线前在线多久 / 离线多久）；实现见 `src/core/uplink.py`。
## 2. 小号被风控 / 封禁（换号流程）

1. 停 bot；
2. NapCat 登出旧号 → 扫码登录新号；
3. 把新号邀请进群；
4. 转让 / 更新管理员：`uv run python scripts/manage.py admins transfer <新号>`（或群内命令）；
5. 上线公告。**代码与数据零改动。**

## 3. 数据库损坏

1. 停 bot（**必须**：restore 会检测 `-wal`/`-shm` 残留与写锁，bot 在跑时会拒绝）；
2. `uv run python scripts/restore.py <最近备份>`，按提示输入 `yes` 确认（脚本会先做完整性校验，
   并在覆盖前把当前库另存为 `act.db.pre-restore-*.bak`）；
3. `uv run python scripts/doctor.py` 验证；
4. 启动 bot。损失窗口 ≤ 每日备份间隔（默认 24h）。

自动化/脚本里调用：加 `--yes` 跳过交互确认；确实要在 bot 运行时强恢复（不推荐）加 `--force`。
误报 `数据库疑似正在被使用` 时，先确认没有别的 python 进程连着 `data/act.db` 再重试。

## 4. 服务器迁移 / 丢失

新机器按 `docs/deploy-*.md` 部署 + `import_handover.py` 导入最近备份 / 交接包。

## 5. 备份策略（默认）

- 每日 03:00 自动备份（bot 内置调度），按**自然日**滚动保留最近 30 天（每天最多一份，
  同一天多次备份只留最新）+ 最近 6 个月各一份；
- 手工多备份几次不会挤掉其它日期：轮转按文件名里的日期分组，不按文件个数；
- 建议每月手动同步一份备份到社团网盘（异地副本）。

## 6. 统计落库与退出

- 统计平时在内存里累加，每 `[stats].flush_seconds`（默认 60s）落库一次；
- 正常退出（SIGTERM / systemd stop / Ctrl+C）会再落库一次，最多等
  `[stats].flush_timeout_seconds`（默认 10s）；超时或失败会打一条
  `退出时统计未落库：pending=… errors=… groups=…` 的日志；
- **SIGKILL / 断电 / 容器被 kill -9** 没有退出钩子：最多丢最近一个落库间隔的内存增量（通常 1 分钟内），
  `checkins` / `admins` 等即时写库的数据不受影响；
- 迁移/初始化有跨进程锁文件（`data/act.db.migrate.lock`）：若进程异常退出留下锁，
  `doctor.py` 会提示；确认没有进程在初始化后删掉该文件即可。

## 7. 协议端失效

切换备选协议端（LLOneBot / Lagrange），仅需改连接方式；平台差异按 `docs/platform-notes.md` 逐项核查。
