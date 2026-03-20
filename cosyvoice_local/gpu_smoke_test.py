from __future__ import annotations

import argparse
import io
import json
import pathlib
import subprocess
import threading
import time
import urllib.request

import soundfile as sf


def query_gpu_sample() -> tuple[int, int] | None:
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            text=True,
        ).strip()
    except Exception:
        return None

    if not output:
        return None

    util, memory = [part.strip() for part in output.split(",", 1)]
    return int(util), int(memory)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9880/tts")
    parser.add_argument("--voice", default="中文女")
    parser.add_argument(
        "--text",
        default="这是一段用于验证 RTX 5080 GPU 推理的 CosyVoice 语音生成测试，需要真正跑在 CUDA 上并返回音频。",
    )
    parser.add_argument(
        "--out",
        default=str(pathlib.Path(__file__).resolve().parent / "logs" / "gpu_test.wav"),
    )
    args = parser.parse_args()

    payload = json.dumps({"text": args.text, "voice": args.voice}).encode("utf-8")
    output_path = pathlib.Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result: dict[str, float | int] = {}
    samples: list[tuple[int, int]] = []
    error: list[str] = []

    def worker() -> None:
        try:
            request = urllib.request.Request(
                args.url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            started = time.time()
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
                result["status"] = response.status
                result["elapsed"] = time.time() - started
                result["bytes"] = len(data)
                output_path.write_bytes(data)
                audio, sample_rate = sf.read(io.BytesIO(data))
                result["frames"] = len(audio)
                result["rate"] = sample_rate
                result["duration"] = len(audio) / float(sample_rate)
        except Exception as exc:
            error.append(str(exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while thread.is_alive():
        sample = query_gpu_sample()
        if sample is not None:
            samples.append(sample)
        time.sleep(0.5)

    thread.join()

    if error:
        raise SystemExit(f"request failed: {error[0]}")

    print(
        json.dumps(
            {
                "request": result,
                "gpu": {
                    "max_utilization_percent": max((util for util, _ in samples), default=0),
                    "max_memory_mb": max((memory for _, memory in samples), default=0),
                    "sample_count": len(samples),
                },
                "output": str(output_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
