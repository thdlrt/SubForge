"""
SubForge — Gradio Web UI
启动方式:
  python app.py              # 默认浏览器打开
  python app.py --window     # 独立桌面窗口（pywebview 套壳浏览器）
"""

import argparse
import atexit
import inspect
import os
from pathlib import Path
import queue
import shutil
import sys
import threading
import time

# 强制 UTF-8（必须在 import auto_subtitle 之前）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import gradio as gr

# 将项目根目录加入 path，确保能 import auto_subtitle
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

import auto_subtitle
import config
import settings_ui
from additionpackage import gamedevtv_downloader, move_files_by_suffix, translate_video_names_zh
from cosyvoice_manager import shutdown_cosyvoice_service
from portutil import pick_free_tcp_port

# 设置页 JSON 文本框等宽样式（Gradio 6+ 需传给 launch(css=...)；旧版仍放在 Blocks 上）
_UI_CSS = """
.aitext-json-sync textarea, .aitext-json-sync input {
    font-family: Consolas, "Cascadia Mono", "Sarasa Mono SC", ui-monospace, monospace !important;
    font-size: 12px !important;
}
"""
_LAUNCH_ACCEPTS_CSS = "css" in inspect.signature(gr.Blocks.launch).parameters


def _parse_launch_args():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument(
        "-w",
        "--window",
        action="store_true",
        help="在独立桌面窗口中打开界面（依赖 pywebview，内嵌 WebView2/CEF）",
    )
    p.add_argument("--host", default="127.0.0.1", help="Gradio 监听地址")
    p.add_argument("--port", type=int, default=7860, help="Gradio 端口")
    args, _unknown = p.parse_known_args()
    return args


def _ensure_localhost_no_proxy() -> None:
    """Gradio launch 会用 httpx 访问 127.0.0.1；若系统代理未排除本机，常出现 startup-events 502。"""
    extra = ("127.0.0.1", "localhost", "::1")
    for key in ("NO_PROXY", "no_proxy"):
        cur = os.environ.get(key, "")
        parts = [p.strip() for p in cur.split(",") if p.strip()]
        for e in extra:
            if e not in parts:
                parts.append(e)
        os.environ[key] = ",".join(parts)


atexit.register(shutdown_cosyvoice_service)


# ======================== 日志捕获 ========================

class _TeeStream:
    """将 Python stdout/stderr 输出同时写入原始流和队列"""

    def __init__(self, original, log_queue):
        self.original = original
        self.queue = log_queue
        self.encoding = getattr(original, "encoding", "utf-8")

    def write(self, msg):
        self.original.write(msg)
        if msg.strip() and "[TTS进度]" not in msg:
            self.queue.put(msg.rstrip("\n"))

    def flush(self):
        self.original.flush()

    def reconfigure(self, **kwargs):
        if hasattr(self.original, "reconfigure"):
            self.original.reconfigure(**kwargs)
        if "encoding" in kwargs:
            self.encoding = kwargs["encoding"]


# 全局锁：同一时间只允许一个处理任务
_processing_lock = threading.Lock()
_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".ts"}
_AUDIO_EXTS = {".aac", ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".wma"}
_GRADIO_TEMP_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Temp" / "gradio"


def clear_gradio_temp_handler():
    """手动清理 Windows 下的 Gradio 临时目录内容。"""
    temp_dir = _GRADIO_TEMP_DIR

    if not temp_dir.exists():
        return f"ℹ 未找到目录，无需清理：{temp_dir}"
    if not temp_dir.is_dir():
        return f"⚠ 目标路径不是目录，已取消清理：{temp_dir}"

    removed_files = 0
    removed_dirs = 0
    failed_items: list[str] = []

    for child in list(temp_dir.iterdir()):
        try:
            if child.is_symlink() or child.is_file():
                child.unlink()
                removed_files += 1
            elif child.is_dir():
                shutil.rmtree(child)
                removed_dirs += 1
            else:
                child.unlink(missing_ok=True)
                removed_files += 1
        except FileNotFoundError:
            continue
        except Exception as exc:
            failed_items.append(f"- {child.name}: {exc}")

    summary = (
        f"✅ 清理完成：删除 {removed_files} 个文件、{removed_dirs} 个目录。"
        f"\n目标目录：{temp_dir}"
    )
    if failed_items:
        details = "\n".join(failed_items[:5])
        more = "" if len(failed_items) <= 5 else f"\n... 另有 {len(failed_items) - 5} 项删除失败"
        summary += f"\n⚠ {len(failed_items)} 项删除失败，常见原因是文件仍被占用：\n{details}{more}"
    return summary


def _run_logged_tool(task_func):
    """Generator: 运行工具箱任务，复用全局锁并流式返回日志。"""
    log_q = queue.Queue()
    done = threading.Event()

    def worker():
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = _TeeStream(old_stdout, log_q)
        sys.stderr = _TeeStream(old_stderr, log_q)
        try:
            task_func()
        except Exception:
            import traceback
            print(f"\n❌ 工具执行失败：\n{traceback.format_exc()}")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            done.set()

    if not _processing_lock.acquire(blocking=False):
        yield "⚠ 已有任务正在处理中，请等待完成后再试。"
        return

    try:
        t = threading.Thread(target=worker, daemon=True)
        t.start()

        log_text = ""
        while not done.is_set() or not log_q.empty():
            try:
                msg = log_q.get(timeout=0.3)
                log_text += msg + "\n"
                yield log_text
            except queue.Empty:
                pass

        while not log_q.empty():
            log_text += log_q.get_nowait() + "\n"
        yield log_text or "✅ 工具执行完成。"
    finally:
        _processing_lock.release()


def _move_files_by_suffix_impl(source_dir, dest_dir, suffix, apply, overwrite):
    suffix = (suffix or "").strip()
    if not suffix:
        raise ValueError("后缀不能为空")
    root = Path(str(source_dir or "").strip()).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"源目录不存在或不是目录：{root}")
    target_dir = Path(str(dest_dir or "").strip()).resolve()
    matches = move_files_by_suffix.iter_matches(root, suffix)
    if not matches:
        print(f"未找到 stem 以 {suffix!r} 结尾的文件：{root}")
        return

    print(f"共 {len(matches)} 个文件匹配后缀 {suffix!r}")
    for src in matches:
        target = target_dir / src.name
        rel = src.relative_to(root)
        if target.resolve() == src.resolve():
            print(f"跳过（已在目标）：{src}")
            continue
        if target.exists() and not overwrite:
            print(f"跳过（目标已存在，勾选覆盖可替换）：{src} -> {target}")
            continue
        if apply:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
            print(f"MOVED {rel} -> {target}")
        else:
            print(f"DRY-RUN {rel} -> {target}")

    if not apply:
        print("\n以上为预览。确认无误后点击执行移动。")


def move_suffix_preview_handler(source_dir, dest_dir, suffix, overwrite):
    yield from _run_logged_tool(
        lambda: _move_files_by_suffix_impl(source_dir, dest_dir, suffix, False, overwrite)
    )


def move_suffix_apply_handler(source_dir, dest_dir, suffix, overwrite):
    yield from _run_logged_tool(
        lambda: _move_files_by_suffix_impl(source_dir, dest_dir, suffix, True, overwrite)
    )


def _translate_video_names_impl(directory, recursive, apply):
    root = Path(str(directory or "").strip()).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"不是目录：{root}")
    if not (config.QWEN_TRANSLATE_API_KEY or "").strip():
        raise RuntimeError("未配置 qwen_translate_api_key，无法批量译名")

    videos = translate_video_names_zh.collect_videos(root, bool(recursive))
    if not videos:
        print(f"未找到视频文件（扩展名 {sorted(translate_video_names_zh.VIDEO_EXTS)}）：{root}")
        return

    entries = []
    for path in videos:
        prefix = translate_video_names_zh.stem_prefix_before_first_underscore(path.stem)
        if not prefix.strip():
            print(f"跳过（无可译前缀）：{path.name}")
            continue
        entries.append((path, prefix))
    if not entries:
        print("未找到可翻译的视频文件名前缀。")
        return

    unique_prefixes = list(dict.fromkeys(prefix for _, prefix in entries))
    batch_size = max(1, int(config.TRANSLATE_BATCH_SIZE))
    n_batches = (len(unique_prefixes) + batch_size - 1) // batch_size
    print(
        f"共 {len(videos)} 个视频，{len(unique_prefixes)} 个不同前缀；"
        f"分 {n_batches} 批请求，至多 {config.TRANSLATE_CONCURRENCY} 批并发。"
    )

    prefix_to_zh = translate_video_names_zh.translate_unique_prefixes(unique_prefixes)
    changed = 0
    for path, prefix in entries:
        raw_zh = prefix_to_zh.get(prefix, prefix)
        zh = translate_video_names_zh.sanitize_name(raw_zh)
        if not zh:
            print(f"跳过（译名为空）：{path.name}")
            continue
        new_path = translate_video_names_zh.unique_target_path(
            path.with_name(zh + path.suffix.lower()),
            source=path,
        )
        if new_path.resolve() == path.resolve():
            print(f"跳过（已是目标名）：{path.name}")
            continue

        print(f"{'RENAME' if apply else 'DRY-RUN'} {path.name}")
        print(f"         -> {new_path.name}")
        changed += 1
        if apply:
            os.rename(path, new_path)

    if not apply:
        print("\n以上为预览。确认无误后点击执行重命名。")
    print(f"共 {'重命名' if apply else '计划重命名'} {changed} 个文件。")


def translate_names_preview_handler(directory, recursive):
    yield from _run_logged_tool(lambda: _translate_video_names_impl(directory, recursive, False))


def translate_names_apply_handler(directory, recursive):
    yield from _run_logged_tool(lambda: _translate_video_names_impl(directory, recursive, True))


def _gamedev_tool_impl(course_url, cookie_path, output_dir, list_only, limit, force):
    url = str(course_url or "").strip()
    if not url:
        raise ValueError("课程链接不能为空")
    cookie = Path(str(cookie_path or gamedevtv_downloader.DEFAULT_COOKIE_PATH).strip()).resolve()
    out_dir = Path(str(output_dir or gamedevtv_downloader.DEFAULT_INPUT_DIR).strip()).resolve()
    limit = max(0, int(float(limit or 0)))

    downloader = gamedevtv_downloader.GameDevDownloader(cookie, out_dir)
    course_slug = gamedevtv_downloader.extract_course_slug(url)
    course_id = downloader.resolve_course_id(url)
    course = downloader.fetch_course(course_id)
    course_title = course.get("title") or f"Course {course_id}"
    lectures = list(downloader.iter_lectures(course))
    if not lectures:
        raise RuntimeError("未从课程 API 中解析到任何带视频的课时。")

    print(f"课程: {course_title}")
    print(f"course_id: {course_id}")
    print(f"课时数: {len(lectures)}")

    if list_only:
        for lec in lectures:
            print(
                f"[{lec.section_index}.{lec.lecture_index}] "
                f"{lec.section_title} / {lec.lecture_title} -> {lec.relative_url}"
            )
        return

    selected = lectures[:limit] if limit > 0 else lectures
    for idx, lecture in enumerate(selected, 1):
        out_path = downloader.build_output_path(course_title, lecture)
        print(f"\n[{idx}/{len(selected)}] {lecture.section_title} / {lecture.lecture_title}")
        if course_slug:
            print(f"  页面: https://gamedev.tv/courses/{course_slug}/{lecture.relative_url}")
        print(f"  输出: {out_path}")
        if out_path.exists() and downloader.is_good_mp4(out_path) and not force:
            meta = downloader.ffprobe_summary(out_path)
            print(
                f"  SKIP 已存在 "
                f"(时长 {meta['duration']:.1f}s, 大小 {meta['size'] / 1024 / 1024:.1f} MB)"
            )
            continue
        downloader.download_hls(lecture, out_path)
        meta = downloader.ffprobe_summary(out_path)
        print(f"  DONE 完成 (时长 {meta['duration']:.1f}s, 大小 {meta['size'] / 1024 / 1024:.1f} MB)")


def gamedev_list_handler(course_url, cookie_path, output_dir):
    yield from _run_logged_tool(
        lambda: _gamedev_tool_impl(course_url, cookie_path, output_dir, True, 0, False)
    )


def gamedev_download_handler(course_url, cookie_path, output_dir, limit, force):
    yield from _run_logged_tool(
        lambda: _gamedev_tool_impl(course_url, cookie_path, output_dir, False, limit, force)
    )


def process_all_input_handler(
    burn_subtitle,
    enable_dubbing,
    enable_enhance,
    enable_ai_analysis,
    ai_analysis_mode,
    translate_video_name,
):
    """一键处理 input 下所有本地视频。"""
    input_root = Path("./input").resolve()
    if not input_root.exists():
        yield f"⚠ input 目录不存在: {input_root}", []
        return
    sources = sorted(
        str(p) for p in input_root.rglob("*")
        if p.is_file() and p.suffix.lower() in _VIDEO_EXTS
    )
    if not sources:
        yield "ℹ input 下未找到可处理的视频文件。", []
        return
    yield from _run_processing(
        sources,
        burn_subtitle,
        enable_dubbing,
        enable_enhance,
        enable_ai_analysis,
        ai_analysis_mode,
        translate_video_name,
    )


# ======================== 处理逻辑 ========================

def _run_processing(
    sources,
    burn_subtitle,
    enable_dubbing,
    enable_enhance,
    enable_ai_analysis,
    ai_analysis_mode,
    translate_video_name,
    enable_speaker_diarization=False,
):
    """Generator: 在后台线程处理视频，实时流式输出日志"""
    log_q = queue.Queue()
    done = threading.Event()
    result_files = []

    def worker():
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = _TeeStream(old_stdout, log_q)
        sys.stderr = _TeeStream(old_stderr, log_q)
        try:
            total = len(sources)
            all_results = []

            if total == 1:
                # 单任务：直接走原流程，无需两阶段
                result = auto_subtitle.process_one(
                    sources[0], burn_subtitle=burn_subtitle,
                    enable_dubbing=enable_dubbing,
                    enable_enhance=enable_enhance,
                    enable_ai_analysis=enable_ai_analysis,
                    ai_analysis_mode=ai_analysis_mode,
                    translate_video_name=translate_video_name,
                    enable_speaker_diarization=enable_speaker_diarization,
                )
                all_results.append(result)
                if result:
                    for key in ("en_srt", "zh_srt", "bi_srt", "summary_md", "final_video", "dubbed_video"):
                        path = result.get(key)
                        if path and os.path.exists(path):
                            result_files.append(path)
            else:
                # 多任务：两阶段策略——先全部下载，再全部处理
                print(f"📋 批量模式：共 {total} 个任务，使用两阶段策略")

                # ── 第一阶段：批量下载 ─────────────────────────────────────
                print(f"\n{'=' * 60}")
                print(f"🌐 第一阶段：批量下载全部视频（共 {total} 个）")
                print("=" * 60)
                prepared_list = []
                for i, src in enumerate(sources, 1):
                    print(f"\n── 下载 [{i}/{total}]: {src}")
                    prepared_list.append(
                        auto_subtitle._prepare_source(
                            src, translate_video_name=translate_video_name
                        )
                    )

                dl_ok   = sum(1 for p in prepared_list if p.get("status") != "失败")
                dl_fail = total - dl_ok
                print(f"\n✅ 下载阶段完成：{dl_ok} 成功 / {dl_fail} 失败 / {total} 总计")

                # ── 第二阶段：批量处理 ─────────────────────────────────────
                print(f"\n{'=' * 60}")
                print("⚙️  第二阶段：批量处理（识别 → AI分析(可选) → 翻译 → 压制字幕）")
                print("=" * 60)
                for i, prepared in enumerate(prepared_list, 1):
                    print(f"\n{'#' * 60}")
                    print(f"## 任务 [{i}/{total}]: {prepared['source']}")
                    print("#" * 60)
                    result = auto_subtitle._process_prepared(
                        prepared, burn_subtitle=burn_subtitle,
                        enable_dubbing=enable_dubbing,
                        enable_enhance=enable_enhance,
                        enable_ai_analysis=enable_ai_analysis,
                        ai_analysis_mode=ai_analysis_mode,
                        enable_speaker_diarization=enable_speaker_diarization,
                    )
                    all_results.append(result)
                    if result:
                        for key in ("en_srt", "zh_srt", "bi_srt", "summary_md", "final_video", "dubbed_video"):
                            path = result.get(key)
                            if path and os.path.exists(path):
                                result_files.append(path)

            auto_subtitle._print_summary(all_results)
        except Exception:
            import traceback
            print(f"\n\u274c 处理时发生错误：\n{traceback.format_exc()}")
        finally:
            if config.TTS_PROVIDER == "cosyvoice":
                shutdown_cosyvoice_service()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            done.set()

    if not _processing_lock.acquire(blocking=False):
        yield "⚠ 已有任务正在处理中，请等待完成后再试。", []
        return

    try:
        t = threading.Thread(target=worker, daemon=True)
        t.start()

        log_text = ""
        while not done.is_set() or not log_q.empty():
            try:
                msg = log_q.get(timeout=0.3)
                log_text += msg + "\n"
                yield log_text, list(result_files)
            except queue.Empty:
                pass

        # 排空队列
        while not log_q.empty():
            log_text += log_q.get_nowait() + "\n"

        yield log_text, list(result_files)
    finally:
        _processing_lock.release()


def process_video_handler(
    urls_text,
    uploaded_files,
    burn_subtitle,
    enable_dubbing,
    enable_enhance,
    enable_ai_analysis,
    ai_analysis_mode,
    translate_video_name,
):
    """Gradio 视频入口：解析输入，启动处理"""
    sources = []

    # 解析 YouTube 链接（每行一个）
    if urls_text and urls_text.strip():
        for line in urls_text.strip().splitlines():
            line = line.strip()
            if line:
                sources.append(line)

    # 解析上传的本地视频
    if uploaded_files:
        for f in uploaded_files:
            path = f if isinstance(f, str) else getattr(f, "name", str(f))
            sources.append(path)

    if not sources:
        yield "⚠ 请输入至少一个 YouTube 链接或上传本地视频文件。", []
        return

    yield from _run_processing(
        sources,
        burn_subtitle,
        enable_dubbing,
        enable_enhance,
        enable_ai_analysis,
        ai_analysis_mode,
        translate_video_name,
    )


def process_audio_handler(uploaded_files, enable_speaker_diarization, enable_ai_analysis, ai_analysis_mode):
    """Gradio 音频入口：处理本地音频，生成字幕和可选 AI 分析。"""
    sources = []

    if enable_speaker_diarization and not (config.SPEAKER_DIARIZATION_HF_TOKEN or "").strip():
        yield "⚠ 已开启说话人区分，但尚未在设置页配置 Hugging Face Token。", []
        return

    if uploaded_files:
        for f in uploaded_files:
            path = f if isinstance(f, str) else getattr(f, "name", str(f))
            if Path(path).suffix.lower() in _AUDIO_EXTS:
                sources.append(path)

    if not sources:
        yield "⚠ 请至少上传一个音频文件。", []
        return

    yield from _run_processing(
        sources,
        False,
        False,
        False,
        enable_ai_analysis,
        ai_analysis_mode,
        False,
        enable_speaker_diarization=enable_speaker_diarization,
    )


# ======================== 构建 UI ========================

def build_ui():
    # 检查 API Key 配置
    api_warning = ""
    if not config.QWEN_TRANSLATE_API_KEY or not config.QWEN_SUMMARY_API_KEY:
        api_warning = (
            "\n> ⚠️ **API Key 未完整配置**：翻译使用 `qwen_translate_*`，AI 分析使用 `qwen_summary_*`。"
        )

    blocks_kw: dict = {"title": "SubForge — AI 字幕生成"}
    if not _LAUNCH_ACCEPTS_CSS:
        blocks_kw["css"] = _UI_CSS
    with gr.Blocks(**blocks_kw) as app:
        gr.Markdown(
            "# 🎬 SubForge — AI 字幕一键生成工具\n"
            "视频模式：识别 + AI 分析 + 翻译；音频模式：转写，可选区分说话人与 AI 分析"
            + api_warning
        )

        with gr.Tabs():
            with gr.Tab("视频"):
                with gr.Row():
                    # ---- 左栏：输入 ----
                    with gr.Column(scale=1):
                        urls_input = gr.Textbox(
                            label="YouTube 链接（每行一个）",
                            placeholder="https://www.youtube.com/watch?v=XXXXX\nhttps://youtu.be/YYYYY",
                            lines=4,
                        )
                        file_input = gr.File(
                            label="或上传本地视频",
                            file_count="multiple",
                            file_types=[".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".ts"],
                        )

                        with gr.Accordion("⚙️ 处理选项", open=False):
                            burn_sub = gr.Checkbox(label="压制硬字幕到视频", value=True)
                            dub_check = gr.Checkbox(
                                label="AI 中文配音（分离背景音 + 可切换 TTS 引擎）",
                                value=True,
                            )
                            enhance_check = gr.Checkbox(
                                label="AI 画质增强（仅 NVIDIA GPU，Real-ESRGAN 超分辨率）",
                                value=False,
                            )
                            ai_analysis_check = gr.Checkbox(
                                label="AI 分析并生成 Markdown（基于转写 SRT）",
                                value=bool(config.AI_ANALYSIS_ENABLED),
                            )
                            ai_analysis_mode = gr.Dropdown(
                                label="AI 分析模式",
                                choices=["通用", "课程", "会议记录", "面试记录"],
                                value=config.AI_ANALYSIS_MODE,
                            )
                            translate_name_check = gr.Checkbox(
                                label="自动将视频名称翻译为中文（下载和本地视频都生效，使用翻译 API）",
                                value=False,
                            )
                            config_hint_md = gr.Markdown(value=settings_ui.config_summary_markdown())

                        process_btn = gr.Button("🚀 开始处理", variant="primary", size="lg")
                        process_input_btn = gr.Button(
                            "🚀 一键处理 input 全部视频",
                            variant="secondary",
                            size="lg",
                        )
                        cleanup_temp_btn = gr.Button(
                            "🧹 清理 Gradio 临时目录",
                            variant="secondary",
                        )
                        cleanup_status = gr.Textbox(
                            label="🛠 维护结果",
                            lines=4,
                            interactive=False,
                            value=f"目标目录：{_GRADIO_TEMP_DIR}",
                        )

                    # ---- 右栏：输出 ----
                    with gr.Column(scale=1):
                        log_output = gr.Textbox(
                            label="📋 处理日志",
                            lines=22,
                            max_lines=50,
                            interactive=False,
                        )
                        file_output = gr.File(
                            label="📦 输出文件（点击下载）",
                            file_count="multiple",
                            interactive=False,
                        )

                process_btn.click(
                    fn=process_video_handler,
                    inputs=[
                        urls_input,
                        file_input,
                        burn_sub,
                        dub_check,
                        enhance_check,
                        ai_analysis_check,
                        ai_analysis_mode,
                        translate_name_check,
                    ],
                    outputs=[log_output, file_output],
                )
                process_input_btn.click(
                    fn=process_all_input_handler,
                    inputs=[
                        burn_sub,
                        dub_check,
                        enhance_check,
                        ai_analysis_check,
                        ai_analysis_mode,
                        translate_name_check,
                    ],
                    outputs=[log_output, file_output],
                )
                cleanup_temp_btn.click(
                    fn=clear_gradio_temp_handler,
                    inputs=[],
                    outputs=[cleanup_status],
                )

            with gr.Tab("音频"):
                with gr.Row():
                    with gr.Column(scale=1):
                        audio_input = gr.File(
                            label="上传本地音频",
                            file_count="multiple",
                            file_types=sorted(_AUDIO_EXTS),
                        )
                        gr.Markdown(
                            "音频模式会输出识别字幕，可选说话人区分与 AI 分析；"
                            "不会执行翻译、压制硬字幕、AI 配音、画质增强。"
                        )
                        audio_speaker_check = gr.Checkbox(
                            label="字幕中区分说话人（需在设置中配置 Hugging Face Token）",
                            value=False,
                        )
                        audio_ai_analysis_check = gr.Checkbox(
                            label="AI 分析并生成 Markdown",
                            value=bool(config.AI_ANALYSIS_ENABLED),
                        )
                        audio_ai_analysis_mode = gr.Dropdown(
                            label="AI 分析模式",
                            choices=["通用", "课程", "会议记录", "面试记录"],
                            value=config.AI_ANALYSIS_MODE,
                        )
                        audio_process_btn = gr.Button("🚀 开始处理音频", variant="primary", size="lg")

                    with gr.Column(scale=1):
                        audio_log_output = gr.Textbox(
                            label="📋 音频处理日志",
                            lines=22,
                            max_lines=50,
                            interactive=False,
                        )
                        audio_file_output = gr.File(
                            label="📦 音频字幕输出（点击下载）",
                            file_count="multiple",
                            interactive=False,
                        )

                audio_process_btn.click(
                    fn=process_audio_handler,
                    inputs=[audio_input, audio_speaker_check, audio_ai_analysis_check, audio_ai_analysis_mode],
                    outputs=[audio_log_output, audio_file_output],
                )

            with gr.Tab("工具箱"):
                with gr.Accordion("按后缀移动文件", open=True):
                    with gr.Row():
                        with gr.Column(scale=1):
                            move_source = gr.Textbox(label="源目录", value=str(Path("./output").resolve()))
                            move_dest = gr.Textbox(label="目标目录", value=str(Path("./output/temp").resolve()))
                            move_suffix = gr.Textbox(label="匹配后缀", value="_配音")
                            move_overwrite = gr.Checkbox(label="目标已存在时覆盖", value=False)
                            with gr.Row():
                                move_preview_btn = gr.Button("预览移动", variant="secondary")
                                move_apply_btn = gr.Button("执行移动", variant="primary")
                        with gr.Column(scale=1):
                            move_log = gr.Textbox(label="移动结果", lines=14, max_lines=40, interactive=False)

                    move_preview_btn.click(
                        fn=move_suffix_preview_handler,
                        inputs=[move_source, move_dest, move_suffix, move_overwrite],
                        outputs=[move_log],
                    )
                    move_apply_btn.click(
                        fn=move_suffix_apply_handler,
                        inputs=[move_source, move_dest, move_suffix, move_overwrite],
                        outputs=[move_log],
                    )

                with gr.Accordion("批量翻译视频文件名", open=True):
                    with gr.Row():
                        with gr.Column(scale=1):
                            name_dir = gr.Textbox(label="视频目录", value=str(Path("./output").resolve()))
                            name_recursive = gr.Checkbox(label="递归扫描子目录", value=True)
                            with gr.Row():
                                name_preview_btn = gr.Button("预览译名", variant="secondary")
                                name_apply_btn = gr.Button("执行重命名", variant="primary")
                        with gr.Column(scale=1):
                            name_log = gr.Textbox(label="译名结果", lines=14, max_lines=40, interactive=False)

                    name_preview_btn.click(
                        fn=translate_names_preview_handler,
                        inputs=[name_dir, name_recursive],
                        outputs=[name_log],
                    )
                    name_apply_btn.click(
                        fn=translate_names_apply_handler,
                        inputs=[name_dir, name_recursive],
                        outputs=[name_log],
                    )

                with gr.Accordion("GameDev.tv 课程下载", open=False):
                    with gr.Row():
                        with gr.Column(scale=1):
                            gamedev_url = gr.Textbox(label="课程或课时链接", placeholder="https://gamedev.tv/courses/...", lines=2)
                            gamedev_cookie = gr.Textbox(label="Cookies 文件", value=str(Path("./cookies/gamedev.txt").resolve()))
                            gamedev_output = gr.Textbox(label="输出根目录", value=str(Path("./input").resolve()))
                            gamedev_limit = gr.Number(label="下载前 N 节（0=全部）", value=0, precision=0)
                            gamedev_force = gr.Checkbox(label="已存在也重新下载", value=False)
                            with gr.Row():
                                gamedev_list_btn = gr.Button("列出课程", variant="secondary")
                                gamedev_download_btn = gr.Button("开始下载", variant="primary")
                        with gr.Column(scale=1):
                            gamedev_log = gr.Textbox(label="下载日志", lines=18, max_lines=80, interactive=False)

                    gamedev_list_btn.click(
                        fn=gamedev_list_handler,
                        inputs=[gamedev_url, gamedev_cookie, gamedev_output],
                        outputs=[gamedev_log],
                    )
                    gamedev_download_btn.click(
                        fn=gamedev_download_handler,
                        inputs=[gamedev_url, gamedev_cookie, gamedev_output, gamedev_limit, gamedev_force],
                        outputs=[gamedev_log],
                    )

            with gr.Tab("设置"):
                settings_ui.build_settings_tab(config_hint_md)

    return app


# ======================== 启动 ========================

if __name__ == "__main__":
    _ensure_localhost_no_proxy()
    launch_args = _parse_launch_args()
    app = build_ui()
    host = launch_args.host
    port = launch_args.port
    use_window = launch_args.window

    if use_window:
        try:
            import webview
        except ImportError:
            print("未安装 pywebview，无法使用 --window。请执行: pip install pywebview")
            sys.exit(1)

    try:
        server_port = pick_free_tcp_port(host, port)
    except RuntimeError as e:
        print(e)
        sys.exit(1)
    if server_port != port:
        print(f"⚠ 端口 {port} 已被占用，已改用 {server_port}（另一实例可能仍在运行）")

    launch_kw = dict(
        server_name=host,
        server_port=server_port,
        theme=gr.themes.Soft(),
        share=False,
        inbrowser=not use_window,
        prevent_thread_lock=use_window,
    )
    if _LAUNCH_ACCEPTS_CSS:
        launch_kw["css"] = _UI_CSS

    app.launch(**launch_kw)

    actual_port = int(getattr(app, "server_port", None) or server_port)

    if use_window:
        # 等服务线程就绪后再打开窗口，避免白屏
        time.sleep(0.8)
        connect_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
        url = f"http://{connect_host}:{actual_port}"
        webview.create_window(
            "SubForge — AI 字幕生成",
            url,
            width=1280,
            height=860,
            min_size=(900, 640),
        )
        webview.start()
