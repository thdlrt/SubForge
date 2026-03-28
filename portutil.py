"""在首选端口被占用时，从一段连续端口中选取第一个可用的 TCP 监听端口。"""

from __future__ import annotations

import socket


def pick_free_tcp_port(host: str, preferred: int, span: int = 40) -> int:
    """
    若 preferred 被占用，在 [preferred, preferred+span) 内找第一个可 bind 的端口。
    探测地址与常见监听方式对齐：0.0.0.0 用 0.0.0.0 探测，避免与仅绑定 0.0.0.0 的进程不一致。
    """
    if preferred < 1 or preferred > 65535:
        raise ValueError("preferred 必须在 1–65535 之间")

    probe_host = host
    if host in ("", "::"):
        probe_host = "127.0.0.1"
    elif host == "0.0.0.0":
        probe_host = "0.0.0.0"

    for p in range(preferred, min(preferred + span, 65536)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((probe_host, p))
        except OSError:
            continue
        return p
    raise RuntimeError(
        f"在 {preferred}–{min(preferred + span - 1, 65535)} 范围内没有可用端口，请关闭占用进程或指定其他端口"
    )
