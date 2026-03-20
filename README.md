# SubForge — AI 字幕 & 配音一键生成工具

YouTube / 本地视频 → 语音识别 → AI 概括总结（可选）→ AI 翻译 → 双语字幕压制 → AI 中文配音，一条命令搞定。支持命令行和 Web UI 两种使用方式。

## 功能介绍

- **YouTube 视频下载** — 自动下载最高画质视频（可配置分辨率上限）
- **本地视频支持** — 直接传入本地视频文件路径，跳过下载
- **批量处理** — 支持同时传入多个文件 / 链接，按顺序依次处理，单个任务失败不影响后续
- **语音识别** — 基于 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)，本地 GPU 加速，生成精准英文字幕
- **AI 翻译** — 调用 Qwen3.5 等大模型 API 批量翻译，支持并发请求（默认 10 并发）
- **AI 内容总结（可选）** — 基于英文 `.srt` 字幕调用大模型生成中文专业总结，输出 Markdown 文档
- **双语字幕** — 自动生成 英文 / 中文 / 双语 三份 `.srt` 字幕文件
- **硬字幕压制** — 通过 ffmpeg 将双语字幕烧录进视频，可直接上传 B 站
- **AI 中文配音** — 使用 [demucs](https://github.com/facebookresearch/demucs) 分离背景音；TTS 可选 [edge-tts](https://github.com/rany2/edge-tts)、阿里云 **Qwen TTS**（DashScope）或本地 **CosyVoice**，自动混合为配音视频
- **AI 画质增强** — 基于 [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) 超分辨率，将视频放大至最高 4K，GPU 加速，自动限制输出不超过 4K 分辨率
- **Web UI** — 基于 Gradio 的可视化界面，拖拽上传 / 粘贴链接即可，实时查看处理日志

## 处理流程

```
视频输入 → ① 下载/导入 → ①.5 AI画质增强(可选) → ② 语音识别(字幕) → ②.5 AI概括总结(可选)
         → ③ AI翻译(中文)
         → ④ 硬字幕压制 → ⑤ 音频分离(demucs) → ⑥ TTS语音合成
         → ⑦ 混合音频 → 配音视频输出
```

每一步都有跳过已存在文件的逻辑，中断后重跑会自动从上次断点继续。

## 环境配置

先说结论：

- 没有 NVIDIA GPU，仍可用：下载、识别、翻译、字幕压制、AI 总结、AI 配音。
- 只有 AI 画质增强（Real-ESRGAN）要求 NVIDIA GPU + CUDA。

### 1. 一键创建环境（推荐）

```bash
conda env create -f environment.yml
conda activate subforge
```

### 2. 安装 Torch（按硬件二选一）

```bash
# NVIDIA GPU（CUDA 12.4，推荐）
pip install -r requirements.cuda124.txt

# 无 NVIDIA GPU（CPU，仅不支持 AI 超分）
pip install -r requirements.cpu.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. 系统工具

| 工具 | 用途 | 安装方式 |
|------|------|----------|
| [ffmpeg](https://ffmpeg.org/) | 视频压制 / 音频处理 / 探测 | `winget install ffmpeg` 或官网下载，需加入 PATH |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube 下载 | 已包含在 `requirements.txt` |

### 4. 安装后自检

```bash
python -c "import torch; print('torch:', torch.__version__, 'cuda:', torch.cuda.is_available())"
python -c "import gradio, faster_whisper, srt, openai; print('python deps ok')"
ffmpeg -version
```

若输出 `cuda: True`，说明可用 AI 超分；若为 `False`，请在 UI 中关闭“AI 画质增强”。

### 5. API Key 配置

```powershell
Copy-Item .\config.example.json .\config.json
```

然后编辑 `config.json`，至少填写：

```json
{
    "qwen_api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxx",
    "qwen_base_url": "https://your-api-endpoint/v1",
    "qwen_model": "your-model-name"
}
```

### 6. 补充说明

faster-whisper 默认优先使用 GPU（CUDA），无 GPU 会自动回退 CPU：
- NVIDIA 显卡 + 安装 [CUDA Toolkit](https://developer.nvidia.com/cuda-toolkit)
- 如无 GPU，脚本会自动回退到 CPU（速度较慢，建议将 `whisper_model` 调小为 `base` 或 `tiny`）

demucs 同样支持 GPU 加速，有 CUDA 时会自动使用。

AI 画质增强（Real-ESRGAN）仅支持 NVIDIA GPU（CUDA）；无 CUDA 时会直接提示不可用，不再走 CPU 慢速增强。

本工具使用 OpenAI SDK 兼容接口，可接入阿里云百炼、DeepSeek、硅基流动等服务。

> `config.json` 含真实密钥，已被 `.gitignore` 排除，不会被 git 跟踪。

### 7. 依赖文件说明

- `requirements.txt`：项目主依赖（不含 torch 三件套）
- `requirements.cuda124.txt`：CUDA 12.4 环境的 torch 依赖（推荐）
- `requirements.cpu.txt`：CPU 环境的 torch 依赖（无 GPU 时使用，不支持 AI 超分）
- `environment.yml`：conda 一键建环境配置

> 若你所在网络访问外网较慢，优先使用上文的清华镜像参数安装基础依赖。

## 使用方法

### Web UI（推荐）

```bash
python app.py
```

**独立桌面窗口**（套壳浏览器，依赖 `pywebview`，Windows 一般自带 WebView2 运行时）：

```bash
pip install pywebview
python app.py --window
# 或简写
python app.py -w
```

默认仍会在系统浏览器中打开 `http://127.0.0.1:7860`；加 `--window` 时用独立窗口加载同一地址，可用 `--host` / `--port` 改监听。

启动后在界面中：

- **设置** 标签页：表单与 **JSON 编辑器实时联动**；**保存并应用** 会写入 `config.json` 并 **自动重启本程序**，新进程重新加载配置，避免内存与磁盘不一致。
- **处理** 标签页：

1. 粘贴 YouTube 链接（每行一个）和/或上传本地视频文件
2. 可选择是否压制硬字幕、是否启用 AI 中文配音、是否启用 AI 画质增强、是否启用 AI 内容总结
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

> 命令行模式默认启用硬字幕压制；AI 配音与 AI 内容总结功能需通过 Web UI 开启。

### 输出结构

每个视频会在 `output/` 下自动创建以视频名命名的子目录：

```
output/
└── My_Video/
    ├── My_Video.mp4              # 原始视频
    ├── My_Video_en.srt           # 英文字幕
    ├── My_Video_summary.md       # AI 中文专业总结（可选）
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
| `video_language` | `null` | `null` / `en` / `zh` / `ja` / `ko` / `fr` / `de` / `es` / `ru` | 视频语言；`null` 表示自动检测，手动指定语言会更快更稳 |
| `subtitle_max_gap_ms` | `2000` | 500~5000 | 词级停顿阈值（毫秒）。大于该值时优先直接断句，是最重要的“按停顿切句”参数 |
| `subtitle_max_chars` | `120` | 40~220 | 基础字幕长度上限。新算法不会一到这个值就硬切，而是把它作为目标长度和后续硬上限的基准 |
> 日常通常只需要先调 `subtitle_max_gap_ms` 和 `subtitle_max_chars`。候选窗口大小已经下沉为算法内部默认值，其余可调项收进了 `subtitle_advanced`，默认一般不用改。

#### 高级断句参数：`subtitle_advanced`

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `subtitle_advanced.target_chars_ratio` | `0.82` | 0.6~1.0 | 候选断点的目标长度比例，实际目标长度 = `subtitle_max_chars * ratio` |
| `subtitle_advanced.min_chars_ratio` | `0.38` | 0.2~0.6 | 过短字幕惩罚阈值，低于该比例会明显降权，减少碎片句 |
| `subtitle_advanced.hard_max_chars_ratio` | `1.35` | 1.1~1.8 | 超长硬上限比例，超过后必须在窗口内选断点 |
| `subtitle_advanced.hard_max_chars_bias` | `18` | 0~40 | 小字幕上限补偿值，避免 `subtitle_max_chars` 较小时过早硬切 |
| `subtitle_advanced.soft_max_duration_sec` | `4.8` | 2.5~6.0 | 软时长阈值，到达后开始积极寻找断点 |
| `subtitle_advanced.hard_max_duration_sec` | `6.4` | 4.0~8.0 | 硬时长阈值，超过后必须落断点 |
| `subtitle_advanced.min_words` | `3` | 1~8 | 最小词数要求，避免把一个完整句过早切成一两个词的碎片 |
| `subtitle_advanced.merge_max_gap_sec` | `0.35` | 0.1~0.8 | 短尾句合并时允许的最大间隔 |
| `subtitle_advanced.merge_max_duration_sec` | `6.0` | 3.0~8.0 | 合并后整条字幕允许的最大时长 |
| `subtitle_advanced.merge_max_chars_ratio` | `1.35` | 1.0~1.8 | 合并后字幕最大长度比例 |
| `subtitle_advanced.merge_max_chars_bias` | `24` | 0~40 | 合并后字幕长度补偿值 |
| `subtitle_advanced.short_tail_max_words` | `3` | 1~6 | 认定为“短尾句”的最大词数 |
| `subtitle_advanced.short_tail_max_chars` | `18` | 6~30 | 认定为“短尾句”的最大字符数 |
| `subtitle_advanced.short_tail_max_duration_sec` | `1.4` | 0.5~2.5 | 认定为“短尾句”的最大时长 |
| `subtitle_advanced.split_max_duration_sec` | `6.8` | 4.0~9.0 | 后处理拆分超长字幕时使用的最大时长阈值 |

> 新版断句器仍然保留内部清理步骤，例如短尾句合并和超长句拆分，但这些属于算法内部流程，不再单独打印后处理日志。

### 下载

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `max_video_height` | `1080` | `720` / `1080` / `1440` / `2160` | YouTube 下载的最大分辨率 |
| `ytdlp_client` | `""` | `ios` / `tv_embedded` / `web` / `""` | 模拟的 YouTube 客户端类型。`ios` 和 `tv_embedded` 有时可绕过 bot 检测；留空则使用默认 web 客户端 |
| `ytdlp_cookies` | `""` | 文件路径或浏览器名 | cookies 配置，支持两种模式（见下方说明）：填文件路径如 `"./cookies.txt"` 使用导出的 cookies 文件；填浏览器名如 `"edge"` 直接从浏览器读取。留空则不使用 |

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

### AI 配音与 TTS 引擎

在 `config.json` 中通过 **`tts_provider`** 选择引擎：

| 取值 | 说明 |
|------|------|
| `edge` | 默认。无需额外密钥，使用微软 Edge 在线 TTS（[语音列表](https://github.com/rany2/edge-tts#voices)） |
| `qwen_tts` | 阿里云 DashScope 多模态 TTS，需配置 `qwen_tts_api_key` 等 |
| `cosyvoice` | 本地 [CosyVoice](https://github.com/FunAudioLLM/CosyVoice)，首次使用会在 `cosyvoice_local/` 自动创建独立环境并下载模型（详见该目录下说明） |

**字幕合并（影响每条 TTS 的文本长度）**：`tts_merge_gap_ms`、`tts_merge_max_chars` 对 edge / qwen_tts 生效；使用 CosyVoice 时额外可用 `cosyvoice_merge_max_chars`。合并越激进，请求次数越少，但单条越长越容易超时或显存压力变大。

**CosyVoice 模式 `cosyvoice_mode`**：`preset`（预设说话人 + `cosyvoice_voice`）、`zero_shot`（参考音频 + 参考文案）、`cross_lingual`（跨语种，依服务端实现而定）。`zero_shot` 需填写 `cosyvoice_prompt_audio_path` 与 `cosyvoice_prompt_text`。可用项目根目录脚本 **`python generate_qwen_reference.py`**（需已配置 Qwen TTS）生成与 Cherry 等音色一致的参考 WAV，并自动生成同内容的 `.txt` 供 prompt 使用。

**性能提示**：CosyVoice 服务端按设计**同一时间只处理一路合成**（避免 OOM）；`cosyvoice_fp16` 默认开启以降低显存占用。修改 `cosyvoice_device` 或与模型相关的配置后，需重启本地 CosyVoice 服务（关闭应用后重开，或自行结束对应进程）。

#### 通用与 edge-tts

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `tts_provider` | `"edge"` | `edge` / `qwen_tts` / `cosyvoice` | 配音引擎 |
| `tts_merge_gap_ms` | `280` | — | 相邻字幕若间隔小于此值（毫秒）可合并为一条 TTS |
| `tts_merge_max_chars` | `90` | — | 合并后单条字幕最大字符数（edge / qwen_tts 路径） |
| `tts_voice` | `"zh-CN-YunjianNeural"` | 参见 edge-tts 文档 | **edge** 下的发音人 |
| `tts_rate` | `"+0%"` | `-50%` ~ `+100%` | TTS 基础语速调整 |
| `tts_volume` | `"+0%"` | `-50%` ~ `+50%` | TTS 音量调整 |
| `tts_bg_volume` | `0.5` | 0.0~1.0 | 背景音混合音量（0=静音，1=原音量） |
| `tts_max_speed` | `1.5` | 1.0~2.0 | 合成语音长于画面对白时段时的最大加速倍率；`1.0` 表示不加速 |

#### Qwen TTS（`tts_provider`: `qwen_tts`）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `qwen_tts_api_key` | `""` | DashScope API Key（必填） |
| `qwen_tts_base_url` | 官方地址 | 一般无需修改 |
| `qwen_tts_model` | `qwen3-tts-flash` | 模型名 |
| `qwen_tts_voice` | `Cherry` | 音色名（以 DashScope 文档为准） |

#### CosyVoice 本地服务（`tts_provider`: `cosyvoice`）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `cosyvoice_api_url` | `http://127.0.0.1:9880` | HTTP 服务地址 |
| `cosyvoice_port` | `9880` | 与 URL 端口一致即可 |
| `cosyvoice_mode` | `preset` | `preset` / `zero_shot` / `cross_lingual` |
| `cosyvoice_voice` | `中文男` | **preset** 模式下的预设说话人名称 |
| `cosyvoice_prompt_audio_path` | `""` | **zero_shot** 等模式下参考音频路径 |
| `cosyvoice_prompt_text` | `""` | 与参考音频对应的文案 |
| `cosyvoice_device` | `cpu` | 推理设备：`cpu` / `cuda` / `auto`（bootstrap 会据环境选择 PyTorch CUDA/CPU 包） |
| `cosyvoice_repo_url` | 官方 Git | CosyVoice 仓库地址 |
| `cosyvoice_model_id` | `FunAudioLLM/CosyVoice-300M-SFT` | 预训练模型 ID |
| `cosyvoice_ttsfrd_id` | `FunAudioLLM/CosyVoice-ttsfrd` | ttsfrd 资源 ID |
| `cosyvoice_model_source` | `auto` | 模型下载源 |
| `cosyvoice_start_timeout` | `900` | 首次拉起服务等待就绪的超时（秒） |
| `cosyvoice_request_timeout` | `180` | 单次合成 HTTP 超时（秒） |
| `cosyvoice_merge_max_chars` | `72` | CosyVoice 路径下合并单条最大字符数 |
| `cosyvoice_fp16` | `true` | GPU 上是否使用半精度以省显存 |

### AI 画质增强

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `enhance_model` | `"RealESRGAN_x4plus"` | `RealESRGAN_x4plus` / `RealESRGAN_x4plus_anime_6B` / `RealESRGAN_x2plus` | 超分模型。通用视频用 `x4plus`；动漫/二次元用 `x4plus_anime_6B`（更轻量）；只需 2x 放大用 `x2plus` |
| `enhance_outscale` | `4` | `2` / `4` | 放大倍数。输出分辨率超过 4K（3840×2160）时会自动限制 |

> 模型权重文件（约 64MB）在首次运行时自动从 GitHub Releases 下载，保存在 `realesrgan` 包目录的 `weights/` 下。

## 常见问题

### YouTube 提示「Sign in to confirm you're not a bot」

YouTube 对部分 IP 或视频启用 bot 检测，yt-dlp 会报错 `Sign in to confirm you're not a bot`，需要配置 cookies 供 yt-dlp 使用。

**配置 cookies 的两种模式：**

#### 模式一：从浏览器自动读取（需关闭浏览器）

在 `config.json` 中填写浏览器名称：

```json
"ytdlp_cookies": "edge"
```

支持的浏览器名：`edge`、`chrome`、`firefox`、`opera`、`brave`、`vivaldi` 等。

> **注意**：浏览器运行时 SQLite 数据库被锁，必须**关闭浏览器**后再运行才能读取成功。

#### 模式二：导出 cookies 文件（浏览器不需要关闭）

1. 在 Chrome / Edge 中安装扩展 [**Get cookies.txt LOCALLY**](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. 打开 [youtube.com](https://www.youtube.com) 并**确保已登录账号**
3. 点击扩展图标 → 选择「Export As」→「cookies.txt」
4. 将导出的文件保存到项目目录，例如 `cookies.txt`
5. 在 `config.json` 中填写路径：
   ```json
   "ytdlp_cookies": "./cookies.txt"
   ```

#### 注意事项

- cookies 文件包含账号登录信息，**请勿分享或提交到 Git**（`config.json` 已在 `.gitignore` 中，cookies 路径只存在于本机 `config.json` 里）
- 导出的 cookies 文件有效期较短（通常几小时到几天），若下载再次报认证错误，重新导出一次即可。推荐使用模式一（从浏览器自动读取）以免反复导出
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
- 使用 **edge** 时可将 `tts_rate` 调为负值（如 `"-10%"`）减慢基础语速

### CosyVoice 首次很慢或占用空间大

- 第一次选择 `cosyvoice` 时会克隆仓库、安装独立 venv、下载 SFT 模型与 ttsfrd 资源，耗时与磁盘占用都较大，属正常现象
- 日志在 `cosyvoice_local/logs/server.log`；若长期无响应可适当增大 `cosyvoice_start_timeout`
- NVIDIA 新卡（如需 CUDA 12.8 的驱动环境）由 `cosyvoice_local/bootstrap.py` 安装匹配的 PyTorch cu128 轮子；仅 CPU 则安装 CPU 版 PyTorch，速度较慢

### CosyVoice 显存不足或合成卡住

- 保持 `cosyvoice_fp16: true`，并避免在合成进行时并行多个任务
- 适当减小 `cosyvoice_merge_max_chars` 或 `tts_merge_max_chars`，缩短单次送入模型的文本
- 可在系统环境变量中设置 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` 缓解碎片化（依 PyTorch 版本而定）

### 画质增强速度慢

- 画质增强仅支持 NVIDIA GPU；请先确认 `python -c "import torch; print(torch.cuda.is_available())"` 输出为 `True`
- 如显存不足报 OOM，可在 `auto_subtitle.py` 中将 `tile_size = 1024` 改小（如 `512`）

### 未检测到 CUDA，AI 超分不可用

- 这是预期行为：当前版本将 AI 超分限定为 NVIDIA GPU 才可用。
- 没有 GPU 时，请在 Web UI 取消勾选“AI 画质增强”，其他功能不受影响。

### 画质增强报 lzma DLL 错误（Windows）

`basicsr` 依赖 `lzma`，conda 自建环境有时缺少 `liblzma.dll`：
```powershell
# 将 base 环境的 DLL 复制到当前环境
Copy-Item "$env:CONDA_PREFIX\..\..\Library\bin\liblzma.dll" "$env:CONDA_PREFIX\Library\bin\"
```

## 项目结构

```
SubForge/
├── auto_subtitle.py          # 核心处理脚本（多步流水线入口）
├── app.py                    # Gradio Web UI
├── settings_ui.py            # Web「设置」页（编辑并保存 config.json）
├── config.py                 # 读取 config.json 的运行时常量
├── config.example.json       # 配置模板（复制为 config.json）
├── config.json               # 本地配置（已被 .gitignore 忽略）
├── utils.py                  # 通用工具
├── cosyvoice_manager.py      # CosyVoice 本地服务拉起与健康检查
├── generate_qwen_reference.py # 用 Qwen TTS 生成本地参考音色 WAV/TXT（供 CosyVoice zero_shot）
├── _run_demucs.py            # demucs 子进程包装（绕过 torchcodec）
├── _run_whisper.py           # Whisper 子进程包装
├── steps/                    # 各步骤实现（下载、转写、翻译、烧录、配音、增强等）
├── cosyvoice_local/          # CosyVoice 独立环境、vendor、模型（大部份在 .gitignore）
├── requirements.txt          # 主依赖（不含 torch 三件套）
├── requirements.cpu.txt      # CPU 版 torch
├── requirements.cuda124.txt  # CUDA 12.4 版 torch（主项目推荐）
├── environment.yml           # conda 一键建环境
├── input/                    # 本地视频输入（默认忽略）
└── output/                   # 处理结果输出（默认忽略）
```

## License

MIT
