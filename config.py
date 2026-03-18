"""
配置加载与全局常量
"""
import os
import json

from runtime import app_path

CONFIG_PATH = str(app_path("config.json"))
CONFIG_EXAMPLE_PATH = str(app_path("config.example.json"))


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
        "tts_voice": "zh-CN-YunjianNeural",
        "tts_rate": "+0%",
        "tts_volume": "+0%",
        "tts_bg_volume": 0.5,
        "tts_max_speed": 1.5,
        "tts_concurrency": 12,
        "ffmpeg_video_encoder": "auto",
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
        print(
            f"⚠ 未找到配置文件 {CONFIG_PATH}，使用默认配置。"
            f"如需填写 API Key，可复制 {CONFIG_EXAMPLE_PATH}"
        )
    return cfg


_cfg = _load_config()
_subtitle_advanced = _cfg["subtitle_advanced"]

WHISPER_MODEL          = _cfg["whisper_model"]
DEVICE                 = _cfg["device"]
COMPUTE_TYPE           = _cfg["compute_type"]
VIDEO_LANGUAGE         = _cfg["video_language"]
MAX_VIDEO_HEIGHT       = _cfg["max_video_height"]
YTDLP_COOKIES          = _cfg["ytdlp_cookies"]
YTDLP_CLIENT           = _cfg["ytdlp_client"]
SUBTITLE_MAX_GAP_MS    = _cfg["subtitle_max_gap_ms"]
SUBTITLE_MAX_CHARS     = _cfg["subtitle_max_chars"]
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
QWEN_API_KEY           = _cfg["qwen_api_key"]
QWEN_BASE_URL          = _cfg["qwen_base_url"]
QWEN_MODEL             = _cfg["qwen_model"]
TRANSLATE_BATCH_SIZE   = _cfg["translate_batch_size"]
TRANSLATE_CONCURRENCY  = _cfg["translate_concurrency"]
API_RETRY              = _cfg["api_retry"]
API_SLEEP              = _cfg["api_sleep"]
FONT_SIZE              = _cfg["font_size"]
SUBTITLE_FONT          = _cfg["subtitle_font"]
SUBTITLE_PRIMARY_COLOR = _cfg["subtitle_primary_color"]
SUBTITLE_OUTLINE_COLOR = _cfg["subtitle_outline_color"]
SUBTITLE_OUTLINE       = _cfg["subtitle_outline"]
SUBTITLE_SHADOW        = _cfg["subtitle_shadow"]
SUBTITLE_MARGIN_V      = _cfg["subtitle_margin_v"]
TTS_VOICE              = _cfg["tts_voice"]
TTS_RATE               = _cfg["tts_rate"]
TTS_VOLUME             = _cfg["tts_volume"]
TTS_BG_VOLUME          = _cfg["tts_bg_volume"]
TTS_MAX_SPEED          = _cfg["tts_max_speed"]
TTS_CONCURRENCY        = _cfg["tts_concurrency"]
FFMPEG_VIDEO_ENCODER   = _cfg["ffmpeg_video_encoder"]
ENHANCE_MODEL          = _cfg["enhance_model"]
ENHANCE_OUTSCALE       = _cfg["enhance_outscale"]

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
