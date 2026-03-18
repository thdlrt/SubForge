# SubForge

SubForge 是一个面向中文工作流的视频处理工具，支持从 YouTube 链接或本地视频出发，完成字幕识别、AI 翻译、AI 总结、双语字幕压制和中文 AI 配音。

推荐阅读顺序：

1. 如果你只是直接使用，先看“直接使用发布包”
2. 如果你需要改配置，再看“基础配置”
3. 如果你要重新打包，再看“重新构建发布包”

## 直接使用发布包

适用系统：

- Windows 10 / 11 x64
- 无需单独安装 Python

使用步骤：

1. 解压 `dist/SubForge/`
2. 在程序目录准备 `config.json`
3. 运行 [`dist\SubForge\SubForge.exe`](e:\code\other\AiText\dist\SubForge\SubForge.exe)
4. Web UI 中粘贴 YouTube 链接或上传本地视频

发布包默认行为：

- `config.json` 从 exe 同目录读取
- `output/` 默认输出到 exe 同目录

## 快速配置

```json
{
  "qwen_api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxx",
  "qwen_base_url": "https://your-api-endpoint/v1",
  "qwen_model": "qwen3.5-plus"
}
```

如果你只是直接使用发布包，通常只需要先确认这些值：

## 基础配置

所有配置都通过 `config.json` 管理。缺失字段会自动回退到内置默认值。

### 最常用参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `whisper_model` | `medium` | 语音识别模型，越大越准也越慢 |
| `device` | `auto` | 推理设备，自动选择 `cuda` 或 `cpu` |
| `compute_type` | `auto` | whisper 推理精度 |
| `video_language` | `null` | 视频语言，留空表示自动检测 |
| `qwen_api_key` | `""` | 翻译和总结用的 API Key |
| `qwen_base_url` | `""` | API 服务地址 |
| `qwen_model` | `qwen3.5-plus` | 翻译与总结模型 |
| `translate_batch_size` | `50` | 每批字幕翻译条数 |
| `translate_concurrency` | `10` | 翻译并发数 |
| `ffmpeg_video_encoder` | `auto` | 视频编码器，支持 `auto / libx264 / h264_nvenc` |
| `tts_voice` | `zh-CN-YunjianNeural` | 中文配音声音 |
| `tts_rate` | `+0%` | TTS 基础语速 |
| `tts_volume` | `+0%` | TTS 音量 |
| `tts_bg_volume` | `0.5` | 背景音混音音量 |
| `tts_max_speed` | `1.5` | TTS 为适配字幕时允许的最大加速倍率 |
| `enhance_model` | `RealESRGAN_x4plus` | 画质增强模型 |
| `enhance_outscale` | `4` | 放大倍率 |

### 字幕样式参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `font_size` | `20` | 字幕字号 |
| `subtitle_font` | `Microsoft YaHei` | 字体名称 |
| `subtitle_primary_color` | `&H00FFFFFF` | 主字体颜色 |
| `subtitle_outline_color` | `&H00000000` | 描边颜色 |
| `subtitle_outline` | `1` | 描边粗细 |
| `subtitle_shadow` | `0` | 阴影强度 |
| `subtitle_margin_v` | `30` | 字幕距底部边距 |

### 下载相关参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_video_height` | `1080` | YouTube 下载最大分辨率 |
| `ytdlp_client` | `""` | 可选 `ios / tv_embedded / web` |
| `ytdlp_cookies` | `""` | 可填 cookies 文件路径或浏览器名 |

### 断句参数

基础断句参数：

- `subtitle_max_gap_ms`
- `subtitle_max_chars`

高级断句参数在 `subtitle_advanced` 下，例如：

- `target_chars_ratio`
- `min_chars_ratio`
- `hard_max_chars_ratio`
- `soft_max_duration_sec`
- `hard_max_duration_sec`
- `merge_max_gap_sec`
- `merge_max_duration_sec`
- `split_max_duration_sec`

如果你不是在专门微调字幕切分效果，通常只需要先调整：

- `subtitle_max_gap_ms`
- `subtitle_max_chars`

## 常见配置建议

普通 CPU 机器：

```json
{
  "whisper_model": "base",
  "device": "cpu",
  "compute_type": "int8",
  "ffmpeg_video_encoder": "libx264"
}
```

有 NVIDIA GPU 的机器：

```json
{
  "device": "cuda",
  "compute_type": "float16",
  "ffmpeg_video_encoder": "h264_nvenc"
}
```

如果目标机器不确定是否有 NVIDIA 显卡，建议：

```json
{
  "ffmpeg_video_encoder": "auto"
}
```

这样第 4 步会优先尝试 `h264_nvenc`，失败时自动回退到 `libx264`。

## 主要功能

- YouTube 视频下载，也支持本地视频直接导入
- faster-whisper 语音识别，生成英文字幕
- AI 翻译为中文字幕，并输出双语字幕
- AI 内容总结，输出 Markdown 文档
- ffmpeg 压制双语硬字幕
- demucs 分离背景音，edge-tts 生成中文配音
- Real-ESRGAN 画质增强，适合有 NVIDIA GPU 的机器
- Gradio Web UI 和命令行两种入口

## Web UI

源码模式下启动方式：

```powershell
python app.py
```

默认地址：

```text
http://127.0.0.1:7860
```

当前界面为中文，主要区域包括：

- YouTube 链接输入
- 本地视频上传
- 处理选项
- 处理日志
- 输出文件下载

## 输出说明

每个视频会在 `output/` 下创建自己的子目录，常见输出包括：

- 英文字幕 `.srt`
- 中文字幕 `.srt`
- 双语字幕 `.srt`
- AI 总结 `.md`
- 硬字幕视频
- 中文配音视频

## 源码运行

### 1. 创建环境

推荐直接使用仓库里的 `environment.yml`：

```powershell
conda env create -f environment.yml
conda activate subforge
```

### 2. 安装 PyTorch

按机器环境二选一：

```powershell
# NVIDIA GPU
pip install -r requirements.cuda124.txt

# 仅 CPU
pip install -r requirements.cpu.txt
```

### 3. 安装项目依赖

```powershell
pip install -r requirements.txt
```

### 4. 准备系统工具

运行流程依赖下面三个工具：

- `ffmpeg`
- `ffprobe`
- `yt-dlp`

源码模式下可以放到系统 `PATH`，也可以放到仓库的 `bin/` 目录中。

### 5. 配置 API

```powershell
Copy-Item .\config.example.json .\config.json
```

然后按前文“基础配置”修改参数。

## 命令行

处理 YouTube 视频：

```powershell
python auto_subtitle.py "https://www.youtube.com/watch?v=XXXXX"
```

处理本地视频：

```powershell
python auto_subtitle.py .\input\my_video.mp4
```

批量处理：

```powershell
python auto_subtitle.py "https://youtu.be/AAA" .\input\a.mp4 "https://youtu.be/BBB"
```

## 重新构建发布包

### 1. 准备外部工具

打包前请先把下面三个文件放进 `bin/`：

- `bin/ffmpeg.exe`
- `bin/ffprobe.exe`
- `bin/yt-dlp.exe`

### 2. 安装构建依赖

```powershell
pip install -r requirements.build.txt
```

### 3. 执行构建

如果当前环境里 `python` 就是目标解释器：

```powershell
.\build_release.ps1
```

如果要显式指定解释器：

```powershell
.\build_release.ps1 -PythonExe "C:\path\to\python.exe"
```

### 4. 构建产物

当前构建脚本只产出文件夹版发布包：

- `dist/SubForge/`

如果你需要对外分发 zip，请手动压缩 `dist/SubForge/`。

### 5. 发布前建议检查

- 确认 `config.example.json` 在包内
- 确认 `ffmpeg / ffprobe / yt-dlp` 已进入 `_internal/bin`
- 在没有 Python 的 Windows x64 机器上做一次真实启动测试
- 测一次字幕压制和中文配音流程

## 目录结构

```text
AiText/
├─ app.py                   # Gradio 中文 Web UI
├─ auto_subtitle.py         # 主流程入口
├─ runtime.py               # 源码模式 / 发布模式运行时适配
├─ _run_whisper.py          # whisper worker
├─ _run_demucs.py           # demucs worker
├─ steps/                   # 各处理步骤
├─ config.example.json      # 配置模板
├─ config.py                # 配置读取与默认值
├─ build_release.ps1        # Windows 发布包构建脚本
├─ subforge.release.spec    # PyInstaller 构建配置
├─ requirements*.txt        # 运行与构建依赖
├─ environment.yml          # conda 环境定义
├─ bin/                     # 发布包所需外部工具
├─ input/                   # 本地输入目录
└─ output/                  # 处理输出目录
```

下面这些目录属于构建产物或缓存，不需要提交到仓库：

- `build/`
- `dist/`
- `release/`
- `__pycache__/`

## 注意事项

- `config.json` 和 `cookies.txt` 包含本地敏感信息，默认不会提交
- Real-ESRGAN 需要 NVIDIA GPU，CPU 环境下建议关闭
- demucs、Real-ESRGAN 首次运行可能会下载模型
- `edge-tts` 和翻译接口需要联网

## License

MIT
