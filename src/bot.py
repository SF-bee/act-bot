"""ACT Bot 启动逻辑（NoneBot2）。

调用链：``uv run python bot.py`` → 本模块 ``main()`` → ``nonebot.init()`` →
加载 ``pyproject.toml`` 中的适配器与插件 → 启动 WebSocket 服务（等待协议端接入）。

注意：这里只写"启动流程"；业务逻辑放在 ``src/plugins/``，平台差异与本文件无关。
"""
from __future__ import annotations

import logging

import nonebot

logger = logging.getLogger("actbot.bot")


def main() -> None:
    from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

    # 先加载 .env（若存在），保证 nonebot 与业务代码读到的环境变量一致
    from src.core.config import load_env_file

    load_env_file()

    nonebot.init()
    driver = nonebot.get_driver()
    # 显式注册 OneBot v11 适配器（反向 WS 的接入路由由适配器提供）
    driver.register_adapter(OneBotV11Adapter)

    @driver.on_startup
    async def _on_startup() -> None:
        """启动钩子：初始化数据库（含迁移）与调度器。"""
        from src.core import db, scheduler

        db_file = await db.init_db()
        logger.info("数据库就绪：%s", db_file)
        scheduler.setup_and_start()

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        from src.core import db, scheduler

        scheduler.shutdown()
        await db.dispose_engine()

    nonebot.load_from_toml("pyproject.toml")
    nonebot.run()


if __name__ == "__main__":
    main()
