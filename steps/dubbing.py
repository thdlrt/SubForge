"""
步骤 5–7：AI 配音（demucs 分离 → edge-tts 合成 → 合并音轨）
"""
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import srt

from config import (
    TTS_VOICE, TTS_RATE, TTS_VOLUME, TTS_BG_VOLUME, TTS_MAX_SPEED,
)


# ---------------------------------------------------------------------------
# 步骤 5：分离音频
# ---------------------------------------------------------------------------

def step5_separate_audio(video_path):
    """用 demucs 将音频分离为人声 + 背景音"""
    print("\n" + "=" * 60)
    print("🎵 第五步：分离音频（人声 / 背景音）...")
    print("=" * 60)

    base = video_path.rsplit(".", 1)[0]
    bg_path = base + "_background.wav"
    if os.path.exists(bg_path):
        print(f"⏭️  背景音已存在，跳过分离: {bg_path}")
        return bg_path

    output_dir = os.path.dirname(video_path)

    # 用 ffmpeg 提取音频为 wav
    audio_path = base + "_audio.wav"
    if not os.path.exists(audio_path):
        cmd_extract = [
            "ffmpeg", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            "-y", audio_path,
        ]
        print("提取音频轨...")
        subprocess.run(cmd_extract, check=True, capture_output=True)

    # 用包装脚本运行 demucs（绕过 torchaudio 对 torchcodec 的硬依赖）
    print("运行 demucs 音频分离（首次运行会下载模型）...")
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wrapper = os.path.join(_project_root, "_run_demucs.py")
    cmd_demucs = [
        sys.executable, wrapper,
        "--two-stems", "vocals",
        "-n", "htdemucs",
        "-o", output_dir,
        audio_path,
    ]
    subprocess.run(cmd_demucs, check=True)

    # demucs 输出：{output_dir}/htdemucs/{stem_name}/no_vocals.wav
    stem_name = Path(audio_path).stem
    demucs_dir = os.path.join(output_dir, "htdemucs", stem_name)
    no_vocals_path = os.path.join(demucs_dir, "no_vocals.wav")

    if not os.path.exists(no_vocals_path):
        raise FileNotFoundError(f"demucs 分离失败，未找到: {no_vocals_path}")

    shutil.move(no_vocals_path, bg_path)
    shutil.rmtree(os.path.join(output_dir, "htdemucs"), ignore_errors=True)

    print(f"✅ 背景音已分离: {bg_path}")
    return bg_path


# ---------------------------------------------------------------------------
# 步骤 6：TTS 语音合成
# ---------------------------------------------------------------------------

def step6_tts_generate(zh_srt_path, video_path):
    """用 edge-tts 为中文字幕生成语音"""
    print("\n" + "=" * 60)
    print("🗣️  第六步：AI 语音合成（edge-tts）...")
    print("=" * 60)

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
        video_path,
    ]
    duration_s = float(subprocess.run(
        probe_cmd, capture_output=True, text=True,
    ).stdout.strip() or "0")
    total_ms = int(duration_s * 1000)
    if total_ms <= 0:
        total_ms = max(int(sub.end.total_seconds() * 1000) for sub in zh_subs) + 1000

    # 空白静音底板
    silence = AudioSegment.silent(duration=total_ms, frame_rate=44100)

    tts_tmp_dir = base + "_tts_tmp"
    os.makedirs(tts_tmp_dir, exist_ok=True)

    # ---- 异步 TTS 生成 ------------------------------------------------

    async def _generate_one(sub, idx, max_retries=3):
        text = sub.content.strip()
        if not text:
            return None
        out_file = os.path.join(tts_tmp_dir, f"{idx:04d}.mp3")
        if os.path.exists(out_file):
            if os.path.getsize(out_file) >= 256:
                return out_file
            os.remove(out_file)
        for attempt in range(1, max_retries + 1):
            try:
                communicate = edge_tts.Communicate(
                    text=text, voice=TTS_VOICE, rate=TTS_RATE, volume=TTS_VOLUME,
                )
                await communicate.save(out_file)
                if os.path.exists(out_file) and os.path.getsize(out_file) >= 256:
                    return out_file
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
        return await asyncio.gather(*[_generate_one(sub, i) for i, sub in enumerate(zh_subs)])

    print(f"生成 {len(zh_subs)} 条 TTS 语音（voice={TTS_VOICE}）...")
    tts_files = asyncio.run(_generate_all())

    async def _retry_one(sub, idx):
        return await _generate_one(sub, idx, max_retries=3)

    # ---- 拼接到时间轴 --------------------------------------------------

    print("拼接 TTS 音频到时间轴...")
    failed_count = 0
    for i, (sub, tts_file) in enumerate(zip(zh_subs, tts_files)):
        if tts_file is None or not os.path.exists(tts_file):
            continue
        try:
            clip = AudioSegment.from_file(tts_file)
        except Exception:
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

        if len(clip) > available_ms and available_ms > 0:
            speed = min(len(clip) / available_ms, TTS_MAX_SPEED)
            sped_file = os.path.join(tts_tmp_dir, f"{i:04d}_fast.wav")
            cmd_speed = [
                "ffmpeg", "-i", tts_file,
                "-filter:a", f"atempo={speed:.3f}",
                "-y", sped_file,
            ]
            subprocess.run(cmd_speed, capture_output=True, check=True)
            clip = AudioSegment.from_file(sped_file)

        silence = silence.overlay(clip, position=start_ms)

        if (i + 1) % 20 == 0:
            print(f"  已拼接 {i + 1}/{len(zh_subs)} 条...")

    if failed_count > 0:
        print(f"  ⚠️  共 {failed_count} 条 TTS 生成失败，对应位置将静音")

    silence.export(tts_output, format="wav")
    shutil.rmtree(tts_tmp_dir, ignore_errors=True)

    print(f"✅ TTS 语音已生成: {tts_output}")
    return tts_output


# ---------------------------------------------------------------------------
# 步骤 7：合并音频 + 替换音轨
# ---------------------------------------------------------------------------

def step7_merge_audio(video_path, bg_path, tts_path):
    """合并背景音 + TTS 语音，替换原视频音轨"""
    print("\n" + "=" * 60)
    print("🎬 第七步：合并音频并生成配音视频...")
    print("=" * 60)

    base = video_path.rsplit(".", 1)[0]
    mixed_audio = base + "_mixed.wav"
    dubbed_video = base + "_配音.mp4"

    if os.path.exists(dubbed_video):
        print(f"⏭️  配音视频已存在，跳过: {dubbed_video}")
        return dubbed_video

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
        "-y", mixed_audio,
    ]
    subprocess.run(cmd_mix, check=True, capture_output=True)

    print("替换视频音轨...")
    cmd_replace = [
        "ffmpeg",
        "-i", video_path,
        "-i", mixed_audio,
        "-c:v", "copy",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-y", dubbed_video,
    ]
    subprocess.run(cmd_replace, check=True, capture_output=True)

    if os.path.exists(mixed_audio):
        os.remove(mixed_audio)

    print(f"✅ 配音视频已生成: {dubbed_video}")
    return dubbed_video
