# SubForge — AI 字幕一键生成工具

YouTube / 本地视频 → 语音识别 → AI 翻译 → 双语字幕压制，一条命令搞定。支持命令行和 Web UI 两种使用方式。

## 功能介绍

- **YouTube 视频下载** — 自动下载最高画质视频（可配置分辨率上限）
- **本地视频支持** — 直接传入本地视频文件路径，跳过下载
- **批量处理** — 支持同时传入多个文件 / 链接，按顺序依次处理，单个任务失败不影响后续
- **语音识别** — 基于 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)，本地 GPU 加速，生成精准英文字幕
- **AI 翻译** — 调用 Qwen3.5 等大模型 API 批量翻译，支持并发请求（默认 10 并发）
- **双语字幕** — 自动生成 英文 / 中文 / 双语 三份 `.srt` 字幕文件
- **硬字幕压制** — 通过 ffmpeg 将双语字幕烧录进视频，可直接上传 B 站
- **Web UI** — 基于 Gradio 的可视化界面，拖拽上传 / 粘贴链接即可，实时查看处理日志

## 环境配置

### 1. Python 依赖

```bash
# 推荐 Python 3.10+
pip install faster-whisper openai srt yt-dlp gradio
```

### 2. 系统工具

| 工具 | 用途 | 安装方式 |
|------|------|----------|
| [ffmpeg](https://ffmpeg.org/) | 视频压制 & 探测 | `winget install ffmpeg` 或官网下载 |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube 下载 | `pip install yt-dlp` |

### 3. GPU 加速（推荐）

faster-whisper 默认使用 GPU（CUDA），需要：
- NVIDIA 显卡 + 安装 [CUDA Toolkit](https://developer.nvidia.com/cuda-toolkit)
- 如无 GPU，脚本会自动回退到 CPU（速度较慢，建议将 `WHISPER_MODEL` 调小为 `base` 或 `tiny`）

### 4. API Key

本工具使用与 OpenAI SDK 兼容的 API 接口，支持任何兼容格式的大模型服务（如阿里云百炼、DeepSeek、硅基流动等）。

**首次配置：**

```bash
# 从模板复制一份本地配置（config.json 已在 .gitignore 中，不会上传到 GitHub）
cp config.example.json config.json
```

然后编辑 `config.json`，填写对应服务的 API Key 和接口地址：

```json
{
    "qwen_api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxx",
    "qwen_base_url": "https://your-api-endpoint/v1",
    "qwen_model": "your-model-name"
}
```

> **注意**：`config.json` 含有你的真实 API Key，已被 `.gitignore` 排除，永远不会被 git 追踪或上传。仓库中只保留 `config.example.json` 作为配置模板。

## 使用方法

### Web UI（推荐）

```bash
python app.py
```

启动后自动打开浏览器访问 `http://127.0.0.1:7860`，在界面中：

1. 粘贴 YouTube 链接（每行一个）和/或上传本地视频文件
2. 可选择是否压制硬字幕
3. 点击「开始处理」，右侧实时显示处理日志
4. 处理完成后直接下载输出文件

### 命令行

#### YouTube 视频

```bash
python auto_subtitle.py "https://www.youtube.com/watch?v=XXXXX"
```

#### 本地视频

```bash
python auto_subtitle.py ./input/my_video.mp4
```

#### 批量处理

支持同时传入多个 YouTube 链接和/或本地文件，按顺序依次处理：

```bash
python auto_subtitle.py "https://youtu.be/AAA" ./input/a.mp4 "https://youtu.be/BBB" ./input/b.mp4
```

- 每个任务独立处理，单个失败会跳过并继续后续任务
- 本地文件和 YouTube 链接可任意混合

### 输出结构

每个视频会在 `output/` 下自动创建以视频名命名的子目录：

```
output/
└── My_Video/
    ├── My_Video.mp4            # 原始视频
    ├── My_Video_en.srt         # 英文字幕
    ├── My_Video_zh.srt         # 中文字幕
    ├── My_Video_bilingual.srt  # 双语字幕（中文在上）
    └── My_Video_硬字幕.mp4      # 压制好的最终视频
```

### 配置说明

所有配置集中在项目根目录的 `config.json` 中，修改后立即生效（无需改代码）。缺失的字段会自动使用默认值。

主要参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `whisper_model` | `"medium"` | 语音识别模型 |
| `video_language` | `"en"` | 视频语言 |
| `max_video_height` | `1080` | 最大下载分辨率 |
| `qwen_api_key` | `""` | API Key（必填） |
| `qwen_model` | `"qwen3.5-plus"` | 翻译模型 |
| `translate_concurrency` | `10` | API 并发请求数 |
| `subtitle_max_gap_ms` | `1500` | 词间间隙超过此值(ms)则断句 |
| `font_size` | `20` | 字幕字体大小 |
| `subtitle_font` | `"Microsoft YaHei"` | 字幕字体 |

## 配置参数详解

### 语音识别

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `whisper_model` | `"medium"` | `tiny` / `base` / `small` / `medium` / `large-v3` | 模型越大越准但越慢，`tiny` 极快低精度，`large-v3` 最准 |
| `device` | `"auto"` | `auto` / `cuda` / `cpu` | 推理设备，`auto` 自动检测 GPU |
| `compute_type` | `"auto"` | `auto` / `float16` / `int8` / `float32` | 推理精度，GPU 推荐 `float16`，CPU 推荐 `int8` |
| `video_language` | `"en"` | `en` / `zh` / `ja` / `ko` / `fr` / `de` / `es` / `ru` / `auto` | 视频语言，`auto` 自动检测（速度稍慢） |
| `subtitle_max_gap_ms` | `1500` | 500~5000 | 词级时间戳间隙阈值（毫秒），超过此值自动断开为新字幕，用于解决音乐/长静音导致的跨段粘连 |

### 下载

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `max_video_height` | `1080` | `720` / `1080` / `1440` / `2160` | YouTube 下载的最大分辨率 |

### 翻译 API

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `qwen_api_key` | `""` | — | API Key（**必填**） |
| `qwen_base_url` | — | — | API 接口地址，填写所用服务商提供的 base URL |
| `qwen_model` | `"qwen3.5-plus"` | `qwen3.5-plus` / `qwen3.5-turbo` / `qwen-turbo` | 翻译使用的模型 |
| `translate_batch_size` | `50` | 10~100 | 每批翻译的字幕条数，越大越快但易超 token 限制 |
| `translate_concurrency` | `10` | 1~20 | 并发请求批数，受 API QPS 限制 |
| `api_retry` | `3` | 1~10 | 单批翻译失败的最大重试次数 |
| `api_sleep` | `0.5` | 0~2 | 并发批次间的错开抖动上限（秒） |

### 字幕样式

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `font_size` | `20` | 16~28 | 字体大小（像素） |
| `subtitle_font` | `"Microsoft YaHei"` | `Microsoft YaHei` / `SimHei` / `Arial` / `Noto Sans CJK SC` | 字体名称 |
| `subtitle_primary_color` | `"&H00FFFFFF"` | 白色 `&H00FFFFFF` / 黄色 `&H0000FFFF` | 字体颜色（ASS 格式：`&H` + 透明度 + BGR 十六进制） |
| `subtitle_outline_color` | `"&H00000000"` | 黑色 `&H00000000` | 描边颜色 |
| `subtitle_outline` | `1` | `0`=无 / `1`=细边 / `2`=粗边 | 描边粗细 |
| `subtitle_shadow` | `0` | `0`=关闭 / `1`=轻阴影 / `2`=重阴影 | 阴影偏移距离 |
| `subtitle_margin_v` | `30` | 10~80 | 字幕距视频底部距离（像素），越大越高 |
