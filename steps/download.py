"""
步骤 1：视频下载与准备
"""
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import config
from utils import sanitize_name


def _hostname_from_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
        return (p.hostname or "").lower()
    except Exception:
        return ""


def _is_youtube_hostname(hostname: str) -> bool:
    if not hostname:
        return False
    if hostname == "youtu.be":
        return True
    return hostname == "youtube.com" or hostname.endswith(".youtube.com")


def _resolve_cookie_value_for_url(url: str) -> str:
    """按 hostname 后缀匹配 ytdlp_cookies_by_host；未命中则用全局 ytdlp_cookies。"""
    host_map = getattr(config, "YTDLP_COOKIES_BY_HOST", None) or {}
    if not isinstance(host_map, dict):
        host_map = {}
    hostname = _hostname_from_url(url)
    if hostname:
        keys_sorted = sorted(host_map.keys(), key=lambda x: len(str(x)), reverse=True)
        for key in keys_sorted:
            k = str(key).strip().lower()
            if not k:
                continue
            if hostname == k or hostname.endswith("." + k):
                v = host_map.get(key)
                return ("" if v is None else str(v)).strip()
    return (config.YTDLP_COOKIES or "").strip()


def _cookies_args_for_value(value: str) -> list:
    """将 cookies 配置（文件路径或浏览器名）转为 yt-dlp 参数；无效则返回空列表。"""
    if not (value or "").strip():
        return []
    value = value.strip()
    if os.path.isfile(value):
        print(f"   使用 cookies 文件: {value}")
        return ["--cookies", value]
    if os.path.sep not in value and "/" not in value and not value.endswith(".txt"):
        print(f"   从浏览器读取 cookies: {value}")
        return ["--cookies-from-browser", value]
    print(f"   ⚠ cookies 文件不存在: {value}，将不使用 cookies")
    return []


def _ytdlp_extra_args(url: str | None) -> list:
    """返回 yt-dlp 的 cookie +（仅 YouTube）client 参数列表。"""
    args = []
    hostname = _hostname_from_url(url) if url else ""
    if hostname and config.YTDLP_CLIENT and _is_youtube_hostname(hostname):
        args += ["--extractor-args", f"youtube:player_client={config.YTDLP_CLIENT}"]
        print(f"   YouTube 客户端: {config.YTDLP_CLIENT}")
    val = _resolve_cookie_value_for_url(url) if url else (config.YTDLP_COOKIES or "").strip()
    args += _cookies_args_for_value(val)
    return args


def _remux_to_mp4(src: Path) -> Path:
    dst = src.with_suffix(".mp4")
    if dst.resolve() == src.resolve():
        return src
    if dst.exists():
        dst = src.parent / f"{src.stem}_remux.mp4"
    print(f"   封装为 MP4: {dst.name}（ffmpeg -c copy）")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(dst),
        ],
        check=True,
    )
    return dst


def _pick_downloaded_video_file(output_dir: Path) -> Path:
    """优先取最新 mp4；否则将 mkv/webm/ts/mov 无损封装为 mp4 后返回。"""
    mp4_files = list(output_dir.glob("*.mp4"))
    if mp4_files:
        return max(mp4_files, key=os.path.getmtime)
    for ext in (".mkv", ".webm", ".ts", ".mov"):
        others = list(output_dir.glob(f"*{ext}"))
        if others:
            src = max(others, key=os.path.getmtime)
            return _remux_to_mp4(src)
    raise FileNotFoundError("未找到下载的视频文件！")


def step1_download_video(url, output_dir):
    """使用 yt-dlp 下载视频（含 HLS 等），输出为 MP4 或无损封装为 MP4。"""
    print("\n" + "=" * 60)
    print("📥 第一步：下载视频...")
    print("=" * 60)

    output_template = os.path.join(output_dir, "%(title)s.%(ext)s")

    fmt = (
        f"bestvideo[height<={config.MAX_VIDEO_HEIGHT}]+bestaudio"
        f"/best[height<={config.MAX_VIDEO_HEIGHT}]"
        f"/bestvideo+bestaudio"
        f"/best"
    )
    cmd = [
        "yt-dlp",
        "-f",
        fmt,
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
        "--no-playlist",
    ]
    cmd += _ytdlp_extra_args(url)
    cmd.append(url)

    subprocess.run(cmd, check=True)

    out = Path(output_dir)
    video_path = _pick_downloaded_video_file(out)
    print(f"✅ 视频已下载: {video_path}")

    # 用 ffprobe 读取并打印视频规格
    try:
        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,codec_name,bit_rate",
            "-show_entries",
            "format=duration,size,bit_rate",
            "-of",
            "default=noprint_wrappers=1",
            str(video_path),
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        info_lines = {}
        for line in probe_result.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info_lines[k.strip()] = v.strip()

        width = info_lines.get("width", "?")
        height = info_lines.get("height", "?")
        codec = info_lines.get("codec_name", "?")
        fps_raw = info_lines.get("r_frame_rate", "?")
        duration = float(info_lines.get("duration", 0))
        filesize = int(info_lines.get("size", 0))
        vbitrate = info_lines.get("bit_rate", "?")

        if "/" in fps_raw:
            num, den = fps_raw.split("/")
            fps_val = f"{int(num) / int(den):.2f}"
        else:
            fps_val = fps_raw

        h = int(duration) // 3600
        m = (int(duration) % 3600) // 60
        s = int(duration) % 60
        dur_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        size_mb = filesize / 1024 / 1024

        vbr_str = f"{int(vbitrate) // 1000} kbps" if vbitrate.isdigit() else vbitrate

        print(f"   📐 分辨率:  {width}x{height}")
        print(f"   🎞️  编码:    {codec}")
        print(f"   ⏱️  帧率:    {fps_val} fps")
        print(f"   ⏳ 时长:    {dur_str}")
        print(f"   💾 文件大小: {size_mb:.1f} MB")
        print(f"   📶 视频码率: {vbr_str}")
    except Exception as e:
        print(f"  ⚠ 无法读取视频规格: {e}")

    return str(video_path)


def prepare_source(source):
    """第一阶段：准备视频（下载或准备本地文件），返回已准备好的视频信息字典。"""
    is_local = os.path.isfile(source)
    try:
        if is_local:
            video_path = os.path.abspath(source)
            video_name = sanitize_name(Path(video_path).stem)
            output_dir = os.path.join("./output", video_name)
            os.makedirs(output_dir, exist_ok=True)

            safe_filename = video_name + Path(video_path).suffix
            target_path = os.path.join(output_dir, safe_filename)
            if os.path.abspath(video_path) != os.path.abspath(target_path):
                import shutil

                if not os.path.exists(target_path):
                    shutil.copy2(video_path, target_path)
                video_path = target_path

            print(f"📁 本地文件已准备: {video_path}")
        else:
            url = source
            temp_dir = "./output/_temp_download"
            os.makedirs(temp_dir, exist_ok=True)

            print(f"📥 下载视频: {url}")

            pre_file = None
            try:
                pre_cmd = ["yt-dlp", "--print", "title", "--no-playlist"]
                pre_cmd += _ytdlp_extra_args(url)
                pre_cmd.append(url)
                title_result = subprocess.run(
                    pre_cmd, capture_output=True, text=True, check=True
                )
                raw_title = title_result.stdout.strip()
                pre_name = sanitize_name(raw_title)
                pre_dir = os.path.join("./output", pre_name)
                pre_file = os.path.join(pre_dir, pre_name + ".mp4")
            except Exception:
                pass

            if pre_file and os.path.exists(pre_file):
                print(f"⏭️  视频已存在，跳过下载: {pre_file}")
                video_path = pre_file
                output_dir = pre_dir
            else:
                video_path = step1_download_video(url, temp_dir)

                video_name = sanitize_name(Path(video_path).stem)
                output_dir = os.path.join("./output", video_name)
                os.makedirs(output_dir, exist_ok=True)

                safe_filename = video_name + Path(video_path).suffix
                target_path = os.path.join(output_dir, safe_filename)
                if os.path.abspath(video_path) != os.path.abspath(target_path):
                    import shutil

                    shutil.move(video_path, target_path)
                    video_path = target_path

                try:
                    os.rmdir(temp_dir)
                except OSError:
                    pass

        return {
            "source": source,
            "video_path": video_path,
            "output_dir": output_dir,
            "status": "已下载",
            "error": None,
        }
    except Exception as e:
        print(f"\n❌ 下载/准备视频失败: {e}")
        return {
            "source": source,
            "video_path": None,
            "output_dir": None,
            "status": "失败",
            "last_step": "1-下载",
            "error": str(e),
        }
