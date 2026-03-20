from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

from config import QWEN_TTS_API_KEY, QWEN_TTS_BASE_URL, QWEN_TTS_MODEL, QWEN_TTS_VOICE


DEFAULT_TEXT = (
    "你好，这是一段用于本地配音模型参考音色的示例语音。"
    "请保持发音清晰、语气自然、节奏平稳，让整体听感更接近正式播报。"
)


def qwen_tts_api_url() -> str:
    base = (QWEN_TTS_BASE_URL or "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
    return f"{base}/services/aigc/multimodal-generation/generation"


def qwen_tts_download(text: str, voice: str, out_file: Path) -> None:
    payload = {
        "model": QWEN_TTS_MODEL,
        "input": {
            "text": " ".join(text.splitlines()).strip(),
            "voice": voice,
            "language_type": "Chinese",
        },
    }
    req = urllib.request.Request(
        qwen_tts_api_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {QWEN_TTS_API_KEY}",
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

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(audio_url, timeout=90) as audio_resp:
        out_file.write_bytes(audio_resp.read())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", default=QWEN_TTS_VOICE or "Cherry")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--out", default="voice_reference_cherry.wav")
    args = parser.parse_args()

    if not QWEN_TTS_API_KEY:
        raise SystemExit("未配置 qwen_tts_api_key，无法生成参考音色")

    output_path = Path(args.out).expanduser()
    if not output_path.is_absolute():
        output_path = (Path(__file__).resolve().parent / output_path).resolve()

    qwen_tts_download(args.text, args.voice, output_path)
    output_path.with_suffix(".txt").write_text(args.text, encoding="utf-8")
    print(f"saved voice reference: {output_path}")
    print(f"saved prompt text: {output_path.with_suffix('.txt')}")


if __name__ == "__main__":
    main()
