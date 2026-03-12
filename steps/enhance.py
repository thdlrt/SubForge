"""
步骤 1.5：AI 画质增强（Real-ESRGAN）
"""
import os
import sys
import subprocess

from config import ENHANCE_MODEL, ENHANCE_OUTSCALE


def step1b_enhance_video(video_path):
    """使用 Real-ESRGAN 对视频进行 AI 超分辨率画质增强"""
    print("\n" + "=" * 60)
    print("✨ 步骤 1.5：AI 画质增强（Real-ESRGAN 超分辨率）...")
    print("=" * 60)

    base = video_path.rsplit(".", 1)[0]
    enhanced_path = base + "_enhanced.mp4"

    if os.path.exists(enhanced_path):
        print(f"⏭️  增强视频已存在，跳过: {enhanced_path}")
        return enhanced_path

    try:
        import cv2
        import torch
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer
    except (ImportError, OSError) as e:
        err = str(e)
        if "lzma" in err.lower() or "liblzma" in err.lower():
            raise RuntimeError(
                "画质增强初始化失败：缺少 liblzma.dll\n"
                "修复方法：将 miniconda3/Library/bin/liblzma.dll 复制到\n"
                "  envs/aiText/Library/bin/ 目录下\n"
                f"错误详情: {e}"
            )
        raise RuntimeError(
            "画质增强需要额外依赖，请运行：\n"
            "  pip install realesrgan basicsr opencv-python\n"
            f"错误详情: {e}"
        )

    model_name = ENHANCE_MODEL
    outscale   = ENHANCE_OUTSCALE

    MODEL_CONFIGS = {
        "RealESRGAN_x4plus": {
            "num_block": 23, "net_scale": 4,
            "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        },
        "RealESRGAN_x4plus_anime_6B": {
            "num_block": 6, "net_scale": 4,
            "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        },
        "RealESRGAN_x2plus": {
            "num_block": 23, "net_scale": 2,
            "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
        },
    }
    if model_name not in MODEL_CONFIGS:
        raise ValueError(f"不支持的增强模型：{model_name}。可选：{list(MODEL_CONFIGS.keys())}")

    cfg    = MODEL_CONFIGS[model_name]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    half   = device.type == "cuda"

    tile_size = 1024 if device.type == "cuda" else 512

    model = RRDBNet(
        num_in_ch=3, num_out_ch=3, num_feat=64,
        num_block=cfg["num_block"], num_grow_ch=32, scale=cfg["net_scale"],
    )
    upsampler = RealESRGANer(
        scale=cfg["net_scale"],
        model_path=cfg["url"],
        model=model,
        tile=tile_size,
        tile_pad=10,
        pre_pad=0,
        half=half,
        device=device,
    )

    cap   = cv2.VideoCapture(video_path)
    fps   = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    max_w, max_h = 3840, 2160
    effective_outscale = min(float(outscale), max_w / w, max_h / h)
    if effective_outscale < outscale:
        print(f"⚠️  输出超过 4K，放大倍数自动调整: {outscale}x → {effective_outscale:.2f}x")
    outscale = effective_outscale

    out_w = int(w * outscale)
    out_h = int(h * outscale)
    dur_min = total / fps / 60 if fps > 0 else 0

    print(f"模型: {model_name}  放大: {outscale:.2f}x  设备: {device}  tile: {tile_size}")
    print(f"分辨率: {w}x{h} → {out_w}x{out_h}  帧率: {fps:.2f}  总帧数: {total}")
    if dur_min > 5:
        print(f"⚠️  视频较长（{dur_min:.0f} 分钟），AI 增强耗时可能数倍于视频时长，请耐心等待。")

    tmp_video = base + "_enhanced_noaudio.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(tmp_video, fourcc, fps, (out_w, out_h))

    import io
    from tqdm import tqdm

    _devnull = io.StringIO()

    with tqdm(total=total, desc="  AI增强进度", unit="帧",
              bar_format="{desc}: {percentage:3.0f}%|{bar}| {n}/{total} 帧 [{elapsed}<{remaining}]",
              dynamic_ncols=True) as pbar:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            _orig, sys.stdout = sys.stdout, _devnull
            try:
                output, _ = upsampler.enhance(img_rgb, outscale=outscale)
            finally:
                sys.stdout = _orig
            writer.write(cv2.cvtColor(output, cv2.COLOR_RGB2BGR))
            pbar.update(1)

    cap.release()
    writer.release()

    print("合并原始音轨...")
    cmd_merge = [
        "ffmpeg",
        "-i", tmp_video,
        "-i", video_path,
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-c:a", "copy",
        "-map", "0:v:0", "-map", "1:a?",
        "-shortest", "-y", enhanced_path,
    ]
    subprocess.run(cmd_merge, check=True, capture_output=True)
    os.remove(tmp_video)

    print(f"✅ 增强视频已生成: {enhanced_path}")
    return enhanced_path
