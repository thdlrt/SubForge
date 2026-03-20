"""
步骤 5–7：AI 配音（demucs 分离 → edge-tts 合成 → 合并音轨）
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import srt

import config
from cosyvoice_manager import ensure_cosyvoice_service


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

def _qwen_tts_api_url():
    base = (config.QWEN_TTS_BASE_URL or "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
    return f"{base}/services/aigc/multimodal-generation/generation"


def _qwen_tts_download(text, out_file):
    payload = {
        "model": config.QWEN_TTS_MODEL,
        "input": {
            "text": " ".join(text.splitlines()).strip(),
            "voice": config.QWEN_TTS_VOICE,
            "language_type": "Chinese",
        },
    }
    req = urllib.request.Request(
        _qwen_tts_api_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.QWEN_TTS_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Qwen TTS 请求失败: {detail or exc}") from exc

    audio_url = body.get("output", {}).get("audio", {}).get("url")
    if not audio_url:
        message = body.get("message") or body.get("code") or "Qwen TTS 未返回音频地址"
        raise RuntimeError(message)

    with urllib.request.urlopen(audio_url, timeout=90) as audio_resp:
        with open(out_file, "wb") as f:
            f.write(audio_resp.read())


def _cosyvoice_tts_download(text, out_file):
    payload = {
        "text": " ".join(text.splitlines()).strip(),
        "mode": (config.COSYVOICE_MODE or "preset").strip().lower(),
        "voice": config.COSYVOICE_VOICE,
        "prompt_audio_path": config.COSYVOICE_PROMPT_AUDIO_PATH,
        "prompt_text": config.COSYVOICE_PROMPT_TEXT,
    }
    req = urllib.request.Request(
        f"{config.COSYVOICE_API_URL.rstrip('/')}/tts",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=float(config.COSYVOICE_REQUEST_TIMEOUT)) as resp:
            audio_bytes = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"CosyVoice 请求失败: {detail or exc}") from exc

    with open(out_file, "wb") as f:
        f.write(audio_bytes)


def _emit_tts_progress(current, total, phase, detail=""):
    current = max(int(current), 0)
    total = max(int(total), 1)
    percent = min(max(int(current * 100 / total), 0), 100)
    phase_label = {
        "generate": "生成",
        "stitch": "拼接",
        "done": "完成",
    }.get(phase, phase)
    message = f"[TTS进度][{phase_label}] {current}/{total} ({percent}%)"
    if detail:
        message += f" - {detail}"
    print(message)


def _subtitle_text(sub):
    return " ".join(part.strip() for part in sub.content.splitlines() if part.strip()).strip()


def _build_tts_units(subs, merge_max_chars: int | None = None):
    if not subs:
        return []

    units = []
    current = None
    max_gap_ms = max(int(config.TTS_MERGE_GAP_MS), 0)
    max_chars = max(int(merge_max_chars if merge_max_chars is not None else config.TTS_MERGE_MAX_CHARS), 1)

    for idx, sub in enumerate(subs):
        text = _subtitle_text(sub)
        if not text:
            continue
        start_ms = int(sub.start.total_seconds() * 1000)
        end_ms = int(sub.end.total_seconds() * 1000)

        if current is None:
            current = {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "texts": [text],
                "source_indices": [idx],
            }
            continue

        gap_ms = start_ms - current["end_ms"]
        candidate_text = "，".join(current["texts"] + [text])
        if gap_ms <= max_gap_ms and len(candidate_text) <= max_chars:
            current["texts"].append(text)
            current["end_ms"] = end_ms
            current["source_indices"].append(idx)
        else:
            units.append(current)
            current = {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "texts": [text],
                "source_indices": [idx],
            }

    if current is not None:
        units.append(current)

    for unit in units:
        unit["text"] = "，".join(unit["texts"])
    return units


def step6_tts_generate(zh_srt_path, video_path):
    """为中文字幕生成语音，支持 edge-tts / qwen tts。"""
    print("\n" + "=" * 60)
    provider = (config.TTS_PROVIDER or "edge").strip().lower()
    if provider in ("qwen_tts", "qwen-tts"):
        provider = "qwen"
    provider_label = {
        "qwen": "Qwen TTS",
        "cosyvoice": "CosyVoice",
    }.get(provider, "edge-tts")
    print(f"🗣️  第六步：AI 语音合成（{provider_label}）...")
    print("=" * 60)

    from pydub import AudioSegment
    if provider == "edge":
        import edge_tts
    elif provider == "cosyvoice":
        print("检查并自动拉起 CosyVoice 本地服务...")
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        ensure_cosyvoice_service()

    base = video_path.rsplit(".", 1)[0]
    tts_output = base + "_tts.wav"
    if os.path.exists(tts_output):
        _emit_tts_progress(1, 1, "done", "已复用现有 TTS 音频")
        print(f"⏭️  TTS 语音已存在，跳过: {tts_output}")
        return tts_output

    # 读取中文字幕
    with open(zh_srt_path, encoding="utf-8") as f:
        zh_subs = list(srt.parse(f.read()))
    merge_max = max(int(config.TTS_MERGE_MAX_CHARS), 1)
    if provider == "cosyvoice" and int(config.COSYVOICE_MERGE_MAX_CHARS) > 0:
        merge_max = min(merge_max, int(config.COSYVOICE_MERGE_MAX_CHARS))
    synth_units = _build_tts_units(zh_subs, merge_max_chars=merge_max)
    if not synth_units:
        raise RuntimeError("中文字幕为空，无法生成 TTS")
    print(
        f"TTS 分组优化：原字幕 {len(zh_subs)} 条 -> 合成分组 {len(synth_units)} 组 "
        f"(merge_gap_ms={config.TTS_MERGE_GAP_MS}, merge_max_chars={merge_max})"
    )
    if provider == "cosyvoice":
        print(
            "提示：CosyVoice 本地 GPU 推理不宜并发多路 /tts（易显存暴涨、前几段快后面像卡死）。"
            "当前按组合并后串行请求服务。"
        )

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
    total_units = max(len(synth_units), 1)
    _emit_tts_progress(0, total_units, "generate", f"准备生成 {len(synth_units)} 组语音")
    semaphore = asyncio.Semaphore(1 if provider == "cosyvoice" else (4 if provider == "qwen" else 12))

    async def _generate_one(unit, idx, max_retries=max(int(config.API_RETRY), 1)):
        text = unit["text"].strip()
        if not text:
            return idx, None
        ext = "wav" if provider in {"qwen", "cosyvoice"} else "mp3"
        out_file = os.path.join(tts_tmp_dir, f"{idx:04d}.{ext}")
        if os.path.exists(out_file):
            if os.path.getsize(out_file) >= 256:
                return idx, out_file
            os.remove(out_file)
        for attempt in range(1, max_retries + 1):
            try:
                async with semaphore:
                    if provider == "qwen":
                        if not config.QWEN_TTS_API_KEY:
                            raise RuntimeError("未配置 qwen_tts_api_key")
                        await asyncio.to_thread(_qwen_tts_download, text, out_file)
                    elif provider == "cosyvoice":
                        await asyncio.to_thread(_cosyvoice_tts_download, text, out_file)
                    else:
                        communicate = edge_tts.Communicate(
                            text=text, voice=config.TTS_VOICE, rate=config.TTS_RATE, volume=config.TTS_VOLUME,
                        )
                        await communicate.save(out_file)
                if os.path.exists(out_file) and os.path.getsize(out_file) >= 256:
                    return idx, out_file
                if os.path.exists(out_file):
                    os.remove(out_file)
            except Exception as e:
                if os.path.exists(out_file):
                    os.remove(out_file)
                if attempt < max_retries:
                    await asyncio.sleep(max(float(config.API_SLEEP), 0.5) * attempt)
                else:
                    print(f"  ⚠️  TTS 第 {idx} 条生成失败（已重试 {max_retries} 次）: {e}")
        return idx, None

    async def _generate_all():
        results = [None] * len(synth_units)
        # CosyVoice：严格串行，避免多请求抢同一块 GPU + 模型内部状态，造成「前几段快、后面卡死」
        if provider == "cosyvoice":
            for i, unit in enumerate(synth_units):
                idx, out_file = await _generate_one(unit, i)
                results[idx] = out_file
                _emit_tts_progress(i + 1, total_units, "generate", f"已生成 {i + 1}/{len(synth_units)} 组")
            return results
        tasks = [asyncio.create_task(_generate_one(unit, i)) for i, unit in enumerate(synth_units)]
        completed = 0
        for task in asyncio.as_completed(tasks):
            idx, out_file = await task
            results[idx] = out_file
            completed += 1
            _emit_tts_progress(completed, total_units, "generate", f"已生成 {completed}/{len(synth_units)} 组")
        return results

    if provider == "qwen":
        active_voice = config.QWEN_TTS_VOICE
    elif provider == "cosyvoice":
        active_voice = (
            f"{config.COSYVOICE_MODE}:{os.path.basename(config.COSYVOICE_PROMPT_AUDIO_PATH) or config.COSYVOICE_VOICE}"
            if (config.COSYVOICE_MODE or "preset").strip().lower() != "preset"
            else config.COSYVOICE_VOICE
        )
    else:
        active_voice = config.TTS_VOICE
    print(f"生成 {len(synth_units)} 组 TTS 语音（provider={provider}, voice={active_voice}）...")
    tts_files = asyncio.run(_generate_all())

    async def _retry_one(unit, idx):
        return await _generate_one(unit, idx, max_retries=max(int(config.API_RETRY), 1))

    # ---- 拼接到时间轴 --------------------------------------------------

    print("拼接 TTS 音频到时间轴...")
    failed_count = 0
    _emit_tts_progress(0, total_units, "stitch", f"开始拼接 {len(synth_units)} 组语音")
    for i, (unit, tts_file) in enumerate(zip(synth_units, tts_files)):
        if tts_file is None or not os.path.exists(tts_file):
            _emit_tts_progress(i + 1, total_units, "stitch", f"已拼接 {i + 1}/{len(synth_units)} 组")
            continue
        try:
            clip = AudioSegment.from_file(tts_file)
        except Exception:
            print(f"  🔄 第 {i} 条 TTS 解码失败，重新生成...")
            os.remove(tts_file)
            retry_file = asyncio.run(_retry_one(synth_units[i], i))
            if retry_file is None:
                failed_count += 1
                _emit_tts_progress(i + 1, total_units, "stitch", f"已拼接 {i + 1}/{len(synth_units)} 组")
                continue
            try:
                clip = AudioSegment.from_file(retry_file)
            except Exception:
                failed_count += 1
                print(f"  ⚠️  第 {i} 条重试后仍无法解码，跳过")
                _emit_tts_progress(i + 1, total_units, "stitch", f"已拼接 {i + 1}/{len(synth_units)} 组")
                continue

        start_ms = unit["start_ms"]
        end_ms = unit["end_ms"]
        available_ms = end_ms - start_ms

        if len(clip) > available_ms and available_ms > 0:
            speed = min(len(clip) / available_ms, config.TTS_MAX_SPEED)
            sped_file = os.path.join(tts_tmp_dir, f"{i:04d}_fast.wav")
            cmd_speed = [
                "ffmpeg", "-i", tts_file,
                "-filter:a", f"atempo={speed:.3f}",
                "-y", sped_file,
            ]
            subprocess.run(cmd_speed, capture_output=True, check=True)
            clip = AudioSegment.from_file(sped_file)

        silence = silence.overlay(clip, position=start_ms)
        _emit_tts_progress(i + 1, total_units, "stitch", f"已拼接 {i + 1}/{len(synth_units)} 组")

        if (i + 1) % 20 == 0:
            print(f"  已拼接 {i + 1}/{len(synth_units)} 组...")

    if failed_count > 0:
        print(f"  ⚠️  共 {failed_count} 条 TTS 生成失败，对应位置将静音")

    silence.export(tts_output, format="wav")
    shutil.rmtree(tts_tmp_dir, ignore_errors=True)

    _emit_tts_progress(total_units, total_units, "done", "TTS 语音生成完成")
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

    bg_vol = config.TTS_BG_VOLUME
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
