#!/usr/bin/env python3
"""Fake OneBot 端到端冒烟：不需要真实 QQ。

流程：
    1. 以隔离数据目录（临时目录）拉起 bot 子进程；
    2. 等待其 WebSocket 服务就绪；
    3. 扮演协议端（Fake OneBot）连上，发送一条 ``/ping`` 群消息；
    4. 断言收到机器人回复（send_group_msg 且内容含 pong）；
    5. 清理（退出 bot、删除临时目录）。

用法：
    uv run python scripts/smoke_fake.py [--timeout 60] [--log-level DEBUG]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 与 bot 子进程共享的测试参数
SELF_ID = 900000001
SMOKE_TOKEN = "smoke-token"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def extract_text(message) -> str:
    """把 OneBot 消息段数组/字符串转为纯文本。"""
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts = []
        for segment in message:
            if isinstance(segment, dict) and segment.get("type") == "text":
                parts.append(str(segment.get("data", {}).get("text", "")))
        return "".join(parts)
    return str(message)


def build_ping_event() -> dict:
    return {
        "time": int(time.time()),
        "self_id": SELF_ID,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": 1234,
        "group_id": 100001,
        "user_id": 100002,
        "raw_message": "/ping",
        "font": 0,
        "sender": {"user_id": 100002, "nickname": "smoke", "card": "", "role": "member"},
        "message": [{"type": "text", "data": {"text": "/ping"}}],
    }


async def _connect_once(websockets, ws_url: str, headers: dict):
    """连接 WS（兼容不同 websockets 版本的头参数名）。"""
    try:
        return await websockets.connect(ws_url, open_timeout=2, additional_headers=headers)
    except TypeError:  # 旧版本参数名
        return await websockets.connect(ws_url, open_timeout=2, extra_headers=headers)


async def run_smoke(timeout: float, log_level: str = "INFO") -> int:
    import websockets

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    tmpdir = tempfile.mkdtemp(prefix="actbot-smoke-")
    env = dict(os.environ)
    env.update(
        {
            "HOST": "127.0.0.1",
            "PORT": str(port),
            "DRIVER": "~fastapi+~httpx+~websockets",
            "LOG_LEVEL": log_level,
            "ACTBOT_DATA_DIR": tmpdir,
            "ONEBOT_ACCESS_TOKEN": SMOKE_TOKEN,
            "COMMAND_START": '["/"]',
        }
    )

    bot = subprocess.Popen(
        [sys.executable, "bot.py"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    ws_url = f"ws://127.0.0.1:{port}/onebot/v11/ws"
    headers = {
        "X-Self-ID": str(SELF_ID),
        "X-Client-Role": "Universal",
        "Authorization": f"Bearer {SMOKE_TOKEN}",
    }
    deadline = time.time() + timeout
    ok = False
    received_log: list[str] = []
    try:
        connection = None
        while time.time() < deadline:
            if bot.poll() is not None:
                break
            try:
                connection = await _connect_once(websockets, ws_url, headers)
                break
            except Exception:
                await asyncio.sleep(0.5)
        if connection is None:
            raise RuntimeError(f"bot 未在 {timeout:.0f}s 内就绪（见下方 bot 日志）")

        async with connection:
            await connection.send(json.dumps(build_ping_event(), ensure_ascii=False))
            reply_text = ""
            while time.time() < deadline:
                raw = await asyncio.wait_for(connection.recv(), timeout=10)
                received_log.append(raw)
                message = json.loads(raw)
                if not isinstance(message, dict) or "action" not in message:
                    continue
                action = message.get("action")
                if action in ("send_msg", "send_group_msg", "send_private_msg"):
                    reply_text = extract_text(message.get("params", {}).get("message"))
                # 应答所有 API 调用，保证机器人侧继续执行
                await connection.send(
                    json.dumps(
                        {
                            "status": "ok",
                            "retcode": 0,
                            "data": {"message_id": 42, "time": int(time.time())},
                            "echo": message.get("echo"),
                        }
                    )
                )
                if "pong" in reply_text:
                    ok = True
                    break

            if ok:
                print(f"✅ Fake OneBot 端到端通过：机器人回复 = {reply_text!r}")
            else:
                print(f"❌ 未在超时内收到预期回复（最后一条回复 = {reply_text!r}）")
    except Exception as exc:  # noqa: BLE001 - 冒烟工具：展示所有异常
        print(f"❌ 冒烟失败：{type(exc).__name__}: {exc}")
        if received_log:
            print(f"（收到 {len(received_log)} 条消息，前 5 条如下）")
            for item in received_log[:5]:
                print("  ←", item[:300])
    finally:
        bot.terminate()
        try:
            bot.wait(timeout=10)
        except Exception:
            bot.kill()
        try:
            output = bot.stdout.read() if bot.stdout else ""
            tail = "\n".join((output or "").splitlines()[-25:])
            if not ok and tail.strip():
                print("---- bot 日志（尾部）----")
                print(tail)
        except Exception:
            pass
        shutil.rmtree(tmpdir, ignore_errors=True)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Fake OneBot 端到端冒烟")
    parser.add_argument("--timeout", type=float, default=60.0, help="总超时时间（秒）")
    parser.add_argument("--log-level", default="INFO", help="bot 子进程日志级别（调试用 DEBUG）")
    args = parser.parse_args()
    return asyncio.run(run_smoke(args.timeout, args.log_level))


if __name__ == "__main__":
    sys.exit(main())
