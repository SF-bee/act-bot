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
