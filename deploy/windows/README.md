# deploy/windows/

> 状态：模板已固化；**PowerShell 服务脚本需在 Windows 10/11 上实测**（本仓库 CI 只覆盖业务层，不覆盖服务注册）。

## 1. 业务层自启（NSSM，推荐）

1. 准备：`cd C:\act-bot && uv sync`（生成 `.venv`），并 `copy .env.example .env` 填好凭据；
2. 下载 [NSSM](https://nssm.cc/) 解压，例如放到 `C:\tools\nssm\`；
3. 管理员 PowerShell：

   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\windows\install-act-bot-service.ps1 -Action install
   ```

   参数可覆盖：`-RepoPath`（默认 `C:\act-bot`）、`-ServiceName`、`-NssmPath`；
4. 卸载：同命令把 `-Action` 换成 `uninstall`。

启动日志：`<RepoPath>\logs\act-bot.out.log` / `act-bot.err.log`（NSSM 自动轮转，10 MB）。

## 2. 业务层手动启动（调试）

双击 `start-act-bot.bat`，或 `".venv\Scripts\python.exe" bot.py`。

## 3. 协议端（NapCat）自启

**本目录不提供 NapCat 的 Windows 服务模板** —— NapCat 在 Windows 的三种装法（Shell + QQ 客户端 / 一键版 / Desktop）各自带启动器，服务化方式随之不同，统一模板会误导。可选：

- 用「任务计划程序」在登录时启动 NapCat 启动器（简单）；
- 用 NSSM 把 NapCat 启动器（`launcher.bat` / `NapCatInstaller.exe` 产物）也注册成服务（需自行确认其无 GUI 依赖）。

## 4. 注意事项

- 电源计划设为「从不睡眠」，否则机器人夜间掉线；
- Docker 路线（另一套）见 `deploy/docker/`，注意 Windows 需 Docker Desktop + WSL2；
- 编码：用 Windows Terminal；业务层已统一 UTF-8 处理。
