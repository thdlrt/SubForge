"""
步骤 2.5：基于 SRT 转写内容的多模式 AI 分析（中文 Markdown）
"""
import os
import re
from datetime import datetime

import srt
from openai import OpenAI

import config


AI_ANALYSIS_MODES = {
    "通用": {
        "key": "general",
        "title": "AI 转写内容分析",
        "system": """你是一名资深内容策划与技术编辑。请基于转写字幕内容，产出专业、结构化、可执行的中文 Markdown 分析。

要求：
1. 输出必须为 Markdown。
2. 严格使用以下一级标题（按顺序）：
# AI 转写内容分析
# 一句话结论
# 核心主题
# 结构化梳理
# 专业洞察
# 实践启发
# 关键术语与原文
3. 语言简洁、信息密度高，避免空话。
4. 不要编造字幕中不存在的具体数据、身份或事实。
5. 如果字幕信息不足，需明确写出“信息不足以判断”。""",
        "user_focus": "请重点提炼：内容主线、关键观点、方法论、可直接落地的实践建议。",
    },
    "课程": {
        "key": "course",
        "title": "课程学习笔记",
        "system": """你是一名擅长技术课程整理的学习教练。请基于转写字幕内容，产出适合复习和落地实践的中文 Markdown 课程笔记。

要求：
1. 输出必须为 Markdown。
2. 严格使用以下一级标题（按顺序）：
# 课程学习笔记
# 课程主线
# 知识点总览
# 分段重点记录
# 操作步骤与方法
# 易错点与注意事项
# 复习清单
# 关键术语与原文
3. 尽量覆盖课程中的重要概念、步骤、例子、提醒和结论，不要遗漏重点。
4. 保留必要的英文术语和专有名词，中文解释要清楚。
5. 不要编造字幕中不存在的内容；信息不足时明确说明。""",
        "user_focus": "请按课程学习场景整理，重点保留知识点、步骤、例子、注意事项和复习要点。",
    },
    "会议记录": {
        "key": "meeting",
        "title": "会议纪要",
        "system": """你是一名专业会议纪要秘书。请基于转写字幕内容，产出清晰、可追踪、适合会后执行的中文 Markdown 会议纪要。

要求：
1. 输出必须为 Markdown。
2. 严格使用以下一级标题（按顺序）：
# 会议纪要
# 会议概览
# 参会角色与发言线索
# 议题与讨论过程
# 已确认结论
# 待办事项
# 分歧与风险
# 后续跟进问题
3. 如果字幕中包含 [说话人1] 这类标签，请优先按说话人归纳；没有标签时使用“发言者 A/B”等弱化表述，不要编造真实身份。
4. 待办事项尽量写明负责人线索、动作和截止时间；缺失则标注“未提及”。
5. 不要编造会议中不存在的决策、数字或承诺。""",
        "user_focus": "请按会议记录场景整理，重点提炼议题、讨论过程、结论、待办、风险和后续问题。",
    },
    "面试记录": {
        "key": "interview",
        "title": "面试记录复盘",
        "system": """你是一名专业面试复盘助手。请基于转写字幕内容，从被面试者视角产出完整、可复盘、适合个人复习改进的中文 Markdown 面试复盘记录。

要求：
1. 输出必须为 Markdown。
2. 严格使用以下一级标题（按顺序）：
# 面试记录复盘
# 面试概览
    # 面试流程梳理
    # 问题清单与作答要点
    # 追问与关键转折
    # 自我回答复盘
    # 暴露的薄弱点
    # 下次优化清单
    3. 核心目标是帮助被面试者复盘整场面试中出现过的问题、追问顺序、自己的回答要点和可以改进的地方。
    4. 如果字幕只包含回答或问题不完整，需要根据回答内容反推最可能的问题，并明确标注为“反推问题”。
    5. 问题整理要尽量保持完整流程：主问题、追问、回答要点、卡顿点、可优化表达。
    6. 不要编造面试结果、面试官评价或字幕中不存在的经历细节；信息不足时明确说明。""",
        "user_focus": "请按被面试者复盘场景整理，重点还原整场问题流程、追问链路、我的回答要点，以及后续如何优化。",
    },
}


def _normalize_mode(mode: str | None) -> str:
    mode = (mode or config.AI_ANALYSIS_MODE or "通用").strip()
    return mode if mode in AI_ANALYSIS_MODES else "通用"


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

    keep_count = max(100, max_chars // 80)
    step = max(1, len(lines) // keep_count)
    sampled = lines[::step]
    if sampled[-1] != lines[-1]:
        sampled.append(lines[-1])

    compact = "\n".join(sampled)
    return compact[:max_chars]


def _summary_path_for_mode(video_path: str, mode: str) -> str:
    mode_key = AI_ANALYSIS_MODES[_normalize_mode(mode)]["key"]
    return video_path.rsplit(".", 1)[0] + f"_summary_{mode_key}.md"


def step2_5_summarize_from_srt(en_srt_path, video_path, mode=None):
    mode = _normalize_mode(mode)
    mode_spec = AI_ANALYSIS_MODES[mode]
    title = mode_spec["title"]

    print("\n" + "=" * 60)
    print(f"🧠 第二点五步：AI 分析并生成 Markdown（{mode}）...")
    print("=" * 60)

    if not config.QWEN_SUMMARY_API_KEY:
        raise RuntimeError("未配置 qwen_summary_api_key，无法执行 AI 分析")

    summary_md_path = _summary_path_for_mode(video_path, mode)
    if os.path.exists(summary_md_path):
        print(f"⏭️  AI 分析结果已存在，跳过生成: {summary_md_path}")
        return summary_md_path

    with open(en_srt_path, "r", encoding="utf-8") as f:
        subs = list(srt.parse(f.read()))
    if not subs:
        raise RuntimeError(f"字幕为空，无法分析: {en_srt_path}")

    transcript = _build_prompt_transcript(subs)
    if not transcript:
        raise RuntimeError(f"字幕内容为空，无法分析: {en_srt_path}")

    client = OpenAI(api_key=config.QWEN_SUMMARY_API_KEY, base_url=config.QWEN_SUMMARY_BASE_URL)

    user_prompt = (
        f"请根据下列转写字幕生成中文 Markdown。\n"
        f"分析模式：{mode}\n"
        f"{mode_spec['user_focus']}\n\n"
        "【转写字幕片段】\n"
        f"{transcript}"
    )

    last_err = None
    summary_md = ""
    for attempt in range(config.API_RETRY):
        try:
            resp = client.chat.completions.create(
                model=config.QWEN_SUMMARY_MODEL,
                messages=[
                    {"role": "system", "content": mode_spec["system"]},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=2600,
                extra_body={"enable_thinking": False},
            )
            summary_md = (resp.choices[0].message.content or "").strip()
            if summary_md:
                break
            last_err = RuntimeError("AI 返回空内容")
        except Exception as e:
            last_err = e
            print(f"    ⚠ AI 分析失败，第 {attempt + 1} 次重试: {e}")

    if not summary_md:
        raise RuntimeError(f"AI 分析生成失败: {last_err}")

    header = (
        f"# {title}\n\n"
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- 分析模式: {mode}\n"
        f"- 来源字幕: {os.path.basename(en_srt_path)}\n"
        f"- 模型: {config.QWEN_SUMMARY_MODEL}\n\n"
    )

    with open(summary_md_path, "w", encoding="utf-8") as f:
        f.write(header)
        heading = f"# {title}"
        if summary_md.startswith(heading):
            f.write(summary_md[len(heading):].lstrip())
        else:
            f.write(summary_md)

    print(f"✅ AI 分析 Markdown 已生成: {summary_md_path}")
    return summary_md_path
