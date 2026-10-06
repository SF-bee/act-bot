#!/usr/bin/env python3
"""群风控端到端冒烟：不需要真实 QQ。

复用 smoke_events 的 Fake OneBot 脚手架，验证：
    1. 群内 /mod add 新增敏感词规则；
    2. 普通成员发违规消息 → 撤回（delete_msg）+ 禁言（set_group_ban）+ 群内警告；
    3. 私聊 /use 绑定群 → /mute -g 从私聊禁言，动作发往正确群、回复回私聊；
    4. /mod log 能查到处置记录；私聊 /config -g 可开关功能。

用法：
    uv run python scripts/smoke_moderation.py [--timeout 90] [--log-level DEBUG]
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
sys.path.insert(0, str(ROOT / "scripts"))

import smoke_events as base  # noqa: E402  （复用 Fake OneBot 脚手架）

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SELF_ID = base.SELF_ID
ADMIN_QQ = base.ADMIN_QQ
GROUP_ID = base.GROUP_ID
NEWCOMER = base.NEWCOMER
SMOKE_TOKEN = base.SMOKE_TOKEN


def build_group_message(text: str, user_id: int = ADMIN_QQ, role: str = "member") -> dict:
    payload = base.build_group_message(text, user_id)
    payload["sender"]["role"] = role
    return payload


def build_private_message(text: str, user_id: int = ADMIN_QQ) -> dict:
    return {
        "time": int(time.time()),
        "self_id": SELF_ID,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": int(time.time() * 1000) % 1000000,
        "user_id": user_id,
        "raw_message": text,
        "font": 0,
        "sender": {"user_id": user_id, "nickname": "smoke", "role": "member"},
        "message": [{"type": "text", "data": {"text": text}}],
    }


async def drain(connection, *, quiet: float = 1.0, max_wait: float = 6.0):
    """应答 API 调用，返回 (主动发送列表, 全部 API 调用列表)。"""
    sends: list[dict] = []
    calls: list[dict] = []
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
        calls.append(message)
        if action in ("send_msg", "send_group_msg", "send_private_msg"):
            sends.append(message)
        await connection.send(
            json.dumps(
                {
                    "status": "ok",
                    "retcode": 0,
                    "data": base.api_reply_for(action, message.get("params", {}) or {}),
                    "echo": message.get("echo"),
                },
                ensure_ascii=False,
            )
        )
        quiet_until = time.time() + quiet
    return sends, calls


def find_call(calls: list[dict], action: str) -> dict | None:
    for call in calls:
        if str(call.get("action")) == action:
            return call
    return None


async def run_smoke(timeout: float, log_level: str = "INFO") -> int:
    import websockets

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    tmpdir = tempfile.mkdtemp(prefix="actbot-smoke-moderation-")
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        print(("  ✅ " if ok else "  ❌ ") + name + (f" — {detail}" if detail else ""))

    try:
        base.bootstrap_admin(tmpdir)
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
            "ACTBOT_CONFIG_FILE": str(Path(tmpdir) / "config.toml"),
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
    output = ""
    try:
        connection = None
        while time.time() < deadline:
            if bot.poll() is not None:
                break
            try:
                connection = await base._connect_once(websockets, ws_url, headers)
                break
            except Exception:
                await asyncio.sleep(0.5)
        if connection is None:
            raise RuntimeError(f"bot 未在 {timeout:.0f}s 内就绪")

        async with connection:
            # 1. 群内新增敏感词规则
            await connection.send(
                json.dumps(
                    build_group_message("/mod add keyword | 违禁词 | mute | 60", ADMIN_QQ, "owner"),
                    ensure_ascii=False,
                )
            )
            sends, _ = await drain(connection, quiet=1.0, max_wait=6.0)
            text = base.extract_text(sends[-1]["params"].get("message")) if sends else ""
            check("群内 /mod add 新增规则", "已新增规则" in text, text[:60].replace("\n", " | "))

            # 2. 普通成员发违规消息 → 撤回 + 禁言 + 警告
            await connection.send(
                json.dumps(build_group_message("这是违禁词，快来", NEWCOMER, "member"), ensure_ascii=False)
            )
            sends, calls = await drain(connection, quiet=1.5, max_wait=8.0)
            recall = find_call(calls, "delete_msg")
            ban = find_call(calls, "set_group_ban")
            warn_text = base.extract_text(sends[-1]["params"].get("message")) if sends else ""
            check("违规消息被撤回", recall is not None)
            check("违规成员被禁言", ban is not None)
            check(
                "禁言时长取自规则",
                ban is not None and int((ban.get("params") or {}).get("duration", 0)) == 60,
                str((ban or {}).get("params")),
            )
            check("群内发出警告", bool(warn_text), warn_text[:60].replace("\n", " | "))

            # 3. 私聊 /use 绑定群
            await connection.send(
                json.dumps(build_private_message("/use {0}".format(GROUP_ID), ADMIN_QQ), ensure_ascii=False)
            )
            sends, _ = await drain(connection, quiet=1.0, max_wait=6.0)
            use_text = base.extract_text(sends[-1]["params"].get("message")) if sends else ""
            check("私聊 /use 绑定群成功", "已绑定群" in use_text, use_text[:60].replace("\n", " | "))

            # 4. 私聊 /mute -g 精确指定群（不用 /use）
            await connection.send(
                json.dumps(
                    build_private_message("/mute -g {0} {1} 120".format(GROUP_ID, NEWCOMER), ADMIN_QQ),
                    ensure_ascii=False,
                )
            )
            sends, calls = await drain(connection, quiet=1.5, max_wait=8.0)
            ban = find_call(calls, "set_group_ban")
            reply = base.extract_text(sends[-1]["params"].get("message")) if sends else ""
            check("私聊 /mute -g 触发禁言", ban is not None)
            check(
                "禁言作用在目标群与目标人",
                ban is not None
                and str((ban.get("params") or {}).get("group_id")) == str(GROUP_ID)
                and str((ban.get("params") or {}).get("user_id")) == str(NEWCOMER),
                str((ban or {}).get("params")),
            )
            check("管理结果回私聊", "已处理" in reply, reply[:60].replace("\n", " | "))

            # 5. 私聊 /mod log 能看到处置记录
            await connection.send(
                json.dumps(
                    build_private_message("/mod log -g {0}".format(GROUP_ID), ADMIN_QQ),
                    ensure_ascii=False,
                )
            )
            sends, _ = await drain(connection, quiet=1.0, max_wait=6.0)
            log_text = base.extract_text(sends[-1]["params"].get("message")) if sends else ""
            check(
                "私聊 /mod log 可见处置记录",
                "风控记录" in log_text or "moderation." in log_text,
                log_text[:70].replace("\n", " | "),
            )

            # 6. 私聊 /config -g 开关功能
            await connection.send(
                json.dumps(
                    build_private_message("/config -g {0} moderation off".format(GROUP_ID), ADMIN_QQ),
                    ensure_ascii=False,
                )
            )
            sends, _ = await drain(connection, quiet=1.0, max_wait=6.0)
            cfg_text = base.extract_text(sends[-1]["params"].get("message")) if sends else ""
            check("私聊 /config -g 可开关功能", "关闭" in cfg_text, cfg_text[:60].replace("\n", " | "))
    except Exception as exc:  # noqa: BLE001 - 冒烟工具：展示所有异常
        failure = f"{type(exc).__name__}: {exc}"
        print(f"❌ 冒烟异常：{failure}")
    finally:
        bot.terminate()
        try:
            bot.wait(timeout=10)
        except Exception:
            bot.kill()
        try:
            output = bot.stdout.read() if bot.stdout else ""
        except Exception:
            pass
        shutil.rmtree(tmpdir, ignore_errors=True)

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks) or 1
    if failure or passed != total or not checks:
        print(f"\n❌ 群风控冒烟未通过（{passed}/{total}）")
        if output.strip():
            print("---- bot 日志（尾部）----")
            print("\n".join(output.splitlines()[-25:]))
        return 1
    print(f"\n✅ 群风控端到端通过（{passed}/{total}）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="群风控端到端冒烟")
    parser.add_argument("--timeout", type=float, default=90.0, help="总超时（秒）")
    parser.add_argument("--log-level", default="INFO", help="bot 子进程日志级别")
    args = parser.parse_args()
    return asyncio.run(run_smoke(args.timeout, args.log_level))


if __name__ == "__main__":
    sys.exit(main())
