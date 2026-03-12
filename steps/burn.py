"""
步骤 4：将字幕烧录进视频（ffmpeg 硬字幕）
"""
import os
import subprocess

from config import (
    FONT_SIZE, SUBTITLE_FONT, SUBTITLE_PRIMARY_COLOR,
    SUBTITLE_OUTLINE_COLOR, SUBTITLE_OUTLINE, SUBTITLE_SHADOW,
    SUBTITLE_MARGIN_V,
)


def step4_burn_subtitles(video_path, srt_path):
    """将双语字幕烧录进视频"""
    print("\n" + "=" * 60)
    print("🔥 第四步：压制硬字幕到视频...")
    print("=" * 60)

    output_path = video_path.rsplit(".", 1)[0] + "_硬字幕.mp4"
    if os.path.exists(output_path):
        print(f"⏭️  硬字幕视频已存在，跳过压制: {output_path}")
        return output_path

    # ffmpeg subtitle filter 路径规则：反斜杠→斜杠，冒号需转义，单引号需转义
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

    cmd = [
        "ffmpeg",
        "-hide_banner", "-loglevel", "warning", "-stats",
        "-i", video_path,
        "-vf", subtitle_filter,
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "medium",
        "-c:a", "copy",
        "-y",
        output_path,
    ]

    print(f"执行命令: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    print(f"✅ 最终视频已生成: {output_path}")
    return output_path
