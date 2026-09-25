# ACT Bot 业务层 Windows 服务安装/卸载脚本（NSSM）
#
# 用法（管理员 PowerShell）：
#   powershell -ExecutionPolicy Bypass -File deploy\windows\install-act-bot-service.ps1 -Action install
#   powershell -ExecutionPolicy Bypass -File deploy\windows\install-act-bot-service.ps1 -Action uninstall
#
# 说明：只依赖 NSSM（第三方小工具），不含 QQ 号 / token / 机器信息；
#       凭据全部来自仓库根 .env（NoneBot 启动时自动加载）。
[CmdletBinding()]
param(
    [ValidateSet('install','uninstall')][string]$Action = 'install',
    [string]$ServiceName = 'act-bot',
    [string]$RepoPath = 'C:\act-bot',
    [string]$NssmPath = 'C:\tools\nssm\nssm.exe'
)

$ErrorActionPreference = 'Stop'

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw '请以管理员身份运行 PowerShell（服务注册需要提权）。'
}
if (-not (Test-Path $NssmPath)) {
    throw "未找到 nssm.exe：$NssmPath。请先下载 NSSM 并用 -NssmPath 指定实际路径。"
}

$python = Join-Path $RepoPath '.venv\Scripts\python.exe'
$entry = Join-Path $RepoPath 'bot.py'
$logDir = Join-Path $RepoPath 'logs'

switch ($Action) {
    'install' {
        if (-not (Test-Path $python)) { throw "未找到虚拟环境解释器：$python。请先在 $RepoPath 执行 uv sync。" }
        if (-not (Test-Path $entry)) { throw "未找到入口文件：$entry。" }
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null

        & $NssmPath install $ServiceName $python $entry
        & $NssmPath set $ServiceName AppDirectory $RepoPath
        & $NssmPath set $ServiceName DisplayName 'ACT Bot (NoneBot2 / OneBot v11)'
        & $NssmPath set $ServiceName Description 'ACT 动漫社 QQ 群机器人业务层（协议端 NapCat 单独部署）'
        & $NssmPath set $ServiceName Start SERVICE_AUTO_START
        & $NssmPath set $ServiceName AppStdout (Join-Path $logDir 'act-bot.out.log')
        & $NssmPath set $ServiceName AppStderr (Join-Path $logDir 'act-bot.err.log')
        & $NssmPath set $ServiceName AppRotateFiles 1
        & $NssmPath set $ServiceName AppRotateOnline 1
        & $NssmPath set $ServiceName AppRotateBytes 10485760
        & $NssmPath set $ServiceName AppExit Default Restart
        & $NssmPath set $ServiceName AppRestartDelay 5000

        Start-Service -Name $ServiceName
        Write-Host "[OK] 服务 $ServiceName 已安装并启动；日志见 $logDir"
    }
    'uninstall' {
        if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
            & $NssmPath remove $ServiceName confirm
            Write-Host "[OK] 服务 $ServiceName 已卸载"
        } else {
            Write-Host "[SKIP] 服务 $ServiceName 不存在"
        }
    }
}
