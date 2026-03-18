"""
SubForge Gradio Web UI.

运行方式: python app.py
"""

import os
import queue
import sys
import threading

from runtime import ensure_app_cwd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ensure_app_cwd()


def _dispatch_worker_mode() -> bool:
    if len(sys.argv) < 2:
        return False

    mode = sys.argv[1]
    if mode == "--worker-whisper":
        from _run_whisper import main as whisper_main

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        whisper_main()
        return True

    if mode == "--worker-demucs":
        from _run_demucs import main as demucs_main

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        demucs_main()
        return True

    return False


if __name__ == "__main__" and _dispatch_worker_mode():
    raise SystemExit(0)

import gradio as gr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auto_subtitle


class _TeeStream:
    """同时把控制台输出写入日志队列。"""

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


_processing_lock = threading.Lock()


def _collect_result_files(result, result_files):
    if not result:
        return
    for key in ("en_srt", "zh_srt", "bi_srt", "summary_md", "final_video", "dubbed_video"):
        path = result.get(key)
        if path and os.path.exists(path):
            result_files.append(path)


def _run_processing(sources, burn_subtitle, enable_dubbing, enable_enhance, enable_summary):
    """在后台线程处理视频，并把日志实时推给 Gradio。"""

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
                result = auto_subtitle.process_one(
                    sources[0],
                    burn_subtitle=burn_subtitle,
                    enable_dubbing=enable_dubbing,
                    enable_enhance=enable_enhance,
                    enable_summary=enable_summary,
                )
                all_results.append(result)
                _collect_result_files(result, result_files)
            else:
                print(f"批量模式: 共 {total} 个任务，使用两阶段流程。")

                print("\n" + "=" * 60)
                print(f"第一阶段: 下载 / 准备全部输入，共 {total} 个")
                print("=" * 60)
                prepared_list = []
                for index, src in enumerate(sources, 1):
                    print(f"\n准备 [{index}/{total}]: {src}")
                    prepared_list.append(auto_subtitle._prepare_source(src))

                dl_ok = sum(1 for item in prepared_list if item.get("status") != "失败")
                dl_fail = total - dl_ok
                print(f"\n准备阶段完成: {dl_ok} 成功 / {dl_fail} 失败 / {total} 总计")

                print("\n" + "=" * 60)
                print("第二阶段: 识别 -> 总结 -> 翻译 -> 压制 -> 配音")
                print("=" * 60)
                for index, prepared in enumerate(prepared_list, 1):
                    print("\n" + "#" * 60)
                    print(f"任务 [{index}/{total}]: {prepared['source']}")
                    print("#" * 60)
                    result = auto_subtitle._process_prepared(
                        prepared,
                        burn_subtitle=burn_subtitle,
                        enable_dubbing=enable_dubbing,
                        enable_enhance=enable_enhance,
                        enable_summary=enable_summary,
                    )
                    all_results.append(result)
                    _collect_result_files(result, result_files)

            auto_subtitle._print_summary(all_results)
        except Exception:
            import traceback

            print(f"\n处理失败:\n{traceback.format_exc()}")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            done.set()

    if not _processing_lock.acquire(blocking=False):
        yield "已存在处理中的任务，请等待当前任务结束后再试。\n", []
        return

    try:
        threading.Thread(target=worker, daemon=True).start()

        log_text = ""
        while not done.is_set() or not log_q.empty():
            try:
                msg = log_q.get(timeout=0.3)
                log_text += msg + "\n"
                yield log_text, list(result_files)
            except queue.Empty:
                pass

        while not log_q.empty():
            log_text += log_q.get_nowait() + "\n"

        yield log_text, list(result_files)
    finally:
        _processing_lock.release()


def process_handler(urls_text, uploaded_files, burn_subtitle, enable_dubbing, enable_enhance, enable_summary):
    """Gradio 入口。"""

    sources = []

    if urls_text and urls_text.strip():
        for line in urls_text.strip().splitlines():
            line = line.strip()
            if line:
                sources.append(line)

    if uploaded_files:
        for file_obj in uploaded_files:
            path = file_obj if isinstance(file_obj, str) else getattr(file_obj, "name", str(file_obj))
            sources.append(path)

    if not sources:
        yield "请至少提供一个 YouTube 链接或一个本地视频文件。\n", []
        return

    yield from _run_processing(
        sources,
        burn_subtitle=burn_subtitle,
        enable_dubbing=enable_dubbing,
        enable_enhance=enable_enhance,
        enable_summary=enable_summary,
    )


def build_ui():
    api_warning = ""
    if not auto_subtitle.QWEN_API_KEY:
        api_warning = "\n> 注意: `config.json` 中未配置 API Key，AI 翻译和 AI 总结可能会失败。"

    with gr.Blocks(title="SubForge | AI 字幕与配音工具") as app:
        gr.Markdown(
            "# SubForge\n"
            "AI 字幕、翻译、总结、压制和中文配音一体化工具。\n\n"
            "支持 YouTube 链接和本地视频文件，适合做双语字幕和中文配音视频。"
            + api_warning
        )

        with gr.Row():
            with gr.Column(scale=1):
                urls_input = gr.Textbox(
                    label="YouTube 链接",
                    placeholder="每行一个链接，例如:\nhttps://www.youtube.com/watch?v=XXXXX\nhttps://youtu.be/YYYYY",
                    lines=4,
                )
                file_input = gr.File(
                    label="本地视频文件",
                    file_count="multiple",
                    file_types=[".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".ts"],
                )

                with gr.Accordion("处理选项", open=False):
                    burn_sub = gr.Checkbox(label="压制硬字幕到视频", value=True)
                    dub_check = gr.Checkbox(label="生成中文 AI 配音", value=True)
                    enhance_check = gr.Checkbox(label="启用 Real-ESRGAN 画质增强，仅 NVIDIA GPU", value=False)
                    summary_check = gr.Checkbox(label="生成 AI 内容总结 Markdown", value=False)
                    gr.Markdown(
                        f"**当前配置**\n\n"
                        f"- Whisper 模型: `{auto_subtitle.WHISPER_MODEL}`\n"
                        f"- 视频语言: `{auto_subtitle.VIDEO_LANGUAGE}`\n"
                        f"- 翻译模型: `{auto_subtitle.QWEN_MODEL}`\n"
                        f"- 翻译并发: `{auto_subtitle.TRANSLATE_CONCURRENCY}`\n"
                        f"- 断句间隔: `{auto_subtitle.SUBTITLE_MAX_GAP_MS}` ms\n"
                        f"- 字幕字体: `{auto_subtitle.SUBTITLE_FONT}` {auto_subtitle.FONT_SIZE}px\n\n"
                        "如需修改默认值，请编辑 `config.json` 后重新启动。"
                    )

                process_btn = gr.Button("开始处理", variant="primary", size="lg")

            with gr.Column(scale=1):
                log_output = gr.Textbox(
                    label="处理日志",
                    lines=22,
                    max_lines=50,
                    interactive=False,
                )
                file_output = gr.File(
                    label="输出文件",
                    file_count="multiple",
                    interactive=False,
                )

        process_btn.click(
            fn=process_handler,
            inputs=[urls_input, file_input, burn_sub, dub_check, enhance_check, summary_check],
            outputs=[log_output, file_output],
        )

    return app


if __name__ == "__main__":
    build_ui().launch(
        server_name="127.0.0.1",
        server_port=7860,
        theme=gr.themes.Soft(),
        share=False,
        inbrowser=True,
    )
