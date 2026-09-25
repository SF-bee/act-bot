# deploy/macos/

macOS（Apple Silicon）**开发/联调**用的业务层保活模板。

> macOS 不是生产平台（生产见 `docs/deploy-ubuntu.md`）；这里解决的是「本机联调时业务层被前台会话/超时带走」的问题。
> 血泪教训：直接用前台终端或带超时的任务跑 `bot.py`，超时一到进程就没了，NapCat 那边就是刷屏的
> `connect ECONNREFUSED ...:8080`——看着像协议端坏了，其实是业务层死了。

## 安装（LaunchAgent，等价于 Linux 的 systemd unit）

```bash
cd <仓库路径>
uv sync                                              # 先有 .venv
sed -e "s#__REPO_PATH__#$PWD#g" -e "s#__HOME__#$HOME#g" \
    deploy/macos/com.actbot.dev.plist.template > ~/Library/LaunchAgents/com.actbot.dev.plist
plutil -lint ~/Library/LaunchAgents/com.actbot.dev.plist   # 必须 OK
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.actbot.dev.plist
```

## 常用操作

```bash
launchctl print gui/$(id -u)/com.actbot.dev | grep -E 'state|pid'   # 状态
tail -f ~/Library/Logs/actbot-dev.log                               # 业务层日志
launchctl kickstart -k gui/$(id -u)/com.actbot.dev                  # 重启
launchctl bootout gui/$(id -u)/com.actbot.dev                       # 停止并卸载
```

## 说明

- `KeepAlive=true` + `ThrottleInterval=10`：进程意外退出 10 秒内自动拉起（实测 `kill -9` 后约 8 秒恢复，协议端随之重连）；
- `HOST=0.0.0.0`：Docker Desktop 跑 NapCat 时容器经网关（192.168.65.254 / `host.docker.internal`）访问业务层，绑 `127.0.0.1` 会一直被拒；只在本机自测可改回；
- 凭据仍来自仓库根 `.env`（plist 里不写 QQ 号 / token）；
- 本模板只针对开发机；生产自启用 `deploy/linux/`（systemd）。
