"""P0 摸底脚本（一次性用途，不进主流水线）。

验四件事（项目起步时的可行性摸底，结论已并入 docs/genshin/architecture.md 与 docs/genshin/data-source.md）：

1. 快照信息：上游 commit 与游戏版本
2. BinOutput/CodexQuest 的语义 tag 全集
3. 假设：HoneyHunterWorld 的 q_XXXX 是否就是上游的 mainQuestId
4. BinOutput/Talk/Quest 的结构推断成功率与失败样本

用法：
    uv run python tools/genshin/p0_probe.py [--limit N] [--old-data PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
from collections import Counter, defaultdict

from gametext import paths
from gametext.genshin import infer
from gametext.genshin.textmap import TextMap

UPSTREAM = paths.upstream("genshin")
BUILD = paths.build("genshin")



def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


# ------------------------------------------------------------------ 1. 快照


def probe_snapshot():
    section("1. 快照信息")
    out = {}
    try:
        commit = subprocess.check_output(
            ["git", "-C", UPSTREAM, "rev-parse", "HEAD"], text=True
        ).strip()
        subject = subprocess.check_output(
            ["git", "-C", UPSTREAM, "log", "-1", "--format=%s%n%cI"], text=True
        ).strip().splitlines()
        out = {"commit": commit, "subject": subject[0], "date": subject[-1]}
        print("commit :", commit)
        print("subject:", subject[0])
        print("date   :", subject[-1])
    except Exception as e:
        print("!! 读不到 git 信息:", e)
        out = {"error": str(e)}
    return out


# --------------------------------------------------------- 2. CodexQuest tag


def probe_codex_tags():
    section("2. CodexQuest 语义 tag 全集")
    root = os.path.join(UPSTREAM, "BinOutput", "CodexQuest")
    if not os.path.isdir(root):
        print("!! 目录不存在:", root)
        return {"error": "missing"}

    files = sorted(f for f in os.listdir(root) if f.endswith(".json"))
    tags = Counter()
    hash_field = Counter()
    for name in files:
        doc = load_json(os.path.join(root, name))
        for obj in walk_dicts(doc):
            # 语义 tag 的判据：对象里同时有一个纯字符串 tag 和一个整数 hash
            strs = [(k, v) for k, v in obj.items() if isinstance(v, str) and v]
            ints = [(k, v) for k, v in obj.items() if isinstance(v, int)]
            if len(obj) == 2 and len(strs) == 1 and len(ints) == 1:
                tags[strs[0][1]] += 1
                hash_field[ints[0][0]] += 1
    print("扫描文件数:", len(files))
    print("tag 载体字段:", dict(hash_field.most_common(3)))
    print("tag 全集 (%d 种):" % len(tags))
    for t, c in tags.most_common():
        print("   %-24s %7d" % (t or "<空>", c))
    return {"files": len(files), "tags": dict(tags)}


def walk_dicts(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk_dicts(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_dicts(v)


# ------------------------------------------------- 3. mainQuestId 对应关系


def probe_id_hypothesis(old_data_path):
    section("3. 假设验证：HoneyHunter q_XXXX == 上游 mainQuestId")

    mq_path = os.path.join(UPSTREAM, "ExcelBinOutput", "MainQuestExcelConfigData.json")
    if not os.path.exists(mq_path):
        print("!! 缺", mq_path)
        return {"error": "missing MainQuestExcelConfigData"}
    main_quests = load_json(mq_path)
    mq = {q["id"]: q for q in main_quests if "id" in q}
    print("上游主任务数:", len(mq))

    if not os.path.exists(old_data_path):
        print("!! 读不到旧抓取结果:", old_data_path)
        print("   跳过对照（这条假设留待有数据时再验）")
        return {"upstream_main_quests": len(mq), "old_data": None}

    old = []
    with open(old_data_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                old.append(json.loads(line))
    old_ids = {o["id"] for o in old}
    print("旧抓取任务数:", len(old_ids))

    hit = old_ids & set(mq)
    print("id 直接命中   : %d / %d  (%.1f%%)" % (len(hit), len(old_ids), 100 * len(hit) / len(old_ids)))
    print("旧有上游无   :", len(old_ids - set(mq)))

    # 用标题文本交叉验证，排除"id 撞巧"
    tm = TextMap.load(UPSTREAM, "CHS")
    checked = matched = 0
    mismatch_samples = []
    for o in old:
        if o["id"] not in mq:
            continue
        h = mq[o["id"]].get("titleTextMapHash")
        title = tm.get(h)
        if title is None:
            continue
        checked += 1
        if title.strip() == (o.get("name") or "").strip():
            matched += 1
        elif len(mismatch_samples) < 8:
            mismatch_samples.append((o["id"], o.get("name"), title))
    print("标题可比对   : %d 条，其中完全一致 %d 条 (%.1f%%)"
          % (checked, matched, 100 * matched / checked if checked else 0))
    if mismatch_samples:
        print("不一致样本:")
        for qid, a, b in mismatch_samples:
            print("   q_%-7s 旧=%-28s 上游=%s" % (qid, a, b))
    return {
        "upstream_main_quests": len(mq),
        "old_quests": len(old_ids),
        "id_hit": len(hit),
        "title_checked": checked,
        "title_matched": matched,
        "mismatch_samples": mismatch_samples,
    }


# ------------------------------------------------------- 4. 结构推断成功率


def probe_inference(limit):
    section("4. BinOutput/Talk/Quest 结构推断")
    root = os.path.join(UPSTREAM, "BinOutput", "Talk", "Quest")
    if not os.path.isdir(root):
        print("!! 目录不存在:", root)
        return {"error": "missing"}

    files = sorted(f for f in os.listdir(root) if f.endswith(".json"))
    print("文件总数:", len(files))
    if limit and limit < len(files):
        random.seed(20260909)
        files = random.sample(files, limit)
        print("本次抽样:", len(files))

    print("装载 TextMapCHS ...")
    tm = TextMap.load(UPSTREAM, "CHS")
    print("  条目数:", len(tm))

    # 第一遍：按 signature 分组
    by_sig = defaultdict(list)
    failures = []
    docs = {}
    empty_talks = []
    for name in files:
        path = os.path.join(root, name)
        doc = load_json(path)
        docs[name] = doc
        sig, nodes, err = infer.signature_of(doc)
        if err:
            failures.append(infer.Failure(name, "signature", err))
            continue
        if not nodes:
            empty_talks.append(name)
        by_sig[sig].append((name, nodes))
    print("空 talk（合法，dialogList 为空）: %d" % len(empty_talks))

    print("\n发现 %d 种 signature：" % len(by_sig))
    schemas = {}
    for sig, items in sorted(by_sig.items(), key=lambda kv: -len(kv[1])):
        print("\n--- signature: %s" % sig.short())
        print("    文件数: %d  例: %s" % (len(items), [n for n, _ in items[:3]]))
        schema, err = infer.infer_schema(
            sig, (nodes for _, nodes in items), lambda h: h in tm
        )
        if err:
            print("    !! 推断失败:", err)
            for name, _ in items:
                failures.append(infer.Failure(name, "schema", err))
            continue
        schemas[sig] = schema
        ev = schema.evidence
        print("    id       = %s   (与 next 重合 %.3f, 次优 %s)"
              % (schema.id_key, ev["id_overlap"], ev["id_runner_up"]))
        print("    next     = %s" % schema.next_key)
        print("    role     = %s" % schema.role_key)
        print("    content  = %s   (命中率 %s, 覆盖率 %s)"
              % (schema.content_key,
                 ev["textmap_hit"].get(schema.content_key),
                 ev["coverage"].get(schema.content_key)))
        print("    其余文本 hash = %s" % (list(schema.other_hash_keys) or "无"))
        for k in sorted(ev["textmap_hit"], key=lambda k: -ev["coverage"][k]):
            print("      %-24s 命中 %.3f  覆盖 %.3f"
                  % (k, ev["textmap_hit"][k], ev["coverage"][k]))

    # 第二遍：按推出的 schema 归一化，统计质量
    section("4b. 归一化质量")
    stats = Counter()
    dangling = 0
    all_ids = set()
    all_next = set()
    unresolved_samples = []
    for sig, items in by_sig.items():
        schema = schemas.get(sig)
        if not schema:
            continue
        for name, _ in items:
            nodes, fail = infer.normalize_talk(docs[name], schema, name)
            if fail:
                failures.append(fail)
                continue
            stats["files_ok"] += 1
            for n in nodes:
                stats["nodes"] += 1
                if n["dialog_id"] is None:
                    stats["node_no_id"] += 1
                else:
                    all_ids.add(n["dialog_id"])
                all_next.update(n["next"])
                if n["content_hash"] is None:
                    stats["node_no_content_field"] += 1
                elif n["content_hash"] == 0:
                    # 字段在但值为 0：黑屏、选项占位之类本来就没有正文的节点
                    stats["node_content_empty"] += 1
                elif tm.get(n["content_hash"]) is None:
                    stats["node_hash_unresolved"] += 1
                    if len(unresolved_samples) < 5:
                        unresolved_samples.append((name, n["content_hash"]))
                if n["role"] is None:
                    stats["node_no_role"] += 1
    dangling = len(all_next - all_ids)

    print("文件 归一化成功 : %d" % stats["files_ok"])
    print("文件 失败       : %d" % len(failures))
    n_all = stats["nodes"] or 1
    print("对话节点总数    : %d" % stats["nodes"])
    print("  无 dialog_id  : %d" % stats["node_no_id"])
    print("  无 content 字段: %d" % stats["node_no_content_field"])
    print("  正文 hash 为 0 : %d (%.2f%%，黑屏/占位，非缺陷)"
          % (stats["node_content_empty"], 100 * stats["node_content_empty"] / n_all))
    print("  hash 查不到文本: %d (%.2f%%)  样本 %s"
          % (stats["node_hash_unresolved"],
             100 * stats["node_hash_unresolved"] / n_all, unresolved_samples))
    print("  无说话人      : %d" % stats["node_no_role"])
    print("悬空 next 引用  : %d" % dangling)

    if failures:
        print("\n失败样本（最多 10 条）:")
        for f in failures[:10]:
            print("   %-24s [%s] %s" % (f.source, f.stage, f.reason))

    return {
        "files_scanned": len(files),
        "empty_talks": len(empty_talks),
        "signatures": len(by_sig),
        "schemas": {
            sig.short(): {
                "files": len(by_sig[sig]),
                "id_key": s.id_key,
                "next_key": s.next_key,
                "role_key": s.role_key,
                "content_key": s.content_key,
                "other_hash_keys": list(s.other_hash_keys),
                "evidence": s.evidence,
            }
            for sig, s in schemas.items()
        },
        "stats": dict(stats),
        "dangling_next": dangling,
        "failures": [f.as_dict() for f in failures],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500,
                    help="Talk/Quest 抽样文件数，0 表示全量")
    ap.add_argument("--old-data", default="", help="旧的网页抓取结果 quests_chs.jsonl（不给就跳过 id 假设那一项）")
    args = ap.parse_args()

    report = {
        "snapshot": probe_snapshot(),
        "codex_tags": probe_codex_tags(),
        "id_hypothesis": probe_id_hypothesis(args.old_data),
        "inference": probe_inference(args.limit),
    }

    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, "p0_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print("\n报告写入:", out)


if __name__ == "__main__":
    main()
