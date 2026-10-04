"""emit 阶段：一份索引 × 多张 TextMap，展开成多语种 JSONL。

各语种由**同一次遍历、同一个顺序**写出，行数相同、逐行 id 相同是结构保证
（AGENTS.md 不变量 2）。文本查不到写 null 而不是空串，并计数上报。

五种产物：scenes（剧情场景）、quests（任务元数据）、messages（短信分支图）、
loose（没进前三种的全部 TextMap 条目）、terms（短名词对照表：TextMap 里名词形的短串，见 `is_term`）。
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter

from ..core import jsonl
from . import textmap
from .contract import CONTRACTS
from .textmap import TextMap

BASE_LANG = "CHS"

OUTPUTS = ("scenes", "quests", "messages", "loose", "terms")

TERM_MAX_CHARS = 16
"""短名词的"短"：基准语种（CHS）≤ 16 字。和 genshin / starrail 同一个口径（那两边去重后的说话人中文名
长度 P99 = 15 / 13）；本项目没有逐行说话人，出场角色表的名字长度见 docs/zzz/manual.md 的"短名词"一节。"""
TERM_REJECT = re.compile(r"[。！？!?；;…\r\n{}<>#$|\\]|test", re.IGNORECASE)
"""带句读 / 换行 / 占位与富文本标记（`{…}`、`<color>`）/ 测试串的不收：那是句子或模板，不是名词。"""
TERM_NEED = re.compile(r"[぀-ヿ㐀-鿿]")


def is_term(chs) -> bool:
    """TextMap 的一条是不是"短名词"：只看基准语种（CHS）那份文本，所以各语种的行集合天然相同。
    和 loose 不同：loose 按 **key** 的形态分（没进剧情 / 任务 / 短信的条目），这里按**文本**的形状收，
    场景出场角色的名字（在 scenes 里）也在内——下游按屏幕上的字查译名，不关心条目归在哪份产物。"""
    return bool(chs) and len(chs) <= TERM_MAX_CHARS and bool(TERM_NEED.search(chs)) \
        and not TERM_REJECT.search(chs)


def _iter_jsonl(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


class Emitter:
    def __init__(self, upstream, build, out_dir, snapshot, compress="zstd"):
        self.upstream = upstream
        self.build = build
        self.out_dir = out_dir
        self.snapshot = snapshot
        self.compress = compress
        os.makedirs(out_dir, exist_ok=True)
        self.stats = Counter()
        self.per_lang = {lang: Counter() for lang in textmap.LANGS}
        self.contract = {}  # 表 -> 语种 -> 契约检查摘要（Checker.summary）
        self._base = None

    def _text(self, table, key, lang, kind):
        if not key:
            return None
        self.per_lang[lang][kind + "_lookups"] += 1
        value = table.get(key)
        if value is None:
            self.per_lang[lang][kind + "_unresolved"] += 1
            # 分开"上游没做本地化"与"上游根本没这条"，否则非中文语种的未解析率
            # 会虚高，看着像流水线坏了（genshin 踩过）
            if self._base is not None and self._base.get(key) is not None:
                self.per_lang[lang][kind + "_untranslated"] += 1
            else:
                self.per_lang[lang][kind + "_absent_upstream"] += 1
        return value

    def _scene_row(self, row, table, lang, meta):
        lines = []
        for ln in row["lines"]:
            lines.append({
                "slot": ln["slot"],
                "text": self._text(table, ln["key"], lang, "text"),
                "key": ln["key"],
            })
        self.per_lang[lang]["lines"] += len(lines)
        perform = row.get("perform")
        return {
            "id": "%s|%s|%s" % (row["category"], row["chapter"], row["scene"]),
            "category": row["category"],
            "chapter": row["chapter"],
            "scene": row["scene"],
            # 来自 FileCfg 的场景元信息：类型（GalGame / Chat / Bubble …）、资源分组、
            # 标题与简介。没匹配上 Perform 表的场景这里是 null。
            "kind": perform["kind"] if perform else None,
            "group": perform["group"] if perform else None,
            "title": self._text(table, perform["title_key"], lang, "title")
                     if perform else None,
            "intro": self._text(table, perform["intro_key"], lang, "intro")
                     if perform else None,
            "quests": row.get("quests") or [],
            # 出场角色表（`_Name_NNN` 按序号排），**不是逐行说话人**——上游没有逐行说话人，
            # 那在 Perform 脚本里，而脚本不在上游仓库（见 index._write_scenes）
            "cast": [self._text(table, k, lang, "speaker") for k in row.get("cast") or []],
            "lines": lines,
            "upstream": meta,
        }

    def _loose_row(self, row, table, lang, meta):
        """没进场景 / 任务 / 短信的条目。文本查询另记一类（loose），不混进 text 的未解析率。"""
        return {
            "id": row["key"],
            "head": row["head"],
            # non_story：按类别前缀排除的非剧情条目（Tips / UIText / Item…）；
            # unmatched：key 形态不是 <类别>_<场景>_<序号>（Comic_* / AutoEvent* / Message_* 残余…）；
            # unused：形态认得、但没进任何产物（只有名字没有台词的场景之类）
            "reason": row["reason"],
            "group": row["group"],
            "seq": row["seq"],
            "text": self._text(table, row["key"], lang, "loose"),
            "upstream": meta,
        }

    def _quest_row(self, row, table, lang, meta):
        return {
            "id": row["quest_id"],
            "name": self._text(table, row.get("name"), lang, "quest"),
            # 游戏里实际显示的标题。子任务的配置名指向父任务，与 name 不同才有值。
            "display_name": self._text(table, row.get("display_name"), lang, "quest"),
            "target": self._text(table, row.get("target"), lang, "quest"),
            "description": self._text(table, row.get("desc"), lang, "quest"),
            "finish": self._text(table, row.get("finish"), lang, "quest"),
            "prev_quests": row.get("prev_quests") or [],
            "next_quests": row.get("next_quests") or [],
            "upstream": meta,
        }

    def _message_row(self, row, table, lang, meta):
        nodes = []
        for node in row["nodes"]:
            msgs = [{
                "message_id": m["message_id"],
                "speaker": self._text(table, m.get("npc_name_key"), lang, "speaker"),
                "text": self._text(table, m["text_key"], lang, "text"),
            } for m in node["messages"]]
            opts = [{
                "text": self._text(table, o["text_key"], lang, "option"),
                "goto_step": o["goto_step"],
            } for o in node["options"]]
            self.per_lang[lang]["message_lines"] += len(msgs)
            nodes.append({"step": node["step"], "messages": msgs, "options": opts})
        return {
            "id": row["group_id"],
            "quests": row.get("quests") or [],
            "nodes": nodes,
            "upstream": meta,
        }

    def _term_row(self, key, table, lang, meta):
        """短名词表的一行：TextMap 的 key 就是出处（配上清单里的上游 commit 可以回查），
        不逐行带 upstream。本语种查不到写 null、计 `terms_missing`（缺译，基准语种一定有）。"""
        value = table.get(key)
        if value is None:
            self.per_lang[lang]["terms_missing"] += 1
        return {"id": key, "text": value}

    def _drop_unused_langs(self, outputs):
        """删掉不再产出的语种留下的旧文件。

        `--langs` 收窄之后，上一次跑出来的那些语种文件会留在语料目录里，看着像
        这次也产了——而且内容是**上一次**的。只清我们自己产的那批文件名，别乱删。
        """
        for what in outputs:
            for lang in textmap.ALL_LANGS:
                if lang in textmap.LANGS:
                    continue
                base = os.path.join(self.out_dir,
                                    "%s_%s.jsonl" % (what, lang.lower()))
                for path in (base, base + ".zst"):
                    if os.path.exists(path):
                        os.remove(path)
                        self.stats["stale_lang_files_removed"] += 1

    def run(self):
        idx = os.path.join(self.build, "index")
        tables = {lang: TextMap.load(self.upstream, lang) for lang in textmap.LANGS}
        self._base = tables.get(BASE_LANG)
        for lang in textmap.LANGS:
            self.per_lang[lang]["textmap_entries"] = len(tables[lang])
            self.per_lang[lang]["textmap_overwritten"] = tables[lang].overwritten

        meta = {"commit": self.snapshot.get("commit"),
                "version": self.snapshot.get("version")}

        outputs = {}
        terms = sorted(k for k, v in self._base.items() if is_term(v))
        for what, rows, builder in (
            ("scenes", _iter_jsonl(os.path.join(idx, "scenes.jsonl")), self._scene_row),
            ("quests", _iter_jsonl(os.path.join(idx, "quests.jsonl")), self._quest_row),
            ("messages", _iter_jsonl(os.path.join(idx, "messages.jsonl")), self._message_row),
            ("loose", _iter_jsonl(os.path.join(idx, "loose.jsonl")), self._loose_row),
            ("terms", terms, self._term_row),
        ):
            base = {lang: os.path.join(self.out_dir,
                                       "%s_%s.jsonl" % (what, lang.lower()))
                    for lang in textmap.LANGS}
            for path in base.values():
                # 上一次可能是另一种形态；留着的话 open_read 会读到旧结果
                jsonl.cleanup_stale(path, self.compress)
            paths = {lang: jsonl.out_path(base[lang], self.compress)
                     for lang in textmap.LANGS}
            handles = {lang: jsonl.open_write(base[lang], self.compress)
                       for lang in textmap.LANGS}
            ids = {lang: [] for lang in textmap.LANGS}
            checkers = {lang: CONTRACTS.checker(what) for lang in textmap.LANGS}
            try:
                for row in rows:
                    for lang in textmap.LANGS:
                        payload = builder(row, tables[lang], lang, meta)
                        self.per_lang[lang][what + "_rows"] += 1
                        ids[lang].append(payload["id"])
                        checkers[lang].check(payload)
                        handles[lang].write(
                            json.dumps(payload, ensure_ascii=False) + "\n")
            finally:
                for h in handles.values():
                    h.close()
            aligned = int(len({tuple(v) for v in ids.values()}) == 1)
            outputs[what] = {"paths": paths, "aligned": aligned}
            self.stats[what + "_aligned"] = aligned
            self.contract[what] = {lang: c.summary() for lang, c in checkers.items()}

        self._drop_unused_langs(outputs)
        self.stats["compress"] = self.compress
        self.stats["langs"] = list(textmap.LANGS)
        return {"outputs": outputs, "contract": self.contract, "stats": dict(self.stats),
                "per_lang": {k: dict(v) for k, v in self.per_lang.items()}}
