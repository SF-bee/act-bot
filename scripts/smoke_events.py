#!/usr/bin/env python3
"""事件中枢端到端冒烟：不需要真实 QQ。

验证链路（全部通过真实 WS 协议行走）：
    1. 拉起 bot 子进程（隔离数据目录）+ 预置一个管理员；
    2. 扮演协议端连接，发一条入群事件 → 期望收到欢迎消息（@ 新人 + 欢迎语）；
    3. 同一个人再入群一次 → 期望因 cooldown 不再欢迎；
    4. 管理员发 /config welcome off → 期望回复已关闭；再发入群事件 → 期望被群级门控拦下；
    5. 管理员发 /config welcome on → 另一个人入群 → 期望再次欢迎；
    6. 管理员发 /audit → 期望能看到 config.set 审计记录；
    7. 管理员发 /welcome on → 期望被引导到 /config（/welcome 只读，开关不重复实现）。

用法：
    uv run python scripts/smoke_events.py [--timeout 90] [--log-level DEBUG]
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

SELF_ID = 900000001
SMOKE_TOKEN = "smoke-token"
ADMIN_QQ = 100002
GROUP_ID = 100001
NEWCOMER = 100003
GROUP_NAME = "冒烟测试群"

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


def has_at(message, qq: int) -> bool:
    """消息里是否 @ 了指定 QQ。"""
    if not isinstance(message, list):
        return False
    return any(
        isinstance(segment, dict)
        and segment.get("type") == "at"
        and str(segment.get("data", {}).get("qq")) == str(qq)
        for segment in message
    )


def build_group_message(text: str, user_id: int = ADMIN_QQ) -> dict:
    return {
        "time": int(time.time()),
        "self_id": SELF_ID,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": int(time.time() * 1000) % 1000000,
        "group_id": GROUP_ID,
        "user_id": user_id,
        "raw_message": text,
        "font": 0,
        "sender": {"user_id": user_id, "nickname": "smoke", "card": "", "role": "owner"},
        "message": [{"type": "text", "data": {"text": text}}],
    }


def build_join_event(user_id: int) -> dict:
    return {
        "time": int(time.time()),
        "self_id": SELF_ID,
        "post_type": "notice",
        "notice_type": "group_increase",
        "sub_type": "approve",
        "group_id": GROUP_ID,
        "user_id": user_id,
        "operator_id": ADMIN_QQ,
    }


def api_reply_for(action: str, params: dict) -> dict:
    """给机器人的 API 调用编一个合理的返回值（协议端视角）。"""
    if action == "get_group_info":
        return {"group_id": GROUP_ID, "group_name": GROUP_NAME, "member_count": 3}
    if action == "get_group_member_info":
        return {
            "user_id": params.get("user_id", NEWCOMER),
            "nickname": "冒烟新人",
            "card": "",
            "role": "member",
        }
    if action == "get_login_info":
        return {"user_id": SELF_ID, "nickname": "smoke"}
    return {"message_id": 42, "time": int(time.time())}


async def _connect_once(websockets, ws_url: str, headers: dict):
    try:
        return await websockets.connect(ws_url, open_timeout=3, additional_headers=headers)
    except TypeError:
        return await websockets.connect(ws_url, open_timeout=3, extra_headers=headers)


async def drain(connection, *, quiet: float = 1.0, max_wait: float = 6.0) -> list[dict]:
    """应答机器人的 API 调用并收集其主动发送的消息，直到安静 ``quiet`` 秒。"""
    sent: list[dict] = []
    deadline = time.time() + max_wait
    quiet_until = time.time() + quiet
    while time.time() < deadline:
        timeout = max(0.05, min(quiet_until, deadline) - time.time())
        try:
            raw = await asyncio.wait_for(connection.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            if time.time() >= quiet_until:
                break
            continue
        message = json.loads(raw)
        if not isinstance(message, dict) or "action" not in message:
            continue
        action = str(message.get("action"))
        if action in ("send_msg", "send_group_msg", "send_private_msg"):
            sent.append(message)
        await connection.send(
            json.dumps(
                {
                    "status": "ok",
                    "retcode": 0,
                    "data": api_reply_for(action, message.get("params", {}) or {}),
                    "echo": message.get("echo"),
                },
                ensure_ascii=False,
            )
        )
        quiet_until = time.time() + quiet
    return sent


def bootstrap_admin(data_dir: str) -> None:
    """在隔离数据目录里预置管理员（复用正式脚本，保证与生产同一套逻辑）。"""
    env = dict(os.environ)
    env["ACTBOT_DATA_DIR"] = data_dir
    subprocess.run(
        [sys.executable, "scripts/bootstrap_admin.py", "--qq", str(ADMIN_QQ)],
        cwd=str(ROOT),
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


async def run_smoke(timeout: float, log_level: str = "INFO") -> int:
    import websockets

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    tmpdir = tempfile.mkdtemp(prefix="actbot-smoke-events-")
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        print(("  ✅ " if ok else "  ❌ ") + name + (f" — {detail}" if detail else ""))

    try:
        bootstrap_admin(tmpdir)
    except subprocess.CalledProcessError as exc:
        print(f"❌ 预置管理员失败：{exc.stdout}")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return 1

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
    failure = ""
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
            raise RuntimeError(f"bot 未在 {timeout:.0f}s 内就绪")

        async with connection:
            # 1. 首次入群 → 欢迎
            await connection.send(json.dumps(build_join_event(NEWCOMER), ensure_ascii=False))
            first = await drain(connection, quiet=1.2, max_wait=8.0)
            text = extract_text(first[-1]["params"].get("message")) if first else ""
            check("入群事件触发欢迎", bool(first), f"收到 {len(first)} 条发送")
            check("欢迎消息 @ 新人", bool(first) and has_at(first[-1]["params"].get("message"), NEWCOMER))
            check("欢迎语含新人占位符渲染", "欢迎" in text and "{" not in text, text[:60])

            # 2. 同一人再次入群（协议端重推）→ cooldown 拦截
            await connection.send(json.dumps(build_join_event(NEWCOMER), ensure_ascii=False))
            repeat = await drain(connection, quiet=0.8, max_wait=3.0)
            check("cooldown 拦下重复入群", not repeat, f"收到 {len(repeat)} 条发送")

            # 3. 关掉本群欢迎 → 门控拦截
            await connection.send(json.dumps(build_group_message("/config welcome off"), ensure_ascii=False))
            off = await drain(connection, quiet=0.8, max_wait=4.0)
            off_text = extract_text(off[-1]["params"].get("message")) if off else ""
            check("/config welcome off 生效", "关闭" in off_text, off_text[:60])

            await connection.send(json.dumps(build_join_event(NEWCOMER + 1), ensure_ascii=False))
            gated = await drain(connection, quiet=0.8, max_wait=3.0)
            check("群级 feature gate 拦下欢迎", not gated, f"收到 {len(gated)} 条发送")

            # 4. 再打开 → 恢复欢迎
            await connection.send(json.dumps(build_group_message("/config welcome on"), ensure_ascii=False))
            on = await drain(connection, quiet=0.8, max_wait=4.0)
            on_text = extract_text(on[-1]["params"].get("message")) if on else ""
            check("/config welcome on 生效", "开启" in on_text, on_text[:60])

            await connection.send(json.dumps(build_join_event(NEWCOMER + 2), ensure_ascii=False))
            again = await drain(connection, quiet=1.2, max_wait=6.0)
            check("重新开启后欢迎恢复", bool(again), f"收到 {len(again)} 条发送")

            # 5. 审计记录
            await connection.send(json.dumps(build_group_message("/audit"), ensure_ascii=False))
            audit_reply = await drain(connection, quiet=0.8, max_wait=4.0)
            audit_text = extract_text(audit_reply[-1]["params"].get("message")) if audit_reply else ""
            check("审计记录可见 config.set", "config.set" in audit_text, audit_text[:80].replace("\n", " | "))

            # 6. /welcome 只读：带开关参数应被引导到 /config
            await connection.send(json.dumps(build_group_message("/welcome on"), ensure_ascii=False))
            hint = await drain(connection, quiet=0.8, max_wait=4.0)
            hint_text = extract_text(hint[-1]["params"].get("message")) if hint else ""
            check(
                "/welcome 引导到 /config（开关不再重复实现）",
                "config welcome on" in hint_text,
                hint_text[:70].replace("\n", " | "),
            )
    except Exception as exc:  # noqa: BLE001 - 冒烟工具：展示所有异常
        failure = f"{type(exc).__name__}: {exc}"
        print(f"❌ 冒烟异常：{failure}")
    finally:
        bot.terminate()
        try:
            bot.wait(timeout=10)
        except Exception:
            bot.kill()
        output = ""
        try:
            output = bot.stdout.read() if bot.stdout else ""
        except Exception:
            pass
        shutil.rmtree(tmpdir, ignore_errors=True)

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks) or 1
    if failure or passed != total or not checks:
        print(f"\n❌ 事件中枢冒烟未通过（{passed}/{total}）")
        if output.strip():
            print("---- bot 日志（尾部）----")
            print("\n".join(output.splitlines()[-25:]))
        return 1
    print(f"\n✅ 事件中枢端到端通过（{passed}/{total}）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="事件中枢端到端冒烟")
    parser.add_argument("--timeout", type=float, default=90.0, help="总超时（秒）")
    parser.add_argument("--log-level", default="INFO", help="bot 子进程日志级别")
    args = parser.parse_args()
    return asyncio.run(run_smoke(args.timeout, args.log_level))


if __name__ == "__main__":
    sys.exit(main())

