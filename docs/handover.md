# 换届交接手册（清单式）

> 目标：**旧负责人：备份 → 导出交接包；新负责人：部署 → 导入 → 改管理员 → 启动。**
> 全程**不传递任何凭据**（新账号自带）；交接前后各做一次验收演练。

## T-14 天（旧负责人）

- [ ] 生成交接包：`uv run python scripts/export_handover.py`
- [ ] 确认新负责人拿到：仓库权限、服务器 / 机器访问方式、交接包文件
- [ ] 检查 `docs/generations.md` 维护者记录

## T-7 天（双方）

- [ ] 带新负责人在"陌生机器"按 `docs/deploy-*.md` 从零部署一次
- [ ] 演练 `import_handover.py` 与 `manage.py admins transfer`

## T-0（切换）

- [ ] 群内公告交接安排
- [ ] 新负责人：准备小号（提前养号）→ 协议端扫码登录 → 导入交接包 → 写管理员
- [ ] 旧号退场（退群，或保留为普通成员并说明）

## T+7（新负责人）

- [ ] 按 `docs/acceptance.md` 复检
- [ ] 更新 `docs/generations.md`
- [ ] 有疑问 → 补充到 `docs/faq.md`

## 交接包内容说明

`manifest.json`（版本 / 统计）、`act.db`（数据）、`uploads/`（附件）、`config.example.toml`、`docs/`。

**绝不包含**：`.env`、`config.toml`、任何 token / 凭据、任何账号登录态（新号需自行扫码）。
