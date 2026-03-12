"""
YouTube 视频下载 + AI字幕生成 + Qwen3.5 API翻译 + 字幕压制 一键脚本
使用方法: python auto_subtitle.py "https://www.youtube.com/watch?v=XXXXX"
"""

import subprocess
import sys
import os
import re
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# 强制 stdout/stderr 使用 UTF-8，避免 Windows GBK 终端无法输出 Emoji
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import srt
from datetime import timedelta
from pathlib import Path


def _sanitize_name(name):
    """将文件/目录名中对 Windows 路径和 ffmpeg subtitle filter 有害的字符替换为下划线。
    主要处理：全角冒号、单引号、Windows 保留字符。"""
    name = name.replace("：", "_")          # 全角冒号
    name = re.sub(r"[\\/:*?\"<>|']", "_", name)  # Windows 非法字符 + 单引号
    name = re.sub(r"_+", "_", name)         # 合并连续下划线
    return name.strip("_. ")


# ======================== 加载配置 ========================
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
        "subtitle_max_gap_ms": 1500,
        "subtitle_max_chars": 80,
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
        "enhance_model": "RealESRGAN_x4plus",
        "enhance_outscale": 4,
    }
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        # 只取非注释字段（跳过 _ 开头的键）
        for k, v in user_cfg.items():
            if not k.startswith("_") and k in defaults:
                defaults[k] = v
    else:
        print(f"⚠ 未找到配置文件 {CONFIG_PATH}，使用默认配置")
    return defaults

_cfg = _load_config()

WHISPER_MODEL          = _cfg["whisper_model"]
DEVICE                 = _cfg["device"]
COMPUTE_TYPE           = _cfg["compute_type"]
VIDEO_LANGUAGE         = _cfg["video_language"]
MAX_VIDEO_HEIGHT       = _cfg["max_video_height"]
YTDLP_COOKIES          = _cfg["ytdlp_cookies"]
YTDLP_CLIENT           = _cfg["ytdlp_client"]
SUBTITLE_MAX_GAP_MS    = _cfg["subtitle_max_gap_ms"]
SUBTITLE_MAX_CHARS     = _cfg["subtitle_max_chars"]
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
ENHANCE_MODEL          = _cfg["enhance_model"]
ENHANCE_OUTSCALE       = _cfg["enhance_outscale"]
# ========================================================


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


def _ytdlp_extra_args():
    """返回 yt-dlp 的 cookie + client 参数列表"""
    args = []
    if YTDLP_CLIENT:
        args += ["--extractor-args", f"youtube:player_client={YTDLP_CLIENT}"]
        print(f"   YouTube 客户端: {YTDLP_CLIENT}")
    if not YTDLP_COOKIES:
        return args
    if os.path.isfile(YTDLP_COOKIES):
        print(f"   使用 cookies 文件: {YTDLP_COOKIES}")
        return args + ["--cookies", YTDLP_COOKIES]
    if os.path.sep not in YTDLP_COOKIES and "/" not in YTDLP_COOKIES and not YTDLP_COOKIES.endswith(".txt"):
        print(f"   从浏览器读取 cookies: {YTDLP_COOKIES}")
        return args + ["--cookies-from-browser", YTDLP_COOKIES]
    print(f"   ⚠ cookies 文件不存在: {YTDLP_COOKIES}，将不使用 cookies")
    return args


def step1_download_video(url, output_dir):
    """第一步：下载 YouTube 视频"""
    print("\n" + "=" * 60)
    print("📥 第一步：下载视频...")
    print("=" * 60)

    output_template = os.path.join(output_dir, "%(title)s.%(ext)s")

    fmt = (
        f"bestvideo[height<={MAX_VIDEO_HEIGHT}]+bestaudio"
        f"/best[height<={MAX_VIDEO_HEIGHT}]"
        f"/bestvideo+bestaudio"
        f"/best"
    )
    cmd = [
        "yt-dlp",
        "-f", fmt,
        "--merge-output-format", "mp4",
        "-o", output_template,
        "--no-playlist",
    ]
    cmd += _ytdlp_extra_args()
    cmd.append(url)

    subprocess.run(cmd, check=True)

    mp4_files = list(Path(output_dir).glob("*.mp4"))
    if not mp4_files:
        raise FileNotFoundError("未找到下载的视频文件！")

    video_path = max(mp4_files, key=os.path.getmtime)
    print(f"✅ 视频已下载: {video_path}")

    # 用 ffprobe 读取并打印视频规格
    try:
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,codec_name,bit_rate",
            "-show_entries", "format=duration,size,bit_rate",
            "-of", "default=noprint_wrappers=1",
            str(video_path)
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        info_lines = {}
        for line in probe_result.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info_lines[k.strip()] = v.strip()

        width     = info_lines.get("width", "?")
        height    = info_lines.get("height", "?")
        codec     = info_lines.get("codec_name", "?")
        fps_raw   = info_lines.get("r_frame_rate", "?")
        duration  = float(info_lines.get("duration", 0))
        filesize  = int(info_lines.get("size", 0))
        vbitrate  = info_lines.get("bit_rate", "?")

        # 计算帧率（分数形式如 24000/1001）
        if "/" in fps_raw:
            num, den = fps_raw.split("/")
            fps_val = f"{int(num)/int(den):.2f}"
        else:
            fps_val = fps_raw

        h = int(duration) // 3600
        m = (int(duration) % 3600) // 60
        s = int(duration) % 60
        dur_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        size_mb = filesize / 1024 / 1024

        vbr_str = f"{int(vbitrate)//1000} kbps" if vbitrate.isdigit() else vbitrate

        print(f"   📐 分辨率:  {width}x{height}")
        print(f"   🎞️  编码:    {codec}")
        print(f"   ⏱️  帧率:    {fps_val} fps")
        print(f"   ⏳ 时长:    {dur_str}")
        print(f"   💾 文件大小: {size_mb:.1f} MB")
        print(f"   📶 视频码率: {vbr_str}")
    except Exception as e:
        print(f"  ⚠ 无法读取视频规格: {e}")

    return str(video_path)


def step1b_enhance_video(video_path):
    """步骤 1.5：使用 Real-ESRGAN 对视频进行 AI 超分辨率画质增强"""
    print("\n" + "=" * 60)
    print("✨ 步骤 1.5：AI 画质增强（Real-ESRGAN 超分辨率）...")
    print("=" * 60)

    base = video_path.rsplit(".", 1)[0]
    enhanced_path = base + "_enhanced.mp4"

    if os.path.exists(enhanced_path):
        print(f"⏭️  增强视频已存在，跳过: {enhanced_path}")
        return enhanced_path

    try:
        import cv2
        import torch
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer
    except (ImportError, OSError) as e:
        err = str(e)
        if "lzma" in err.lower() or "liblzma" in err.lower():
            raise RuntimeError(
                "画质增强初始化失败：缺少 liblzma.dll\n"
                "修复方法：将 miniconda3/Library/bin/liblzma.dll 复制到\n"
                "  envs/aiText/Library/bin/ 目录下\n"
                f"错误详情: {e}"
            )
        raise RuntimeError(
            "画质增强需要额外依赖，请运行：\n"
            "  pip install realesrgan basicsr opencv-python\n"
            f"错误详情: {e}"
        )

    model_name = ENHANCE_MODEL
    outscale   = ENHANCE_OUTSCALE

    MODEL_CONFIGS = {
        "RealESRGAN_x4plus": {
            "num_block": 23, "net_scale": 4,
            "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        },
        "RealESRGAN_x4plus_anime_6B": {
            "num_block": 6, "net_scale": 4,
            "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        },
        "RealESRGAN_x2plus": {
            "num_block": 23, "net_scale": 2,
            "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
        },
    }
    if model_name not in MODEL_CONFIGS:
        raise ValueError(f"不支持的增强模型：{model_name}。可选：{list(MODEL_CONFIGS.keys())}")

    cfg    = MODEL_CONFIGS[model_name]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    half   = device.type == "cuda"

    # tile=1024：1080p 只分 4 块（2×2），比 512 少 3 倍；整帧(tile=0)会 OOM
    tile_size = 1024 if device.type == "cuda" else 512

    model = RRDBNet(
        num_in_ch=3, num_out_ch=3, num_feat=64,
        num_block=cfg["num_block"], num_grow_ch=32, scale=cfg["net_scale"],
    )
    upsampler = RealESRGANer(
        scale=cfg["net_scale"],
        model_path=cfg["url"],
        model=model,
        tile=tile_size,
        tile_pad=10,
        pre_pad=0,
        half=half,
        device=device,
    )

    cap   = cv2.VideoCapture(video_path)
    fps   = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # 限制输出最大 4K（3840×2160）
    max_w, max_h = 3840, 2160
    effective_outscale = min(float(outscale), max_w / w, max_h / h)
    if effective_outscale < outscale:
        print(f"⚠️  输出超过 4K，放大倍数自动调整: {outscale}x → {effective_outscale:.2f}x")
    outscale = effective_outscale

    out_w = int(w * outscale)
    out_h = int(h * outscale)
    dur_min = total / fps / 60 if fps > 0 else 0

    print(f"模型: {model_name}  放大: {outscale:.2f}x  设备: {device}  tile: {tile_size}")
    print(f"分辨率: {w}x{h} → {out_w}x{out_h}  帧率: {fps:.2f}  总帧数: {total}")
    if dur_min > 5:
        print(f"⚠️  视频较长（{dur_min:.0f} 分钟），AI 增强耗时可能数倍于视频时长，请耐心等待。")

    tmp_video = base + "_enhanced_noaudio.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(tmp_video, fourcc, fps, (out_w, out_h))

    import io
    from tqdm import tqdm

    _devnull = io.StringIO()

    with tqdm(total=total, desc="  AI增强进度", unit="帧",
              bar_format="{desc}: {percentage:3.0f}%|{bar}| {n}/{total} 帧 [{elapsed}<{remaining}]",
              dynamic_ncols=True) as pbar:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            _orig, sys.stdout = sys.stdout, _devnull
            try:
                output, _ = upsampler.enhance(img_rgb, outscale=outscale)
            finally:
                sys.stdout = _orig
            writer.write(cv2.cvtColor(output, cv2.COLOR_RGB2BGR))
            pbar.update(1)

    cap.release()
    writer.release()

    print("合并原始音轨...")
    cmd_merge = [
        "ffmpeg",
        "-i", tmp_video,
        "-i", video_path,
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-c:a", "copy",
        "-map", "0:v:0", "-map", "1:a?",
        "-shortest", "-y", enhanced_path,
    ]
    subprocess.run(cmd_merge, check=True, capture_output=True)
    os.remove(tmp_video)

    print(f"✅ 增强视频已生成: {enhanced_path}")
    return enhanced_path


def step2_transcribe(video_path):
    """第二步：用 Whisper 识别语音，生成外语字幕"""
    print("\n" + "=" * 60)
    print("🎤 第二步：语音识别生成外语字幕（本地 GPU）...")
    print("=" * 60)

    en_srt_path = video_path.rsplit(".", 1)[0] + "_en.srt"
    if os.path.exists(en_srt_path):
        print(f"⏭️  外语字幕已存在，跳过转录: {en_srt_path}")
        with open(en_srt_path, encoding="utf-8") as f:
            subs = list(srt.parse(f.read()))
        print(f"   ↳ 共读取 {len(subs)} 条字幕")
        return en_srt_path, subs

    from faster_whisper import WhisperModel

    print(f"加载模型 '{WHISPER_MODEL}'（首次运行会自动下载，请耐心等待）...")
    model = WhisperModel(WHISPER_MODEL, device=DEVICE, compute_type=COMPUTE_TYPE)

    print("开始转录...")
    lang_arg = VIDEO_LANGUAGE if VIDEO_LANGUAGE else None
    if lang_arg:
        print(f"指定识别语言: {lang_arg}")
    else:
        print("语言设置为 null，将自动检测...")
    segments, info = model.transcribe(
        video_path,
        language=lang_arg,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        word_timestamps=True,
    )

    print(f"检测到语言: {info.language}, 置信度: {info.language_probability:.2f}")

    gap_threshold = SUBTITLE_MAX_GAP_MS / 1000.0  # 转为秒
    max_chars = SUBTITLE_MAX_CHARS
    _PUNCT_BREAK = frozenset('.?!,;:…，。？！；：、')
    # 逐段收集，使 Ctrl+C 可在段间打断（list() 会在 C++ 内部阻塞直到全部完成）
    raw_segs = []
    try:
        for seg in segments:
            raw_segs.append(seg)
    except KeyboardInterrupt:
        del model
        import gc; gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        raise
    subs = []
    idx = 0

    def _flush_chunk(chunk):
        """将一组词生成一条字幕"""
        nonlocal idx
        if not chunk:
            return
        idx += 1
        text = "".join(w.word for w in chunk).strip()
        text = text.rstrip('.?!,;:…，。？！；：、')
        subs.append(srt.Subtitle(
            index=idx,
            start=timedelta(seconds=chunk[0].start),
            end=timedelta(seconds=chunk[-1].end),
            content=text
        ))

    for seg in raw_segs:
        words = seg.words if seg.words else []
        if not words:
            # 无词级时间戳时直接使用段级信息
            idx += 1
            subs.append(srt.Subtitle(
                index=idx,
                start=timedelta(seconds=seg.start),
                end=timedelta(seconds=seg.end),
                content=seg.text.strip()
            ))
        else:
            # 按词间间隙 + 最大字符数分割字幕
            # 字符超限时双向搜索最近标点，优先向前回退，其次向后预读
            LOOK_BACK = 8   # 向前（chunk 内回退）最多搜几个词
            LOOK_AHEAD = 2  # 向后（预读后续词）最多搜几个词
            chunk_words = [words[0]]
            chunk_len = len(words[0].word.strip())
            wi = 1
            while wi < len(words):
                w_prev = words[wi - 1]
                w_curr = words[wi]
                word_text = w_curr.word.strip()
                gap_break = w_curr.start - w_prev.end > gap_threshold
                len_break = chunk_len + len(word_text) > max_chars

                if gap_break:
                    _flush_chunk(chunk_words)
                    chunk_words = []
                    chunk_len = 0
                elif len_break:
                    # ── 向前搜：在已有 chunk 中回退找标点 ──────────────
                    back_at = -1
                    search_back_from = len(chunk_words) - 1
                    search_back_to   = max(0, len(chunk_words) - LOOK_BACK)
                    for bi in range(search_back_from, search_back_to - 1, -1):
                        if chunk_words[bi].word.rstrip()[-1:] in _PUNCT_BREAK:
                            back_at = bi
                            break

                    if back_at >= 0:
                        _flush_chunk(chunk_words[:back_at + 1])
                        chunk_words = chunk_words[back_at + 1:]
                        chunk_len = sum(len(w.word.strip()) for w in chunk_words)
                        # w_curr 正常追加到下面
                    else:
                        # ── 向后搜：预读后续词找标点 ──────────────────
                        ahead_at = -1
                        for ai in range(wi, min(len(words), wi + LOOK_AHEAD)):
                            if words[ai].word.rstrip()[-1:] in _PUNCT_BREAK:
                                ahead_at = ai
                                break

                        if ahead_at >= 0:
                            # 接受到标点词（含），再断句
                            for j in range(wi, ahead_at + 1):
                                chunk_words.append(words[j])
                                chunk_len += len(words[j].word.strip())
                            _flush_chunk(chunk_words)
                            chunk_words = []
                            chunk_len = 0
                            wi = ahead_at + 1
                            continue  # wi 已更新，跳过末尾追加
                        else:
                            # 两侧都没找到标点 → 直接在当前位置截断（无需标点结尾）
                            _flush_chunk(chunk_words)
                            chunk_words = []
                            chunk_len = 0

                chunk_words.append(w_curr)
                chunk_len += len(word_text)
                wi += 1
            _flush_chunk(chunk_words)
        if idx % 20 == 0 and idx > 0:
            print(f"  已处理 {idx} 条字幕...")

    # 显式释放 Whisper 模型，避免 GPU 显存残留导致后续步骤被 OS 静默终止
    del model, raw_segs
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print("  ↳ GPU 显存已释放")
    except ImportError:
        pass

    with open(en_srt_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(subs))

    print(f"✅ 外语字幕已生成: {en_srt_path} (共 {len(subs)} 条)")
    return en_srt_path, subs


def translate_batch_qwen(texts):
    """用 Qwen3.5 API 批量翻译"""
    from openai import OpenAI

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    # 每行一条字幕，要求模型按行对应输出
    user_content = "\n".join(texts)

    for attempt in range(API_RETRY):
        try:
            response = client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.3,
                max_tokens=4096,
            )

            result = response.choices[0].message.content.strip()

            # 按换行拆分
            translated_lines = [line.strip() for line in result.split("\n") if line.strip()]

            # 检查行数是否匹配
            if len(translated_lines) == len(texts):
                return translated_lines

            # 行数不匹配，如果差距不大，尝试补齐或截断
            if len(translated_lines) > len(texts):
                return translated_lines[:len(texts)]

            # 行数太少，回退逐条翻译
            print(f"    ⚠ 行数不匹配 ({len(translated_lines)} vs {len(texts)})，第 {attempt+1} 次重试...")
            continue

        except Exception as e:
            print(f"    ⚠ API 调用出错: {e}，第 {attempt+1} 次重试...")
            time.sleep(2)

    # 全部重试失败，逐条翻译
    print("    ⚠ 批量翻译失败，回退逐条翻译...")
    return translate_one_by_one(texts)


def translate_one_by_one(texts):
    """逐条翻译（兜底方案）"""
    from openai import OpenAI

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    results = []

    for text in texts:
        try:
            response = client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {"role": "system", "content": "将以下英文翻译成简体中文，只输出翻译结果："},
                    {"role": "user", "content": text}
                ],
                temperature=0.3,
                max_tokens=256,
                extra_body={"enable_thinking": False},
            )
            translated = response.choices[0].message.content.strip()
            results.append(translated if translated else text)
        except Exception:
            results.append(text)
        time.sleep(0.5)  # 逐条翻译时加点间隔

    return results


def step3_translate(subs, video_path):
    """第三步：用 Qwen3.5 API 并发翻译字幕"""
    print("\n" + "=" * 60)
    print(f"🌐 第三步：使用 Qwen3.5 API 翻译字幕（并发 {TRANSLATE_CONCURRENCY} 批）...")
    print("=" * 60)

    zh_srt_path  = video_path.rsplit(".", 1)[0] + "_zh.srt"
    bi_srt_path  = video_path.rsplit(".", 1)[0] + "_bilingual.srt"
    if os.path.exists(zh_srt_path) and os.path.exists(bi_srt_path):
        print(f"⏭️  中文/双语字幕已存在，跳过翻译:")
        print(f"   ↳ {zh_srt_path}")
        print(f"   ↳ {bi_srt_path}")
        return zh_srt_path, bi_srt_path

    total = len(subs)
    # 将字幕切成若干批，记录每批的起始索引
    batches = [
        (batch_start, subs[batch_start: batch_start + TRANSLATE_BATCH_SIZE])
        for batch_start in range(0, total, TRANSLATE_BATCH_SIZE)
    ]
    batch_count = len(batches)
    print(f"共 {total} 条字幕，分 {batch_count} 批，每批 {TRANSLATE_BATCH_SIZE} 条，并发 {TRANSLATE_CONCURRENCY} 批")

    # results[batch_start] = [translated_text, ...]
    results = {}
    completed = 0

    def _translate_batch(batch_start, batch):
        # 轻微随机抖动，避免并发请求完全同时到达
        time.sleep(batch_start % TRANSLATE_CONCURRENCY * API_SLEEP / TRANSLATE_CONCURRENCY)
        texts = [sub.content for sub in batch]
        return batch_start, translate_batch_qwen(texts)

    executor = ThreadPoolExecutor(max_workers=TRANSLATE_CONCURRENCY)
    try:
        futures = {
            executor.submit(_translate_batch, bs, batch): bs
            for bs, batch in batches
        }
        for future in as_completed(futures):
            batch_start, translated_texts = future.result()
            results[batch_start] = translated_texts
            completed += 1
            done_subs = min(batch_start + TRANSLATE_BATCH_SIZE, total)
            print(f"  ✅ 批次 {batch_start // TRANSLATE_BATCH_SIZE + 1}/{batch_count} 完成 "
                  f"(字幕 {batch_start + 1}–{done_subs})  [{completed}/{batch_count} 批已完成]")
    except KeyboardInterrupt:
        print("\n⚠️  翻译被中断，取消剩余批次...")
        for f in futures:
            f.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)

    # 按原始顺序拼装翻译结果
    translated_subs = []
    for batch_start, batch in batches:
        translated_texts = results[batch_start]
        for j, sub in enumerate(batch):
            translated_subs.append(srt.Subtitle(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                content=translated_texts[j]
            ))

    # 保存中文 SRT
    zh_srt_path = video_path.rsplit(".", 1)[0] + "_zh.srt"
    with open(zh_srt_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(translated_subs))

    # 生成双语字幕
    bilingual_subs = []
    for orig, trans in zip(subs, translated_subs):
        bilingual_sub = srt.Subtitle(
            index=orig.index,
            start=orig.start,
            end=orig.end,
            content=f"{trans.content}\n{orig.content}"
        )
        bilingual_subs.append(bilingual_sub)

    bi_srt_path = video_path.rsplit(".", 1)[0] + "_bilingual.srt"
    with open(bi_srt_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(bilingual_subs))

    print(f"✅ 中文字幕已生成: {zh_srt_path}")
    print(f"✅ 双语字幕已生成: {bi_srt_path}")
    return zh_srt_path, bi_srt_path


def step4_burn_subtitles(video_path, srt_path):
    """第四步：将字幕烧录进视频"""
    print("\n" + "=" * 60)
    print("🔥 第四步：压制硬字幕到视频...")
    print("=" * 60)

    output_path = video_path.rsplit(".", 1)[0] + "_硬字幕.mp4"
    if os.path.exists(output_path):
        print(f"⏭️  硬字幕视频已存在，跳过压制: {output_path}")
        return output_path
    # ffmpeg subtitle filter 路径规则：反斜杠→斜杠，冒号需转义，单引号需转义
    srt_escaped = srt_path.replace("\\", "/").replace("'", "\\'").replace(":", "\\:")

    style = (
        f"FontSize={FONT_SIZE}"
        f",FontName={SUBTITLE_FONT}"
        f",PrimaryColour={SUBTITLE_PRIMARY_COLOR}"
        f",OutlineColour={SUBTITLE_OUTLINE_COLOR}"
        f",Outline={SUBTITLE_OUTLINE}"
        f",Shadow={SUBTITLE_SHADOW}"
        f",MarginV={SUBTITLE_MARGIN_V}"
        f",Bold=1"
    )
    subtitle_filter = f"subtitles='{srt_escaped}':force_style='{style}'"

    cmd = [
        "ffmpeg",
        "-hide_banner", "-loglevel", "warning", "-stats",
        "-i", video_path,
        "-vf", subtitle_filter,
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "medium",
        "-c:a", "copy",
        "-y",
        output_path
    ]

    print(f"执行命令: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    print(f"✅ 最终视频已生成: {output_path}")
    return output_path


# ======================== AI 配音步骤 ========================

def step5_separate_audio(video_path):
    """第五步：用 demucs 将音频分离为人声 + 背景音"""
    print("\n" + "=" * 60)
    print("🎵 第五步：分离音频（人声 / 背景音）...")
    print("=" * 60)

    base = video_path.rsplit(".", 1)[0]
    bg_path = base + "_background.wav"
    if os.path.exists(bg_path):
        print(f"⏭️  背景音已存在，跳过分离: {bg_path}")
        return bg_path

    output_dir = os.path.dirname(video_path)

    # 先用 ffmpeg 提取音频为 wav（demucs 需要音频输入）
    audio_path = base + "_audio.wav"
    if not os.path.exists(audio_path):
        cmd_extract = [
            "ffmpeg", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            "-y", audio_path
        ]
        print("提取音频轨...")
        subprocess.run(cmd_extract, check=True, capture_output=True)

    # 用 demucs 分离（htdemucs 模型，双轨：vocals + no_vocals）
    # 使用包装脚本 _run_demucs.py 绕过 torchaudio 2.10 对 torchcodec 的硬依赖
    print("运行 demucs 音频分离（首次运行会下载模型）...")
    wrapper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_run_demucs.py")
    cmd_demucs = [
        sys.executable, wrapper,
        "--two-stems", "vocals",
        "-n", "htdemucs",
        "-o", output_dir,
        audio_path
    ]
    subprocess.run(cmd_demucs, check=True)

    # demucs 输出结构：{output_dir}/htdemucs/{stem_name}/vocals.wav + no_vocals.wav
    stem_name = Path(audio_path).stem
    demucs_dir = os.path.join(output_dir, "htdemucs", stem_name)
    no_vocals_path = os.path.join(demucs_dir, "no_vocals.wav")

    if not os.path.exists(no_vocals_path):
        raise FileNotFoundError(f"demucs 分离失败，未找到: {no_vocals_path}")

    # 移动背景音到工作目录，清理 demucs 临时目录
    import shutil
    shutil.move(no_vocals_path, bg_path)
    shutil.rmtree(os.path.join(output_dir, "htdemucs"), ignore_errors=True)

    print(f"✅ 背景音已分离: {bg_path}")
    return bg_path


def step6_tts_generate(zh_srt_path, video_path):
    """第六步：用 edge-tts 为中文字幕生成语音"""
    print("\n" + "=" * 60)
    print("🗣️  第六步：AI 语音合成（edge-tts）...")
    print("=" * 60)

    import asyncio
    import edge_tts
    from pydub import AudioSegment

    base = video_path.rsplit(".", 1)[0]
    tts_output = base + "_tts.wav"
    if os.path.exists(tts_output):
        print(f"⏭️  TTS 语音已存在，跳过: {tts_output}")
        return tts_output

    # 读取中文字幕
    with open(zh_srt_path, encoding="utf-8") as f:
        zh_subs = list(srt.parse(f.read()))

    # 获取视频总时长（毫秒）
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    duration_s = float(subprocess.run(
        probe_cmd, capture_output=True, text=True
    ).stdout.strip() or "0")
    total_ms = int(duration_s * 1000)
    if total_ms <= 0:
        total_ms = max(int(sub.end.total_seconds() * 1000) for sub in zh_subs) + 1000

    # 创建空白静音底板
    silence = AudioSegment.silent(duration=total_ms, frame_rate=44100)

    # 临时目录存放单条 TTS 音频
    tts_tmp_dir = base + "_tts_tmp"
    os.makedirs(tts_tmp_dir, exist_ok=True)

    async def _generate_one(sub, idx, max_retries=3):
        """为单条字幕生成 TTS 音频，失败自动重试"""
        text = sub.content.strip()
        if not text:
            return None

        out_file = os.path.join(tts_tmp_dir, f"{idx:04d}.mp3")

        # 已存在则校验有效性，损坏就删掉重新生成
        if os.path.exists(out_file):
            if os.path.getsize(out_file) >= 256:
                return out_file
            os.remove(out_file)

        for attempt in range(1, max_retries + 1):
            try:
                communicate = edge_tts.Communicate(
                    text=text,
                    voice=TTS_VOICE,
                    rate=TTS_RATE,
                    volume=TTS_VOLUME,
                )
                await communicate.save(out_file)
                # 验证生成的文件
                if os.path.exists(out_file) and os.path.getsize(out_file) >= 256:
                    return out_file
                # 文件太小视为损坏
                if os.path.exists(out_file):
                    os.remove(out_file)
            except Exception as e:
                if os.path.exists(out_file):
                    os.remove(out_file)
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * attempt)
                else:
                    print(f"  ⚠️  TTS 第 {idx} 条生成失败（已重试 {max_retries} 次）: {e}")
        return None

    async def _generate_all():
        tasks = []
        for i, sub in enumerate(zh_subs):
            tasks.append(_generate_one(sub, i))
        return await asyncio.gather(*tasks)

    print(f"生成 {len(zh_subs)} 条 TTS 语音（voice={TTS_VOICE}）...")
    tts_files = asyncio.run(_generate_all())

    async def _retry_one(sub, idx):
        """拼接阶段发现损坏文件时的同步重试入口"""
        return await _generate_one(sub, idx, max_retries=3)

    # 将每条 TTS 音频按字幕时间位置叠加到静音底板
    print("拼接 TTS 音频到时间轴...")
    failed_count = 0
    for i, (sub, tts_file) in enumerate(zip(zh_subs, tts_files)):
        if tts_file is None or not os.path.exists(tts_file):
            continue

        try:
            clip = AudioSegment.from_file(tts_file)
        except Exception:
            # 解码失败：删除损坏文件，同步重试生成
            print(f"  🔄 第 {i} 条 TTS 解码失败，重新生成...")
            os.remove(tts_file)
            retry_file = asyncio.run(_retry_one(zh_subs[i], i))
            if retry_file is None:
                failed_count += 1
                continue
            try:
                clip = AudioSegment.from_file(retry_file)
            except Exception:
                failed_count += 1
                print(f"  ⚠️  第 {i} 条重试后仍无法解码，跳过")
                continue
        start_ms = int(sub.start.total_seconds() * 1000)
        end_ms = int(sub.end.total_seconds() * 1000)
        available_ms = end_ms - start_ms

        # 如果 TTS 音频比字幕时长长，用 ffmpeg atempo 加速适配
        if len(clip) > available_ms and available_ms > 0:
            speed = len(clip) / available_ms
            if speed > TTS_MAX_SPEED:
                speed = TTS_MAX_SPEED  # 限制最大加速倍率，避免语速过快
            sped_file = os.path.join(tts_tmp_dir, f"{i:04d}_fast.wav")
            cmd_speed = [
                "ffmpeg", "-i", tts_file,
                "-filter:a", f"atempo={speed:.3f}",
                "-y", sped_file
            ]
            subprocess.run(cmd_speed, capture_output=True, check=True)
            clip = AudioSegment.from_file(sped_file)

        # 叠加到对应时间位置
        silence = silence.overlay(clip, position=start_ms)

        if (i + 1) % 20 == 0:
            print(f"  已拼接 {i + 1}/{len(zh_subs)} 条...")

    if failed_count > 0:
        print(f"  ⚠️  共 {failed_count} 条 TTS 生成失败，对应位置将静音")

    # 导出最终 TTS 音轨
    silence.export(tts_output, format="wav")

    # 清理临时文件
    import shutil
    shutil.rmtree(tts_tmp_dir, ignore_errors=True)

    print(f"✅ TTS 语音已生成: {tts_output}")
    return tts_output


def step7_merge_audio(video_path, bg_path, tts_path):
    """第七步：合并背景音 + TTS 语音，替换原视频音轨
    video_path: 作为视频源的文件（可能是烧了字幕的版本，也可能是原始视频）
    输出文件名与 video_path 同名，追加 _配音 后缀，确保 skip 判断不因换源而误判。
    """
    print("\n" + "=" * 60)
    print("🎬 第七步：合并音频并生成配音视频...")
    print("=" * 60)

    base = video_path.rsplit(".", 1)[0]
    mixed_audio = base + "_mixed.wav"
    dubbed_video = base + "_配音.mp4"

    if os.path.exists(dubbed_video):
        print(f"⏭️  配音视频已存在，跳过: {dubbed_video}")
        return dubbed_video

    # 用 ffmpeg 混合背景音和 TTS 语音
    # amix: 默认会 normalize，用 volume 先调低背景音量
    bg_vol = TTS_BG_VOLUME
    print(f"混合音频（背景音量: {bg_vol}）...")
    cmd_mix = [
        "ffmpeg",
        "-i", tts_path,
        "-i", bg_path,
        "-filter_complex",
        f"[1:a]volume={bg_vol}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[out]",
        "-map", "[out]",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-y", mixed_audio
    ]
    subprocess.run(cmd_mix, check=True, capture_output=True)

    # 用 ffmpeg 替换原视频的音轨
    print("替换视频音轨...")
    cmd_replace = [
        "ffmpeg",
        "-i", video_path,
        "-i", mixed_audio,
        "-c:v", "copy",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-y", dubbed_video
    ]
    subprocess.run(cmd_replace, check=True, capture_output=True)

    # 清理中间文件
    for tmp in [mixed_audio]:
        if os.path.exists(tmp):
            os.remove(tmp)

    print(f"✅ 配音视频已生成: {dubbed_video}")
    return dubbed_video


def _prepare_source(source):
    """第一阶段：准备视频（下载或准备本地文件），返回已准备好的视频信息字典。
    成功时包含 video_path / output_dir；失败时 status='失败' 且 video_path=None。"""
    is_local = os.path.isfile(source)
    try:
        if is_local:
            video_path = os.path.abspath(source)
            video_name = _sanitize_name(Path(video_path).stem)
            output_dir = os.path.join("./output", video_name)
            os.makedirs(output_dir, exist_ok=True)

            safe_filename = video_name + Path(video_path).suffix
            target_path = os.path.join(output_dir, safe_filename)
            if os.path.abspath(video_path) != os.path.abspath(target_path):
                import shutil
                if not os.path.exists(target_path):
                    shutil.copy2(video_path, target_path)
                video_path = target_path

            print(f"📁 本地文件已准备: {video_path}")
        else:
            url = source
            temp_dir = "./output/_temp_download"
            os.makedirs(temp_dir, exist_ok=True)

            print(f"📥 下载视频: {url}")

            pre_file = None
            try:
                pre_cmd = ["yt-dlp", "--print", "title", "--no-playlist"]
                pre_cmd += _ytdlp_extra_args()
                pre_cmd.append(url)
                title_result = subprocess.run(
                    pre_cmd,
                    capture_output=True, text=True, check=True
                )
                raw_title = title_result.stdout.strip()
                pre_name = _sanitize_name(raw_title)
                pre_dir  = os.path.join("./output", pre_name)
                pre_file = os.path.join(pre_dir, pre_name + ".mp4")
            except Exception:
                pass

            if pre_file and os.path.exists(pre_file):
                print(f"⏭️  视频已存在，跳过下载: {pre_file}")
                video_path = pre_file
                output_dir = pre_dir
            else:
                video_path = step1_download_video(url, temp_dir)

                video_name = _sanitize_name(Path(video_path).stem)
                output_dir = os.path.join("./output", video_name)
                os.makedirs(output_dir, exist_ok=True)

                safe_filename = video_name + Path(video_path).suffix
                target_path = os.path.join(output_dir, safe_filename)
                if os.path.abspath(video_path) != os.path.abspath(target_path):
                    import shutil
                    shutil.move(video_path, target_path)
                    video_path = target_path

                try:
                    os.rmdir(temp_dir)
                except OSError:
                    pass

        return {
            "source": source,
            "video_path": video_path,
            "output_dir": output_dir,
            "status": "已下载",
            "error": None,
        }
    except Exception as e:
        print(f"\n❌ 下载/准备视频失败: {e}")
        return {
            "source": source,
            "video_path": None,
            "output_dir": None,
            "status": "失败",
            "last_step": "1-下载",
            "error": str(e),
        }


def _process_prepared(prepared, burn_subtitle=True, enable_dubbing=False, enable_enhance=False):
    """第二阶段：处理已下载的视频（识别 → 翻译 → 压制字幕 → 配音）。
    接受 _prepare_source() 返回的字典；若准备阶段已失败则直接透传错误结果。"""
    source = prepared["source"]

    if prepared.get("status") == "失败":
        return {
            "source": source,
            "video": None,
            "en_srt": None, "zh_srt": None, "bi_srt": None,
            "final_video": None, "dubbed_video": None,
            "status": "失败",
            "last_step": prepared.get("last_step", "1-下载"),
            "error": prepared.get("error", "下载失败"),
        }

    video_path = prepared["video_path"]
    output_dir = prepared["output_dir"]

    print(f"\n   工作目录: {os.path.abspath(output_dir)}")
    print(f"   语音识别: faster-whisper [{WHISPER_MODEL}] ← 本地 GPU")
    print(f"   翻译引擎: Qwen3.5 API [{QWEN_MODEL}] ← 云端大模型")

    current_step = "初始化"
    en_srt_path = zh_srt_path = bi_srt_path = None
    final_video = dubbed_video = None

    try:
        if enable_enhance:
            current_step = "1.5-AI画质增强"
            video_path = step1b_enhance_video(video_path)

        current_step = "2-语音识别"
        en_srt_path, subs = step2_transcribe(video_path)

        current_step = "3-翻译字幕"
        zh_srt_path, bi_srt_path = step3_translate(subs, video_path)

        if burn_subtitle:
            current_step = "4-压制字幕"
            final_video = step4_burn_subtitles(video_path, bi_srt_path)

        if enable_dubbing:
            current_step = "5-分离音频"
            bg_path = step5_separate_audio(video_path)
            current_step = "6-TTS语音合成"
            tts_path = step6_tts_generate(zh_srt_path, video_path)
            current_step = "7-合并配音"
            dub_base = final_video if final_video and os.path.exists(final_video) else video_path
            dubbed_video = step7_merge_audio(dub_base, bg_path, tts_path)

        current_step = "完成"
    except Exception as e:
        print(f"\n❌ 在步骤 [{current_step}] 失败: {e}")
        return {
            "source": source,
            "video": video_path,
            "en_srt": en_srt_path,
            "zh_srt": zh_srt_path,
            "bi_srt": bi_srt_path,
            "final_video": final_video,
            "dubbed_video": dubbed_video,
            "status": "失败",
            "last_step": current_step,
            "error": str(e),
        }

    print("\n" + "=" * 60)
    print("🎉 处理完成！")
    print("=" * 60)
    print(f"  原始视频:   {video_path}")
    if en_srt_path:
        print(f"  外语字幕:   {en_srt_path}")
    if zh_srt_path:
        print(f"  中文字幕:   {zh_srt_path}")
    if bi_srt_path:
        print(f"  双语字幕:   {bi_srt_path}")
    if final_video:
        print(f"  最终视频:   {final_video}")
    if dubbed_video:
        print(f"  配音视频:   {dubbed_video}")

    return {
        "source": source,
        "video": video_path,
        "en_srt": en_srt_path,
        "zh_srt": zh_srt_path,
        "bi_srt": bi_srt_path,
        "final_video": final_video,
        "dubbed_video": dubbed_video,
        "status": "成功",
        "last_step": "完成",
    }


def process_one(source, burn_subtitle=True, enable_dubbing=False, enable_enhance=False):
    """处理单个视频源（本地文件或 YouTube 链接）。
    组合 _prepare_source + _process_prepared，保持向后兼容。"""
    prepared = _prepare_source(source)
    return _process_prepared(prepared, burn_subtitle=burn_subtitle,
                             enable_dubbing=enable_dubbing, enable_enhance=enable_enhance)


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print('  python auto_subtitle.py <源1> [源2] [源3] ...')
        print()
        print('每个"源"可以是 YouTube 链接或本地视频路径，多个源按顺序依次处理。')
        print()
        print("示例:")
        print('  # 单个 YouTube 视频')
        print('  python auto_subtitle.py "https://www.youtube.com/watch?v=XXXXX"')
        print()
        print('  # 单个本地文件')
        print('  python auto_subtitle.py ./input/my_video.mp4')
        print()
        print('  # 批量混合（YouTube + 本地文件）')
        print('  python auto_subtitle.py "https://youtu.be/AAA" ./input/a.mp4 "https://youtu.be/BBB"')
        sys.exit(1)

    sources = sys.argv[1:]
    total = len(sources)

    try:
        results = []
        if total == 1:
            results.append(process_one(sources[0]))
        else:
            print(f"📋 批量模式：共 {total} 个任务，使用两阶段策略")

            print("\n" + "=" * 60)
            print(f"🌐 第一阶段：批量下载全部视频（共 {total} 个）")
            print("=" * 60)
            prepared_list = []
            for i, src in enumerate(sources, 1):
                print(f"\n── 下载 [{i}/{total}]: {src}")
                prepared_list.append(_prepare_source(src))

            dl_ok  = sum(1 for p in prepared_list if p.get("status") != "失败")
            dl_fail = total - dl_ok
            print(f"\n✅ 下载阶段完成：{dl_ok} 成功 / {dl_fail} 失败 / {total} 总计")

            print("\n" + "=" * 60)
            print("⚙️  第二阶段：批量处理（识别 → 翻译 → 压制字幕）")
            print("=" * 60)
            for i, prepared in enumerate(prepared_list, 1):
                print("\n" + "#" * 60)
                print(f"## 任务 [{i}/{total}]: {prepared['source']}")
                print("#" * 60)
                results.append(_process_prepared(prepared))

        _print_summary(results)
    except KeyboardInterrupt:
        print("\n\n⚠️  已中断（Ctrl+C），退出")
        os._exit(130)


def _print_summary(results):
    """打印所有任务的执行结果汇总表"""
    if not results:
        return
    print("\n" + "=" * 60)
    print("📋 执行结果汇总")
    print("=" * 60)
    success = sum(1 for r in results if r and r.get("status") == "成功")
    fail    = len(results) - success
    for i, r in enumerate(results, 1):
        if not r:
            print(f"  [{i}] ❌ 未知错误（无返回结果）")
            continue
        source = r.get("source", r.get("video", "?"))
        name = os.path.basename(source) if os.path.isfile(str(source)) else source
        if len(name) > 50:
            name = name[:47] + "..."
        status = r.get("status", "未知")
        step   = r.get("last_step", "?")
        if status == "成功":
            print(f"  [{i}] ✅ {name}  →  全部完成")
        else:
            err = r.get("error", "")
            print(f"  [{i}] ❌ {name}  →  失败于 [{step}]: {err}")
    print(f"\n  合计: {success} 成功 / {fail} 失败 / {len(results)} 总计")
    print("=" * 60)


if __name__ == "__main__":
    main()