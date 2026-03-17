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
    TTS_CONCURRENCY,
)


def step5_separate_audio(video_path):
    """用 demucs 将音频分离为人声 + 背景音"""
    print("\n" + "=" * 60)
    print("🎍 第五步：分离音频（人声 / 背景音）...")
    print("=" * 60)

    base = video_path.rsplit(".", 1)[0]
    bg_path = base + "_background.wav"
    if os.path.exists(bg_path):
        print(f"⏭️  背景音已存在，跳过分离: {bg_path}")
        return bg_path

    output_dir = os.path.dirname(video_path)
    audio_path = base + "_audio.wav"
    if not os.path.exists(audio_path):
        cmd_extract = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-i", video_path,
            "-vn", "-sn", "-dn",
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            "-y",
            audio_path,
        ]
        print("提取音频轨...")
        subprocess.run(cmd_extract, check=True, capture_output=True)

    print("运行 demucs 音频分离（首次运行会下载模型）...")
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wrapper = os.path.join(project_root, "_run_demucs.py")
    cmd_demucs = [
        sys.executable, wrapper,
        "--two-stems", "vocals",
        "-n", "htdemucs",
        "-o", output_dir,
        audio_path,
    ]
    subprocess.run(cmd_demucs, check=True)

    stem_name = Path(audio_path).stem
    demucs_dir = os.path.join(output_dir, "htdemucs", stem_name)
    no_vocals_path = os.path.join(demucs_dir, "no_vocals.wav")

    if not os.path.exists(no_vocals_path):
        raise FileNotFoundError(f"demucs 分离失败，未找到: {no_vocals_path}")

    shutil.move(no_vocals_path, bg_path)
    shutil.rmtree(os.path.join(output_dir, "htdemucs"), ignore_errors=True)

    print(f"✅ 背景音已分离: {bg_path}")
    return bg_path


def _escape_ffmpeg_filter_path(path):
    return path.replace("\\", "/").replace("'", "\\'").replace(":", "\\:")


def _probe_audio_duration_ms(audio_path):
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    result = subprocess.run(
        probe_cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=True,
    )
    duration_s = float((result.stdout or "").strip() or "0")
    return max(0, int(round(duration_s * 1000)))


def _build_atempo_filter(speed):
    filters = []
    remaining = max(float(speed), 0.01)
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.5f}")
    return ",".join(filters)


def _render_tts_track_ffmpeg(clip_entries, total_ms, output_path, work_dir):
    script_path = os.path.join(work_dir, "mix.ffscript")
    duration_s = max(total_ms, 1) / 1000.0
    labels = ["[base]"]
    lines = [f"anullsrc=r=44100:cl=stereo:d={duration_s:.3f}[base]"]

    for idx, clip in enumerate(clip_entries):
        label = f"[a{idx}]"
        clip_path = _escape_ffmpeg_filter_path(clip["path"])
        start_ms = max(0, int(clip["start_ms"]))
        lines.append(
            f"amovie='{clip_path}',"
            "aresample=44100,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"adelay={start_ms}|{start_ms}{label}"
        )
        labels.append(label)

    lines.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0[out]"
    )
    Path(script_path).write_text(";\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        "ffmpeg",
        "-hide_banner", "-loglevel", "error", "-stats",
        "-/filter_complex", script_path,
        "-map", "[out]",
        "-c:a", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        "-y",
        output_path,
    ]
    subprocess.run(cmd, check=True)


def _render_tts_track_pydub(clip_entries, total_ms, output_path):
    from pydub import AudioSegment

    timeline = AudioSegment.silent(duration=total_ms, frame_rate=44100).set_channels(2)
    for idx, clip in enumerate(clip_entries, 1):
        segment = AudioSegment.from_file(clip["path"])
        timeline = timeline.overlay(segment, position=clip["start_ms"])
        if idx % 20 == 0:
            print(f"  已回退拼接 {idx}/{len(clip_entries)} 条...")
    timeline.export(output_path, format="wav")


def step6_tts_generate(zh_srt_path, video_path):
    """用 edge-tts 为中文字幕生成语音"""
    print("\n" + "=" * 60)
    print("🗣️  第六步：AI 语音合成（edge-tts）...")
    print("=" * 60)

    import edge_tts

    base = video_path.rsplit(".", 1)[0]
    tts_output = base + "_tts.wav"
    if os.path.exists(tts_output):
        print(f"⏭️  TTS 语音已存在，跳过: {tts_output}")
        return tts_output

    with open(zh_srt_path, encoding="utf-8") as f:
        zh_subs = list(srt.parse(f.read()))
    if not zh_subs:
        raise RuntimeError(f"中文字幕为空，无法生成 TTS: {zh_srt_path}")

    total_ms = 0
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        duration_s = float(subprocess.run(
            probe_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=True,
        ).stdout.strip() or "0")
        total_ms = int(duration_s * 1000)
    except Exception:
        total_ms = 0
    if total_ms <= 0:
        total_ms = max(int(sub.end.total_seconds() * 1000) for sub in zh_subs) + 1000

    tts_tmp_dir = base + "_tts_tmp"
    os.makedirs(tts_tmp_dir, exist_ok=True)

    concurrency = max(1, int(TTS_CONCURRENCY))
    semaphore = asyncio.Semaphore(concurrency)

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
                async with semaphore:
                    communicate = edge_tts.Communicate(
                        text=text,
                        voice=TTS_VOICE,
                        rate=TTS_RATE,
                        volume=TTS_VOLUME,
                    )
                    await communicate.save(out_file)
                if os.path.exists(out_file) and os.path.getsize(out_file) >= 256:
                    return out_file
                if os.path.exists(out_file):
                    os.remove(out_file)
            except Exception as exc:
                if os.path.exists(out_file):
                    os.remove(out_file)
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * attempt)
                else:
                    print(f"  ⚠️  TTS 第 {idx} 条生成失败（已重试 {max_retries} 次）: {exc}")
        return None

    async def _generate_all():
        tasks = [_generate_one(sub, i) for i, sub in enumerate(zh_subs)]
        return await asyncio.gather(*tasks)

    async def _retry_one(sub, idx):
        return await _generate_one(sub, idx, max_retries=3)

    print(f"生成 {len(zh_subs)} 条 TTS 语音（voice={TTS_VOICE}, concurrency={concurrency}）...")
    tts_files = asyncio.run(_generate_all())

    print("整理 TTS 片段并拼接到时间轴...")
    failed_count = 0
    max_speed = max(1.0, float(TTS_MAX_SPEED))
    clip_entries = []

    for i, (sub, tts_file) in enumerate(zip(zh_subs, tts_files)):
        if tts_file is None or not os.path.exists(tts_file):
            continue

        try:
            clip_ms = _probe_audio_duration_ms(tts_file)
        except Exception:
            print(f"  🔄 第 {i} 条 TTS 探测失败，重新生成...")
            try:
                os.remove(tts_file)
            except OSError:
                pass
            retry_file = asyncio.run(_retry_one(zh_subs[i], i))
            if retry_file is None:
                failed_count += 1
                continue
            try:
                clip_ms = _probe_audio_duration_ms(retry_file)
                tts_file = retry_file
            except Exception:
                failed_count += 1
                print(f"  ⚠️  第 {i} 条重试后仍无法读取，跳过")
                continue

        start_ms = int(sub.start.total_seconds() * 1000)
        end_ms = int(sub.end.total_seconds() * 1000)
        available_ms = end_ms - start_ms

        prepared_path = tts_file
        if clip_ms > available_ms and available_ms > 0:
            speed = min(clip_ms / available_ms, max_speed)
            if speed > 1.0001:
                sped_file = os.path.join(tts_tmp_dir, f"{i:04d}_fast.wav")
                cmd_speed = [
                    "ffmpeg",
                    "-hide_banner", "-loglevel", "error",
                    "-i", tts_file,
                    "-filter:a", _build_atempo_filter(speed),
                    "-ar", "44100",
                    "-ac", "2",
                    "-y", sped_file,
                ]
                subprocess.run(cmd_speed, capture_output=True, check=True)
                prepared_path = sped_file

        clip_entries.append({
            "path": prepared_path,
            "start_ms": start_ms,
        })

        if (i + 1) % 20 == 0:
            print(f"  已整理 {i + 1}/{len(zh_subs)} 条...")

    if failed_count > 0:
        print(f"  ⚠️  共 {failed_count} 条 TTS 生成失败，对应位置将静音")

    clip_entries.sort(key=lambda item: item["start_ms"])

    try:
        _render_tts_track_ffmpeg(clip_entries, total_ms, tts_output, tts_tmp_dir)
        print("  ↳ 已使用 ffmpeg 一次性混音")
    except Exception as exc:
        print(f"  ⚠️  ffmpeg 混音失败，回退到 pydub: {exc}")
        _render_tts_track_pydub(clip_entries, total_ms, tts_output)

    shutil.rmtree(tts_tmp_dir, ignore_errors=True)

    print(f"✅ TTS 语音已生成: {tts_output}")
    return tts_output


def step7_merge_audio(video_path, bg_path, tts_path):
    """合并背景音 + TTS 语音，并直接输出最终配音视频"""
    print("\n" + "=" * 60)
    print("🎀 第七步：合并音频并生成配音视频...")
    print("=" * 60)

    base = video_path.rsplit(".", 1)[0]
    dubbed_video = base + "_配音.mp4"

    if os.path.exists(dubbed_video):
        print(f"⏭️  配音视频已存在，跳过: {dubbed_video}")
        return dubbed_video

    bg_vol = TTS_BG_VOLUME
    print(f"混合音频并封装视频（背景音量: {bg_vol}）...")
    cmd = [
        "ffmpeg",
        "-hide_banner", "-loglevel", "error", "-stats",
        "-i", video_path,
        "-i", tts_path,
        "-i", bg_path,
        "-filter_complex",
        f"[2:a]volume={bg_vol}[bg];[1:a][bg]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[out]",
        "-map", "0:v:0",
        "-map", "[out]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-y", dubbed_video,
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    print(f"✅ 配音视频已生成: {dubbed_video}")
    return dubbed_video
