# SubForge — AI 字幕 & 配音一键生成工具

YouTube / 本地视频 → 语音识别 → AI 翻译 → 双语字幕压制 → AI 中文配音，一条命令搞定。支持命令行和 Web UI 两种使用方式。

## 功能介绍

- **YouTube 视频下载** — 自动下载最高画质视频（可配置分辨率上限）
- **本地视频支持** — 直接传入本地视频文件路径，跳过下载
- **批量处理** — 支持同时传入多个文件 / 链接，按顺序依次处理，单个任务失败不影响后续
- **语音识别** — 基于 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)，本地 GPU 加速，生成精准英文字幕
- **AI 翻译** — 调用 Qwen3.5 等大模型 API 批量翻译，支持并发请求（默认 10 并发）
- **双语字幕** — 自动生成 英文 / 中文 / 双语 三份 `.srt` 字幕文件
- **硬字幕压制** — 通过 ffmpeg 将双语字幕烧录进视频，可直接上传 B 站
- **AI 中文配音** — 使用 [demucs](https://github.com/facebookresearch/demucs) 分离背景音 + [edge-tts](https://github.com/rany2/edge-tts) 合成中文语音，自动混合为配音视频
- **AI 画质增强** — 基于 [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) 超分辨率，将视频放大至最高 4K，GPU 加速，自动限制输出不超过 4K 分辨率
- **Web UI** — 基于 Gradio 的可视化界面，拖拽上传 / 粘贴链接即可，实时查看处理日志

## 处理流程

```
视频输入 → ① 下载/导入 → ①.5 AI画质增强(可选) → ② 语音识别(字幕) → ③ AI翻译(中文)
         → ④ 硬字幕压制 → ⑤ 音频分离(demucs) → ⑥ TTS语音合成
         → ⑦ 混合音频 → 配音视频输出
```

每一步都有跳过已存在文件的逻辑，中断后重跑会自动从上次断点继续。

## 环境配置

### 1. Python 依赖

```bash
# 推荐 Python 3.10+，conda 环境
conda create -n subforge python=3.10
conda activate subforge

# 核心依赖
pip install faster-whisper openai srt yt-dlp gradio

# 配音功能依赖
pip install demucs edge-tts pydub soundfile

# 画质增强依赖
pip install realesrgan basicsr opencv-python
```

> **Windows CUDA 版 torch**：如果 `torch` 是 CPU 版（`torch.__version__` 末尾含 `+cpu`），画质增强只能用 CPU，速度极慢。RTX 显卡请重装 CUDA 版：
> ```bash
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124 --force-reinstall --no-deps
> ```

> **basicsr 兼容性修复**：`basicsr 1.4.2` 引用了 torchvision 旧 API，需手动 patch 一行（安装后执行一次）：
> 找到 `site-packages/basicsr/data/degradations.py`，将
> `from torchvision.transforms.functional_tensor import rgb_to_grayscale`
> 改为
> `from torchvision.transforms.functional import rgb_to_grayscale`

> **关于 soundfile**：`torchaudio 2.10+` 默认使用 `torchcodec` 保存音频，但该库在 Windows 上存在 FFmpeg DLL 兼容问题。本项目通过 `_run_demucs.py` 包装脚本用 `soundfile` 替代 `torchcodec` 进行音频保存，因此 **必须安装 soundfile**（`pip install soundfile`），否则 demucs 音频分离步骤会失败。

### 2. 系统工具

| 工具 | 用途 | 安装方式 |
|------|------|----------|
| [ffmpeg](https://ffmpeg.org/) | 视频压制 / 音频处理 / 探测 | `winget install ffmpeg` 或官网下载，需加入 PATH |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube 下载 | `pip install yt-dlp`（已包含在上方依赖中） |

### 3. GPU 加速（推荐）

faster-whisper 默认使用 GPU（CUDA），需要：
- NVIDIA 显卡 + 安装 [CUDA Toolkit](https://developer.nvidia.com/cuda-toolkit)
- 如无 GPU，脚本会自动回退到 CPU（速度较慢，建议将 `whisper_model` 调小为 `base` 或 `tiny`）

demucs 同样支持 GPU 加速，有 CUDA 时会自动使用。

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
2. 可选择是否压制硬字幕、是否启用 AI 中文配音、是否启用 AI 画质增强
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

> 命令行模式默认启用硬字幕压制，配音功能需通过 Web UI 开启。

### 输出结构

每个视频会在 `output/` 下自动创建以视频名命名的子目录：

```
output/
└── My_Video/
    ├── My_Video.mp4              # 原始视频
    ├── My_Video_en.srt           # 英文字幕
    ├── My_Video_zh.srt           # 中文字幕
    ├── My_Video_bilingual.srt    # 双语字幕（中文在上）
    ├── My_Video_硬字幕.mp4        # 压制好的字幕视频
    ├── My_Video_audio.wav        # 提取的音频（配音时生成）
    ├── My_Video_background.wav   # 分离的背景音（配音时生成）
    ├── My_Video_tts.wav          # TTS 合成语音（配音时生成）
    └── My_Video_配音.mp4          # 最终配音视频（含字幕 + 中文配音）
```

## 配置参数详解

所有配置集中在项目根目录的 `config.json` 中，修改后立即生效（无需改代码）。缺失的字段会自动使用默认值。

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
| `ytdlp_cookies` | `""` | 文件路径字符串 | Netscape 格式的 cookies 文件路径（解决 YouTube 要求登录验证的问题），留空则不使用 |

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

### AI 配音

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `tts_voice` | `"zh-CN-YunjianNeural"` | 参见 [edge-tts 语音列表](https://github.com/rany2/edge-tts#voices) | TTS 语音角色，推荐：`zh-CN-YunxiNeural`（年轻男声）、`zh-CN-XiaoxiaoNeural`（女声） |
| `tts_rate` | `"+0%"` | `-50%` ~ `+100%` | TTS 基础语速调整 |
| `tts_volume` | `"+0%"` | `-50%` ~ `+50%` | TTS 音量调整 |
| `tts_bg_volume` | `0.5` | 0.0~1.0 | 背景音混合音量（0=静音，1=原音量） |
| `tts_max_speed` | `1.5` | 1.0~2.0 | TTS 最大加速倍率。当合成语音比字幕时间长时会加速适配，此值限制最大加速，避免语速过快听不清。设为 `1.0` 则完全不加速 |

### AI 画质增强

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `enhance_model` | `"RealESRGAN_x4plus"` | `RealESRGAN_x4plus` / `RealESRGAN_x4plus_anime_6B` / `RealESRGAN_x2plus` | 超分模型。通用视频用 `x4plus`；动漫/二次元用 `x4plus_anime_6B`（更轻量）；只需 2x 放大用 `x2plus` |
| `enhance_outscale` | `4` | `2` / `4` | 放大倍数。输出分辨率超过 4K（3840×2160）时会自动限制 |

> 模型权重文件（约 64MB）在首次运行时自动从 GitHub Releases 下载，保存在 `realesrgan` 包目录的 `weights/` 下。

## 常见问题

### YouTube 提示「Sign in to confirm you're not a bot」

YouTube 对部分 IP 或视频要求登录认证，yt-dlp 会报错 `Sign in to confirm you're not a bot`。

**解决方法：导出浏览器 cookies 供 yt-dlp 使用。**

#### 方法一：浏览器扩展导出（推荐，适合普通用户）

1. 在 Chrome / Edge 中安装扩展 [**Get cookies.txt LOCALLY**](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. 打开 [youtube.com](https://www.youtube.com) 并**确保已登录账号**
3. 点击扩展图标 → 选择「Export As」→「cookies.txt」
4. 将导出的文件保存到项目目录，例如 `cookies.txt`
5. 在 `config.json` 中填写路径：
   ```json
   "ytdlp_cookies": "./cookies.txt"
   ```

#### 方法二：yt-dlp 直接从浏览器读取（无需手动导出）

yt-dlp 支持直接读取已安装浏览器的 cookies，**但此方式不支持通过 config.json 配置**，需要临时在命令行使用：

```bash
yt-dlp --cookies-from-browser chrome "https://www.youtube.com/watch?v=XXXXX"
# 或 edge / firefox / opera 等
```

#### 注意事项

- cookies 文件包含账号登录信息，**请勿分享或提交到 Git**（`config.json` 已在 `.gitignore` 中，cookies 路径只存在于本机 `config.json` 里）
- cookies 有有效期，若下载再次报认证错误，重新导出一次即可
- 建议创建一个专用的小号用于导出 cookies，避免主账号暴露

### demucs 分离音频时报 torchcodec / torchaudio 错误

`torchaudio 2.10+` 默认依赖 `torchcodec` 保存音频，而 `torchcodec` 在 Windows 上需要 FFmpeg full-shared DLLs，通常会报 `Could not load libtorchcodec` 错误。

**解决方案**（本项目已内置处理）：
1. 确保已安装 `soundfile`：`pip install soundfile`
2. 卸载 `torchcodec`（如已安装）：`pip uninstall torchcodec`
3. 本项目通过 `_run_demucs.py` 包装脚本自动用 `soundfile` 替代 `torchcodec` 保存音频，无需手动修改 demucs 源码

### GPU 内存不足

- 将 `whisper_model` 改为更小的模型（`base` 或 `small`）
- demucs 可通过 `--segment` 参数控制每次处理的音频长度（当前使用默认值）

### 翻译速度慢

- 增大 `translate_batch_size`（每批更多字幕，减少 API 调用次数）
- 增大 `translate_concurrency`（更多并发请求，受 API 限速约束）
- 使用更快的模型如 `qwen3.5-turbo`

### 配音语速过快

- 降低 `tts_max_speed`（如设为 `1.2` 甚至 `1.0`）
- 调整 `tts_rate` 为负值（如 `"-10%"`）减慢 TTS 基础语速

### 画质增强速度慢

- 确认是否用上了 GPU：日志应显示 `设备: cuda`；若显示 `cpu` 请参考上方安装 CUDA 版 torch
- 对于 1080p 视频，RTX 3090 约 **3~5 帧/秒**（≈ 视频时长的 6~10 倍处理时间），属正常范围
- 如显存不足报 OOM，可在 `auto_subtitle.py` 中将 `tile_size = 1024` 改小（如 `512`）

### 画质增强报 lzma DLL 错误（Windows）

`basicsr` 依赖 `lzma`，conda 自建环境有时缺少 `liblzma.dll`：
```powershell
# 将 base 环境的 DLL 复制到当前环境
Copy-Item "$env:CONDA_PREFIX\..\..\Library\bin\liblzma.dll" "$env:CONDA_PREFIX\Library\bin\"
```

## 项目结构

```
SubForge/
├── auto_subtitle.py       # 核心处理脚本（7 步流水线）
├── app.py                 # Gradio Web UI
├── _run_demucs.py         # demucs 包装脚本（绕过 torchcodec）
├── config.json            # 本地配置（不上传，含 API Key）
├── config.example.json    # 配置模板
├── .gitignore
├── README.md
├── input/                 # 本地视频输入目录
└── output/                # 处理结果输出目录
```

## License

MIT
