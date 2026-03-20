"""
Local CosyVoice FastAPI server for preset-speaker TTS.

注意：CosyVoice 的 CosyVoiceModel 内部 lock 只保护部分字典，并不能串行化整段推理。
若同时进入多路 /tts（或多线程），会重复占 GPU 显存直至 OOM。这里用进程内全局锁
保证任意时刻只有一路推理，并在每次结束后 gc + empty_cache；可选 fp16 降低峰值显存。
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import os
import sys
import tempfile
import threading
from pathlib import Path

DEVICE_MODE = os.environ.get("COSYVOICE_DEVICE", "cpu").strip().lower()
if DEVICE_MODE == "cpu":
    os.environ["CUDA_VISIBLE_DEVICES"] = ""

# 缓解显存碎片（需较新 CUDA / PyTorch；无效时会被忽略）
if "PYTORCH_CUDA_ALLOC_CONF" not in os.environ:
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import torch
import torchaudio
from fastapi import FastAPI, HTTPException, Request, Response
import uvicorn


ROOT = Path(__file__).resolve().parent
REPO_DIR = ROOT / "vendor" / "CosyVoice"
MODEL_ROOT = ROOT / "pretrained_models"

if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
if str(REPO_DIR / "third_party" / "Matcha-TTS") not in sys.path:
    sys.path.insert(0, str(REPO_DIR / "third_party" / "Matcha-TTS"))

from cosyvoice.cli.cosyvoice import AutoModel  # type: ignore


# 整段推理互斥：库内部并非全程持锁，必须在这里串行化
INFERENCE_LOCK = threading.Lock()

app = FastAPI(title="AiText CosyVoice Local Server")
_model = None
_voices: list[str] | None = None
_runtime_device = "cpu"


def _env_fp16() -> bool:
    if DEVICE_MODE == "cpu":
        return False
    return os.environ.get("COSYVOICE_FP16", "1").strip().lower() in ("1", "true", "yes", "on")


def _model_dir() -> Path:
    model_name = os.environ.get("COSYVOICE_MODEL_DIR_NAME", "CosyVoice-300M-SFT")
    return MODEL_ROOT / model_name


def _ensure_model():
    global _model, _voices, _runtime_device
    if _model is None:
        model_dir = _model_dir()
        if not model_dir.exists():
            raise RuntimeError(f"CosyVoice model not found: {model_dir}")
        fp16 = _env_fp16() and torch.cuda.is_available()
        _model = AutoModel(model_dir=str(model_dir), fp16=fp16)
        _voices = list(_model.list_available_spks())
        _runtime_device = "cuda" if torch.cuda.is_available() and DEVICE_MODE != "cpu" else "cpu"
    return _model


def _resolve_prompt_audio_path(raw_path: str) -> str:
    prompt_path = Path(raw_path).expanduser()
    if not prompt_path.is_absolute():
        prompt_path = (ROOT.parent / prompt_path).resolve()
    if not prompt_path.exists():
        raise FileNotFoundError(f"prompt audio not found: {prompt_path}")
    return str(prompt_path)


def _collect_audio_incremental(generator) -> torch.Tensor:
    """流式累加，避免 list(生成器) 长时间持有大量中间 dict / tensor 引用。"""
    audio = None
    for item in generator:
        speech = item["tts_speech"]
        if isinstance(speech, torch.Tensor):
            t = speech.detach().cpu()
        else:
            t = torch.tensor(speech)
        if t.ndim == 1:
            t = t.unsqueeze(0)
        if audio is None:
            audio = t
        else:
            audio = torch.cat([audio, t], dim=-1)
        del item, speech, t
    if audio is None:
        raise RuntimeError("CosyVoice returned empty audio")
    return audio


def _release_cuda_memory() -> None:
    gc.collect()
    if torch.cuda.is_available():
        try:
            torch.cuda.synchronize()
        except Exception:
            pass
        torch.cuda.empty_cache()


def _tts_blocking(body: dict) -> bytes:
    text = str(body.get("text", "")).strip()
    voice = str(body.get("voice", "")).strip()
    mode = str(body.get("mode", "preset")).strip().lower() or "preset"
    prompt_audio_path = str(body.get("prompt_audio_path", "")).strip()
    prompt_text = str(body.get("prompt_text", "")).strip()
    if not text:
        raise ValueError("text is required")
    if mode == "preset" and not voice:
        raise ValueError("voice is required")

    with INFERENCE_LOCK:
        try:
            model = _ensure_model()
            available = _voices or []
            if mode == "preset" and available and voice not in available:
                raise ValueError(f"unknown voice: {voice}. available: {', '.join(available)}")

            if mode == "zero_shot":
                if not prompt_audio_path:
                    raise ValueError("prompt_audio_path is required for zero_shot mode")
                if not prompt_text:
                    raise ValueError("prompt_text is required for zero_shot mode")
                gen = model.inference_zero_shot(
                    text,
                    prompt_text,
                    _resolve_prompt_audio_path(prompt_audio_path),
                    stream=False,
                )
            elif mode == "cross_lingual":
                if not prompt_audio_path:
                    raise ValueError("prompt_audio_path is required for cross_lingual mode")
                gen = model.inference_cross_lingual(
                    text,
                    _resolve_prompt_audio_path(prompt_audio_path),
                    stream=False,
                )
            else:
                gen = model.inference_sft(text, voice, stream=False)

            audio = _collect_audio_incremental(gen)
            del gen

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                torchaudio.save(tmp_path, audio, model.sample_rate)
                data = Path(tmp_path).read_bytes()
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            del audio
            return data
        finally:
            _release_cuda_memory()


@app.get("/health")
def health():
    model = _ensure_model()
    return {
        "status": "ok",
        "sample_rate": model.sample_rate,
        "voices": _voices or [],
        "device": _runtime_device,
        "supported_modes": ["preset", "zero_shot", "cross_lingual"],
        "fp16": _env_fp16(),
        "inference_global_lock": True,
        "pid": os.getpid(),
    }


@app.get("/voices")
def voices():
    _ensure_model()
    return {"voices": _voices or []}


@app.on_event("startup")
async def _startup_log():
    import logging

    logging.getLogger("uvicorn.error").info(
        "CosyVoice server pid=%s device=%s fp16_env=%s (单 worker，推理全局串行锁)",
        os.getpid(),
        DEVICE_MODE,
        os.environ.get("COSYVOICE_FP16", "1"),
    )


@app.post("/tts")
async def tts(request: Request):
    body = await request.json()
    try:
        data = await asyncio.to_thread(_tts_blocking, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(data, media_type="audio/wav")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9880)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", workers=1)


if __name__ == "__main__":
    main()
