#!/usr/bin/env python3
"""导出换届交接包（数据 + 文档；绝不包含任何凭据）。

用法：
    uv run python scripts/export_handover.py [--output 路径]

交接包内容（tar.gz）：
    manifest.json        # 版本 / 导出时间 / 结构版本 / 数据统计
    act.db               # 数据库快照（在线备份 + 完整性校验）
    uploads/             # 附件目录（若存在）
    config.example.toml  # 业务配置模板（不含真实值）
    docs/                # 交接与运维文档（handover / ops / design / onebot-contract / platform-notes ...）

绝不包含：.env、config/config.toml、任何 token / 凭据。
"""
from __future__ import annotations

import argparse
import datetime
import json
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TABLES = [
    "admins",
    "groups",
    "departments",
    "events",
    "event_signups",
    "announcements",
    "archive_items",
    "settings",
    "audit_log",
]
DOCS = [
    "handover.md",
    "ops.md",
    "design.md",
    "onebot-contract.md",
    "platform-notes.md",
    "acceptance.md",
    "deploy.md",
]


def _schema_version(db_file: Path) -> int:
    with sqlite3.connect(str(db_file)) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _counts(db_file: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    with sqlite3.connect(str(db_file)) as conn:
        for table in TABLES:
            try:
                result[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            except sqlite3.Error:
                result[table] = -1
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 ACT Bot 换届交接包")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="输出文件（默认 data/backups/act-handover-<时间>.tar.gz）",
    )
    args = parser.parse_args()

    import src
    from src.core import backup, paths

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output = args.output or (paths.backups_dir() / f"act-handover-{timestamp}.tar.gz")
    paths.ensure_dir(output.parent)

    with tempfile.TemporaryDirectory(prefix="actbot-handover-") as tmp:
        tmpdir = Path(tmp)
        db_snapshot = backup.backup_database(dest_dir=tmpdir)

        manifest = {
            "app": "act-bot",
            "version": src.__version__,
            "exported_at": datetime.datetime.now().astimezone().isoformat(),
            "schema_version": _schema_version(db_snapshot),
            "counts": _counts(db_snapshot),
        }
        (tmpdir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        with tarfile.open(output, "w:gz") as tar:
            tar.add(tmpdir / "manifest.json", arcname="manifest.json")
            tar.add(db_snapshot, arcname="act.db")
            uploads = paths.uploads_dir()
            if uploads.is_dir():
                tar.add(uploads, arcname="uploads")
            example = paths.PROJECT_ROOT / "config" / "config.example.toml"
            if example.is_file():
                tar.add(example, arcname="config.example.toml")
            for name in DOCS:
                doc = paths.PROJECT_ROOT / "docs" / name
                if doc.is_file():
                    tar.add(doc, arcname=f"docs/{name}")

    print(f"✅ 交接包已导出：{output}")
    print("   · 不含任何凭据（.env / config.toml 均不打包）")
    print("   · 新负责人请按包内 docs/handover.md 操作")
    return 0


if __name__ == "__main__":
    sys.exit(main())
