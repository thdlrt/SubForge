"""
将目录下视频文件名译为简体中文：只取「第一个下划线 _ 之前」的部分参与翻译，
下划线及其后内容丢弃，扩展名不变。

依赖 config.json 中的 qwen_translate_api_key / qwen_translate_base_url / qwen_translate_model（与主项目一致）。
与字幕翻译类似：相同前缀只译一次；按 translate_batch_size 多标题合并为一次 API 请求；
多批之间用 translate_concurrency 并发（见 config.json）。

示例（仅预览）：
  python additionpackage/translate_video_names_zh.py "E:\\videos"

执行重命名：
  python additionpackage/translate_video_names_zh.py "E:\\videos" --apply

含子目录：
  python additionpackage/translate_video_names_zh.py "E:\\videos" -r --apply
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
from utils import sanitize_name  # noqa: E402

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts", ".flv", ".wmv"}


def stem_prefix_before_first_underscore(stem: str) -> str:
    """只保留第一个 _ 之前的部分用于翻译；无 _ 则整段 stem。"""
    if "_" not in stem:
        return stem
    return stem.split("_", 1)[0]


FILENAME_BATCH_SYSTEM = (
    "将用户给出的每一行视为一个独立的视频标题，全部翻译成简体中文。\n"
    "输出要求：行数必须与输入完全一致；按顺序每行只输出对应一行的译文；"
    "不要编号、不要解释、不要空行；不要加引号。\n"
    "专有名词按中文游戏开发语境保留。"
)


def _translate_single_prefix(text: str) -> str:
    """单条兜底（与 download 中单条逻辑一致）。"""
    text = (text or "").strip()
    if not text:
        return text
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.QWEN_TRANSLATE_API_KEY, base_url=config.QWEN_TRANSLATE_BASE_URL)
        resp = client.chat.completions.create(
            model=config.QWEN_TRANSLATE_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "将给定视频标题翻译成简体中文。"
                        "只输出译文，不要解释，不要加引号。"
                        "专有名词按中文游戏开发语境保留。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=256,
        )
        zh = (resp.choices[0].message.content or "").strip()
        if zh:
            return zh
    except Exception as e:
        print(f"   WARN 单条翻译失败，保持原文: {e}", file=sys.stderr)
    return text


def _batch_translate_prefix_lines(texts: list[str]) -> list[str]:
    """
    一批标题一次 API 调用；行数需与 texts 一致。
    失败或行数不匹配时重试，最后对该批逐条兜底。
    """
    if not texts:
        return []
    from openai import OpenAI

    client = OpenAI(api_key=config.QWEN_TRANSLATE_API_KEY, base_url=config.QWEN_TRANSLATE_BASE_URL)
    user_content = "\n".join(texts)
    max_tokens = min(4096, max(256, 80 * len(texts)))

    for attempt in range(config.API_RETRY):
        try:
            resp = client.chat.completions.create(
                model=config.QWEN_TRANSLATE_MODEL,
                messages=[
                    {"role": "system", "content": FILENAME_BATCH_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=max_tokens,
            )
            raw = (resp.choices[0].message.content or "").strip()
            lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
            if len(lines) == len(texts):
                return lines
            if len(lines) > len(texts):
                return lines[: len(texts)]
            print(
                f"   ⚠ 批量译名行数不匹配 ({len(lines)} vs {len(texts)})，"
                f"第 {attempt + 1}/{config.API_RETRY} 次重试...",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"   ⚠ 批量译名 API 错误: {e}，第 {attempt + 1}/{config.API_RETRY} 次重试...",
                file=sys.stderr,
            )
            time.sleep(2)

    print("   ⚠ 批量译名失败，本批改逐条翻译...", file=sys.stderr)
    return [_translate_single_prefix(t) for t in texts]


def translate_unique_prefixes(unique_prefixes: list[str]) -> dict[str, str]:
    """
    将有序、去重后的前缀列表译成中文；内部按批合并请求，多批并发。
    """
    if not unique_prefixes:
        return {}
    batch_size = max(1, int(config.TRANSLATE_BATCH_SIZE))
    conc = max(1, int(config.TRANSLATE_CONCURRENCY))
    batches = [
        unique_prefixes[i : i + batch_size]
        for i in range(0, len(unique_prefixes), batch_size)
    ]

    parts: list[list[str] | None] = [None] * len(batches)

    def _safe_batch(idx: int, batch: list[str]) -> tuple[int, list[str]]:
        try:
            return idx, _batch_translate_prefix_lines(batch)
        except Exception as e:
            print(f"   ⚠ 批次 {idx + 1} 异常，使用原文: {e}", file=sys.stderr)
            return idx, list(batch)

    with ThreadPoolExecutor(max_workers=min(conc, len(batches))) as ex:
        futs = {ex.submit(_safe_batch, i, b): i for i, b in enumerate(batches)}
        for fut in as_completed(futs):
            idx, lines = fut.result()
            parts[idx] = lines

    flat: list[str] = []
    for p in parts:
        if p is None:
            continue
        flat.extend(p)

    if len(flat) != len(unique_prefixes):
        print(
            f"   ⚠ 译名总数异常 ({len(flat)} vs {len(unique_prefixes)})，按位置截断/填充",
            file=sys.stderr,
        )
        while len(flat) < len(unique_prefixes):
            flat.append(unique_prefixes[len(flat)])
        flat = flat[: len(unique_prefixes)]

    return dict(zip(unique_prefixes, flat))


def collect_videos(directory: Path, recursive: bool) -> list[Path]:
    if recursive:
        files: list[Path] = []
        for p in directory.rglob("*"):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                files.append(p)
        return sorted(files)
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )


def unique_target_path(desired: Path, source: Path | None = None) -> Path:
    """若已存在则追加 _2、_3…（source 为当前文件时，同名表示无需改名）。"""
    if source is not None and desired.resolve() == source.resolve():
        return desired
    if not desired.exists():
        return desired
    stem = desired.stem
    suf = desired.suffix
    parent = desired.parent
    n = 2
    while True:
        cand = parent / f"{stem}_{n}{suf}"
        if not cand.exists():
            return cand
        if source is not None and cand.resolve() == source.resolve():
            return cand
        n += 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="视频文件名译中文（仅译第一个 _ 前，去掉 _ 后）")
    ap.add_argument("directory", type=Path, help="要处理的目录")
    ap.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="包含子目录中的视频",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="实际重命名（默认仅打印计划）",
    )
    args = ap.parse_args()

    root = args.directory.resolve()
    if not root.is_dir():
        print(f"错误：不是目录：{root}", file=sys.stderr)
        return 2

    videos = collect_videos(root, args.recursive)
    if not videos:
        print(f"未找到视频文件（扩展名 {sorted(VIDEO_EXTS)}）：{root}")
        return 0

    if not (config.QWEN_TRANSLATE_API_KEY or "").strip():
        print("错误：config.json 中未配置 qwen_translate_api_key。", file=sys.stderr)
        return 2

    entries: list[tuple[Path, str]] = []
    for path in videos:
        stem = path.stem
        prefix = stem_prefix_before_first_underscore(stem)
        if not prefix.strip():
            print(f"跳过（无可译前缀）：{path.name}")
            continue
        entries.append((path, prefix))

    if not entries:
        return 0

    unique_prefixes = list(dict.fromkeys(p for _, p in entries))
    batch_size = max(1, int(config.TRANSLATE_BATCH_SIZE))
    n_batches = (len(unique_prefixes) + batch_size - 1) // batch_size
    print(
        f"共 {len(videos)} 个视频，{len(unique_prefixes)} 个不同前缀；"
        f"分 {n_batches} 批请求（每批至多 {batch_size} 条），"
        f"至多 {config.TRANSLATE_CONCURRENCY} 批并发（可在 config 中调整 translate_batch_size / translate_concurrency）。"
    )

    prefix_to_zh = translate_unique_prefixes(unique_prefixes)

    for path, prefix in entries:
        ext = path.suffix
        raw_zh = prefix_to_zh.get(prefix, prefix)
        zh = sanitize_name(raw_zh)
        if not zh:
            print(f"跳过（译名为空）：{path.name}")
            continue

        new_name = zh + ext.lower() if ext else zh
        desired = path.with_name(new_name)
        new_path = unique_target_path(desired, source=path)

        if new_path.resolve() == path.resolve():
            print(f"跳过（已是目标名）：{path.name}")
            continue

        print(f"{'RENAME' if args.apply else 'DRY-RUN'} {path.name}")
        print(f"         -> {new_path.name}")

        if args.apply:
            os.rename(path, new_path)

    if not args.apply:
        print("\n以上为预览。确认无误后追加 --apply 执行重命名。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
