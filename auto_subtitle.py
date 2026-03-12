"""
YouTube 视频下载 + AI字幕生成 + Qwen3.5 API翻译 + 字幕压制 一键脚本
使用方法: python auto_subtitle.py "https://www.youtube.com/watch?v=XXXXX"
"""

import sys
import os

# 强制 stdout/stderr 使用 UTF-8，避免 Windows GBK 终端无法输出 Emoji
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# ======================== 从模块导入 ========================

# 配置常量（app.py 通过 auto_subtitle.XXXX 访问，需全部重导出）
from config import *  # noqa: F401,F403

# 各步骤函数
from steps.download   import step1_download_video, prepare_source as _prepare_source
from steps.enhance    import step1b_enhance_video
from steps.transcribe import step2_transcribe
from steps.translate  import step3_translate
from steps.burn       import step4_burn_subtitles
from steps.dubbing    import step5_separate_audio, step6_tts_generate, step7_merge_audio


# ======================== 流程编排 ========================


def _process_prepared(prepared, burn_subtitle=True, enable_dubbing=False, enable_enhance=False):
    """第二阶段：处理已下载的视频（识别 → 翻译 → 压制字幕 → 配音）。
    接受 _prepare_source() 返回的字典；若准备阶段已失败则直接透传错误结果。"""
    source = prepared["source"]

    if prepared.get("status") == "失败":
        return {
            "source": source,
            "video": None,
            "en_srt": None, "zh_srt": None, "bi_srt": None,
            "final_video": None, "dubbed_video": None,
            "status": "失败",
            "last_step": prepared.get("last_step", "1-下载"),
            "error": prepared.get("error", "下载失败"),
        }

    video_path = prepared["video_path"]
    output_dir = prepared["output_dir"]

    print(f"\n   工作目录: {os.path.abspath(output_dir)}")
    print(f"   语音识别: faster-whisper [{WHISPER_MODEL}] ← 本地 GPU")
    print(f"   翻译引擎: Qwen3.5 API [{QWEN_MODEL}] ← 云端大模型")

    current_step = "初始化"
    en_srt_path = zh_srt_path = bi_srt_path = None
    final_video = dubbed_video = None

    try:
        if enable_enhance:
            current_step = "1.5-AI画质增强"
            video_path = step1b_enhance_video(video_path)

        current_step = "2-语音识别"
        en_srt_path, subs = step2_transcribe(video_path)

        current_step = "3-翻译字幕"
        zh_srt_path, bi_srt_path = step3_translate(subs, video_path)

        if burn_subtitle:
            current_step = "4-压制字幕"
            final_video = step4_burn_subtitles(video_path, bi_srt_path)

        if enable_dubbing:
            current_step = "5-分离音频"
            bg_path = step5_separate_audio(video_path)
            current_step = "6-TTS语音合成"
            tts_path = step6_tts_generate(zh_srt_path, video_path)
            current_step = "7-合并配音"
            dub_base = final_video if final_video and os.path.exists(final_video) else video_path
            dubbed_video = step7_merge_audio(dub_base, bg_path, tts_path)

        current_step = "完成"
    except Exception as e:
        print(f"\n❌ 在步骤 [{current_step}] 失败: {e}")
        return {
            "source": source,
            "video": video_path,
            "en_srt": en_srt_path,
            "zh_srt": zh_srt_path,
            "bi_srt": bi_srt_path,
            "final_video": final_video,
            "dubbed_video": dubbed_video,
            "status": "失败",
            "last_step": current_step,
            "error": str(e),
        }

    print("\n" + "=" * 60)
    print("🎉 处理完成！")
    print("=" * 60)
    print(f"  原始视频:   {video_path}")
    if en_srt_path:
        print(f"  外语字幕:   {en_srt_path}")
    if zh_srt_path:
        print(f"  中文字幕:   {zh_srt_path}")
    if bi_srt_path:
        print(f"  双语字幕:   {bi_srt_path}")
    if final_video:
        print(f"  最终视频:   {final_video}")
    if dubbed_video:
        print(f"  配音视频:   {dubbed_video}")

    return {
        "source": source,
        "video": video_path,
        "en_srt": en_srt_path,
        "zh_srt": zh_srt_path,
        "bi_srt": bi_srt_path,
        "final_video": final_video,
        "dubbed_video": dubbed_video,
        "status": "成功",
        "last_step": "完成",
    }


def process_one(source, burn_subtitle=True, enable_dubbing=False, enable_enhance=False):
    """处理单个视频源（本地文件或 YouTube 链接）。
    组合 _prepare_source + _process_prepared，保持向后兼容。"""
    prepared = _prepare_source(source)
    return _process_prepared(prepared, burn_subtitle=burn_subtitle,
                             enable_dubbing=enable_dubbing, enable_enhance=enable_enhance)


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print('  python auto_subtitle.py <源1> [源2] [源3] ...')
        print()
        print('每个"源"可以是 YouTube 链接或本地视频路径，多个源按顺序依次处理。')
        print()
        print("示例:")
        print('  # 单个 YouTube 视频')
        print('  python auto_subtitle.py "https://www.youtube.com/watch?v=XXXXX"')
        print()
        print('  # 单个本地文件')
        print('  python auto_subtitle.py ./input/my_video.mp4')
        print()
        print('  # 批量混合（YouTube + 本地文件）')
        print('  python auto_subtitle.py "https://youtu.be/AAA" ./input/a.mp4 "https://youtu.be/BBB"')
        sys.exit(1)

    sources = sys.argv[1:]
    total = len(sources)

    try:
        results = []
        if total == 1:
            results.append(process_one(sources[0]))
        else:
            print(f"📋 批量模式：共 {total} 个任务，使用两阶段策略")

            print("\n" + "=" * 60)
            print(f"🌐 第一阶段：批量下载全部视频（共 {total} 个）")
            print("=" * 60)
            prepared_list = []
            for i, src in enumerate(sources, 1):
                print(f"\n── 下载 [{i}/{total}]: {src}")
                prepared_list.append(_prepare_source(src))

            dl_ok  = sum(1 for p in prepared_list if p.get("status") != "失败")
            dl_fail = total - dl_ok
            print(f"\n✅ 下载阶段完成：{dl_ok} 成功 / {dl_fail} 失败 / {total} 总计")

            print("\n" + "=" * 60)
            print("⚙️  第二阶段：批量处理（识别 → 翻译 → 压制字幕）")
            print("=" * 60)
            for i, prepared in enumerate(prepared_list, 1):
                print("\n" + "#" * 60)
                print(f"## 任务 [{i}/{total}]: {prepared['source']}")
                print("#" * 60)
                results.append(_process_prepared(prepared))

        _print_summary(results)
    except KeyboardInterrupt:
        print("\n\n⚠️  已中断（Ctrl+C），退出")
        os._exit(130)


def _print_summary(results):
    """打印所有任务的执行结果汇总表"""
    if not results:
        return
    print("\n" + "=" * 60)
    print("📋 执行结果汇总")
    print("=" * 60)
    success = sum(1 for r in results if r and r.get("status") == "成功")
    fail    = len(results) - success
    for i, r in enumerate(results, 1):
        if not r:
            print(f"  [{i}] ❌ 未知错误（无返回结果）")
            continue
        source = r.get("source", r.get("video", "?"))
        name = os.path.basename(source) if os.path.isfile(str(source)) else source
        if len(name) > 50:
            name = name[:47] + "..."
        status = r.get("status", "未知")
        step   = r.get("last_step", "?")
        if status == "成功":
            print(f"  [{i}] ✅ {name}  →  全部完成")
        else:
            err = r.get("error", "")
            print(f"  [{i}] ❌ {name}  →  失败于 [{step}]: {err}")
    print(f"\n  合计: {success} 成功 / {fail} 失败 / {len(results)} 总计")
    print("=" * 60)


if __name__ == "__main__":
    main()
