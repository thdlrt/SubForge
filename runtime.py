"""
Runtime helpers for source mode and frozen release builds.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def app_path(*parts: str) -> Path:
    return app_root().joinpath(*parts)


def bundle_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)


def ensure_app_cwd() -> Path:
    root = app_root()
    root.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    return root


def output_root() -> Path:
    path = app_path("output")
    path.mkdir(parents=True, exist_ok=True)
    return path


_COMMAND_CANDIDATES = {
    "ffmpeg": ["ffmpeg.exe", "ffmpeg"],
    "ffprobe": ["ffprobe.exe", "ffprobe"],
    "yt-dlp": ["yt-dlp.exe", "yt-dlp"],
}


def resolve_command(name: str) -> str:
    candidates = _COMMAND_CANDIDATES.get(name.lower(), [name])
    for root in (app_path("bin"), bundle_path("bin")):
        for candidate in candidates:
            candidate_path = root / candidate
            if candidate_path.exists():
                return str(candidate_path)

    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found

    expected = app_path("bin")
    raise FileNotFoundError(
        f"Missing executable: {name}. Put it in {expected} or add it to PATH."
    )


def whisper_worker_command(args_json: str) -> list[str]:
    if is_frozen():
        return [sys.executable, "--worker-whisper", args_json]
    return [sys.executable, "-u", str(bundle_path("_run_whisper.py")), args_json]


def demucs_worker_command(args: list[str]) -> list[str]:
    if is_frozen():
        return [sys.executable, "--worker-demucs", *args]
    return [sys.executable, str(bundle_path("_run_demucs.py")), *args]
