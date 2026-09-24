#!/usr/bin/env python3
"""导入换届交接包（覆盖当前数据；导入前请停止 bot）。

用法：
    uv run python scripts/import_handover.py <交接包.tar.gz> [--yes]

行为：
    1. 解压到临时目录并校验 manifest 与数据库完整性；
    2. 将当前库另存为 *.pre-import-*.bak；
    3. 覆盖 data/act.db；uploads/ 中同名文件跳过（不覆盖现有）；
    4. 打印后续步骤（写管理员 → 验收清单）。
"""
from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """防目录穿越的安全解压（跨平台）。"""
    for member in tar.getmembers():
        member_path = (dest / member.name).resolve()
        try:
            member_path.relative_to(dest.resolve())
        except ValueError:
            raise RuntimeError(f"交接包包含非法路径：{member.name}")
    try:
        tar.extractall(dest, filter="data")  # Python >= 3.12
    except TypeError:  # pragma: no cover - 旧版本回退
        tar.extractall(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description="导入 ACT Bot 换届交接包")
    parser.add_argument("archive", type=Path, help="交接包路径（.tar.gz）")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认")
    args = parser.parse_args()

    from src.core import db, paths

    archive = args.archive
    if not archive.is_file():
        print(f"❌ 交接包不存在：{archive}")
        return 1

    with tempfile.TemporaryDirectory(prefix="actbot-import-") as tmp:
        tmpdir = Path(tmp)
        with tarfile.open(archive, "r:gz") as tar:
            _safe_extract(tar, tmpdir)

        manifest_file = tmpdir / "manifest.json"
        db_file = tmpdir / "act.db"
        if not db_file.is_file():
            print("❌ 交接包缺少 act.db")
            return 1
        if manifest_file.is_file():
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            print(
                f"交接包信息：{manifest.get('app')} v{manifest.get('version')}"
                f"（导出时间 {manifest.get('exported_at')}）"
            )

        check = db.integrity_check(db_file)
        if check != "ok":
            print(f"❌ 交接包数据库校验失败：{check}")
            return 1

        target = paths.db_path()
        if target.exists() and not args.yes:
            answer = input(f"将覆盖现有数据库 {target}，确认？[y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                print("已取消。")
                return 1

        paths.ensure_dir(target.parent)
        if target.exists():
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            safety = target.with_name(f"{target.name}.pre-import-{stamp}.bak")
            shutil.copy2(target, safety)
            print(f"已另存当前库：{safety}")
        shutil.copy2(db_file, target)
        for suffix in ("-wal", "-shm"):
            residual = Path(f"{target}{suffix}")
            if residual.exists():
                residual.unlink()

        uploads_src = tmpdir / "uploads"
        if uploads_src.is_dir():
            uploads_dst = paths.ensure_dir(paths.uploads_dir())
            copied = skipped = 0
            for item in uploads_src.rglob("*"):
                if not item.is_file():
                    continue
                rel = item.relative_to(uploads_src)
                dst = uploads_dst / rel
                if dst.exists():
                    skipped += 1
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst)
                copied += 1
            print(f"附件：新增 {copied} 个，跳过同名 {skipped} 个")

    print("✅ 导入完成。后续步骤：")
    print("   1) 写入 / 转让管理员：uv run python scripts/manage.py admins transfer <新QQ>")
    print("   2) 启动 bot 并执行 docs/acceptance.md 的验收清单")
    return 0


if __name__ == "__main__":
    sys.exit(main())
