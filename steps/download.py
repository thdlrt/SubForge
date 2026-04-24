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


def _is_gamedev_hostname(hostname: str) -> bool:
    return bool(hostname) and hostname.endswith("gamedev.tv")


def check_gamedev_url_for_ytdlp(url: str) -> None:
    """
    yt-dlp 内置的 GameDevTV 提取器只支持「学习中心」数字 ID 链接：
    https://www.gamedev.tv/dashboard/courses/<course_id>/<lecture_id>
    课程前台 slug 页（/courses/课程名/课时名）会落入 generic 并报 Unsupported URL。
    """
    if not (url or "").strip():
        return
    p = urlparse(url.strip())
    host = (p.hostname or "").lower()
    if not _is_gamedev_hostname(host):
        return
    path = p.path or ""
    if "/dashboard/courses/" in path:
        return
    if "/courses/" in path:
        raise ValueError(
            "GameDev.tv：当前链接是课程前台 slug 页面，yt-dlp 无法解析（会报 Unsupported URL）。\n"
            "请从网站「My Courses / 我的课程」进入已购课程，点开某一课时的播放页，复制地址栏链接，\n"
            "应为：\n"
            "  https://www.gamedev.tv/dashboard/courses/课程数字ID/课时数字ID\n"
            "不要使用 gamedev.tv/courses/课程名/课时名 这类链接。\n"
            "并确保已配置登录 Cookie（如 ytdlp_cookies_by_host 中的 gamedev.tv）。"
        )


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
    """返回 yt-dlp 的 cookie +（仅 YouTube）client + 站点头 等参数列表。"""
    args = []
    hostname = _hostname_from_url(url) if url else ""
    if hostname and _is_gamedev_hostname(hostname):
        # 部分 API/CDN 校验 Referer，与 cookies 一并提供
        args += ["--add-header", "Referer:https://gamedev.tv/"]
    if hostname and _is_youtube_hostname(hostname):
        # 新版 yt-dlp 在部分 YouTube 链路上需要远程 EJS challenge 组件，否则只会拿到 storyboard。
        args += ["--remote-components", "ejs:github"]
        print("   YouTube challenge 组件: ejs:github")
        if config.YTDLP_CLIENT:
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


def _translate_title_with_qwen(raw_title: str) -> str:
    """使用 Qwen 将视频标题翻译为简体中文；失败时返回原文。"""
    text = (raw_title or "").strip()
    if not text:
        return text
    if not (config.QWEN_API_KEY or "").strip():
        print("   ⚠ 未配置 qwen_api_key，跳过中文命名")
        return text
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.QWEN_API_KEY, base_url=config.QWEN_BASE_URL)
        resp = client.chat.completions.create(
            model=config.QWEN_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "将给定视频标题翻译成简体中文。"
                        "只输出译文，不要解释，不要加引号。"
                        "专有名词按中文游戏开发语境保留。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=128,
        )
        zh = (resp.choices[0].message.content or "").strip()
        if zh:
            return zh
    except Exception as e:
        print(f"   WARN 中文命名翻译失败，保持原标题: {e}")
    return text


def _rename_video_to_zh(video_path: str) -> str:
    """将视频文件名翻译为中文并重命名（同目录），返回新路径。"""
    old_path = os.path.abspath(video_path)
    if not os.path.isfile(old_path):
        return video_path
    stem = Path(old_path).stem
    ext = Path(old_path).suffix
    zh_title = sanitize_name(_translate_title_with_qwen(stem))
    if not zh_title:
        return video_path
    new_path = os.path.join(os.path.dirname(old_path), zh_title + ext)
    if os.path.abspath(new_path) == old_path:
        return video_path
    if os.path.exists(new_path):
        print(f"   ⚠ 中文命名目标已存在，跳过重命名: {new_path}")
        return video_path
    os.rename(old_path, new_path)
    print(f"   RENAMED 已重命名为中文标题: {os.path.basename(new_path)}")
    return new_path


def step1_download_video(url, output_dir):
    """使用 yt-dlp 下载视频（含 HLS 等），输出为 MP4 或无损封装为 MP4。"""
    check_gamedev_url_for_ytdlp(url)

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

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        hostname = _hostname_from_url(url)
        if _is_youtube_hostname(hostname):
            hint_lines = [
                "YouTube 下载失败。",
                "常见原因：",
                "1) cookies 过期/不完整；",
                "2) 代理出口不稳定（视频签名 URL 绑定出口 IP，切换节点会触发 403）；",
                "3) 代理规则未同时覆盖 youtube.com 与 *.googlevideo.com。",
                "4) yt-dlp 未拿到 YouTube challenge 组件，日志会出现 n challenge solving failed / Only images are available。",
                "",
                "建议：",
                "- 重新导出 YouTube cookies（Netscape 格式）；",
                "- 确保 yt-dlp 全流程走同一个稳定代理出口（避免负载均衡轮换）；",
                "- 在代理工具中将 youtube.com / googlevideo.com 设为同一路由策略。",
                "- 若日志出现 challenge 相关警告，确认当前网络可访问 github.com 以下载 yt-dlp 的 EJS 组件。",
            ]
            raise RuntimeError("\n".join(hint_lines)) from e
        raise

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


def prepare_source(source, translate_video_name=False):
    """第一阶段：准备媒体（下载或准备本地文件），返回已准备好的媒体信息字典。"""
    is_local = os.path.isfile(source)
    try:
        if is_local:
            video_path = os.path.abspath(source)
            video_name = sanitize_name(Path(video_path).stem)
            media_kind = "audio" if Path(video_path).suffix.lower() in {
                ".aac", ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".wma"
            } else "video"
            output_dir = os.path.join("./output", video_name)
            os.makedirs(output_dir, exist_ok=True)

            safe_filename = video_name + Path(video_path).suffix
            target_path = os.path.join(output_dir, safe_filename)
            if os.path.abspath(video_path) != os.path.abspath(target_path):
                import shutil

                if not os.path.exists(target_path):
                    shutil.copy2(video_path, target_path)
                video_path = target_path

            print(f"📁 本地{ '音频' if media_kind == 'audio' else '视频' }已准备: {video_path}")
        else:
            url = source
            media_kind = "video"
            temp_dir = "./output/_temp_download"
            os.makedirs(temp_dir, exist_ok=True)

            print(f"📥 下载视频: {url}")

            check_gamedev_url_for_ytdlp(url)

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

        if translate_video_name and video_path and os.path.isfile(video_path):
            video_path = _rename_video_to_zh(video_path)

        return {
            "source": source,
            "video_path": video_path,
            "output_dir": output_dir,
            "media_kind": media_kind,
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
