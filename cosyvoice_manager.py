"""
Helpers for bootstrapping and auto-starting the local CosyVoice service.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

import config


ROOT = Path(__file__).resolve().parent
COSYVOICE_ROOT = ROOT / "cosyvoice_local"
BOOTSTRAP_SCRIPT = COSYVOICE_ROOT / "bootstrap.py"
SERVER_SCRIPT = COSYVOICE_ROOT / "server.py"
PID_FILE = COSYVOICE_ROOT / "server.pid"


def _venv_python() -> Path:
    if os.name == "nt":
        return COSYVOICE_ROOT / ".venv" / "Scripts" / "python.exe"
    return COSYVOICE_ROOT / ".venv" / "bin" / "python"


def _healthcheck() -> bool:
    try:
        with urllib.request.urlopen(f"{config.COSYVOICE_API_URL.rstrip('/')}/health", timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _server_host_port() -> tuple[str, int]:
    parsed = urlparse(config.COSYVOICE_API_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or int(config.COSYVOICE_PORT)
    return host, port


def _spawn_server() -> None:
    py = _venv_python()
    if not py.exists():
        raise RuntimeError("CosyVoice 虚拟环境尚未准备完成")

    log_dir = COSYVOICE_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / "server.log", "a", encoding="utf-8")
    host, port = _server_host_port()

    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )

    env = os.environ.copy()
    env["COSYVOICE_MODEL_DIR_NAME"] = Path(config.COSYVOICE_MODEL_ID).name
    env["COSYVOICE_DEVICE"] = str(config.COSYVOICE_DEVICE)
    env["COSYVOICE_FP16"] = "1" if config.COSYVOICE_FP16 else "0"
    proc = subprocess.Popen(
        [str(py), str(SERVER_SCRIPT), "--host", host, "--port", str(port)],
        cwd=str(COSYVOICE_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=creationflags,
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")


def shutdown_cosyvoice_service() -> None:
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        PID_FILE.unlink(missing_ok=True)
        return

    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
    else:
        subprocess.run(["kill", str(pid)], check=False, capture_output=True)

    PID_FILE.unlink(missing_ok=True)


def ensure_cosyvoice_service() -> None:
    if _healthcheck():
        return
    # 仅当我们曾记录过子进程 PID 时才 taskkill，避免健康检查偶发失败误杀手动启动的服务
    if PID_FILE.exists():
        shutdown_cosyvoice_service()
    PID_FILE.unlink(missing_ok=True)

    subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            "--repo-url",
            config.COSYVOICE_REPO_URL,
            "--model-id",
            config.COSYVOICE_MODEL_ID,
            "--ttsfrd-id",
            config.COSYVOICE_TTSFRD_ID,
            "--model-source",
            config.COSYVOICE_MODEL_SOURCE,
            "--device",
            config.COSYVOICE_DEVICE,
        ],
        check=True,
        cwd=str(COSYVOICE_ROOT),
    )

    if _healthcheck():
        return

    _spawn_server()
    deadline = time.time() + max(int(config.COSYVOICE_START_TIMEOUT), 30)
    while time.time() < deadline:
        if _healthcheck():
            return
        time.sleep(2)

    raise RuntimeError("CosyVoice 服务启动超时，请查看 cosyvoice_local/logs/server.log")
