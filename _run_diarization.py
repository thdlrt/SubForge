"""
Wrapper script: apply speaker diarization to an SRT file in an isolated child process.

Usage: python _run_diarization.py <json_args>
"""
import json
import io
import os
import re
import sys
import warnings
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout

import numpy as np
import srt


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s+")

warnings.filterwarnings(
    "ignore",
    message=r"\s*torchcodec is not installed correctly so built-in audio decoding will fail.*",
    category=UserWarning,
)


def _choose_device(device_name: str) -> str:
    requested = (device_name or "auto").strip().lower()
    if requested in {"cpu", "cuda"}:
        return requested

    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _speechbrain_device(device_name: str) -> str:
    chosen = _choose_device(device_name)
    if chosen == "cuda":
        return "cuda:0"
    return chosen


def _overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def _load_subtitles(srt_path: str):
    with open(srt_path, encoding="utf-8") as handle:
        return list(srt.parse(handle.read()))


def _speaker_counter(subtitles) -> Counter:
    counts: Counter = Counter()
    for subtitle in subtitles:
        text = (subtitle.content or "").strip()
        match = re.match(r"^\[([^\]]+)\]", text)
        if match:
            counts[match.group(1)] += 1
    return counts


def _format_speaker_summary(counts: Counter) -> str:
    if not counts:
        return "未识别到说话人标签"
    return "，".join(f"{speaker}: {count} 条" for speaker, count in sorted(counts.items()))


def _load_audio_waveform(media_path: str):
    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise RuntimeError("缺少 pydub 依赖，无法解码音频") from exc

    try:
        segment = AudioSegment.from_file(media_path)
    except Exception as exc:
        raise RuntimeError(
            f"无法通过 ffmpeg 解码音频，请确认 ffmpeg 可用且文件格式受支持: {exc}"
        ) from exc

    segment = segment.set_channels(1).set_frame_rate(16000)
    sample_rate = int(segment.frame_rate)
    sample_width = int(segment.sample_width)
    raw = np.array(segment.get_array_of_samples(), dtype=np.float32)
    if raw.size == 0:
        raise RuntimeError("音频为空，无法执行说话人区分")

    max_abs = float(1 << (8 * sample_width - 1)) if sample_width > 0 else 32768.0
    waveform = (raw / max_abs).clip(-1.0, 1.0)

    import torch

    tensor = torch.from_numpy(waveform).unsqueeze(0)
    return {"waveform": tensor, "sample_rate": sample_rate}


def _diarize_with_pyannote(model_name: str, hf_token: str, device_name: str, audio_input: dict):
    from pyannote.audio import Pipeline
    import torch

    print(f"Loading diarization model '{model_name}'...")
    silent_buffer = io.StringIO()
    with redirect_stdout(silent_buffer), redirect_stderr(silent_buffer):
        pipeline = Pipeline.from_pretrained(model_name, token=hf_token)
        target_device = _choose_device(device_name)
        pipeline.to(torch.device(target_device))
        pipeline_input = {
            "waveform": audio_input["waveform"].to(torch.device(target_device)),
            "sample_rate": audio_input["sample_rate"],
        }
        diarization = pipeline(pipeline_input)

    print(f"Running diarization on {target_device}...")

    annotation = diarization
    if hasattr(diarization, "speaker_diarization"):
        annotation = diarization.speaker_diarization
    elif isinstance(diarization, dict) and "speaker_diarization" in diarization:
        annotation = diarization["speaker_diarization"]

    if not hasattr(annotation, "itertracks"):
        raise RuntimeError(
            f"pyannote 返回了不支持的说话人区分结果类型: {type(diarization).__name__}"
        )

    segments: list[tuple[float, float, str]] = []
    for turn, _track, speaker in annotation.itertracks(yield_label=True):
        segments.append((float(turn.start), float(turn.end), str(speaker)))
    segments.sort(key=lambda item: (item[0], item[1]))
    return segments


def _slice_waveform(audio_input: dict, start_sec: float, end_sec: float):
    waveform = audio_input["waveform"]
    sample_rate = int(audio_input["sample_rate"])
    total_samples = waveform.shape[1]
    start_index = max(0, min(int(start_sec * sample_rate), total_samples))
    end_index = max(start_index + 1, min(int(end_sec * sample_rate), total_samples))
    return waveform[:, start_index:end_index]


def _estimate_speaker_count(embeddings: np.ndarray) -> int:
    sample_count = len(embeddings)
    if sample_count < 4:
        return 1 if sample_count < 2 else 2

    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    best_k = 1
    best_score = -1.0
    max_k = min(6, sample_count - 1)
    for speaker_count in range(2, max_k + 1):
        labels = AgglomerativeClustering(
            n_clusters=speaker_count,
            metric="cosine",
            linkage="average",
        ).fit_predict(embeddings)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(embeddings, labels, metric="cosine")
        if score > best_score:
            best_score = score
            best_k = speaker_count

    return best_k if best_score >= 0.02 else 1


def _diarize_with_speechbrain(audio_input: dict, subtitles, device_name: str):
    try:
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError as exc:
        raise RuntimeError(
            "缺少 speechbrain 依赖，无法使用本地说话人区分回退路径"
        ) from exc

    import torch
    import torch.nn.functional as F
    from sklearn.cluster import AgglomerativeClustering

    target_device = _speechbrain_device(device_name)
    print("Falling back to local speechbrain speaker clustering...")
    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime", "speechbrain_spkrec"),
        run_opts={"device": target_device},
    )

    embeddings = []
    indexed_subtitles = []
    total_duration = audio_input["waveform"].shape[1] / float(audio_input["sample_rate"])

    for idx, subtitle in enumerate(subtitles):
        text = (subtitle.content or "").strip()
        if not text:
            continue

        start_sec = subtitle.start.total_seconds()
        end_sec = subtitle.end.total_seconds()
        duration = max(0.0, end_sec - start_sec)
        desired = max(1.2, duration)
        pad = max(0.0, (desired - duration) / 2.0)
        clip_start = max(0.0, start_sec - pad)
        clip_end = min(total_duration, end_sec + pad)
        if clip_end - clip_start < 0.4:
            continue

        chunk = _slice_waveform(audio_input, clip_start, clip_end).to(torch.device(target_device))
        with torch.inference_mode():
            embedding = classifier.encode_batch(chunk).squeeze(0).squeeze(0).detach().cpu()
        embeddings.append(embedding)
        indexed_subtitles.append(idx)

    if not embeddings:
        raise RuntimeError("未能提取任何有效语音片段，无法执行说话人区分")

    stacked = torch.stack(embeddings)
    normalized = F.normalize(stacked, p=2, dim=1).numpy()
    speaker_count = _estimate_speaker_count(normalized)
    if speaker_count <= 1:
        labels = np.zeros(len(indexed_subtitles), dtype=np.int32)
    else:
        labels = AgglomerativeClustering(
            n_clusters=speaker_count,
            metric="cosine",
            linkage="average",
        ).fit_predict(normalized)

    segments: list[tuple[float, float, str]] = []
    for subtitle_idx, label in zip(indexed_subtitles, labels):
        subtitle = subtitles[subtitle_idx]
        segments.append(
            (
                float(subtitle.start.total_seconds()),
                float(subtitle.end.total_seconds()),
                f"SBK_{int(label)}",
            )
        )

    segments.sort(key=lambda item: (item[0], item[1]))
    print(f"Speechbrain clustering complete: {speaker_count} speakers estimated")
    return segments


def _all_tagged(subtitles) -> bool:
    texts = [(sub.content or "").strip() for sub in subtitles if (sub.content or "").strip()]
    return bool(texts) and all(_PREFIX_RE.match(text) for text in texts)


def main() -> None:
    args = json.loads(sys.argv[1])
    media_path = args["media_path"]
    srt_path = args["srt_path"]
    hf_token = args["hf_token"]
    model_name = args["model_name"]
    device_name = args["device_name"]
    label_prefix = args["label_prefix"]

    if not hf_token:
        raise RuntimeError("未配置 Hugging Face Token，无法启用说话人区分")

    subtitles = _load_subtitles(srt_path)
    if not subtitles:
        print("No subtitles found; skipping diarization.")
        return
    if _all_tagged(subtitles):
        counts = _speaker_counter(subtitles)
        print(f"Speaker labels already exist; skipping diarization. {_format_speaker_summary(counts)}")
        return

    audio_input = _load_audio_waveform(media_path)
    try:
        segments = _diarize_with_pyannote(model_name, hf_token, device_name, audio_input)
    except Exception as exc:
        print(f"⚠️ pyannote 说话人区分失败，切换到本地回退方案: {exc}")
        segments = _diarize_with_speechbrain(audio_input, subtitles, device_name)

    speaker_map: dict[str, str] = {}
    next_index = 1
    tagged_count = 0

    for subtitle in subtitles:
        text = (subtitle.content or "").strip()
        if not text or _PREFIX_RE.match(text):
            continue

        sub_start = subtitle.start.total_seconds()
        sub_end = subtitle.end.total_seconds()
        best_label = None
        best_overlap = 0.0

        for seg_start, seg_end, seg_label in segments:
            if seg_end <= sub_start:
                continue
            if seg_start >= sub_end:
                break
            overlap = _overlap(sub_start, sub_end, seg_start, seg_end)
            if overlap > best_overlap:
                best_overlap = overlap
                best_label = seg_label

        if not best_label:
            continue

        if best_label not in speaker_map:
            speaker_map[best_label] = f"{label_prefix}{next_index}"
            next_index += 1

        subtitle.content = f"[{speaker_map[best_label]}] {text}"
        tagged_count += 1

    for idx, subtitle in enumerate(subtitles, 1):
        subtitle.index = idx

    with open(srt_path, "w", encoding="utf-8") as handle:
        handle.write(srt.compose(subtitles))

    counts = _speaker_counter(subtitles)
    print(
        f"Speaker diarization complete: 本次新增 {tagged_count} 条标签，"
        f"当前共 {len(counts)} 位说话人（{_format_speaker_summary(counts)}）"
    )


if __name__ == "__main__":
    main()