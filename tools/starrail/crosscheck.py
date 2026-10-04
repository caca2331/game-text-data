"""与独立第二来源的交叉校验（一次性用途，不进主流水线）。

**先说清楚这个校验能做到什么、做不到什么。**

原神那边能拿旧爬虫数据按 `dialogId` 逐条对齐，因为两边用同一套游戏内编号。崩铁
没有这种条件：`Dimbreath/StarRailData`（GitHub）返回 `Repository access blocked`；
`mrzjy/StarrailDialog` 只有 6–10 KB 的样本文件且停在 2024 年的 2.x；其余社区语料
要么是加工过的 wiki 文本，要么早已过期。

唯一活着且体量足够的独立来源是 HuggingFace 的 `simon3000/starrail-voice`：40 万条
语音记录，**从语音文件那条完全不同的路径提取**，与我们走 TextMap 的路子互相独立。
两个限制，都是实测出来的：

1. **它按 `.wem` 文件名索引，没有 TalkSentenceID**，只能按文本内容比对，不能按 id
   逐条对齐。
2. **`transcription` 字段只有中文。** 数据集的 `language` 字段说的是**音频**语言；
   标记为 Japanese / English / Korean 的行，转录文本一样是中文。所以**只能校验中文**，
   四语种对齐用它验不了。（第一版脚本按 language 分语种比对，日韩命中率 0.7% / 2.0%，
   查下去才发现是这个原因，不是我们的日韩文本有问题。）

因此本校验只回答一个问题：**我们从 TextMap 解出来的中文对不对** —— 凡是能在语音转录
里找到的句子应当逐字一致，对不上就说明解引用接错了。

它回答不了"有没有漏"：语音只覆盖有配音的台词，我们的语料还包含大量无配音文本。

数据集整包 241 GB（含音频），这里用 HF 的 rows API 只取行、不取音频。

用法：
    uv run python tools/starrail/crosscheck.py [--samples 3000]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

from gametext import paths
from gametext.core import jsonl as _jsonl          # 产物可能是 .zst，统一走它

DATA = paths.corpus("starrail")

DATASET = "simon3000/starrail-voice"
ROWS_API = "https://datasets-server.huggingface.co/rows"
PAGE = 100  # rows API 的单次上限

# language 字段指的是音频语言，仅用于分组统计
AUDIO_LANGS = ("Chinese(PRC)", "English", "Japanese", "Korean")


def fetch_rows(offset: int, length: int) -> list:
    url = "%s?dataset=%s&config=default&split=train&offset=%d&length=%d" % (
        ROWS_API, urllib.parse.quote(DATASET, safe=""), offset, length)
    req = urllib.request.Request(url, headers={"User-Agent": "starrail-crosscheck"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("rows", [])


def norm(text):
    """比对用归一化：去掉占位符与富文本标记、压掉空白。

    上游文本带 {NICKNAME}、{F#她}{M#他}、<color=...> 等标记，语音转录里是渲染后的
    结果，直接逐字比会全是假不一致。
    """
    if not text:
        return ""
    text = re.sub(r"\{[^{}]*\}", "", text)
    text = re.sub(r"<[^<>]*>", "", text)
    text = text.replace("\\n", "").replace("#", "")
    return re.sub(r"\s+", "", text)


def iter_events(lang):
    """遍历全部带文本的事件：任务脚本 + 任务外对话。

    不按 kind 过滤——控制事件（trigger/wait）的 custom_string 若是
    `TalkSentence_<id>`，它也带一句台词（见 src/gametext/starrail/script.py）。第一版按
    kind in (talk, option) 过滤，把选项对话的回答整批漏掉了。
    """
    for name, key in (("missions", "id"), ("dialogues", "id")):
        path = os.path.join(DATA, "%s_%s.jsonl" % (name, lang))
        if not _jsonl.exists(path):
            continue
        if True:
            for row in _jsonl.iter_rows(path):
                groups = ([sc["events"] for sc in row.get("scripts") or []]
                          if name == "missions" else [row["events"]])
                for events in groups:
                    for e in events:
                        if e.get("text"):
                            yield row[key], e
                        reply = e.get("reply")
                        if reply and reply.get("text"):
                            yield row[key], reply


def load_corpus(lang):
    """读语料，返回 (归一化文本 -> [(来源 id, speaker, 原文)], 台词总数)。"""
    if not _jsonl.exists(os.path.join(DATA, "missions_%s.jsonl" % lang)):
        sys.exit("读不到语料：missions_%s.jsonl（先跑 uv run gametext starrail all）" % lang)
    index = defaultdict(list)
    total = 0
    for src, e in iter_events(lang):
        total += 1
        index[norm(e["text"])].append((src, e.get("speaker"), e["text"]))
    return index, total


def load_en_speakers():
    """sentence_id -> 英文说话人。语音集的 speaker 用英文内部标识，得对英文语料比。"""
    out = {}
    for _src, e in iter_events("en"):
        if e.get("speaker") and e.get("sentence_id") is not None:
            out.setdefault(e["sentence_id"], e["speaker"])
    return out


def section(title):
    bar = "=" * 70
    print()
    print(bar)
    print(title)
    print(bar)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3000,
                    help="从语音数据集抽多少行（按 100 取整）")
    ap.add_argument("--seed", type=int, default=20260909)
    args = ap.parse_args()

    section("0. 语料与第二来源")
    chs, chs_total = load_corpus("chs")
    print("本地 chs 台词 %d 条，去重后 %d 种" % (chs_total, len(chs)))
    # chs 归一化文本 -> sentence_id，用来跨到英文语料查说话人
    sid_of = {}
    for _src, e in iter_events("chs"):
        if e.get("sentence_id") is not None:
            sid_of.setdefault(norm(e["text"]), e["sentence_id"])
    en_speaker = load_en_speakers()
    print("本地 en  带说话人的台词 %d 条" % len(en_speaker))

    print()
    print("第二来源：%s（HF rows API，只取行不取音频）" % DATASET)
    try:
        probe = urllib.request.Request(
            "%s?dataset=%s&config=default&split=train&offset=0&length=1"
            % (ROWS_API, urllib.parse.quote(DATASET, safe="")),
            headers={"User-Agent": "starrail-crosscheck"})
        with urllib.request.urlopen(probe, timeout=60) as r:
            total_rows = json.load(r).get("num_rows_total")
    except Exception as e:
        sys.exit("取不到第二来源：%s" % e)
    print("数据集总行数：%s（transcription 一律中文，见文件头说明）" % total_rows)

    random.seed(args.seed)
    pages = max(1, args.samples // PAGE)
    offsets = random.sample(range(0, max(1, total_rows - PAGE)), pages)

    section("1. 抽样比对：语音转录（中文）vs 我们解出的中文")
    by_audio = Counter()
    hit_by_audio = Counter()
    checked = hit = 0
    miss_by_type = Counter()
    miss_samples = []
    speaker_checked = speaker_match = 0
    speaker_diff = []

    for off in offsets:
        try:
            rows = fetch_rows(off, PAGE)
        except Exception as e:
            print("  offset %d 取失败：%s" % (off, e))
            continue
        for r in rows:
            row = r["row"]
            text = (row.get("transcription") or "").strip()
            if not text:
                continue
            audio_lang = row.get("language") or "?"
            checked += 1
            by_audio[audio_lang] += 1
            key = norm(text)
            if key in chs:
                hit += 1
                hit_by_audio[audio_lang] += 1
                spk = (row.get("speaker") or "").strip()
                ours = en_speaker.get(sid_of.get(key))
                if spk and ours:
                    speaker_checked += 1
                    if spk.lower() == ours.lower():
                        speaker_match += 1
                    elif len(speaker_diff) < 6:
                        speaker_diff.append((text[:22], spk, ours))
            else:
                miss_by_type[row.get("voice_type") or "<空>"] += 1
                if len(miss_samples) < 5:
                    miss_samples.append((row.get("voice_type") or "-", text[:44]))

    print("比对 %d 条，命中 %d 条 (%.1f%%)"
          % (checked, hit, 100 * hit / max(checked, 1)))
    print()
    print("按音频语种分组（转录都是中文，命中率应当接近，差异只反映抽样）：")
    for lang in AUDIO_LANGS:
        n = by_audio.get(lang, 0)
        if n:
            print("  %-14s 抽到 %5d  命中 %5d  %5.1f%%"
                  % (lang, n, hit_by_audio[lang], 100 * hit_by_audio[lang] / n))
    print()
    print("未命中的 voice_type 分布（多为角色语音/闲聊，不在任务语料范围）：")
    for vt, n in miss_by_type.most_common(6):
        print("  %-26s %5d" % (vt[:26], n))
    for vt, t in miss_samples:
        print("    [%s] %s" % (vt[:16], t))

    section("2. 命中者的说话人（对英文语料比，语音集用的是英文内部标识）")
    if speaker_checked:
        print("可比对 %d 条，一致 %d 条 (%.1f%%)"
              % (speaker_checked, speaker_match,
                 100 * speaker_match / speaker_checked))
        for t, theirs, ours in speaker_diff:
            print("  「%s」 语音集=%s  我们(EN)=%s" % (t, theirs, ours))
    else:
        print("没有可比对的说话人（语音集 speaker 多为空，或该句在英文语料里无说话人）")


if __name__ == "__main__":
    main()
