"""
步骤 2：语音识别（Whisper 子进程）
"""
import json
import os
import subprocess
import sys

import srt

from config import (
    WHISPER_MODEL, DEVICE, COMPUTE_TYPE, VIDEO_LANGUAGE,
    SUBTITLE_MAX_GAP_MS, SUBTITLE_MAX_CHARS,
)


def step2_transcribe(video_path):
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
        return en_srt_path, subs

    wrapper = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "_run_whisper.py")
    args_json = json.dumps({
        "video_path": os.path.abspath(video_path),
        "en_srt_path": os.path.abspath(en_srt_path),
        "whisper_model": WHISPER_MODEL,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "video_language": VIDEO_LANGUAGE,
        "gap_threshold": SUBTITLE_MAX_GAP_MS / 1000.0,
        "max_chars": SUBTITLE_MAX_CHARS,
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
        raise RuntimeError(f"Whisper 转录子进程异常退出 (exit code {ret})")

    print("  ↳ GPU 显存已随子进程释放")

    with open(en_srt_path, encoding="utf-8") as f:
        subs = list(srt.parse(f.read()))
    return en_srt_path, subs
