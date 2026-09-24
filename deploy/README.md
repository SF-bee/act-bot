# deploy/

分平台部署资源目录（按需完善；当前指引见 `docs/deploy*.md`）：

- `linux/` —— systemd unit 模板（napcat.service / act-bot.service）
- `windows/` —— 服务安装脚本（NSSM / WinSW）与启动 bat 模板
- `docker/` —— docker-compose 模板（napcat + act-bot）
- `macos/` —— 开发辅助说明（可选）

> P0 阶段先占位；部署实施时固化具体模板，并同步 `docs/deploy-*.md`。
