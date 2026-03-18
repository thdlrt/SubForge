# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH)

packages = [
    "gradio",
    "gradio_client",
    "groovy",
    "safehttpx",
    "faster_whisper",
    "ctranslate2",
    "openai",
    "srt",
    "yt_dlp",
    "demucs",
    "edge_tts",
    "pydub",
    "soundfile",
    "realesrgan",
    "basicsr",
    "cv2",
    "torch",
    "torchaudio",
    "torchvision",
    "tqdm",
]

datas = []
binaries = []
hiddenimports = [
    "_run_whisper",
    "_run_demucs",
    "steps",
    "steps.download",
    "steps.enhance",
    "steps.transcribe",
    "steps.summarize",
    "steps.translate",
    "steps.burn",
    "steps.dubbing",
]

for package in packages:
    collected_datas, collected_binaries, collected_hiddenimports = collect_all(package)
    datas += collected_datas
    binaries += collected_binaries
    hiddenimports += collected_hiddenimports

for filename in ("ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe"):
    candidate = project_root / "bin" / filename
    if candidate.exists():
        datas.append((str(candidate), "bin"))

for filename in ("config.example.json", "README.md"):
    candidate = project_root / filename
    if candidate.exists():
        datas.append((str(candidate), "."))

a = Analysis(
    ["app.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SubForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="SubForge",
)
