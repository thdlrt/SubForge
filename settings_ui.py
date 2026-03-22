"""
Gradio「设置」页：表单与 JSON 双向联动；仅「保存并应用」写盘并重启进程。
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
import time
from typing import Any

import gradio as gr

import config


def restart_program() -> None:
    """启动新的本应用进程后退出当前进程（配置已在磁盘上）。"""
    python = sys.executable
    script = os.path.abspath(sys.argv[0])
    args = [python, script, *sys.argv[1:]]
    cwd = os.path.abspath(os.getcwd())
    # 子进程独立运行；父进程立即退出，浏览器会短暂断开
    subprocess.Popen(args, cwd=cwd, close_fds=False)
    os._exit(0)


def _cfg_get(cfg: dict, path: str) -> Any:
    cur: Any = cfg
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _set_nested(root: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = root
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _coerce_field(path: str, kind: str, raw: Any) -> Any:
    if kind == "optional_lang":
        if raw is None:
            return None
        s = str(raw).strip()
        return s if s else None
    if kind == "str":
        return "" if raw is None else str(raw)
    if kind == "password":
        return "" if raw is None else str(raw)
    if kind == "int":
        if raw is None:
            return 0
        return int(round(float(raw)))
    if kind == "float":
        if raw is None:
            return 0.0
        return float(raw)
    if kind == "bool":
        return bool(raw)
    if kind == "dropdown":
        return raw
    if kind == "json_dict":
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        s = str(raw).strip()
        if not s:
            return {}
        return json.loads(s)
    return raw


def _format_for_widget(path: str, kind: str, val: Any) -> Any:
    if kind == "optional_lang":
        return "" if val is None else str(val)
    if kind == "password":
        return val or ""
    if kind == "bool":
        return bool(val)
    if kind == "int":
        return int(val) if val is not None else 0
    if kind == "float":
        return float(val) if val is not None else 0.0
    if kind == "dropdown":
        return val
    if kind == "json_dict":
        d = val if isinstance(val, dict) else {}
        return json.dumps(d, indent=2, ensure_ascii=False)
    return str(val) if val is not None else ""


def _field(
    path: str,
    kind: str,
    label: str,
    *,
    choices: list | None = None,
    lines: int = 1,
    precision: int | None = None,
):
    return {
        "path": path,
        "kind": kind,
        "label": label,
        "choices": choices,
        "lines": lines,
        "precision": precision,
    }


FIELD_GROUPS: list[tuple[str, list[dict]]] = [
    (
        "语音识别 / 视频",
        [
            _field("whisper_model", "dropdown", "Whisper 模型", choices=["tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo"]),
            _field("device", "dropdown", "设备", choices=["auto", "cuda", "cpu"]),
            _field("compute_type", "dropdown", "计算精度", choices=["auto", "int8", "int8_float16", "float16", "float32"]),
            _field("video_language", "optional_lang", "视频语言（留空=自动）"),
            _field("max_video_height", "dropdown", "最大视频高度", choices=[720, 1080, 1440, 2160]),
        ],
    ),
    (
        "下载 (yt-dlp)",
        [
            _field("ytdlp_cookies", "str", "Cookies（如 ./cookies/youtube.txt 或浏览器名；未命中域名映射时用）"),
            _field(
                "ytdlp_cookies_by_host",
                "json_dict",
                "按域名 Cookies（JSON：键为后缀如 gamedev.tv，值为路径或浏览器名）",
                lines=6,
            ),
            _field("ytdlp_client", "str", "YouTube 客户端（ios/tv_embedded/web，留空默认）"),
        ],
    ),
    (
        "字幕（基础）",
        [
            _field("subtitle_max_gap_ms", "int", "字幕最大间隔 (ms)"),
            _field("subtitle_max_chars", "int", "单条字幕最大字符数"),
        ],
    ),
    (
        "字幕断句（高级 subtitle_advanced）",
        [
            _field("subtitle_advanced.target_chars_ratio", "float", "target_chars_ratio", precision=3),
            _field("subtitle_advanced.min_chars_ratio", "float", "min_chars_ratio", precision=3),
            _field("subtitle_advanced.hard_max_chars_ratio", "float", "hard_max_chars_ratio", precision=3),
            _field("subtitle_advanced.hard_max_chars_bias", "float", "hard_max_chars_bias", precision=1),
            _field("subtitle_advanced.soft_max_duration_sec", "float", "soft_max_duration_sec", precision=2),
            _field("subtitle_advanced.hard_max_duration_sec", "float", "hard_max_duration_sec", precision=2),
            _field("subtitle_advanced.min_words", "int", "min_words"),
            _field("subtitle_advanced.merge_max_gap_sec", "float", "merge_max_gap_sec", precision=3),
            _field("subtitle_advanced.merge_max_duration_sec", "float", "merge_max_duration_sec", precision=2),
            _field("subtitle_advanced.merge_max_chars_ratio", "float", "merge_max_chars_ratio", precision=3),
            _field("subtitle_advanced.merge_max_chars_bias", "float", "merge_max_chars_bias", precision=1),
            _field("subtitle_advanced.short_tail_max_words", "int", "short_tail_max_words"),
            _field("subtitle_advanced.short_tail_max_chars", "int", "short_tail_max_chars"),
            _field("subtitle_advanced.short_tail_max_duration_sec", "float", "short_tail_max_duration_sec", precision=2),
            _field("subtitle_advanced.split_max_duration_sec", "float", "split_max_duration_sec", precision=2),
        ],
    ),
    (
        "翻译 API (Qwen 兼容)",
        [
            _field("qwen_api_key", "password", "Qwen API Key"),
            _field("qwen_base_url", "str", "Base URL"),
            _field("qwen_model", "str", "模型名"),
            _field("translate_batch_size", "int", "每批翻译条数"),
            _field("translate_concurrency", "int", "并发批数"),
            _field("api_retry", "int", "失败重试次数"),
            _field("api_sleep", "float", "批次间抖动上限 (秒)", precision=2),
        ],
    ),
    (
        "字幕样式 (ASS)",
        [
            _field("font_size", "int", "字体大小"),
            _field("subtitle_font", "str", "字体名"),
            _field("subtitle_primary_color", "str", "主颜色 (ASS &H...)"),
            _field("subtitle_outline_color", "str", "描边颜色"),
            _field("subtitle_outline", "int", "描边粗细 0–2"),
            _field("subtitle_shadow", "int", "阴影 0–2"),
            _field("subtitle_margin_v", "int", "底部边距 (px)"),
        ],
    ),
    (
        "TTS / 配音",
        [
            _field("tts_provider", "dropdown", "TTS 引擎", choices=["edge", "qwen_tts", "cosyvoice"]),
            _field("tts_voice", "str", "edge-tts 发音人"),
            _field("tts_rate", "str", "edge 语速 e.g. +0%"),
            _field("tts_volume", "str", "edge 音量 e.g. +0%"),
            _field("tts_bg_volume", "float", "背景音音量 0–1", precision=2),
            _field("tts_max_speed", "float", "对白加速上限倍率", precision=2),
            _field("tts_merge_gap_ms", "int", "TTS 合并间隔 (ms)"),
            _field("tts_merge_max_chars", "int", "TTS 合并最大字符"),
            _field("qwen_tts_api_key", "password", "Qwen TTS API Key"),
            _field("qwen_tts_base_url", "str", "Qwen TTS Base URL"),
            _field("qwen_tts_model", "str", "Qwen TTS 模型"),
            _field("qwen_tts_voice", "str", "Qwen TTS 音色"),
        ],
    ),
    (
        "CosyVoice 本地",
        [
            _field("cosyvoice_api_url", "str", "HTTP 服务地址"),
            _field("cosyvoice_port", "int", "端口"),
            _field("cosyvoice_mode", "dropdown", "模式", choices=["preset", "zero_shot", "cross_lingual"]),
            _field("cosyvoice_voice", "str", "预设说话人"),
            _field("cosyvoice_prompt_audio_path", "str", "参考音频路径 (zero_shot)"),
            _field("cosyvoice_prompt_text", "str", "参考文案", lines=2),
            _field("cosyvoice_device", "dropdown", "推理设备", choices=["cpu", "cuda", "auto"]),
            _field("cosyvoice_repo_url", "str", "CosyVoice 仓库 URL"),
            _field("cosyvoice_model_id", "str", "模型 ID"),
            _field("cosyvoice_ttsfrd_id", "str", "ttsfrd 资源 ID"),
            _field("cosyvoice_model_source", "str", "模型下载源"),
            _field("cosyvoice_start_timeout", "int", "启动超时 (秒)"),
            _field("cosyvoice_request_timeout", "int", "单次请求超时 (秒)"),
            _field("cosyvoice_merge_max_chars", "int", "CosyVoice 合并最大字符"),
            _field("cosyvoice_fp16", "bool", "GPU FP16"),
        ],
    ),
    (
        "画质增强",
        [
            _field(
                "enhance_model",
                "dropdown",
                "Real-ESRGAN 模型",
                choices=[
                    "RealESRGAN_x4plus",
                    "RealESRGAN_x4plus_anime_6B",
                    "RealESRGAN_x2plus",
                ],
            ),
            _field("enhance_outscale", "dropdown", "放大倍数", choices=[2, 4]),
        ],
    ),
]


def all_field_specs() -> list[dict]:
    out = []
    for _, fields in FIELD_GROUPS:
        out.extend(fields)
    return out


def _make_widget(spec: dict, cfg: dict):
    path = spec["path"]
    kind = spec["kind"]
    label = spec["label"]
    val = _cfg_get(cfg, path)
    fv = _format_for_widget(path, kind, val)

    if kind == "dropdown":
        ch = spec["choices"] or []
        v = fv if fv in ch else ch[0]
        return gr.Dropdown(label=label, choices=ch, value=v)
    if kind == "json_dict":
        return gr.Textbox(
            label=label,
            value=str(fv),
            lines=spec.get("lines", 6),
        )
    if kind in ("str", "optional_lang"):
        return gr.Textbox(label=label, value=str(fv), lines=spec.get("lines", 1))
    if kind == "password":
        return gr.Textbox(label=label, value=str(fv), type="password", lines=1)
    if kind == "int":
        return gr.Number(label=label, value=int(fv), precision=0)
    if kind == "float":
        return gr.Number(label=label, value=float(fv), precision=spec.get("precision", 2))
    if kind == "bool":
        return gr.Checkbox(label=label, value=bool(fv))
    return gr.Textbox(label=label, value=str(fv))


def pack_overlay(values: list[Any], specs: list[dict]) -> dict:
    overlay: dict = {}
    for spec, raw in zip(specs, values):
        path = spec["path"]
        kind = spec["kind"]
        v = _coerce_field(path, kind, raw)
        _set_nested(overlay, path, v)
    return overlay


def _merged_config_from_values(values: list[Any], specs: list[dict]) -> dict:
    base = copy.deepcopy(config._load_config())
    overlay = pack_overlay(list(values), specs)
    config.deep_merge_overlay(base, overlay)
    config.coerce_config_values(base)
    return base


def _norm_cfg(d: dict) -> str:
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def config_summary_markdown() -> str:
    """主界面「当前配置」摘要。"""
    p = (config.TTS_PROVIDER or "edge").strip().lower()
    if p in ("qwen_tts", "qwen-tts"):
        tts_line = (
            f"**当前 TTS**: `Qwen TTS` · 模型 `{config.QWEN_TTS_MODEL}` · 音色 `{config.QWEN_TTS_VOICE}`"
        )
    elif p == "cosyvoice":
        tts_line = (
            f"**当前 TTS**: `CosyVoice` · 音色 `{config.COSYVOICE_VOICE}` · 服务 `{config.COSYVOICE_API_URL}`"
        )
    else:
        tts_line = f"**当前 TTS**: `edge-tts` · 音色 `{config.TTS_VOICE}`"
    key_ok = "已配置" if (config.QWEN_API_KEY or "").strip() else "未配置"
    return (
        f"{tts_line}\n\n"
        f"**当前配置** *(内存中的已加载配置)*\n\n"
        f"- 语音模型: `{config.WHISPER_MODEL}` · 语言: `{config.VIDEO_LANGUAGE}`\n"
        f"- 翻译模型: `{config.QWEN_MODEL}` · 并发: `{config.TRANSLATE_CONCURRENCY}` · API Key: {key_ok}\n"
        f"- 断句间隙: `{config.SUBTITLE_MAX_GAP_MS}` ms · "
        f"字体: `{config.SUBTITLE_FONT}` {config.FONT_SIZE}px\n\n"
        f"*在 **设置** 中改完后点 **保存并应用**（会写 `config.json` 并**重启程序**）。*"
    )


def build_settings_tab(
    config_hint_md: gr.Markdown,
) -> None:
    specs = all_field_specs()
    cfg = config._load_config()

    gr.Markdown(
        "### ⚙️ 应用设置\n"
        "- **上方表单** 与 **下方 JSON** 实时联动：改表单会更新 JSON；改 JSON（合法）会回填表单。\n"
        "- **保存并应用**：写入 `config.json` 后 **自动重启本程序**，新进程重新加载配置，避免内存与磁盘不一致。\n"
        "- JSON 语法错误时不会改表单；修正为合法 JSON 后会自动同步。"
    )

    field_components: list = []
    for title, fields in FIELD_GROUPS:
        with gr.Accordion(title, open=title in ("语音识别 / 视频", "翻译 API (Qwen 兼容)", "TTS / 配音")):
            for spec in fields:
                field_components.append(_make_widget(spec, cfg))

    status = gr.Markdown("")

    def _json_text_from_values(*vals: Any) -> str:
        d = _merged_config_from_values(list(vals), specs)
        return json.dumps(d, indent=2, ensure_ascii=False)

    initial_json = _json_text_from_values(*values_from_disk(specs))

    # 使用 Textbox 而非 Code：Gradio 的 Code 作为 outputs 时，多控件绑定同一输出时
    # 常无法正确刷新；Textbox + gr.update(value=...) 稳定。
    json_preview = gr.Textbox(
        label="完整配置 JSON（与表单联动，可直接编辑）",
        value=initial_json,
        lines=22,
        max_lines=40,
        elem_classes=["aitext-json-sync"],
    )

    def form_to_json(*vals: Any):
        txt = _json_text_from_values(*vals)
        return gr.update(value=txt)

    def json_to_form(json_text: str | None, *vals: Any):
        if json_text is None or not str(json_text).strip():
            return tuple(gr.update() for _ in specs)
        try:
            user = json.loads(json_text)
        except json.JSONDecodeError:
            return tuple(gr.update() for _ in specs)

        base = copy.deepcopy(config._load_config())
        config.deep_merge_overlay(base, user)
        config.coerce_config_values(base)

        from_form = _merged_config_from_values(list(vals), specs)
        if _norm_cfg(base) == _norm_cfg(from_form):
            return tuple(gr.update() for _ in specs)

        out = [
            _format_for_widget(s["path"], s["kind"], _cfg_get(base, s["path"]))
            for s in specs
        ]
        return tuple(out)

    def wire_sync():
        inputs_form = field_components
        out_json = [json_preview]

        def handler(*vals: Any):
            return form_to_json(*vals)

        # 每个控件单独绑定：Textbox 用 input 实时；Number/Dropdown/Checkbox 用 change
        for comp in field_components:
            if isinstance(comp, gr.Textbox):
                comp.input(fn=handler, inputs=inputs_form, outputs=out_json)
            else:
                comp.change(fn=handler, inputs=inputs_form, outputs=out_json)

        # JSON 编辑 → 表单（用 input 实时；与下方表单 push 的 JSON 通过 _norm 比较避免死循环）
        json_preview.input(
            fn=json_to_form,
            inputs=[json_preview, *field_components],
            outputs=field_components,
        )

    wire_sync()

    def do_save_and_restart(*vals: Any):
        overlay = pack_overlay(list(vals), specs)
        ok, msg = config.save_config_to_disk_only(overlay)
        if not ok:
            return (
                f"<span style='color:crimson'>{msg}</span>",
                gr.update(),
            )

        def _delayed_restart():
            time.sleep(0.35)
            restart_program()

        threading.Thread(target=_delayed_restart, daemon=True).start()
        return (
            "<span style='color:green'>已保存 config.json，正在重启进程… "
            "浏览器可能短暂断开，请稍后<strong>刷新页面</strong>或重新打开 http://127.0.0.1:7860 。</span>",
            gr.update(value=config_summary_markdown()),
        )

    save_btn = gr.Button("💾 保存并应用（写入后重启程序）", variant="primary")
    save_btn.click(
        fn=do_save_and_restart,
        inputs=field_components,
        outputs=[status, config_hint_md],
    )


def values_from_disk(specs: list[dict]) -> list[Any]:
    disk = config._load_config()
    return [_format_for_widget(s["path"], s["kind"], _cfg_get(disk, s["path"])) for s in specs]
