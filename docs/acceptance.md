# 验收清单（每平台部署后逐项打勾）

## 通用（业务层）

- [ ] `uv run pytest -q` 全绿
- [ ] （Docker 路线）`docker compose -f deploy/docker/docker-compose.yml config` 通过
- [ ] `uv run python scripts/doctor.py` 全绿
- [ ] `uv run python scripts/smoke_fake.py` 通过（Fake 端到端）
- [ ] `scripts/backup.py` 能生成备份；`scripts/restore.py` 能恢复
- [ ] `scripts/manage.py admins list` 正常

## 协议端接入后（真实端点）

- [ ] `scripts/smoke_protocol.py` 通过（get_login_info / get_version_info）
- [ ] 群内发送 `/ping` 收到回复
- [ ] `/帮助`、`/版本`、`/统计`、`/权限` 正常（英文别名 `/help`、`/version`、`/stats`、`/op` 仍可用）
- [ ] 断线重连：重启协议端后 bot 自动恢复（观察日志）

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
