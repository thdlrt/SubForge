"""
步骤 3：翻译字幕（Qwen API）
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import srt

from config import (
    QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL, SYSTEM_PROMPT,
    TRANSLATE_BATCH_SIZE, TRANSLATE_CONCURRENCY, API_RETRY, API_SLEEP,
)


def translate_batch_qwen(texts):
    """用 Qwen API 批量翻译"""
    from openai import OpenAI

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    user_content = "\n".join(texts)

    for attempt in range(API_RETRY):
        try:
            response = client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.3,
                max_tokens=4096,
            )

            result = response.choices[0].message.content.strip()
            translated_lines = [line.strip() for line in result.split("\n") if line.strip()]

            if len(translated_lines) == len(texts):
                return translated_lines

            if len(translated_lines) > len(texts):
                return translated_lines[:len(texts)]

            print(f"    ⚠ 行数不匹配 ({len(translated_lines)} vs {len(texts)})，第 {attempt+1} 次重试...")
            continue

        except Exception as e:
            print(f"    ⚠ API 调用出错: {e}，第 {attempt+1} 次重试...")
            time.sleep(2)

    print("    ⚠ 批量翻译失败，回退逐条翻译...")
    return translate_one_by_one(texts)


def translate_one_by_one(texts):
    """逐条翻译（兜底方案）"""
    from openai import OpenAI

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    results = []

    for text in texts:
        try:
            response = client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {"role": "system", "content": "将以下英文翻译成简体中文，只输出翻译结果："},
                    {"role": "user", "content": text}
                ],
                temperature=0.3,
                max_tokens=256,
                extra_body={"enable_thinking": False},
            )
            translated = response.choices[0].message.content.strip()
            results.append(translated if translated else text)
        except Exception:
            results.append(text)
        time.sleep(0.5)

    return results


def step3_translate(subs, video_path):
    """用 Qwen API 并发翻译字幕"""
    print("\n" + "=" * 60)
    print(f"🌐 第三步：使用 Qwen3.5 API 翻译字幕（并发 {TRANSLATE_CONCURRENCY} 批）...")
    print("=" * 60)

    zh_srt_path  = video_path.rsplit(".", 1)[0] + "_zh.srt"
    bi_srt_path  = video_path.rsplit(".", 1)[0] + "_bilingual.srt"
    if os.path.exists(zh_srt_path) and os.path.exists(bi_srt_path):
        print(f"⏭️  中文/双语字幕已存在，跳过翻译:")
        print(f"   ↳ {zh_srt_path}")
        print(f"   ↳ {bi_srt_path}")
        return zh_srt_path, bi_srt_path

    total = len(subs)
    batches = [
        (batch_start, subs[batch_start: batch_start + TRANSLATE_BATCH_SIZE])
        for batch_start in range(0, total, TRANSLATE_BATCH_SIZE)
    ]
    batch_count = len(batches)
    print(f"共 {total} 条字幕，分 {batch_count} 批，每批 {TRANSLATE_BATCH_SIZE} 条，并发 {TRANSLATE_CONCURRENCY} 批")

    results = {}
    completed = 0

    def _translate_batch(batch_start, batch):
        time.sleep(batch_start % TRANSLATE_CONCURRENCY * API_SLEEP / TRANSLATE_CONCURRENCY)
        texts = [sub.content for sub in batch]
        return batch_start, translate_batch_qwen(texts)

    executor = ThreadPoolExecutor(max_workers=TRANSLATE_CONCURRENCY)
    try:
        futures = {
            executor.submit(_translate_batch, bs, batch): bs
            for bs, batch in batches
        }
        for future in as_completed(futures):
            batch_start, translated_texts = future.result()
            results[batch_start] = translated_texts
            completed += 1
            done_subs = min(batch_start + TRANSLATE_BATCH_SIZE, total)
            print(f"  ✅ 批次 {batch_start // TRANSLATE_BATCH_SIZE + 1}/{batch_count} 完成 "
                  f"(字幕 {batch_start + 1}–{done_subs})  [{completed}/{batch_count} 批已完成]")
    except KeyboardInterrupt:
        print("\n⚠️  翻译被中断，取消剩余批次...")
        for f in futures:
            f.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)

    # 按原始顺序拼装翻译结果
    translated_subs = []
    for batch_start, batch in batches:
        translated_texts = results[batch_start]
        for j, sub in enumerate(batch):
            translated_subs.append(srt.Subtitle(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                content=translated_texts[j]
            ))

    with open(zh_srt_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(translated_subs))

    bilingual_subs = []
    for orig, trans in zip(subs, translated_subs):
        bilingual_subs.append(srt.Subtitle(
            index=orig.index,
            start=orig.start,
            end=orig.end,
            content=f"{trans.content}\n{orig.content}"
        ))

    with open(bi_srt_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(bilingual_subs))

    print(f"✅ 中文字幕已生成: {zh_srt_path}")
    print(f"✅ 双语字幕已生成: {bi_srt_path}")
    return zh_srt_path, bi_srt_path
