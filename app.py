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
import queue
import socket
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
from cosyvoice_manager import shutdown_cosyvoice_service

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


def _pick_server_port(host: str, preferred: int, span: int = 40) -> int:
    """若 preferred 被占用，在 [preferred, preferred+span) 内找第一个可用 TCP 端口。"""
    probe_host = host
    if host in ("0.0.0.0", "", "::"):
        probe_host = "127.0.0.1"
    for p in range(preferred, preferred + span):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((probe_host, p))
        except OSError:
            continue
        return p
    raise RuntimeError(
        f"在 {preferred}–{preferred + span - 1} 范围内没有可用端口，请关闭占用进程或指定 --port"
    )

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


# ======================== 处理逻辑 ========================

def _run_processing(sources, burn_subtitle, enable_dubbing, enable_enhance, enable_summary):
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
                    enable_summary=enable_summary,
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
                    prepared_list.append(auto_subtitle._prepare_source(src))

                dl_ok   = sum(1 for p in prepared_list if p.get("status") != "失败")
                dl_fail = total - dl_ok
                print(f"\n✅ 下载阶段完成：{dl_ok} 成功 / {dl_fail} 失败 / {total} 总计")

                # ── 第二阶段：批量处理 ─────────────────────────────────────
                print(f"\n{'=' * 60}")
                print("⚙️  第二阶段：批量处理（识别 → 总结(可选) → 翻译 → 压制字幕）")
                print("=" * 60)
                for i, prepared in enumerate(prepared_list, 1):
                    print(f"\n{'#' * 60}")
                    print(f"## 任务 [{i}/{total}]: {prepared['source']}")
                    print("#" * 60)
                    result = auto_subtitle._process_prepared(
                        prepared, burn_subtitle=burn_subtitle,
                        enable_dubbing=enable_dubbing,
                        enable_enhance=enable_enhance,
                        enable_summary=enable_summary,
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


def process_handler(urls_text, uploaded_files, burn_subtitle, enable_dubbing,
                    enable_enhance, enable_summary):
    """Gradio 入口：解析输入，启动处理"""
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

    yield from _run_processing(sources, burn_subtitle, enable_dubbing, enable_enhance, enable_summary)


# ======================== 构建 UI ========================

def build_ui():
    # 检查 API Key 配置
    api_warning = ""
    if not config.QWEN_API_KEY:
        api_warning = (
            "\n> ⚠️ **API Key 未配置**：请先复制 `config.example.json` → `config.json` 并填写 API Key，否则 AI 总结/翻译步骤会失败。"
        )

    blocks_kw: dict = {"title": "SubForge — AI 字幕生成"}
    if not _LAUNCH_ACCEPTS_CSS:
        blocks_kw["css"] = _UI_CSS
    with gr.Blocks(**blocks_kw) as app:
        gr.Markdown(
            "# 🎬 SubForge — AI 字幕一键生成工具\n"
            "YouTube / 本地视频 → 语音识别 → AI 总结(可选) → AI 翻译 → 双语字幕压制"
            + api_warning
        )

        with gr.Tabs():
            with gr.Tab("处理"):
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
                            summary_check = gr.Checkbox(
                                label="AI 内容概括总结（基于英文 SRT 生成中文 Markdown）",
                                value=False,
                            )
                            config_hint_md = gr.Markdown(value=settings_ui.config_summary_markdown())

                        process_btn = gr.Button("🚀 开始处理", variant="primary", size="lg")

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
                    fn=process_handler,
                    inputs=[urls_input, file_input, burn_sub, dub_check, enhance_check, summary_check],
                    outputs=[log_output, file_output],
                )

            with gr.Tab("设置"):
                settings_ui.build_settings_tab(config_hint_md)

    return app


# ======================== 启动 ========================

if __name__ == "__main__":
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
        server_port = _pick_server_port(host, port)
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
