"""Voice/Items 与 Lut 的正向配音证据；不把缺映射当成没有配音。"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

from . import infer

TRIGGERS = ("Dialog", "DungeonReminder")


def _has_audio(node):
    """资源路径本身是明文锚点；容器、文件名字段也可能混淆。"""
    if isinstance(node, str):
        return node.lower().endswith(".wem")
    if isinstance(node, dict):
        return any(_has_audio(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_audio(v) for v in node)
    return False


def load(upstream, universes):
    """返回 {trigger: set(id)}、统计与 Failure 列表。

    以 trigger 字段名聚合同一来源中的 schema，用已解析的 Talk / Reminder id
    集合识别参数字段。只接受唯一的高命中字段；推不出或有歧义记入 unparsed。
    Items 还要求有 wem 路径，Lut 本身就是事件映射。Emo 与 Voice 根目录的
    遗留副本不参与：Emo 是表情，根目录那些文件在 Items 中有对应副本。
    """
    result = {t: set() for t in TRIGGERS}
    stats, failures = Counter(), []
    base = os.path.join(upstream, "BinOutput", "Voice")
    known = set().union(*universes.values()) - {0}
    for source in ("Items", "Lut"):
        directory = os.path.join(base, source)
        files = sorted(n for n in os.listdir(directory) if n.endswith(".json")) \
            if os.path.isdir(directory) else []
        if not files:
            failures.append(infer.Failure(
                "BinOutput/Voice/" + source, "voice_source",
                "语音映射目录缺失或没有 JSON；请更新 sparse 快照"))
            continue
        stats["voice_%s_files" % source.lower()] = len(files)
        groups = defaultdict(list)
        recognized = 0
        for name in files:
            with open(os.path.join(directory, name), encoding="utf-8") as f:
                doc = json.load(f)
            if not isinstance(doc, dict) or any(not isinstance(r, dict) for r in doc.values()):
                failures.append(infer.Failure(
                    "BinOutput/Voice/%s/%s" % (source, name), "voice_layout",
                    "预期事件 id 到对象的字典"))
                continue
            stats["voice_%s_records" % source.lower()] += len(doc)
            for row in doc.values():
                triggers = [k for k, v in row.items() if isinstance(v, str) and v in TRIGGERS]
                if not triggers:
                    stats["voice_%s_other_trigger" % source.lower()] += 1
                    continue
                if len(triggers) != 1:
                    failures.append(infer.Failure(
                        "BinOutput/Voice/%s/%s" % (source, name), "voice_trigger",
                        "触发类型字段不唯一"))
                    continue
                recognized += 1
                if source == "Items" and not _has_audio(row):
                    stats["voice_items_without_audio"] += 1
                    continue
                groups[triggers[0]].append((name, row))

        if not recognized:
            failures.append(infer.Failure(
                "BinOutput/Voice/" + source, "voice_trigger",
                "源中没有可识别的 Dialog / DungeonReminder 触发，不能确认结构"))

        evidence = {}
        source_ids = {t: set() for t in TRIGGERS}
        for trigger_key, entries in sorted(groups.items()):
            candidates = infer.infer_id_paths(
                ({k: v for k, v in r.items() if type(v) is int and v > 0}
                 for _, r in entries), {"arg": known}, min_count=1)["arg"]
            evidence[trigger_key] = infer.summarize_paths(candidates)
            if len(candidates) != 1:
                failures.append(infer.Failure(
                    "BinOutput/Voice/" + source, "voice_args",
                    "不能唯一识别语音触发参数字段",
                    {"trigger_key": trigger_key, "candidates": evidence[trigger_key],
                     "files": sorted({name for name, _ in entries})}))
                continue
            arg_key = candidates[0]["path"]
            for _, row in entries:
                arg = row.get(arg_key)
                if type(arg) is int and arg > 0:
                    source_ids[row[trigger_key]].add(arg)
                else:
                    # 省略 / 显式为 0 的参数是无目标的事件占位，不猜 id。
                    stats["voice_%s_without_arg" % source.lower()] += 1
        stats["voice_%s_fields" % source.lower()] = evidence
        for trigger, ids in source_ids.items():
            stats["voice_%s_%s_ids" % (source.lower(), trigger)] = len(ids)
            result[trigger].update(ids)
    for trigger, ids in result.items():
        stats["voice_%s_ids" % trigger] = len(ids)
        stats["voice_%s_matched_ids" % trigger] = len(ids & universes[trigger])
    return result, stats, failures
