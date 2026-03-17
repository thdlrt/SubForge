"""
步骤 2.5：基于英文 SRT 的 AI 内容概括总结（中文 Markdown）
"""
import os
import re
from datetime import datetime

import srt
from openai import OpenAI

from config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL, API_RETRY

_SUMMARY_SYSTEM_PROMPT = """你是一名资深内容策划与技术编辑。请基于字幕内容，产出专业、结构化、可执行的中文总结。

要求：
1. 输出必须为 Markdown。
2. 严格使用以下一级标题，且按顺序输出：
# 视频内容专业总结
# 一句话结论
# 核心主题
# 结构化梳理
# 专业洞察
# 实践启发
# 关键术语与英文原词
3. 语言简洁，信息密度高，避免空话。
4. 不要编造字幕中不存在的具体数据或事实。
5. 如果字幕信息不足，需明确写出“信息不足以判断”。
"""


def _normalize_text(text):
    text = text.replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _format_ts(td):
    total_seconds = int(td.total_seconds())
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _build_prompt_transcript(subs, max_chars=18000):
    lines = []
    for sub in subs:
        text = _normalize_text(sub.content)
        if not text:
            continue
        lines.append(f"[{_format_ts(sub.start)}] {text}")

    if not lines:
        return ""

    transcript = "\n".join(lines)
    if len(transcript) <= max_chars:
        return transcript

    # 字幕过长时按时间均匀抽样，尽量保留全片结构信息。
    keep_count = max(100, max_chars // 80)
    step = max(1, len(lines) // keep_count)
    sampled = lines[::step]
    if sampled[-1] != lines[-1]:
        sampled.append(lines[-1])

    compact = "\n".join(sampled)
    return compact[:max_chars]


def _has_usable_summary(summary_md_path):
    if not os.path.exists(summary_md_path):
        return False
    try:
        with open(summary_md_path, "r", encoding="utf-8") as f:
            return bool(f.read().strip())
    except Exception:
        return False


def step2_5_summarize_from_srt(en_srt_path, video_path):
    print("\n" + "=" * 60)
    print("第二点五步：AI 内容概括总结（中文 Markdown）...")
    print("=" * 60)

    if not QWEN_API_KEY:
        raise RuntimeError("未配置 qwen_api_key，无法执行 AI 内容概括总结")

    summary_md_path = video_path.rsplit(".", 1)[0] + "_summary.md"
    if _has_usable_summary(summary_md_path):
        print(f"⏭️  AI 总结已存在，跳过生成: {summary_md_path}")
        return summary_md_path
    if os.path.exists(summary_md_path):
        print(f"⚠️  AI 总结文件为空或不可读，将重新生成: {summary_md_path}")

    with open(en_srt_path, "r", encoding="utf-8") as f:
        subs = list(srt.parse(f.read()))
    if not subs:
        raise RuntimeError(f"字幕为空，无法总结: {en_srt_path}")

    transcript = _build_prompt_transcript(subs)
    if not transcript:
        raise RuntimeError(f"字幕内容为空，无法总结: {en_srt_path}")

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    user_prompt = (
        "请根据下列英文字幕生成中文专业总结。\n"
        "请重点提炼：内容主线、关键观点、方法论、可直接落地的实践建议。\n\n"
        "【英文字幕片段】\n"
        f"{transcript}"
    )

    last_err = None
    summary_md = ""
    for attempt in range(API_RETRY):
        try:
            resp = client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=2200,
                extra_body={"enable_thinking": False},
            )
            summary_md = (resp.choices[0].message.content or "").strip()
            if summary_md:
                break
            last_err = RuntimeError("AI 返回空内容")
        except Exception as e:
            last_err = e
            print(f"    ⚠️  总结生成失败，第 {attempt + 1} 次重试: {e}")

    if not summary_md:
        raise RuntimeError(f"AI 总结生成失败: {last_err}")

    header = (
        "# 视频内容专业总结\n\n"
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- 来源字幕: {os.path.basename(en_srt_path)}\n"
        f"- 模型: {QWEN_MODEL}\n\n"
    )

    with open(summary_md_path, "w", encoding="utf-8") as f:
        f.write(header)
        if summary_md.startswith("# 视频内容专业总结"):
            f.write(summary_md[len("# 视频内容专业总结"):].lstrip())
        else:
            f.write(summary_md)

    print(f"✅ AI 内容总结已生成: {summary_md_path}")
    return summary_md_path
