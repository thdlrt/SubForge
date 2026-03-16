"""
Wrapper script: run Whisper transcription in an isolated child process.

The child process releases GPU memory when it exits, which avoids some
Windows + CUDA instability in ctranslate2 / faster-whisper.

Usage: python _run_whisper.py <json_args>
"""
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import timedelta

import srt


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


_STRONG_END_PUNCT = frozenset(".?!" + "\u2026\u3002\uFF1F\uFF01")
_WEAK_BREAK_PUNCT = frozenset(",;:" + "\uFF0C\uFF1B\uFF1A\u3001")
_ALL_BREAK_PUNCT = _STRONG_END_PUNCT | _WEAK_BREAK_PUNCT
_CONNECTOR_WORDS = frozenset({
    "and", "or", "but", "nor", "so", "yet", "for",
    "because", "since", "if", "when", "while", "although", "though",
    "unless", "until", "whereas", "however", "therefore", "thus",
    "then", "than", "that", "which", "who", "whom", "whose", "where",
    "after", "before", "once", "as", "whether",
})
_TAIL_TOKENS = frozenset({
    "a", "an", "the", "to", "of", "for", "with", "from", "in", "on", "at",
    "and", "or", "but", "because", "that", "which", "as", "if", "when", "while",
})
_DEDUPE_STRIP_CHARS = ".!?" + "\u3002\uFF1F\uFF01"
_TRIM_CHARS = (
    " \t\n\r\"'`"
    + "\u201C\u201D\u2018\u2019"
    + "()[]{}<>.,;:!?"
    + "\u2026\uFF0C\u3002\uFF1F\uFF01\uFF1B\uFF1A\u3001"
)


@dataclass
class TimedWord:
    text: str
    start: float
    end: float


def _load_segmentation_config(args):
    return {
        "target_chars_ratio": float(args.get("target_chars_ratio", 0.82)),
        "min_chars_ratio": float(args.get("min_chars_ratio", 0.38)),
        "hard_max_chars_ratio": float(args.get("hard_max_chars_ratio", 1.35)),
        "hard_max_chars_bias": int(args.get("hard_max_chars_bias", 18)),
        "soft_max_duration_sec": float(args.get("soft_max_duration_sec", 4.8)),
        "hard_max_duration_sec": float(args.get("hard_max_duration_sec", 6.4)),
        "min_words": max(1, int(args.get("min_words", 3))),
        "look_back_words": 10,
        "look_ahead_words": 6,
    }


def _load_merge_config(args):
    return {
        "max_gap_sec": float(args.get("merge_max_gap_sec", 0.35)),
        "max_duration_sec": float(args.get("merge_max_duration_sec", 6.0)),
        "max_chars_ratio": float(args.get("merge_max_chars_ratio", 1.35)),
        "max_chars_bias": int(args.get("merge_max_chars_bias", 24)),
        "short_tail_max_words": max(1, int(args.get("short_tail_max_words", 3))),
        "short_tail_max_chars": max(1, int(args.get("short_tail_max_chars", 18))),
        "short_tail_max_duration_sec": float(args.get("short_tail_max_duration_sec", 1.4)),
    }


def _load_split_config(args):
    return {
        "max_duration_sec": float(args.get("split_max_duration_sec", 6.8)),
    }


def _normalized_token(text):
    return (text or "").strip().lower().strip(_TRIM_CHARS)


def _last_visible_char(text):
    stripped = (text or "").rstrip()
    return stripped[-1:] if stripped else ""


def _join_words(words):
    return "".join(word.text for word in words).strip()


def _lexical_word_count(words):
    return sum(1 for word in words if _normalized_token(word.text))


def _gap_after(words, end_idx):
    if end_idx >= len(words) - 1:
        return float("inf")
    return max(0.0, words[end_idx + 1].start - words[end_idx].end)


def _is_connector_boundary(words, end_idx):
    prev_token = _normalized_token(words[end_idx].text)
    next_token = _normalized_token(words[end_idx + 1].text) if end_idx + 1 < len(words) else ""
    return prev_token in _CONNECTOR_WORDS or next_token in _CONNECTOR_WORDS


def _break_score(words, start_idx, end_idx, gap_threshold, target_chars, min_chars, max_duration):
    chunk = words[start_idx:end_idx + 1]
    text = _join_words(chunk)
    if not text:
        return float("-inf")

    char_len = len(text)
    duration = max(0.0, words[end_idx].end - words[start_idx].start)
    lexical_count = _lexical_word_count(chunk)
    last_char = _last_visible_char(words[end_idx].text)
    gap = _gap_after(words, end_idx)

    score = 0.0

    if last_char in _STRONG_END_PUNCT:
        score += 140.0
    elif last_char in _WEAK_BREAK_PUNCT:
        score += 70.0

    if gap >= gap_threshold:
        score += 160.0
    else:
        score += min(45.0, gap * 60.0)

    score -= abs(char_len - target_chars) * 1.15

    if char_len < min_chars:
        score -= (min_chars - char_len) * 2.5

    if lexical_count < 3:
        score -= 45.0

    if duration < 1.0:
        score -= 25.0
    elif duration > max_duration:
        score -= (duration - max_duration) * 30.0

    if _is_connector_boundary(words, end_idx):
        score -= 85.0

    if last_char not in _ALL_BREAK_PUNCT and gap < 0.18:
        score -= 18.0

    return score


def _best_break_in_window(words, start_idx, window_start, window_end, gap_threshold,
                          target_chars, min_chars, max_chars, max_duration):
    best_idx = None
    best_score = float("-inf")

    for end_idx in range(window_start, window_end + 1):
        text = _join_words(words[start_idx:end_idx + 1])
        if not text:
            continue

        duration = max(0.0, words[end_idx].end - words[start_idx].start)
        if len(text) > max_chars or duration > max_duration + 0.8:
            continue

        score = _break_score(
            words, start_idx, end_idx, gap_threshold, target_chars, min_chars, max_duration
        )
        if score > best_score:
            best_idx = end_idx
            best_score = score

    return best_idx


def _choose_chunk_end(words, start_idx, gap_threshold, max_chars, segmentation_config):
    n_words = len(words)
    target_chars = max(24, int(max_chars * segmentation_config["target_chars_ratio"]))
    min_chars = max(14, int(max_chars * segmentation_config["min_chars_ratio"]))
    hard_max_chars = max(
        max_chars + segmentation_config["hard_max_chars_bias"],
        int(max_chars * segmentation_config["hard_max_chars_ratio"]),
    )
    soft_max_duration = segmentation_config["soft_max_duration_sec"]
    hard_max_duration = segmentation_config["hard_max_duration_sec"]
    min_lexical_words = segmentation_config["min_words"]
    look_back_words = segmentation_config["look_back_words"]
    look_ahead_words = segmentation_config["look_ahead_words"]

    end_idx = start_idx
    while end_idx < n_words:
        chunk = words[start_idx:end_idx + 1]
        text = _join_words(chunk)
        char_len = len(text)
        duration = max(0.0, words[end_idx].end - words[start_idx].start)
        lexical_count = _lexical_word_count(chunk)
        gap = _gap_after(words, end_idx)
        last_char = _last_visible_char(words[end_idx].text)

        if gap >= gap_threshold and text:
            return end_idx

        if (
            last_char in _STRONG_END_PUNCT
            and lexical_count >= min_lexical_words
            and char_len >= min_chars
        ):
            return end_idx

        should_search = (
            char_len >= target_chars
            or duration >= soft_max_duration
            or lexical_count >= 14
        )
        if should_search:
            window_start = max(start_idx + min_lexical_words - 1, end_idx - max(1, look_back_words))
            window_end = min(n_words - 1, end_idx + max(0, look_ahead_words))
            best_idx = _best_break_in_window(
                words,
                start_idx,
                window_start,
                window_end,
                gap_threshold,
                target_chars,
                min_chars,
                hard_max_chars,
                hard_max_duration,
            )
            if best_idx is not None:
                return best_idx

        if char_len >= hard_max_chars or duration >= hard_max_duration:
            window_start = max(start_idx + 1, end_idx - max(1, look_back_words))
            best_idx = _best_break_in_window(
                words,
                start_idx,
                window_start,
                end_idx,
                gap_threshold,
                target_chars,
                min_chars,
                hard_max_chars,
                hard_max_duration,
            )
            return best_idx if best_idx is not None else end_idx

        end_idx += 1

    return n_words - 1


def _build_subtitles_from_words(words, gap_threshold, max_chars, segmentation_config):
    subtitles = []
    start_idx = 0

    while start_idx < len(words):
        end_idx = _choose_chunk_end(
            words, start_idx, gap_threshold, max_chars, segmentation_config
        )
        chunk = words[start_idx:end_idx + 1]
        text = _join_words(chunk)
        if text:
            subtitles.append(srt.Subtitle(
                index=0,
                start=timedelta(seconds=chunk[0].start),
                end=timedelta(seconds=chunk[-1].end),
                content=text,
            ))
        start_idx = end_idx + 1

    for idx, subtitle in enumerate(subtitles, 1):
        subtitle.index = idx
    return subtitles


def _dedupe_adjacent_subs(items):
    if not items:
        return items

    deduped = [items[0]]
    for current in items[1:]:
        previous = deduped[-1]
        prev_text = (previous.content or "").strip()
        cur_text = (current.content or "").strip()
        if not prev_text or not cur_text:
            deduped.append(current)
            continue

        gap = (current.start - previous.end).total_seconds()
        same_norm = (
            prev_text.lower().rstrip(_DEDUPE_STRIP_CHARS)
            == cur_text.lower().rstrip(_DEDUPE_STRIP_CHARS)
        )
        if same_norm and gap <= 0.6:
            previous.end = max(previous.end, current.end)
            continue

        deduped.append(current)

    for idx, subtitle in enumerate(deduped, 1):
        subtitle.index = idx
    return deduped


def _ends_with_strong_punct(text):
    stripped = (text or "").rstrip()
    return stripped[-1:] in _STRONG_END_PUNCT if stripped else False


def _ends_with_weak_punct(text):
    stripped = (text or "").rstrip()
    return stripped[-1:] in _WEAK_BREAK_PUNCT if stripped else False


def _last_token(text):
    tokens = (text or "").strip().lower().split()
    if not tokens:
        return ""
    return tokens[-1].strip(_TRIM_CHARS)


def _looks_like_enum_piece(text, merge_config):
    normalized = (text or "").strip()
    if not normalized:
        return False

    tokens = [token for token in normalized.split() if token.strip()]
    first_token = _normalized_token(tokens[0]) if tokens else ""
    return (
        len(tokens) <= merge_config["short_tail_max_words"] + 2
        and len(normalized) <= merge_config["short_tail_max_chars"] + 16
        and (
            _ends_with_weak_punct(normalized)
            or first_token in {"and", "or", "nor"}
        )
    )


def _merge_short_tail_subs(items, max_chars_limit, merge_config):
    if not items:
        return items

    merged = [items[0]]
    max_merge_gap = merge_config["max_gap_sec"]
    max_merged_duration = merge_config["max_duration_sec"]

    for current in items[1:]:
        previous = merged[-1]
        prev_text = (previous.content or "").strip()
        cur_text = (current.content or "").strip()
        gap = (current.start - previous.end).total_seconds()

        current_word_count = len([token for token in cur_text.split() if token.strip()])
        current_is_short = (
            current_word_count <= merge_config["short_tail_max_words"]
            or len(cur_text) <= merge_config["short_tail_max_chars"]
        )
        current_is_fast = (
            (current.end - current.start).total_seconds()
            <= merge_config["short_tail_max_duration_sec"]
        )
        previous_tail_is_open = not _ends_with_strong_punct(prev_text)
        previous_tail_is_connector = _last_token(prev_text) in _TAIL_TOKENS
        previous_ends_with_weak_punct = _ends_with_weak_punct(prev_text)
        previous_is_enum_piece = _looks_like_enum_piece(prev_text, merge_config)
        current_is_enum_piece = _looks_like_enum_piece(cur_text, merge_config)

        merged_text = f"{prev_text} {cur_text}".strip() if prev_text else cur_text
        merged_duration = (current.end - previous.start).total_seconds()
        merged_len_ok = len(merged_text) <= max(
            max_chars_limit + merge_config["max_chars_bias"],
            int(max_chars_limit * merge_config["max_chars_ratio"]),
        )
        enum_merge_duration_ok = merged_duration <= max_merged_duration + 1.0

        should_merge = (
            0.0 <= gap <= max_merge_gap
            and merged_len_ok
            and (
                (
                    merged_duration <= max_merged_duration
                    and (
                        (current_is_short and current_is_fast and previous_tail_is_open)
                        or previous_tail_is_connector
                    )
                )
                or (
                    enum_merge_duration_ok
                    and (previous_is_enum_piece or previous_ends_with_weak_punct)
                    and (current_is_short or current_is_enum_piece)
                )
            )
        )

        if should_merge:
            previous.content = merged_text
            previous.end = current.end
        else:
            merged.append(current)

    for idx, subtitle in enumerate(merged, 1):
        subtitle.index = idx
    return merged


def _split_overlong_subs(items, max_chars_limit, split_config):
    if not items:
        return items

    output = []
    hard_max_duration = split_config["max_duration_sec"]

    def emit_parts(subtitle, parts):
        total_secs = (subtitle.end - subtitle.start).total_seconds()
        if total_secs <= 0:
            total_secs = 0.001

        weights = [max(1, len(part)) for part in parts]
        weight_sum = sum(weights)
        cursor = subtitle.start

        for idx, part in enumerate(parts):
            if idx == len(parts) - 1:
                end_time = subtitle.end
            else:
                ratio = weights[idx] / weight_sum
                end_time = cursor + timedelta(seconds=max(0.25, total_secs * ratio))
            output.append(srt.Subtitle(
                index=0,
                start=cursor,
                end=end_time,
                content=part.strip(),
            ))
            cursor = end_time

    for subtitle in items:
        text = (subtitle.content or "").strip()
        if not text:
            output.append(subtitle)
            continue

        duration = (subtitle.end - subtitle.start).total_seconds()
        if len(text) <= max_chars_limit and duration <= hard_max_duration:
            output.append(subtitle)
            continue

        parts = [
            part.strip()
            for part in re.split(r"(?<=[.?!\u2026\u3002\uFF1F\uFF01])\s+", text)
            if part.strip()
        ]
        if len(parts) <= 1:
            parts = [
                part.strip()
                for part in re.split(r"(?<=[,;:\uFF0C\uFF1B\uFF1A\u3001])\s+", text)
                if part.strip()
            ]

        if len(parts) <= 1:
            output.append(subtitle)
            continue

        emit_parts(subtitle, parts)

    for idx, subtitle in enumerate(output, 1):
        subtitle.index = idx
    return output


def _segment_raw_segments(raw_segments, gap_threshold, max_chars, segmentation_config):
    subtitles = []
    buffered_words = []

    def flush_buffer():
        nonlocal buffered_words
        if not buffered_words:
            return
        subtitles.extend(_build_subtitles_from_words(
            buffered_words, gap_threshold, max_chars, segmentation_config
        ))
        buffered_words = []

    for segment in raw_segments:
        words = list(segment.words) if segment.words else []
        if not words:
            flush_buffer()
            text = (segment.text or "").strip()
            if text:
                subtitles.append(srt.Subtitle(
                    index=0,
                    start=timedelta(seconds=segment.start),
                    end=timedelta(seconds=segment.end),
                    content=text,
                ))
            continue

        for word in words:
            start = word.start if word.start is not None else segment.start
            end = word.end if word.end is not None else segment.end
            start = float(start if start is not None else 0.0)
            end = float(end if end is not None else start)
            if end < start:
                end = start
            buffered_words.append(TimedWord(text=word.word or "", start=start, end=end))

    flush_buffer()

    for idx, subtitle in enumerate(subtitles, 1):
        subtitle.index = idx
    return subtitles


def main():
    args = json.loads(sys.argv[1])

    video_path = args["video_path"]
    en_srt_path = args["en_srt_path"]
    whisper_model = args["whisper_model"]
    device = args["device"]
    compute_type = args["compute_type"]
    video_language = args["video_language"]
    gap_threshold = args["gap_threshold"]
    max_chars = args["max_chars"]
    segmentation_config = _load_segmentation_config(args)
    merge_config = _load_merge_config(args)
    split_config = _load_split_config(args)

    from faster_whisper import WhisperModel

    print(f"Loading Whisper model '{whisper_model}'...")
    model = WhisperModel(whisper_model, device=device, compute_type=compute_type)

    print("Starting transcription...")
    language_arg = video_language if video_language else None
    if language_arg:
        print(f"Forced language: {language_arg}")
    else:
        print("Language not set; using auto detection...")

    segments, info = model.transcribe(
        video_path,
        language=language_arg,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        word_timestamps=True,
    )

    print(f"Detected language: {info.language}, confidence: {info.language_probability:.2f}")

    raw_segments = list(segments)
    subtitles = _segment_raw_segments(
        raw_segments,
        gap_threshold=gap_threshold,
        max_chars=max_chars,
        segmentation_config=segmentation_config,
    )

    subtitles = _dedupe_adjacent_subs(subtitles)

    subtitles = _merge_short_tail_subs(subtitles, max_chars, merge_config)

    subtitles = _split_overlong_subs(subtitles, max_chars, split_config)

    for idx, subtitle in enumerate(subtitles, 1):
        subtitle.index = idx

    print(f"Transcription complete: {len(subtitles)} subtitles")

    with open(en_srt_path, "w", encoding="utf-8") as file:
        file.write(srt.compose(subtitles))
    print(f"English subtitles written: {en_srt_path} ({len(subtitles)} items)")


if __name__ == "__main__":
    main()
