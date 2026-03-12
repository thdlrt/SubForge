"""
步骤 1：视频下载与准备
"""
import os
import subprocess
import sys
from pathlib import Path

from config import (
    MAX_VIDEO_HEIGHT, YTDLP_COOKIES, YTDLP_CLIENT,
)
from utils import sanitize_name


def _ytdlp_extra_args():
    """返回 yt-dlp 的 cookie + client 参数列表"""
    args = []
    if YTDLP_CLIENT:
        args += ["--extractor-args", f"youtube:player_client={YTDLP_CLIENT}"]
        print(f"   YouTube 客户端: {YTDLP_CLIENT}")
    if not YTDLP_COOKIES:
        return args
    if os.path.isfile(YTDLP_COOKIES):
        print(f"   使用 cookies 文件: {YTDLP_COOKIES}")
        return args + ["--cookies", YTDLP_COOKIES]
    if os.path.sep not in YTDLP_COOKIES and "/" not in YTDLP_COOKIES and not YTDLP_COOKIES.endswith(".txt"):
        print(f"   从浏览器读取 cookies: {YTDLP_COOKIES}")
        return args + ["--cookies-from-browser", YTDLP_COOKIES]
    print(f"   ⚠ cookies 文件不存在: {YTDLP_COOKIES}，将不使用 cookies")
    return args


def step1_download_video(url, output_dir):
    """下载 YouTube 视频"""
    print("\n" + "=" * 60)
    print("📥 第一步：下载视频...")
    print("=" * 60)

    output_template = os.path.join(output_dir, "%(title)s.%(ext)s")

    fmt = (
        f"bestvideo[height<={MAX_VIDEO_HEIGHT}]+bestaudio"
        f"/best[height<={MAX_VIDEO_HEIGHT}]"
        f"/bestvideo+bestaudio"
        f"/best"
    )
    cmd = [
        "yt-dlp",
        "-f", fmt,
        "--merge-output-format", "mp4",
        "-o", output_template,
        "--no-playlist",
    ]
    cmd += _ytdlp_extra_args()
    cmd.append(url)

    subprocess.run(cmd, check=True)

    mp4_files = list(Path(output_dir).glob("*.mp4"))
    if not mp4_files:
        raise FileNotFoundError("未找到下载的视频文件！")

    video_path = max(mp4_files, key=os.path.getmtime)
    print(f"✅ 视频已下载: {video_path}")

    # 用 ffprobe 读取并打印视频规格
    try:
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,codec_name,bit_rate",
            "-show_entries", "format=duration,size,bit_rate",
            "-of", "default=noprint_wrappers=1",
            str(video_path)
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        info_lines = {}
        for line in probe_result.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info_lines[k.strip()] = v.strip()

        width     = info_lines.get("width", "?")
        height    = info_lines.get("height", "?")
        codec     = info_lines.get("codec_name", "?")
        fps_raw   = info_lines.get("r_frame_rate", "?")
        duration  = float(info_lines.get("duration", 0))
        filesize  = int(info_lines.get("size", 0))
        vbitrate  = info_lines.get("bit_rate", "?")

        if "/" in fps_raw:
            num, den = fps_raw.split("/")
            fps_val = f"{int(num)/int(den):.2f}"
        else:
            fps_val = fps_raw

        h = int(duration) // 3600
        m = (int(duration) % 3600) // 60
        s = int(duration) % 60
        dur_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        size_mb = filesize / 1024 / 1024

        vbr_str = f"{int(vbitrate)//1000} kbps" if vbitrate.isdigit() else vbitrate

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
                pre_cmd += _ytdlp_extra_args()
                pre_cmd.append(url)
                title_result = subprocess.run(
                    pre_cmd,
                    capture_output=True, text=True, check=True
                )
                raw_title = title_result.stdout.strip()
                pre_name = sanitize_name(raw_title)
                pre_dir  = os.path.join("./output", pre_name)
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
