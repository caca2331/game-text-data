"""与旧爬虫结果的交叉校验（一次性用途，不进主流水线）。

旧数据来自维护者早先的一个网页爬虫，抓 HoneyHunterWorld
所得，3818 条。它质量有问题（见该项目 README 的已知缺陷），但作为**独立第二来源**
做 diff 很有价值：新方案是从解包数据推断出来的，只有拿一份完全不同来源的数据对
一遍，才能确认字段没接错、TextMap 没解错。

用法：
    uv run python tools/genshin/crosscheck.py [--old PATH] [--new PATH]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

from gametext import paths
from gametext.core import jsonl as _jsonl          # 产物可能是 .zst，统一走它

NEW_DEFAULT = os.path.join(paths.corpus("genshin"), "quests_chs.jsonl")

SCAFFOLD = ("$HIDDEN", "$UNRELEASED")


def load(path):
    out = {}
    for row in _jsonl.iter_rows(path):
        out[row["id"]] = row
    return out


def is_scaffold(name):
    name = name or ""
    return any(m in name for m in SCAFFOLD) or "test" in name.lower()


def norm(text):
    """比对用的归一化：去掉富文本标记、性别分支和空白。

    上游文本里带 {RUBY#...}、{PLAYERAVATAR#...}、#{M#..}{F#..}、<color=..> 之类
    标记，HoneyHunterWorld 渲染时已经把它们处理掉了，直接逐字比会全是假不一致。
    """
    if not text:
        return ""
    text = re.sub(r"\{[^{}]*\}", "", text)
    text = re.sub(r"<[^<>]*>", "", text)
    text = text.replace("#", "").replace("*", "")
    return re.sub(r"\s+", "", text)


def placeholder_match(old_text, new_text):
    """新文本含占位符、旧文本是它的渲染结果。

    新数据忠实保留上游的 `{NICKNAME}`、`{F#她}{M#他}` 等占位符，而
    HoneyHunterWorld 渲染时已经替换成了"玩家"之类的具体词，逐字比必然不同。
    判据：把新文本按占位符切成若干固定片段，这些片段按原顺序出现在旧文本里。
    """
    if "{" not in new_text:
        return False
    pos = 0
    for piece in re.split(r"\{[^{}]*\}", new_text):
        piece = piece.replace("#", "").strip()
        if not piece:
            continue
        found = old_text.find(piece, pos)
        if found < 0:
            return False
        pos = found + len(piece)
    return True


def old_lines(row):
    """旧数据的对话是**树**：dialog 里每项含 dialogues = {dialogId: {line,...}}。
    展平成 {dialogId(int): 台词}。"""
    out = {}
    for node in row.get("dialog") or []:
        if not isinstance(node, dict):
            continue
        for did, d in (node.get("dialogues") or {}).items():
            if isinstance(d, dict) and d.get("line"):
                try:
                    out[int(did)] = d["line"]
                except (TypeError, ValueError):
                    pass
    return out


def new_lines(row):
    return {d["dialog_id"]: d["text"]
            for d in row.get("dialog") or []
            if d.get("dialog_id") is not None and d.get("text")}


def section(t):
    bar = "=" * 68
    print("\n%s\n%s\n%s" % (bar, t, bar))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, help="第二来源（网页爬虫产出的 quests_chs.jsonl）的路径")
    ap.add_argument("--new", default=NEW_DEFAULT)
    args = ap.parse_args()

    if not os.path.exists(args.old):
        sys.exit("读不到旧数据：%s" % args.old)
    old, new = load(args.old), load(args.new)
    OL = {q: old_lines(old[q]) for q in old}
    NL = {q: new_lines(new[q]) for q in new}
    print("旧 %d 条任务 / %d 条台词" % (len(old), sum(len(v) for v in OL.values())))
    print("新 %d 条任务 / %d 条台词" % (len(new), sum(len(v) for v in NL.values())))

    # ---------------------------------------------------------- 1. id diff
    section("1. 任务 id 集合双向 diff")
    only_old = sorted(set(old) - set(new))
    only_new = sorted(set(new) - set(old))
    both = sorted(set(old) & set(new))
    print("共有 %d，仅旧有 %d，仅新有 %d" % (len(both), len(only_old), len(only_new)))
    print("仅旧有（新方案的缺口）：")
    for qid in only_old:
        print("   q_%-8s %s" % (qid, old[qid].get("name")))
    scaffold_new = sum(1 for q in only_new if is_scaffold(new[q].get("name")))
    print("仅新有 %d 条（旧爬虫漏掉的）：废案脚手架 %d，真任务 %d"
          % (len(only_new), scaffold_new, len(only_new) - scaffold_new))
    for qid in [q for q in only_new if not is_scaffold(new[q].get("name"))][:8]:
        print("   q_%-8s %s" % (qid, new[qid].get("name")))

    # ------------------------------------------------- 2. 空对话的影响面
    section("2. 旧数据的空对话，新方案补回来多少")
    old_empty = [q for q in both if not OL[q]]
    recovered = [q for q in old_empty if NL[q]]
    print("共有 id 中旧数据一条台词都没有：%d" % len(old_empty))
    print("其中新方案有台词：%d (%.1f%%)，仍为空 %d"
          % (len(recovered), 100 * len(recovered) / max(len(old_empty), 1),
             len(old_empty) - len(recovered)))
    print("补回的台词总数：%d" % sum(len(NL[q]) for q in recovered))
    print("按旧数据的任务类型：",
          dict(Counter(old[q].get("type") for q in recovered).most_common()))
    for qid in recovered[:5]:
        first = next(iter(NL[qid].values()), "")
        print("   q_%-8s %-20s 新有 %4d 条  首句：%s"
              % (qid, (new[qid].get("name") or "")[:20], len(NL[qid]), first[:32]))

    # ------------------------------------------------------ 3. 台词量对比
    section("3. 共有任务的台词条数对比")
    more = less = same = 0
    shrunk = []
    for qid in both:
        o, n = len(OL[qid]), len(NL[qid])
        if n > o:
            more += 1
        elif n < o:
            less += 1
            shrunk.append((o - n, qid, o, n))
        else:
            same += 1
    print("新 > 旧：%d   相等：%d   新 < 旧：%d" % (more, same, less))
    shrunk.sort(reverse=True)
    if shrunk:
        print("新方案台词反而更少的（需要解释）：")
        for delta, qid, o, n in shrunk[:12]:
            print("   q_%-8s 旧 %4d -> 新 %4d  (-%d)  %s"
                  % (qid, o, n, delta, (new[qid].get("name") or "")[:26]))

    # ----------------------------------------- 4. 按 dialogId 对齐逐条比对
    section("4. 按 dialogId 对齐，逐条比对台词文本")
    ids_both = ids_only_old = ids_only_new = 0
    exact = normed = placeholder = differ = 0
    diffs = []
    all_new_ids = set()
    for q in new:
        all_new_ids |= set(NL[q])
    only_old_ids = []
    for qid in both:
        o, n = OL[qid], NL[qid]
        common = o.keys() & n.keys()
        ids_both += len(common)
        ids_only_new += len(n.keys() - o.keys())
        for did in o.keys() - n.keys():
            ids_only_old += 1
            only_old_ids.append(did)
        for did in common:
            a, b = o[did], n[did]
            if a == b:
                exact += 1
            elif norm(a) == norm(b):
                normed += 1
            elif placeholder_match(a, b):
                placeholder += 1
            else:
                differ += 1
                if len(diffs) < 6:
                    diffs.append((qid, did, a[:46], b[:46]))
    tot = ids_both or 1
    print("共有 dialogId %d；仅旧有 %d；仅新有 %d" % (ids_both, ids_only_old, ids_only_new))
    print("  逐字相同           %7d (%.2f%%)" % (exact, 100 * exact / tot))
    print("  去富文本标记后相同 %7d (%.2f%%)" % (normed, 100 * normed / tot))
    print("  仅占位符差异       %7d (%.2f%%)  新数据保留 {NICKNAME} 等原样，"
          "旧站点已渲染成具体词" % (placeholder, 100 * placeholder / tot))
    print("  真不同             %7d (%.2f%%)" % (differ, 100 * differ / tot))
    for qid, did, a, b in diffs:
        print("   q_%s #%s" % (qid, did))
        print("     旧: %s" % a)
        print("     新: %s" % b)

    in_other = sum(1 for d in only_old_ids if d in all_new_ids)
    print("\n仅旧有的 %d 条台词里：%d 条在新数据的**别的任务**下（只是归属不同，"
          "未丢失），%d 条新数据完全没有（占旧台词 %.2f%%）"
          % (len(only_old_ids), in_other, len(only_old_ids) - in_other,
             100 * (len(only_old_ids) - in_other)
             / max(sum(len(v) for v in OL.values()), 1)))

    # ---------------------------------------------------------- 5. 废案
    section("5. 废案任务")
    print("旧 %d 条 / 新 %d 条（均保留，不删除，由下游按 name/tag 过滤）"
          % (sum(1 for q in old if is_scaffold(old[q].get("name"))),
             sum(1 for q in new if is_scaffold(new[q].get("name")))))


if __name__ == "__main__":
    main()
