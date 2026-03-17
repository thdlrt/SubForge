"""
步骤 4：将字幕烧录进视频（ffmpeg 硬字幕）
"""
import os
import subprocess
from functools import lru_cache

from config import (
    FONT_SIZE, SUBTITLE_FONT, SUBTITLE_PRIMARY_COLOR,
    SUBTITLE_OUTLINE_COLOR, SUBTITLE_OUTLINE, SUBTITLE_SHADOW,
    SUBTITLE_MARGIN_V, FFMPEG_VIDEO_ENCODER,
)


@lru_cache(maxsize=1)
def _ffmpeg_encoders_text():
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=True,
    )
    return result.stdout


def _has_ffmpeg_encoder(name):
    try:
        return name in _ffmpeg_encoders_text()
    except Exception:
        return False


def _pick_video_encoder():
    preferred = (FFMPEG_VIDEO_ENCODER or "auto").strip().lower()
    if preferred == "auto":
        preferred = "h264_nvenc" if _has_ffmpeg_encoder("h264_nvenc") else "libx264"

    if preferred == "h264_nvenc":
        if not _has_ffmpeg_encoder("h264_nvenc"):
            print("⚠️  未检测到 h264_nvenc，回退到 libx264")
            preferred = "libx264"
        else:
            return preferred, [
                "-c:v", "h264_nvenc",
                "-preset", "p5",
                "-rc", "vbr",
                "-cq", "19",
                "-b:v", "0",
            ]

    if preferred == "libx264":
        return preferred, ["-c:v", "libx264", "-crf", "18", "-preset", "medium"]

    raise ValueError(
        f"不支持的 ffmpeg_video_encoder: {FFMPEG_VIDEO_ENCODER}. "
        "可选值: auto / libx264 / h264_nvenc"
    )


def step4_burn_subtitles(video_path, srt_path):
    """将双语字幕烧录进视频"""
    print("\n" + "=" * 60)
    print("🎞️  第四步：压制硬字幕到视频...")
    print("=" * 60)

    output_path = video_path.rsplit(".", 1)[0] + "_硬字幕.mp4"
    if os.path.exists(output_path):
        print(f"⏭️  硬字幕视频已存在，跳过压制: {output_path}")
        return output_path

    srt_escaped = srt_path.replace("\\", "/").replace("'", "\\'").replace(":", "\\:")
    style = (
        f"FontSize={FONT_SIZE}"
        f",FontName={SUBTITLE_FONT}"
        f",PrimaryColour={SUBTITLE_PRIMARY_COLOR}"
        f",OutlineColour={SUBTITLE_OUTLINE_COLOR}"
        f",Outline={SUBTITLE_OUTLINE}"
        f",Shadow={SUBTITLE_SHADOW}"
        f",MarginV={SUBTITLE_MARGIN_V}"
        f",Bold=1"
    )
    subtitle_filter = f"subtitles='{srt_escaped}':force_style='{style}'"
    encoder_name, encoder_args = _pick_video_encoder()

    cmd = [
        "ffmpeg",
        "-hide_banner", "-loglevel", "warning", "-stats",
        "-i", video_path,
        "-vf", subtitle_filter,
        *encoder_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-y",
        output_path,
    ]

    print(f"视频编码器: {encoder_name}")
    print(f"执行命令: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    print(f"✅ 最终视频已生成: {output_path}")
    return output_path
