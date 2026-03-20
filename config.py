"""
配置加载与全局常量
"""
import os
import json

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def _load_config():
    """从 config.json 加载配置，缺失字段使用默认值"""
    defaults = {
        "whisper_model": "medium",
        "device": "auto",
        "compute_type": "auto",
        "video_language": None,
        "max_video_height": 1080,
        "ytdlp_cookies": "",
        "ytdlp_client": "",
        "subtitle_max_gap_ms": 2000,
        "subtitle_max_chars": 120,
        "qwen_api_key": "",
        "qwen_base_url": "",
        "qwen_model": "qwen3.5-plus",
        "translate_batch_size": 50,
        "translate_concurrency": 10,
        "api_retry": 3,
        "api_sleep": 0.5,
        "font_size": 20,
        "subtitle_font": "Microsoft YaHei",
        "subtitle_primary_color": "&H00FFFFFF",
        "subtitle_outline_color": "&H00000000",
        "subtitle_outline": 1,
        "subtitle_shadow": 0,
        "subtitle_margin_v": 30,
        "tts_provider": "edge",
        "tts_voice": "zh-CN-YunjianNeural",
        "tts_rate": "+0%",
        "tts_volume": "+0%",
        "tts_bg_volume": 0.5,
        "tts_max_speed": 1.5,
        "tts_merge_gap_ms": 280,
        "tts_merge_max_chars": 90,
        "qwen_tts_api_key": "",
        "qwen_tts_base_url": "https://dashscope.aliyuncs.com/api/v1",
        "qwen_tts_model": "qwen3-tts-flash",
        "qwen_tts_voice": "Cherry",
        "cosyvoice_api_url": "http://127.0.0.1:9880",
        "cosyvoice_port": 9880,
        "cosyvoice_mode": "preset",
        "cosyvoice_voice": "中文男",
        "cosyvoice_prompt_audio_path": "",
        "cosyvoice_prompt_text": "",
        "cosyvoice_device": "cpu",
        "cosyvoice_repo_url": "https://github.com/FunAudioLLM/CosyVoice.git",
        "cosyvoice_model_id": "FunAudioLLM/CosyVoice-300M-SFT",
        "cosyvoice_ttsfrd_id": "FunAudioLLM/CosyVoice-ttsfrd",
        "cosyvoice_model_source": "auto",
        "cosyvoice_start_timeout": 900,
        "cosyvoice_request_timeout": 180,
        "cosyvoice_merge_max_chars": 72,
        "cosyvoice_fp16": True,
        "enhance_model": "RealESRGAN_x4plus",
        "enhance_outscale": 4,
    }
    subtitle_advanced_defaults = {
        "target_chars_ratio": 0.82,
        "min_chars_ratio": 0.38,
        "hard_max_chars_ratio": 1.35,
        "hard_max_chars_bias": 18,
        "soft_max_duration_sec": 4.8,
        "hard_max_duration_sec": 6.4,
        "min_words": 3,
        "merge_max_gap_sec": 0.35,
        "merge_max_duration_sec": 6.0,
        "merge_max_chars_ratio": 1.35,
        "merge_max_chars_bias": 24,
        "short_tail_max_words": 3,
        "short_tail_max_chars": 18,
        "short_tail_max_duration_sec": 1.4,
        "split_max_duration_sec": 6.8,
    }
    cfg = defaults.copy()
    cfg["subtitle_advanced"] = subtitle_advanced_defaults.copy()
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        for k, v in user_cfg.items():
            if k.startswith("_"):
                continue
            if k in defaults:
                cfg[k] = v

        legacy_advanced_keys = {
            f"subtitle_{key}": key for key in subtitle_advanced_defaults
        }
        for legacy_key, advanced_key in legacy_advanced_keys.items():
            if legacy_key in user_cfg:
                cfg["subtitle_advanced"][advanced_key] = user_cfg[legacy_key]

        user_advanced = user_cfg.get("subtitle_advanced", {})
        if isinstance(user_advanced, dict):
            for k, v in user_advanced.items():
                if k in subtitle_advanced_defaults:
                    cfg["subtitle_advanced"][k] = v
    else:
        print(f"⚠ 未找到配置文件 {CONFIG_PATH}，使用默认配置")
    coerce_config_values(cfg)
    return cfg


def coerce_config_values(cfg: dict) -> None:
    """就地修正配置类型（磁盘加载或 Web 保存后调用）。"""
    int_fields = (
        "max_video_height",
        "subtitle_max_gap_ms",
        "subtitle_max_chars",
        "translate_batch_size",
        "translate_concurrency",
        "api_retry",
        "font_size",
        "subtitle_outline",
        "subtitle_shadow",
        "subtitle_margin_v",
        "tts_merge_gap_ms",
        "tts_merge_max_chars",
        "cosyvoice_port",
        "cosyvoice_start_timeout",
        "cosyvoice_request_timeout",
        "cosyvoice_merge_max_chars",
        "enhance_outscale",
    )
    for k in int_fields:
        if k not in cfg or cfg[k] is None:
            continue
        cfg[k] = int(round(float(cfg[k])))

    for k in ("api_sleep", "tts_bg_volume", "tts_max_speed"):
        if k not in cfg or cfg[k] is None:
            continue
        cfg[k] = float(cfg[k])

    if "cosyvoice_fp16" in cfg and cfg["cosyvoice_fp16"] is not None:
        cfg["cosyvoice_fp16"] = bool(cfg["cosyvoice_fp16"])

    vl = cfg.get("video_language")
    if isinstance(vl, str) and not vl.strip():
        cfg["video_language"] = None

    sa = cfg.get("subtitle_advanced")
    if not isinstance(sa, dict):
        return
    int_sa = {"min_words", "short_tail_max_words", "short_tail_max_chars"}
    for k, v in list(sa.items()):
        if v is None:
            continue
        if k in int_sa:
            sa[k] = int(round(float(v)))
        else:
            sa[k] = float(v)


def deep_merge_overlay(base: dict, overlay: dict) -> dict:
    """将 overlay 深度合并进 base（就地修改 base）。"""
    for k, v in overlay.items():
        if k.startswith("_"):
            continue
        if (
            k in base
            and isinstance(base.get(k), dict)
            and isinstance(v, dict)
        ):
            deep_merge_overlay(base[k], v)
        else:
            base[k] = v
    return base


def assign_from_cfg(cfg: dict) -> None:
    """用一份完整配置字典刷新本模块中的全局常量（供运行中热更新）。"""
    global _cfg, _subtitle_advanced
    global WHISPER_MODEL, DEVICE, COMPUTE_TYPE, VIDEO_LANGUAGE, MAX_VIDEO_HEIGHT
    global YTDLP_COOKIES, YTDLP_CLIENT, SUBTITLE_MAX_GAP_MS, SUBTITLE_MAX_CHARS
    global SUBTITLE_TARGET_CHARS_RATIO, SUBTITLE_MIN_CHARS_RATIO
    global SUBTITLE_HARD_MAX_CHARS_RATIO, SUBTITLE_HARD_MAX_CHARS_BIAS
    global SUBTITLE_SOFT_MAX_DURATION_SEC, SUBTITLE_HARD_MAX_DURATION_SEC
    global SUBTITLE_MIN_WORDS, SUBTITLE_MERGE_MAX_GAP_SEC
    global SUBTITLE_MERGE_MAX_DURATION_SEC, SUBTITLE_MERGE_MAX_CHARS_RATIO
    global SUBTITLE_MERGE_MAX_CHARS_BIAS, SUBTITLE_SHORT_TAIL_MAX_WORDS
    global SUBTITLE_SHORT_TAIL_MAX_CHARS, SUBTITLE_SHORT_TAIL_MAX_DURATION_SEC
    global SUBTITLE_SPLIT_MAX_DURATION_SEC
    global QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL
    global TRANSLATE_BATCH_SIZE, TRANSLATE_CONCURRENCY, API_RETRY, API_SLEEP
    global FONT_SIZE, SUBTITLE_FONT, SUBTITLE_PRIMARY_COLOR, SUBTITLE_OUTLINE_COLOR
    global SUBTITLE_OUTLINE, SUBTITLE_SHADOW, SUBTITLE_MARGIN_V
    global TTS_PROVIDER, TTS_VOICE, TTS_RATE, TTS_VOLUME, TTS_BG_VOLUME, TTS_MAX_SPEED
    global TTS_MERGE_GAP_MS, TTS_MERGE_MAX_CHARS
    global QWEN_TTS_API_KEY, QWEN_TTS_BASE_URL, QWEN_TTS_MODEL, QWEN_TTS_VOICE
    global COSYVOICE_API_URL, COSYVOICE_PORT, COSYVOICE_MODE, COSYVOICE_VOICE
    global COSYVOICE_PROMPT_AUDIO_PATH, COSYVOICE_PROMPT_TEXT, COSYVOICE_DEVICE
    global COSYVOICE_REPO_URL, COSYVOICE_MODEL_ID, COSYVOICE_TTSFRD_ID
    global COSYVOICE_MODEL_SOURCE, COSYVOICE_START_TIMEOUT, COSYVOICE_REQUEST_TIMEOUT
    global COSYVOICE_MERGE_MAX_CHARS, COSYVOICE_FP16
    global ENHANCE_MODEL, ENHANCE_OUTSCALE

    _cfg = cfg
    _subtitle_advanced = cfg["subtitle_advanced"]
    WHISPER_MODEL = cfg["whisper_model"]
    DEVICE = cfg["device"]
    COMPUTE_TYPE = cfg["compute_type"]
    VIDEO_LANGUAGE = cfg["video_language"]
    MAX_VIDEO_HEIGHT = cfg["max_video_height"]
    YTDLP_COOKIES = cfg["ytdlp_cookies"]
    YTDLP_CLIENT = cfg["ytdlp_client"]
    SUBTITLE_MAX_GAP_MS = cfg["subtitle_max_gap_ms"]
    SUBTITLE_MAX_CHARS = cfg["subtitle_max_chars"]
    SUBTITLE_TARGET_CHARS_RATIO = _subtitle_advanced["target_chars_ratio"]
    SUBTITLE_MIN_CHARS_RATIO = _subtitle_advanced["min_chars_ratio"]
    SUBTITLE_HARD_MAX_CHARS_RATIO = _subtitle_advanced["hard_max_chars_ratio"]
    SUBTITLE_HARD_MAX_CHARS_BIAS = _subtitle_advanced["hard_max_chars_bias"]
    SUBTITLE_SOFT_MAX_DURATION_SEC = _subtitle_advanced["soft_max_duration_sec"]
    SUBTITLE_HARD_MAX_DURATION_SEC = _subtitle_advanced["hard_max_duration_sec"]
    SUBTITLE_MIN_WORDS = _subtitle_advanced["min_words"]
    SUBTITLE_MERGE_MAX_GAP_SEC = _subtitle_advanced["merge_max_gap_sec"]
    SUBTITLE_MERGE_MAX_DURATION_SEC = _subtitle_advanced["merge_max_duration_sec"]
    SUBTITLE_MERGE_MAX_CHARS_RATIO = _subtitle_advanced["merge_max_chars_ratio"]
    SUBTITLE_MERGE_MAX_CHARS_BIAS = _subtitle_advanced["merge_max_chars_bias"]
    SUBTITLE_SHORT_TAIL_MAX_WORDS = _subtitle_advanced["short_tail_max_words"]
    SUBTITLE_SHORT_TAIL_MAX_CHARS = _subtitle_advanced["short_tail_max_chars"]
    SUBTITLE_SHORT_TAIL_MAX_DURATION_SEC = _subtitle_advanced["short_tail_max_duration_sec"]
    SUBTITLE_SPLIT_MAX_DURATION_SEC = _subtitle_advanced["split_max_duration_sec"]
    QWEN_API_KEY = cfg["qwen_api_key"]
    QWEN_BASE_URL = cfg["qwen_base_url"]
    QWEN_MODEL = cfg["qwen_model"]
    TRANSLATE_BATCH_SIZE = cfg["translate_batch_size"]
    TRANSLATE_CONCURRENCY = cfg["translate_concurrency"]
    API_RETRY = cfg["api_retry"]
    API_SLEEP = cfg["api_sleep"]
    FONT_SIZE = cfg["font_size"]
    SUBTITLE_FONT = cfg["subtitle_font"]
    SUBTITLE_PRIMARY_COLOR = cfg["subtitle_primary_color"]
    SUBTITLE_OUTLINE_COLOR = cfg["subtitle_outline_color"]
    SUBTITLE_OUTLINE = cfg["subtitle_outline"]
    SUBTITLE_SHADOW = cfg["subtitle_shadow"]
    SUBTITLE_MARGIN_V = cfg["subtitle_margin_v"]
    TTS_PROVIDER = cfg["tts_provider"]
    TTS_VOICE = cfg["tts_voice"]
    TTS_RATE = cfg["tts_rate"]
    TTS_VOLUME = cfg["tts_volume"]
    TTS_BG_VOLUME = cfg["tts_bg_volume"]
    TTS_MAX_SPEED = cfg["tts_max_speed"]
    TTS_MERGE_GAP_MS = cfg["tts_merge_gap_ms"]
    TTS_MERGE_MAX_CHARS = cfg["tts_merge_max_chars"]
    QWEN_TTS_API_KEY = cfg["qwen_tts_api_key"]
    QWEN_TTS_BASE_URL = cfg["qwen_tts_base_url"]
    QWEN_TTS_MODEL = cfg["qwen_tts_model"]
    QWEN_TTS_VOICE = cfg["qwen_tts_voice"]
    COSYVOICE_API_URL = cfg["cosyvoice_api_url"]
    COSYVOICE_PORT = cfg["cosyvoice_port"]
    COSYVOICE_MODE = cfg["cosyvoice_mode"]
    COSYVOICE_VOICE = cfg["cosyvoice_voice"]
    COSYVOICE_PROMPT_AUDIO_PATH = cfg["cosyvoice_prompt_audio_path"]
    COSYVOICE_PROMPT_TEXT = cfg["cosyvoice_prompt_text"]
    COSYVOICE_DEVICE = cfg["cosyvoice_device"]
    COSYVOICE_REPO_URL = cfg["cosyvoice_repo_url"]
    COSYVOICE_MODEL_ID = cfg["cosyvoice_model_id"]
    COSYVOICE_TTSFRD_ID = cfg["cosyvoice_ttsfrd_id"]
    COSYVOICE_MODEL_SOURCE = cfg["cosyvoice_model_source"]
    COSYVOICE_START_TIMEOUT = cfg["cosyvoice_start_timeout"]
    COSYVOICE_REQUEST_TIMEOUT = cfg["cosyvoice_request_timeout"]
    COSYVOICE_MERGE_MAX_CHARS = cfg["cosyvoice_merge_max_chars"]
    COSYVOICE_FP16 = cfg["cosyvoice_fp16"]
    ENHANCE_MODEL = cfg["enhance_model"]
    ENHANCE_OUTSCALE = cfg["enhance_outscale"]


def save_config_overlay(overlay: dict) -> tuple[bool, str]:
    """
    将表单产生的嵌套字典合并进当前配置，写入 config.json，并 assign_from_cfg。
    overlay 中可只包含用户修改过的键；未出现的键保留磁盘上的值。
    """
    ok, msg = save_config_to_disk_only(overlay)
    if not ok:
        return False, msg
    assign_from_cfg(_load_config())
    return (
        True,
        "已保存并应用到当前进程。若修改了 CosyVoice 设备/模型/端口等，请重启本应用以使已启动的 CosyVoice 进程使用新配置。",
    )


def save_config_to_disk_only(overlay: dict) -> tuple[bool, str]:
    """
    仅将合并后的配置写入 config.json，不修改内存中的 config 全局变量。
    供「保存后重启进程」等场景使用。
    """
    cfg = _load_config()
    deep_merge_overlay(cfg, overlay)
    coerce_config_values(cfg)
    try:
        parent = os.path.dirname(os.path.abspath(CONFIG_PATH))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except OSError as e:
        return False, f"写入 config.json 失败: {e}"
    return True, "ok"


def reload_config_from_disk() -> tuple[bool, str]:
    """重新读取 config.json 并刷新全局常量。"""
    cfg = _load_config()
    assign_from_cfg(cfg)
    return True, "已从磁盘重新加载配置。"


_cfg = _load_config()
assign_from_cfg(_cfg)

SYSTEM_PROMPT = """You are a professional subtitle translator specializing in game development, computer graphics, and software engineering. You translate subtitles into fluent, natural Simplified Chinese regardless of the source language.

Rules:
1. Detect the source language automatically and translate into Simplified Chinese.
2. Keep technical terms accurate. Examples:
   - "shader" → "着色器", "rendering pipeline" → "渲染管线", "mesh" → "网格"
   - "frame rate" → "帧率", "occlusion culling" → "遮挡剔除"
3. Terms commonly kept in English in the Chinese game dev community should stay in English: Unity, Unreal, GPU, CPU, API, GDC, LOD, PBR, HLSL, etc.
4. Each line in the input is a separate subtitle. Translate each line independently.
5. Output ONLY the translations, one per line, in the same order. No numbering, no explanations, no extra text.
6. The number of output lines MUST exactly match the number of input lines."""
