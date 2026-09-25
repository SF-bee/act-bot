@echo off
rem 手动前台启动（调试用）；生产建议注册为服务，见 install-act-bot-service.ps1
chcp 65001 >nul
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" bot.py
pause
