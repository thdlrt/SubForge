"""
递归扫描目录，将「无扩展名的文件名以指定后缀结尾」的文件移动到目标目录。

示例（仅预览，不移动）：
  python additionpackage/move_files_by_suffix.py "E:\\videos\\course" -d "E:\\out\\配音" --suffix "_配音"

实际移动需加 --apply：
  python additionpackage/move_files_by_suffix.py "E:\\videos\\course" -d "E:\\out\\配音" --suffix "_配音" --apply
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def iter_matches(root: Path, suffix: str) -> list[Path]:
    """stem 必须以 suffix 结尾（例如 stem 以 _配音 结尾）。"""
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.stem.endswith(suffix):
            out.append(p)
    return sorted(out)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="按文件名后缀递归移动文件到指定目录")
    ap.add_argument("source", type=Path, help="要扫描的根目录（含子文件夹）")
    ap.add_argument(
        "-d",
        "--dest",
        type=Path,
        required=True,
        help="目标目录（不存在时会创建）",
    )
    ap.add_argument(
        "--suffix",
        default="_配音",
        help='匹配「无扩展名文件名」的结尾，例如 "_配音" 会匹配 foo_配音.mp4（默认：_配音）',
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="实际执行移动（默认仅列出将要执行的操作）",
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="目标已存在同名文件时仍覆盖移动（谨慎）",
    )
    args = ap.parse_args()

    suffix = args.suffix
    if not suffix:
        print("错误：--suffix 不能为空", file=sys.stderr)
        return 2

    root = args.source.resolve()
    if not root.is_dir():
        print(f"错误：源目录不存在或不是目录：{root}", file=sys.stderr)
        return 2

    dest_dir = args.dest.resolve()
    matches = iter_matches(root, suffix)
    if not matches:
        print(f"未找到 stem 以 {suffix!r} 结尾的文件：{root}")
        return 0

    print(f"共 {len(matches)} 个文件匹配后缀 {suffix!r}")
    for src in matches:
        name = src.name
        target = dest_dir / name
        rel = src.relative_to(root)
        if target.resolve() == src.resolve():
            print(f"跳过（已在目标）：{src}")
            continue
        if target.exists() and not args.overwrite:
            print(f"跳过（目标已存在，加 --overwrite 可覆盖）：{src} -> {target}")
            continue
        if args.apply:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
            print(f"MOVED {rel} -> {target}")
        else:
            print(f"DRY-RUN {rel} -> {target}")

    if not args.apply:
        print("\n以上为预览。确认无误后追加 --apply 执行移动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
