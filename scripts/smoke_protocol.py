#!/usr/bin/env python3
"""契约冒烟：连接真实协议端（需其开启 WebSocket 服务端模式），验证 OneBot 子集能力。

用法：
    uv run python scripts/smoke_protocol.py --url ws://127.0.0.1:3001 --token <token>

可选：
    --send-group <群号> --text "测试消息"    # 实际发送一条消息（默认只做只读探测）

说明：需要先在协议端（NapCat WebUI → 网络配置）开启 WebSocket 服务器并配置 token。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _rpc(conn, action: str, params: dict | None = None, echo: int = 1) -> dict:
    payload = {"action": action, "params": params or {}, "echo": str(echo)}
    conn.send(json.dumps(payload, ensure_ascii=False))
    while True:
        message = json.loads(conn.recv())
        if isinstance(message, dict) and message.get("echo") == payload["echo"]:
            return message


def main() -> int:
    parser = argparse.ArgumentParser(description="对真实协议端做契约冒烟（只读探测）")
    parser.add_argument("--url", default=None, help="协议端 WS 地址（默认读 .env 的 ACTBOT_PROTOCOL_WS_URL）")
    parser.add_argument("--token", default=None, help="token（默认读 .env 的 ACTBOT_PROTOCOL_TOKEN）")
    parser.add_argument("--send-group", default=None, help="可选：向该群发送测试消息")
    parser.add_argument("--text", default="ACT Bot 契约冒烟测试", help="配合 --send-group 的消息内容")
    args = parser.parse_args()

    from src.core.config import get_settings

    settings = get_settings()
    url = (args.url or settings.protocol_ws_url or "").strip()
    token = (args.token or settings.protocol_token or "").strip()
    if not url:
        print("❌ 未提供 WS 地址：请用 --url，或在 .env 设置 ACTBOT_PROTOCOL_WS_URL")
        return 1

    try:
        from websockets.sync.client import connect
    except ImportError:
        print("❌ 缺少 websockets 依赖：请运行 `uv sync`")
        return 1

    headers = {"Authorization": f"Bearer {token}"} if token else None
    try:
        kwargs = {"open_timeout": 10}
        if headers:
            kwargs["additional_headers"] = headers
        with connect(url, **kwargs) as conn:
            login = _rpc(conn, "get_login_info")
            print("登录信息：", login.get("data"))
            version = _rpc(conn, "get_version_info", echo=2)
            print("版本信息：", version.get("data"))
            if args.send_group:
                result = _rpc(
                    conn,
                    "send_group_msg",
                    {"group_id": int(args.send_group), "message": args.text},
                    echo=3,
                )
                print("发送结果：", result.get("status"), result.get("data"))
        print("✅ 契约冒烟完成")
        return 0
    except Exception as exc:  # noqa: BLE001 - 部署验收工具
        print(f"❌ 连接或调用失败：{type(exc).__name__}: {exc}")
        print("提示：确认协议端已开启 WebSocket 服务端模式，且地址 / 端口 / token 与协议端一致。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
