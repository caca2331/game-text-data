"""P0 摸底脚本（一次性用途，不进主流水线）。

项目起步时的上游结构摸底，结论已并入 docs/starrail/data-source.md 与 docs/starrail/architecture.md。验这几项：

1. TextMap 的分片与 `TextMapMain` 到底是什么关系，`Main` 那套含不含对话正文
2. `Story/` 三个子目录分别是什么
3. 对话链路（Story 脚本 -> TalkSentenceConfig -> TextMap）的实际命中率
4. 任务表规模，以及 `Story/Mission` 子目录名与 MainMissionID 的对应关系
5. 短信系统（`Message*`）的规模——决定是否纳入首版

用法：
    uv run python tools/starrail/p0_probe.py
"""

from __future__ import annotations

import json
import os
import random
import re
from collections import Counter

from gametext import paths
from gametext.core import snapshot
from gametext.starrail import UPSTREAM as UP
from gametext.starrail.textmap import LANGS, TextMap, shard_files

UPSTREAM = paths.upstream("starrail")
BUILD = paths.build("starrail")

TALK_ID_RE = re.compile(r'"TalkSentenceID"\s*:\s*(\d+)')
TYPE_RE = re.compile(r'"\$type"\s*:\s*"([^"]+)"')


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def section(title):
    bar = "=" * 70
    print("\n%s\n%s\n%s" % (bar, title, bar))


def probe_snapshot():
    section("1. 快照")
    info = snapshot.describe(UP, UPSTREAM, fetch=False)
    print("commit :", info["commit"])
    print("version:", info["version"], "|", info["version_subject"])
    print("date   :", info["commit_date"])
    for w in snapshot.check_liveness(UP, UPSTREAM, info):
        print("!! 存活检测:", w)
    return info


def probe_textmap():
    section("2. TextMap：分片与 Main 表")
    base = os.path.join(UPSTREAM, "TextMap")
    out = {}
    tables = {}
    for lang in LANGS:
        files = shard_files(base, lang)
        sizes = {f: os.path.getsize(os.path.join(base, f)) for f in files}
        tm = TextMap.load(UPSTREAM, lang)
        tables[lang] = tm
        print("%-4s 文件 %s" % (lang, [
            "%s(%.1fMB)" % (f, s / 1024 / 1024) for f, s in sizes.items()]))
        print("     合计 %d 条，分片重叠 %d" % (len(tm), tm.collisions))
        out[lang] = {"files": list(sizes), "entries": len(tm),
                     "collisions": tm.collisions}

    # Main 表到底是什么：与主表的 key 交集，以及它的文本长什么样
    main_name = "TextMapMainCHS.json"
    main_path = os.path.join(base, main_name)
    if os.path.exists(main_path):
        main = load_json(main_path)
        big = {}
        for f in shard_files(base, "CHS"):
            if f.startswith("TextMapMain"):
                continue
            big.update(load_json(os.path.join(base, f)))
        inter = main.keys() & big.keys()
        print("\n%s：%d 条；主表 %d 条；交集 %d"
              % (main_name, len(main), len(big), len(inter)))
        print("Main 表文本样本：", list(main.values())[:5])
        out["main_table"] = {"entries": len(main), "intersection": len(inter)}
    return out, tables


def probe_story_dirs():
    section("3. Story/ 三个子目录")
    root = os.path.join(UPSTREAM, "Story")
    out = {}
    for sub in sorted(os.listdir(root)):
        p = os.path.join(root, sub)
        if not os.path.isdir(p):
            continue
        files = []
        for dirpath, _dirnames, filenames in os.walk(p):
            files += [os.path.join(dirpath, f) for f in filenames
                      if f.endswith(".json")]
        talk_files = 0
        sample_types = Counter()
        random.seed(7)
        for f in random.sample(files, min(40, len(files))):
            with open(f, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            if TALK_ID_RE.search(text):
                talk_files += 1
            sample_types.update(t.split(".")[-1] for t in TYPE_RE.findall(text))
        print("%-20s %5d 个 json；抽 %d 个，其中 %d 个含 TalkSentenceID"
              % (sub, len(files), min(40, len(files)), talk_files))
        print("     常见 $type：", [t for t, _ in sample_types.most_common(8)])
        out[sub] = {"files": len(files), "with_talk": talk_files}
    return out


def probe_dialogue_chain(tables):
    section("4. 对话链路：Story -> TalkSentenceConfig -> TextMap")
    cfg_path = os.path.join(UPSTREAM, "ExcelOutput", "TalkSentenceConfig.json")
    rows = load_json(cfg_path)
    sentences = {}
    for r in rows:
        sid = r.get("TalkSentenceID")
        if sid is None:
            continue
        sentences[sid] = {
            "text": (r.get("TalkSentenceText") or {}).get("Hash"),
            "name": (r.get("TextmapTalkSentenceName") or {}).get("Hash"),
        }
    print("TalkSentenceConfig 条目：%d" % len(sentences))

    chs = tables["CHS"]
    have_text = sum(1 for v in sentences.values() if chs.get(v["text"]) is not None)
    have_name = sum(1 for v in sentences.values() if chs.get(v["name"]) is not None)
    print("  台词能查到文本：%d (%.2f%%)" % (have_text, 100 * have_text / len(sentences)))
    print("  说话人名能查到：%d (%.2f%%)" % (have_name, 100 * have_name / len(sentences)))
    for lang in LANGS:
        n = sum(1 for v in sentences.values()
                if tables[lang].get(v["text"]) is not None)
        print("    %-4s %.2f%%" % (lang, 100 * n / len(sentences)))

    # 引用源分布。**必须扫 Config/Level**：只看 Story/ 的话覆盖率仅 6.57%，
    # 加上 Config/Level 才到 65% —— P0 第一版就是这么踩坑的。
    by_root = Counter()
    referenced = set()
    for root in ("Config", "Story"):
        base = os.path.join(UPSTREAM, root)
        if not os.path.isdir(base):
            continue
        for dirpath, _d, filenames in os.walk(base):
            rel = os.path.relpath(dirpath, UPSTREAM).split(os.sep)
            key = "/".join(rel[:2])
            for f in filenames:
                if not f.endswith(".json"):
                    continue
                with open(os.path.join(dirpath, f), encoding="utf-8",
                          errors="replace") as fh:
                    ids = {int(x) for x in TALK_ID_RE.findall(fh.read())}
                if ids:
                    by_root[key] += len(ids)
                    referenced |= ids
    print()
    print("引用源分布（每文件去重后累加）：")
    for k, n in by_root.most_common(8):
        print("  %-32s %8d" % (k, n))
    print()
    print("引用到 %d 个不重复 TalkSentenceID，占配置表 %.2f%%"
          % (len(referenced), 100 * len(referenced) / len(sentences)))
    print("  其中在 TalkSentenceConfig 里找得到：%d" % len(referenced & set(sentences)))
    print("  配置表里有、但没有任何脚本引用的：%d" % len(set(sentences) - referenced))
    return {"sentences": len(sentences), "referenced": len(referenced),
            "unreferenced": len(set(sentences) - referenced)}


def probe_missions():
    section("5. 任务表与目录对应关系")
    ex = os.path.join(UPSTREAM, "ExcelOutput")
    main = load_json(os.path.join(ex, "MainMission.json"))
    sub = load_json(os.path.join(ex, "SubMission.json"))
    main_ids = {m["MainMissionID"] for m in main if "MainMissionID" in m}
    print("MainMission %d 条，SubMission %d 条" % (len(main), len(sub)))
    print("MainMission.Type 分布：",
          dict(Counter(m.get("Type") for m in main).most_common()))

    dirs = {d for d in os.listdir(os.path.join(UPSTREAM, "Story", "Mission"))
            if d.isdigit()}
    dir_ids = {int(d) for d in dirs}
    print("Story/Mission 子目录 %d 个" % len(dir_ids))
    print("  目录名命中 MainMissionID：%d" % len(dir_ids & main_ids))
    print("  有目录但表里没有：%d  %s"
          % (len(dir_ids - main_ids), sorted(dir_ids - main_ids)[:6]))
    print("  有任务但没目录：%d（多半是无剧情脚本的任务）" % len(main_ids - dir_ids))
    return {"main": len(main), "sub": len(sub), "dirs": len(dir_ids),
            "dirs_matched": len(dir_ids & main_ids)}


def probe_messages(tables):
    section("6. 短信系统规模（决定是否纳入首版）")
    ex = os.path.join(UPSTREAM, "ExcelOutput")
    out = {}
    for name in ("MessageItemConfig.json", "MessageSectionConfig.json",
                 "MessageGroupConfig.json", "MessageContactsConfig.json"):
        p = os.path.join(ex, name)
        if not os.path.exists(p):
            print("%-30s 不存在" % name)
            continue
        rows = load_json(p)
        print("%-30s %5d 条" % (name, len(rows)))
        out[name] = len(rows)
        if name == "MessageItemConfig.json" and rows:
            hashes = [(r.get("MainText") or {}).get("Hash") for r in rows]
            hashes = [h for h in hashes if h]
            hit = sum(1 for h in hashes if tables["CHS"].get(h) is not None)
            print("     MainText 能查到文本：%d / %d" % (hit, len(hashes)))
            print("     字段样本：", sorted(rows[0].keys())[:10])
    return out


def main():
    report = {}
    report["snapshot"] = probe_snapshot()
    report["textmap"], tables = probe_textmap()
    report["story_dirs"] = probe_story_dirs()
    report["dialogue_chain"] = probe_dialogue_chain(tables)
    report["missions"] = probe_missions()
    report["messages"] = probe_messages(tables)

    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, "p0_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print("\n报告写入:", out)


if __name__ == "__main__":
    main()
