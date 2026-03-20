"""
CosyVoice local bootstrapper.

Creates an isolated venv, clones the official CosyVoice repo, installs
dependencies, and downloads the SFT preset-speaker model.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REPO_DIR = ROOT / "vendor" / "CosyVoice"
MODEL_ROOT = ROOT / "pretrained_models"
INSTALL_STAMP = ROOT / ".install.stamp"
BOOTSTRAP_VERSION = "cosyvoice-bootstrap-v3"

DEFAULT_REPO_URL = "https://github.com/FunAudioLLM/CosyVoice.git"
DEFAULT_MODEL_ID = "FunAudioLLM/CosyVoice-300M-SFT"
DEFAULT_TTSFRD_ID = "FunAudioLLM/CosyVoice-ttsfrd"
DEFAULT_MODEL_SOURCE = "auto"
DEFAULT_DEVICE = "auto"


def _run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print(">>", " ".join(str(x) for x in cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def _detect_nvidia_gpu_name() -> str:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
        )
        return (result.stdout or "").splitlines()[0].strip()
    except Exception:
        return ""


def _build_runtime_requirements_file() -> Path:
    src = REPO_DIR / "requirements.txt"
    dst = ROOT / "runtime.requirements.txt"
    excluded_prefixes = (
        "torch==",
        "torchaudio==",
        "openai-whisper==",
    )
    lines = []
    for raw in src.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if any(line.startswith(prefix) for prefix in excluded_prefixes):
            continue
        lines.append(raw)
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dst


def _resolve_torch_stack(device: str) -> tuple[list[str], str]:
    normalized = (device or "auto").strip().lower()
    gpu_name = _detect_nvidia_gpu_name()
    use_cuda = normalized == "cuda" or (normalized == "auto" and bool(gpu_name))

    if use_cuda:
        torch_args = [
            "torch==2.7.1",
            "torchaudio==2.7.1",
            "--index-url",
            "https://download.pytorch.org/whl/cu128",
        ]
        stack_tag = f"cuda-cu128:{gpu_name or 'gpu'}"
    else:
        torch_args = [
            "torch==2.7.1",
            "torchaudio==2.7.1",
            "--index-url",
            "https://download.pytorch.org/whl/cpu",
        ]
        stack_tag = "cpu"
    return torch_args, stack_tag

def _install_torch_stack(py: Path, torch_args: list[str]) -> None:
    _run([str(py), "-m", "pip", "install", *torch_args])


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _ensure_venv() -> Path:
    py = _venv_python()
    if py.exists():
        return py
    ROOT.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    return py


def _ensure_repo(repo_url: str) -> None:
    repo_parent = REPO_DIR.parent
    repo_parent.mkdir(parents=True, exist_ok=True)
    if not REPO_DIR.exists():
        _run(["git", "clone", "--recursive", repo_url, str(REPO_DIR)])
    else:
        _run(["git", "submodule", "update", "--init", "--recursive"], cwd=REPO_DIR)


def _install_requirements(py: Path, device: str) -> None:
    requirements_path = REPO_DIR / "requirements.txt"
    runtime_requirements = _build_runtime_requirements_file()
    torch_args, torch_stack_tag = _resolve_torch_stack(device)
    stamp_input = "\n".join(
        [
            BOOTSTRAP_VERSION,
            hashlib.sha1(requirements_path.read_bytes()).hexdigest(),
            hashlib.sha1(runtime_requirements.read_bytes()).hexdigest(),
            torch_stack_tag,
        ]
    ).encode("utf-8")
    stamp_value = hashlib.sha1(stamp_input).hexdigest()
    if INSTALL_STAMP.exists() and INSTALL_STAMP.read_text(encoding="utf-8").strip() == stamp_value:
        return
    _install_torch_stack(py, torch_args)
    _run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools<81",
            "wheel",
        ]
    )
    _run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            "-r",
            str(runtime_requirements),
            "-i",
            "https://mirrors.aliyun.com/pypi/simple/",
            "--trusted-host",
            "mirrors.aliyun.com",
        ]
    )
    _run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "fastapi",
            "uvicorn",
            "huggingface_hub",
            "modelscope",
            "-i",
            "https://mirrors.aliyun.com/pypi/simple/",
            "--trusted-host",
            "mirrors.aliyun.com",
        ]
    )
    INSTALL_STAMP.write_text(stamp_value, encoding="utf-8")


def _download_with_helper(py: Path, model_id: str, ttsfrd_id: str, model_source: str) -> None:
    model_dir = MODEL_ROOT / Path(model_id).name
    ttsfrd_dir = MODEL_ROOT / Path(ttsfrd_id).name
    if model_dir.exists() and any(model_dir.iterdir()) and ttsfrd_dir.exists() and any(ttsfrd_dir.iterdir()):
        return

    MODEL_ROOT.mkdir(parents=True, exist_ok=True)

    code = r"""
import os

model_id = os.environ["COSYVOICE_MODEL_ID"]
ttsfrd_id = os.environ["COSYVOICE_TTSFRD_ID"]
model_dir = os.environ["COSYVOICE_MODEL_DIR"]
ttsfrd_dir = os.environ["COSYVOICE_TTSFRD_DIR"]
source = os.environ.get("COSYVOICE_MODEL_SOURCE", "auto")
errors = []

if source in ("auto", "huggingface"):
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(model_id, local_dir=model_dir)
        snapshot_download(ttsfrd_id, local_dir=ttsfrd_dir)
        print("downloaded models via huggingface_hub")
        raise SystemExit(0)
    except Exception as exc:
        errors.append(f"huggingface: {exc}")

if source in ("auto", "modelscope"):
    try:
        from modelscope import snapshot_download

        def ms_name(name: str) -> str:
            if name.startswith("FunAudioLLM/"):
                return "iic/" + name.split("/", 1)[1]
            return name

        snapshot_download(ms_name(model_id), local_dir=model_dir)
        snapshot_download(ms_name(ttsfrd_id), local_dir=ttsfrd_dir)
        print("downloaded models via modelscope")
        raise SystemExit(0)
    except Exception as exc:
        errors.append(f"modelscope: {exc}")

raise RuntimeError("model download failed: " + " | ".join(errors))
"""

    env = os.environ.copy()
    env["COSYVOICE_MODEL_ID"] = model_id
    env["COSYVOICE_TTSFRD_ID"] = ttsfrd_id
    env["COSYVOICE_MODEL_DIR"] = str(model_dir)
    env["COSYVOICE_TTSFRD_DIR"] = str(ttsfrd_dir)
    env["COSYVOICE_MODEL_SOURCE"] = model_source
    _run([str(py), "-c", code], env=env)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--ttsfrd-id", default=DEFAULT_TTSFRD_ID)
    parser.add_argument("--model-source", default=DEFAULT_MODEL_SOURCE, choices=["auto", "huggingface", "modelscope"])
    parser.add_argument("--device", default=DEFAULT_DEVICE, choices=["auto", "cpu", "cuda"])
    args = parser.parse_args()

    py = _ensure_venv()
    _ensure_repo(args.repo_url)
    _install_requirements(py, args.device)
    _download_with_helper(py, args.model_id, args.ttsfrd_id, args.model_source)
    print("CosyVoice bootstrap finished.")


if __name__ == "__main__":
    main()
