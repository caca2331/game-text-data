"""assemble 阶段：把 index 的中间层装配成任务树。

**刻意不解引用文本**，产物里存的仍是 TextMapHash。这样 emit 就是纯粹的
"一份任务树 × 四张 TextMap"，四语种同源同序成了结构保证而不是约定
（AGENTS.md 不变量 3）。
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _iter_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


# CodexQuest 里每个文本节点自带明文语义 tag，递归找"同时含 hash 和 tag 的二元
# 对象"即可，不必认识外层随机 key。见 docs/genshin/data-source.md。
CODEX_CHAPTER_TITLE = "ChapterTitle"
CODEX_CHAPTER_NUM = "ChapterNum"


def _walk_tagged(node):
    """产出 (tag, hash)。判据：对象恰好两个字段，一个非空字符串、一个整数。"""
    if isinstance(node, dict):
        strs = [v for v in node.values() if isinstance(v, str) and v]
        ints = [v for v in node.values() if isinstance(v, int) and not isinstance(v, bool)]
        if len(node) == 2 and len(strs) == 1 and len(ints) == 1:
            yield strs[0], ints[0]
        for v in node.values():
            yield from _walk_tagged(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_tagged(v)


class Assembler:
    def __init__(self, upstream: str, build: str):
        self.upstream = upstream
        self.build = build
        self.stats = Counter()

    def load_chapters(self) -> dict:
        """chapterId -> {title_hash, num_hash}，来自 BinOutput/CodexQuest。"""
        root = os.path.join(self.upstream, "BinOutput", "CodexQuest")
        out = {}
        if not os.path.isdir(root):
            return out
        for name in sorted(os.listdir(root)):
            if not name.endswith(".json") or not name[:-5].isdigit():
                continue
            tags = defaultdict(list)
            for tag, h in _walk_tagged(_load(os.path.join(root, name))):
                tags[tag].append(h)
            out[int(name[:-5])] = {
                "title_hash": (tags.get(CODEX_CHAPTER_TITLE) or [None])[0],
                "num_hash": (tags.get(CODEX_CHAPTER_NUM) or [None])[0],
            }
        self.stats["chapters"] = len(out)
        return out

    def load_step_meta(self) -> dict:
        """subId -> 明文元数据，来自 QuestExcelConfigData。

        **只取明文字段**（order / failCondComb 等）。这张表里的
        stepDescTextMapHash / guideTipsTextMapHash 是死字段：17 814 条里只有 698
        条能查到文本。步骤正文由 index 阶段从 BinOutput/Quest 取，命中率 99.97%。
        """
        path = os.path.join(
            self.upstream, "ExcelBinOutput", "QuestExcelConfigData.json")
        meta = {}
        for row in _load(path):
            if row.get("subId") is None:
                continue
            meta[row["subId"]] = {
                "order": row.get("order"),
                "fail_cond": row.get("failCondComb"),
            }
        self.stats["step_meta"] = len(meta)
        return meta

    def merge_steps(self, indexed, step_meta):
        """把 index 给的步骤文本与 Excel 的明文元数据按 sub_id 合起来。"""
        out = []
        for s in indexed:
            meta = step_meta.get(s["sub_id"], {})
            if s["sub_id"] is not None and not meta:
                self.stats["step_not_in_excel"] += 1
            out.append({
                "sub_id": s["sub_id"],
                "order": meta.get("order"),
                "desc_hash": s.get("desc_hash"),
                "fail_cond": meta.get("fail_cond"),
            })
        out.sort(key=lambda s: (s["order"] is None, s["order"]))
        self.stats["steps"] += len(out)
        return out

    def run(self) -> str:
        idx = os.path.join(self.build, "index")
        talks = {t["talk_id"]: t for t in _iter_jsonl(os.path.join(idx, "talks.jsonl"))}
        chapters = self.load_chapters()
        step_meta = self.load_step_meta()

        out_path = os.path.join(self.build, "assembled.jsonl")
        with open(out_path, "w", encoding="utf-8") as out:
            for q in _iter_jsonl(os.path.join(idx, "quests.jsonl")):
                qid = q["main_quest_id"]
                chapter = chapters.get(q.get("chapter_id")) or {}
                dialog = []
                # 显式引用与前缀推测分开标记，下游可按 attribution 过滤
                for kind, key in (("explicit", "talk_ids"),
                                  ("inferred", "talk_ids_inferred")):
                    for tid in q.get(key) or []:
                        talk = talks.get(tid)
                        if not talk:
                            self.stats["talk_missing"] += 1
                            continue
                        self.stats["dialog_" + kind] += len(talk["dialog"])
                        for node in talk["dialog"]:
                            node = dict(node)
                            node["talk_id"] = tid
                            node["attribution"] = kind
                            node["subdir"] = talk.get("subdir")
                            dialog.append(node)
                self.stats["quests"] += 1
                self.stats["dialog_nodes"] += len(dialog)
                if not dialog:
                    self.stats["quests_without_dialog"] += 1
                out.write(json.dumps({
                    "id": qid,
                    "title_hash": q.get("title_hash"),
                    "desc_hash": q.get("desc_hash"),
                    "title_hash_alt": q.get("title_hash_alt"),
                    "desc_hash_alt": q.get("desc_hash_alt"),
                    "chapter_id": q.get("chapter_id"),
                    "chapter_title_hash": chapter.get("title_hash"),
                    "chapter_num_hash": chapter.get("num_hash"),
                    "series": q.get("series"),
                    "tag": q.get("tag"),
                    "steps": self.merge_steps(q.get("steps") or [], step_meta),
                    "dialog": dialog,
                }, ensure_ascii=False) + "\n")
        return out_path
