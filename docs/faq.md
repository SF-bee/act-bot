# FAQ

- **Q：为什么不用官方 QQ 机器人开放平台？**
  A：功能受限（无法读全量群消息、主动消息受限、无群管理），不满足社团需求。详见 `docs/design.md`。
- **Q：机器人要一直开着电脑吗？**
  A：需要一台常开设备（服务器优先；也可以是旧电脑）。
- **Q：小号会不会被封？**
  A：有风控风险；缓解措施：专用小号、养号、控频、固定环境。换号流程见 `docs/ops.md`。
- **Q：数据在哪里？**
  A：全部在 `data/`（act.db + uploads + backups）；备份与交接都围绕它。
- **Q：能用 Windows / macOS 接手吗？**
  A：可以。Windows：`docs/deploy-windows.md`；macOS（开发）：`docs/deploy-macos-dev.md`。
- **Q：`manage.py admins add <QQ> --role owner` 被拒绝了？**
  A：owner 全库唯一，第二个 owner 会被拒绝。首次初始化用 `scripts/bootstrap_admin.py`，
  换届用 `scripts/manage.py admins transfer <新号>`（先把旧 owner 降级再提升）。
- **Q：`restore.py` 提示「数据库疑似正在被使用」？**
  A：说明还有进程连着 `data/act.db`（或崩溃留下了 `-wal`/`-shm`）。先停 bot、确认没有别的
  python 进程；确实要强恢复加 `--force`（不推荐）。非交互环境加 `--yes`。
- **Q：退出日志里出现「退出时统计未落库」？**
  A：退出钩子等统计落库超时（默认 `[stats].flush_timeout_seconds = 10`）或写库失败，
  最多丢最近一个落库间隔（默认 60s）的内存增量；可调大该值，或查磁盘/权限问题。