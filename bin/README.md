# 发布包附带工具

在执行 `build_release.ps1` 之前，把下面三个文件放到当前目录：

- `ffmpeg.exe`
- `ffprobe.exe`
- `yt-dlp.exe`

发布包会优先使用这里的可执行文件；源码模式下如果这里不存在，则回退到系统 `PATH`。
