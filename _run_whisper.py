"""
Wrapper script: 在独立子进程中运行 Whisper 转录。
子进程退出时 OS 自动回收 GPU 显存，避免 ctranslate2 析构在 Windows CUDA 下 segfault。
Usage: python _run_whisper.py <json_args>
"""
import sys
import os
import json

# 强制 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# 确保能 import 项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import srt
from datetime import timedelta


def main():
    args = json.loads(sys.argv[1])

    video_path     = args["video_path"]
    en_srt_path    = args["en_srt_path"]
    whisper_model  = args["whisper_model"]
    device         = args["device"]
    compute_type   = args["compute_type"]
    video_language = args["video_language"]
    gap_threshold  = args["gap_threshold"]
    max_chars      = args["max_chars"]

    from faster_whisper import WhisperModel

    print(f"加载模型 '{whisper_model}'（首次运行会自动下载，请耐心等待）...")
    model = WhisperModel(whisper_model, device=device, compute_type=compute_type)

    print("开始转录...")
    lang_arg = video_language if video_language else None
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

    _PUNCT_BREAK = frozenset('.?!,;:…，。？！；：、')
    raw_segs = []
    for seg in segments:
        raw_segs.append(seg)

    subs = []
    idx = 0

    def _flush_chunk(chunk):
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
            idx += 1
            subs.append(srt.Subtitle(
                index=idx,
                start=timedelta(seconds=seg.start),
                end=timedelta(seconds=seg.end),
                content=seg.text.strip()
            ))
        else:
            LOOK_BACK = 8
            LOOK_AHEAD = 2
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
                    else:
                        ahead_at = -1
                        for ai in range(wi, min(len(words), wi + LOOK_AHEAD)):
                            if words[ai].word.rstrip()[-1:] in _PUNCT_BREAK:
                                ahead_at = ai
                                break

                        if ahead_at >= 0:
                            for j in range(wi, ahead_at + 1):
                                chunk_words.append(words[j])
                                chunk_len += len(words[j].word.strip())
                            _flush_chunk(chunk_words)
                            chunk_words = []
                            chunk_len = 0
                            wi = ahead_at + 1
                            continue
                        else:
                            _flush_chunk(chunk_words)
                            chunk_words = []
                            chunk_len = 0

                chunk_words.append(w_curr)
                chunk_len += len(word_text)
                wi += 1
            _flush_chunk(chunk_words)
        if idx % 20 == 0 and idx > 0:
            print(f"  已处理 {idx} 条字幕...")

    print(f"  ✅ 转录完成，共生成 {idx} 条字幕")

    with open(en_srt_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(subs))
    print(f"✅ 外语字幕已生成: {en_srt_path} (共 {len(subs)} 条)")
    # 子进程退出后 OS 自动回收 GPU 显存


if __name__ == "__main__":
    main()
