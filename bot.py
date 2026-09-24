#!/usr/bin/env python3
"""ACT Bot 启动入口（根目录薄封装；启动逻辑见 ``src/bot.py``）。

用法：``uv run python bot.py``
"""
from src.bot import main

if __name__ == "__main__":
    main()
