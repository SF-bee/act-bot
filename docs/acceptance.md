# 验收清单（每平台部署后逐项打勾）

## 通用（业务层）

- [ ] `uv run pytest -q` 全绿
- [ ] （Docker 路线）`docker compose -f deploy/docker/docker-compose.yml config` 通过
- [ ] `uv run python scripts/doctor.py` 全绿（允许出现 ⚠️ 警告项，如库被占用时）
- [ ] `uv run python scripts/smoke_fake.py` 通过（Fake 端到端）
- [ ] `scripts/backup.py` 能生成备份；`scripts/restore.py` 能恢复（先停 bot；
  交互确认或加 `--yes`；bot 在跑时会拒绝）
- [ ] 同一天连做两次备份后再触发轮转，只保留当天最新一份、不影响其它日期
- [ ] `scripts/manage.py admins list` 正常
- [ ] `manage.py admins add <QQ> --role owner` 被拒绝并提示 `transfer`/`bootstrap_admin.py`
- [ ] 退出（Ctrl+C / `systemctl stop`）日志无「退出时统计未落库」，或其中的计数符合预期

## 协议端接入后（真实端点）

- [ ] `scripts/smoke_protocol.py` 通过（get_login_info / get_version_info）
- [ ] 群内发送 `/ping` 收到回复
- [ ] `/帮助`、`/版本`、`/统计`、`/权限` 正常（英文别名 `/help`、`/version`、`/stats`、`/op` 仍可用）
- [ ] `/统计`、`/统计 本周`、`/统计 近7天` 显示区间汇总与「近 N 日」走势；管理员额外看到命令/自动回复/错误/Top N
- [ ] 到 `[stats].digest_at` 后管理员私聊收到昨日群活跃简报（群里没有动静）
- [ ] 在 `config/config.toml` 加一段 `[[push]]` 并重启；到点收到推送，`/push` 能看到该条，`/push test <名称>` 可立即试发
- [ ] 断线重连：重启协议端后 bot 自动恢复（观察日志）

## 群互动 · 签到（默认关闭）

- [ ] 在 `config/config.toml` 打开 `checkin = true` 并重启，群内 `/config checkin on`
- [ ] `/签到` 打卡成功（返回连续天数与累计次数）；同一天再发只提示「已经签过」，次数不增加
- [ ] `/签到榜` 显示本群排行，`/签到榜 累计` 切换为累计榜
- [ ] `/帮助` 里能看到 `/签到`、`/签到榜`
- [ ] 重启业务层后签到数据仍在（`checkins` 表）

## 交接演练（换届前必做）

- [ ] 在"陌生机器"按 `docs/deploy-*.md` 从零部署
- [ ] `export_handover.py` → 新机器 `import_handover.py` → 数据一致
- [ ] `manage.py admins transfer` 完成管理员变更
- [ ] 更新 `docs/generations.md` 维护者记录

## 群管理 · 风控（需要机器人是群管理员）

- [ ] `/mod add keyword | 测试词 | warn` 能新增规则；`/mod list` 可见
- [ ] 普通成员发含测试词的消息 → 被撤回并收到 @ 警告；累计到阈值后自动禁言
- [ ] 连发多条消息触发刷屏 → 自动禁言；`/mod log` 可查到 `moderation.*` 记录
- [ ] `/mod test <文本>` 只显示命中规则、不处置
- [ ] 私聊 `/use <群号>` 绑定后，`/mute <qq>` 能作用到该群，回复回到私聊
- [ ] `dry_run = true` 时只写审计、不执行真实撤回/禁言
