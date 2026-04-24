"""
步骤 2：语音识别（Whisper 子进程）
"""
import json
import os
import re
import subprocess
import sys
from collections import Counter

import srt

import config


_SPEAKER_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s+")


def _all_subtitles_have_speaker_prefix(subs) -> bool:
    texts = [(sub.content or "").strip() for sub in subs if (sub.content or "").strip()]
    return bool(texts) and all(_SPEAKER_PREFIX_RE.match(text) for text in texts)


def _speaker_summary(subs) -> str:
    counts: Counter = Counter()
    for sub in subs:
        text = (sub.content or "").strip()
        match = re.match(r"^\[([^\]]+)\]", text)
        if match:
            counts[match.group(1)] += 1
    if not counts:
        return "未识别到说话人标签"
    return "，".join(f"{speaker}: {count} 条" for speaker, count in sorted(counts.items()))


def _apply_speaker_diarization(media_path, en_srt_path, subs):
    if _all_subtitles_have_speaker_prefix(subs):
        print(f"⏭️  字幕已带说话人标签，跳过区分（{_speaker_summary(subs)}）")
        return subs

    wrapper = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "_run_diarization.py",
    )
    args_json = json.dumps({
        "media_path": os.path.abspath(media_path),
        "srt_path": os.path.abspath(en_srt_path),
        "hf_token": config.SPEAKER_DIARIZATION_HF_TOKEN,
        "model_name": config.SPEAKER_DIARIZATION_MODEL,
        "device_name": config.SPEAKER_DIARIZATION_DEVICE,
        "label_prefix": config.SPEAKER_DIARIZATION_LABEL_PREFIX,
    }, ensure_ascii=False)

    proc = subprocess.Popen(
        [sys.executable, "-u", wrapper, args_json],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout:
        print(line, end="", flush=True)
    ret = proc.wait()
    if ret != 0:
        raise RuntimeError(f"说话人区分子进程异常退出 (exit code {ret})")

    with open(en_srt_path, encoding="utf-8") as f:
        return list(srt.parse(f.read()))


def step2_transcribe(video_path, enable_speaker_diarization=False):
    """用 Whisper 识别语音，生成外语字幕。
    在独立子进程中运行，子进程退出时 OS 自动回收 GPU 显存。"""
    print("\n" + "=" * 60)
    print("🎤 第二步：语音识别生成外语字幕（本地 GPU）...")
    print("=" * 60)

    en_srt_path = video_path.rsplit(".", 1)[0] + "_en.srt"
    if os.path.exists(en_srt_path):
        print(f"⏭️  外语字幕已存在，跳过转录: {en_srt_path}")
        with open(en_srt_path, encoding="utf-8") as f:
            subs = list(srt.parse(f.read()))
        print(f"   ↳ 共读取 {len(subs)} 条字幕")
        if enable_speaker_diarization:
            print("🗣️  已启用说话人区分，尝试为现有字幕补充标签...")
            subs = _apply_speaker_diarization(video_path, en_srt_path, subs)
        return en_srt_path, subs

    wrapper = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "_run_whisper.py")
    args_json = json.dumps({
        "video_path": os.path.abspath(video_path),
        "en_srt_path": os.path.abspath(en_srt_path),
        "whisper_model": config.WHISPER_MODEL,
        "device": config.DEVICE,
        "compute_type": config.COMPUTE_TYPE,
        "video_language": config.VIDEO_LANGUAGE,
        "gap_threshold": config.SUBTITLE_MAX_GAP_MS / 1000.0,
        "max_chars": config.SUBTITLE_MAX_CHARS,
        "target_chars_ratio": config.SUBTITLE_TARGET_CHARS_RATIO,
        "min_chars_ratio": config.SUBTITLE_MIN_CHARS_RATIO,
        "hard_max_chars_ratio": config.SUBTITLE_HARD_MAX_CHARS_RATIO,
        "hard_max_chars_bias": config.SUBTITLE_HARD_MAX_CHARS_BIAS,
        "soft_max_duration_sec": config.SUBTITLE_SOFT_MAX_DURATION_SEC,
        "hard_max_duration_sec": config.SUBTITLE_HARD_MAX_DURATION_SEC,
        "min_words": config.SUBTITLE_MIN_WORDS,
        "merge_max_gap_sec": config.SUBTITLE_MERGE_MAX_GAP_SEC,
        "merge_max_duration_sec": config.SUBTITLE_MERGE_MAX_DURATION_SEC,
        "merge_max_chars_ratio": config.SUBTITLE_MERGE_MAX_CHARS_RATIO,
        "merge_max_chars_bias": config.SUBTITLE_MERGE_MAX_CHARS_BIAS,
        "short_tail_max_words": config.SUBTITLE_SHORT_TAIL_MAX_WORDS,
        "short_tail_max_chars": config.SUBTITLE_SHORT_TAIL_MAX_CHARS,
        "short_tail_max_duration_sec": config.SUBTITLE_SHORT_TAIL_MAX_DURATION_SEC,
        "split_max_duration_sec": config.SUBTITLE_SPLIT_MAX_DURATION_SEC,
    }, ensure_ascii=False)

    proc = subprocess.Popen(
        [sys.executable, "-u", wrapper, args_json],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout:
        print(line, end="", flush=True)
    ret = proc.wait()

    if ret != 0:
        # Windows + CUDA 下可能在进程退出阶段异常，但字幕文件已成功写出。
        # 若输出可读且非空，则视为成功并继续后续流程。
        if os.path.exists(en_srt_path):
            try:
                with open(en_srt_path, encoding="utf-8") as f:
                    subs = list(srt.parse(f.read()))
                if subs:
                    print(f"⚠️ Whisper 子进程异常退出 (exit code {ret})，但字幕已生成且可读取，继续后续步骤。")
                    print("  ↳ GPU 显存已随子进程释放")
                    if enable_speaker_diarization:
                        print("🗣️  已启用说话人区分，继续处理字幕标签...")
                        subs = _apply_speaker_diarization(video_path, en_srt_path, subs)
                    return en_srt_path, subs
            except Exception:
                pass
        raise RuntimeError(f"Whisper 转录子进程异常退出 (exit code {ret})")

    print("  ↳ GPU 显存已随子进程释放")

    with open(en_srt_path, encoding="utf-8") as f:
        subs = list(srt.parse(f.read()))
    if enable_speaker_diarization:
        print("🗣️  已启用说话人区分，处理字幕标签...")
        subs = _apply_speaker_diarization(video_path, en_srt_path, subs)
    return en_srt_path, subs
