# 验收清单（每平台部署后逐项打勾）

## 通用（业务层）

- [ ] `uv run pytest -q` 全绿
- [ ] `uv run python scripts/doctor.py` 全绿
- [ ] `uv run python scripts/smoke_fake.py` 通过（Fake 端到端）
- [ ] `scripts/backup.py` 能生成备份；`scripts/restore.py` 能恢复
- [ ] `scripts/manage.py admins list` 正常

## 协议端接入后（真实端点）

- [ ] `scripts/smoke_protocol.py` 通过（get_login_info / get_version_info）
- [ ] 群内发送 `/ping` 收到回复
- [ ] `/version`、`/权限` 正常
- [ ] 断线重连：重启协议端后 bot 自动恢复（观察日志）

## 交接演练（换届前必做）

- [ ] 在"陌生机器"按 `docs/deploy-*.md` 从零部署
- [ ] `export_handover.py` → 新机器 `import_handover.py` → 数据一致
- [ ] `manage.py admins transfer` 完成管理员变更
- [ ] 更新 `docs/generations.md` 维护者记录
