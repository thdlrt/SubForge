"""
SubForge — Gradio Web UI
启动方式: python app.py
"""

import sys
import os
import queue
import threading

# 强制 UTF-8（必须在 import auto_subtitle 之前）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import gradio as gr

# 将项目根目录加入 path，确保能 import auto_subtitle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auto_subtitle


# ======================== 日志捕获 ========================

class _TeeStream:
    """将 Python stdout/stderr 输出同时写入原始流和队列"""

    def __init__(self, original, log_queue):
        self.original = original
        self.queue = log_queue
        self.encoding = getattr(original, "encoding", "utf-8")

    def write(self, msg):
        self.original.write(msg)
        if msg.strip():
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

def _run_processing(sources, burn_subtitle, enable_dubbing, enable_enhance):
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
                    enable_dubbing=enable_dubbing, enable_enhance=enable_enhance
                )
                all_results.append(result)
                if result:
                    for key in ("en_srt", "zh_srt", "bi_srt", "final_video", "dubbed_video"):
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
                print("⚙️  第二阶段：批量处理（识别 → 翻译 → 压制字幕）")
                print("=" * 60)
                for i, prepared in enumerate(prepared_list, 1):
                    print(f"\n{'#' * 60}")
                    print(f"## 任务 [{i}/{total}]: {prepared['source']}")
                    print("#" * 60)
                    result = auto_subtitle._process_prepared(
                        prepared, burn_subtitle=burn_subtitle,
                        enable_dubbing=enable_dubbing, enable_enhance=enable_enhance
                    )
                    all_results.append(result)
                    if result:
                        for key in ("en_srt", "zh_srt", "bi_srt", "final_video", "dubbed_video"):
                            path = result.get(key)
                            if path and os.path.exists(path):
                                result_files.append(path)

            auto_subtitle._print_summary(all_results)
        finally:
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


def process_handler(urls_text, uploaded_files, burn_subtitle, enable_dubbing, enable_enhance):
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

    yield from _run_processing(sources, burn_subtitle, enable_dubbing, enable_enhance)


# ======================== 构建 UI ========================

def build_ui():
    # 检查 API Key 配置
    api_warning = ""
    if not auto_subtitle.QWEN_API_KEY:
        api_warning = (
            "\n> ⚠️ **API Key 未配置**：请先复制 `config.example.json` → `config.json` 并填写 API Key，否则翻译步骤会失败。"
        )

    with gr.Blocks(
        title="SubForge — AI 字幕生成",
    ) as app:
        gr.Markdown(
            "# 🎬 SubForge — AI 字幕一键生成工具\n"
            "YouTube / 本地视频 → 语音识别 → AI 翻译 → 双语字幕压制"
            + api_warning
        )

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
                        label="AI 中文配音（分离背景音 + edge-tts 语音合成）",
                        value=True,
                    )
                    enhance_check = gr.Checkbox(
                        label="AI 画质增强（Real-ESRGAN 超分辨率，耗时较长）",
                        value=False,
                    )
                    gr.Markdown(
                        f"**当前配置** *(来自 config.json)*\n\n"
                        f"- 语音模型: `{auto_subtitle.WHISPER_MODEL}` · "
                        f"语言: `{auto_subtitle.VIDEO_LANGUAGE}`\n"
                        f"- 翻译模型: `{auto_subtitle.QWEN_MODEL}` · "
                        f"并发: `{auto_subtitle.TRANSLATE_CONCURRENCY}`\n"
                        f"- 断句间隙: `{auto_subtitle.SUBTITLE_MAX_GAP_MS}` ms · "
                        f"字体: `{auto_subtitle.SUBTITLE_FONT}` {auto_subtitle.FONT_SIZE}px\n\n"
                        f"*如需修改，请编辑项目根目录的 `config.json` 后重启*"
                    )

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

        # 绑定事件
        process_btn.click(
            fn=process_handler,
            inputs=[urls_input, file_input, burn_sub, dub_check, enhance_check],
            outputs=[log_output, file_output],
        )

    return app


# ======================== 启动 ========================

if __name__ == "__main__":
    app = build_ui()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        theme=gr.themes.Soft(),
        share=False,
        inbrowser=True,
    )
