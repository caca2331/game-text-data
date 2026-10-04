"""emit 阶段：一份任务树 × 多张 TextMap，展开成多语种 JSONL。

各语种文件由**同一次遍历、同一个顺序**写出，所以行数相同、逐行 id 相同是结构
保证，不是靠事后校验（AGENTS.md 不变量 2）。校验仍然做，但那是防呆。

文本查不到时写 `null` 而不是空字符串 —— 两者语义不同，且必须计数上报。
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

# 基准语种：用来区分"上游没做本地化"与"上游根本没这段文本"。
# 这两者混在一起会让非中文语种的未解析率虚高，看着像流水线坏了
# （genshin 踩过，EN 的标题未解析率一度显示 40%）。
BASE_LANG = "CHS"

# 上游文本里的动态占位符，形如 {TEXTJOIN#87}
_TEXTJOIN = re.compile(r"\{TEXTJOIN#(\d+)\}")

# 五份产物（报告逐份校验多语种对齐）
OUTPUTS = ("missions", "dialogues", "messages", "sentences", "terms")

TERM_MAX_CHARS = 16
"""短名词的"短"：基准语种（CHS）≤ 16 字。和 genshin 同一个口径（那边的依据是去重后的
说话人中文名长度 P99 = 15）；本项目 4.5.0 的说话人中文名 P99 见 docs/starrail/manual.md 的"短名词"一节。"""
TERM_REJECT = re.compile(r"[。！？!?；;…\r\n{}<>#$|\\]|test", re.IGNORECASE)
"""带句读 / 换行 / 占位与富文本标记（`{TEXTJOIN#87}`、`{NICKNAME}`、`<color>`）/ 测试串的不收：
那是句子或模板，不是名词。"""
TERM_NEED = re.compile(r"[぀-ヿ㐀-鿿]")


def is_term(chs) -> bool:
    """TextMap 的一条是不是"短名词"：只看基准语种（CHS）那份文本，所以各语种的行集合天然相同。
    上游没有"这条是人名 / 称号"的标记，按引用它的表去筛会漏，所以只按形状收：短、有汉字或假名、
    不是句子或模板。用它的下游按自己的查询键去重、消歧。"""
    return bool(chs) and len(chs) <= TERM_MAX_CHARS and bool(TERM_NEED.search(chs)) \
        and not TERM_REJECT.search(chs)


def _iter_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


class Emitter:
    def __init__(self, upstream: str, build: str, out_dir: str, snapshot: dict,
                 compress: str = "zstd"):
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
        self._textjoin = {}

    def _text(self, table: TextMap, text_hash, lang: str, kind: str):
        if text_hash is None:
            self.per_lang[lang][kind + "_no_hash"] += 1
            return None
        self.per_lang[lang][kind + "_lookups"] += 1
        value = table.get(text_hash)
        if value is None:
            self.per_lang[lang][kind + "_unresolved"] += 1
            if self._base is not None and self._base.get(text_hash) is not None:
                self.per_lang[lang][kind + "_untranslated"] += 1
            else:
                self.per_lang[lang][kind + "_absent_upstream"] += 1
        return value

    def _label(self, table, text_hash, lang, kind):
        """取一段**标签**文本，并把 `{TEXTJOIN#n}` 换成它的默认取值。

        只对标签这么做，**对话正文一律保持原样**——占位符本身是信息（玩家的选择），
        要不要替换是下游的事。但地点名里留着 `{TEXTJOIN#87}` 就没法当归属维度用了。
        """
        value = self._text(table, text_hash, lang, kind)
        if not value or "{TEXTJOIN#" not in value:
            return value

        def sub(m):
            h = self._textjoin.get(m.group(1))
            if h is None:
                self.per_lang[lang][kind + "_textjoin_unknown"] += 1
                return m.group(0)
            return table.get(h) or m.group(0)

        return _TEXTJOIN.sub(sub, value)

    def _event(self, table, e, lang):
        """展开一个事件。控制事件（trigger/wait）也保留，它们是分支图的边。

        控制事件的 custom_string 可能本身就是一句台词（`TalkSentence_<id>`），
        那样它也带 text_hash，要一起展开——不然选项对话只剩问、没有答。
        """
        if e["kind"] not in ("talk", "option"):
            out = {"kind": e["kind"], "custom_string": e["custom_string"]}
            if "text_hash" in e:
                out["sentence_id"] = e["sentence_id"]
                out["speaker"] = self._text(table, e["name_hash"], lang, "speaker")
                out["text"] = self._text(table, e["text_hash"], lang, "text")
                out["voice_id"] = e.get("voice_id")
                out["voice"] = e.get("voice", "unknown")
            return out
        out = {
            "kind": e["kind"],
            "sentence_id": e["sentence_id"],
            "speaker": self._text(table, e["name_hash"], lang, "speaker"),
            "text": self._text(table, e["text_hash"], lang, "text"),
            "voice_id": e["voice_id"],
            "voice": e["voice"],
            "carrier": e.get("carrier"),
        }
        if e["kind"] == "option":
            out["trigger"] = e.get("trigger")
            r = e.get("reply")
            out["reply"] = {
                "sentence_id": r["sentence_id"],
                "speaker": self._text(table, r["name_hash"], lang, "speaker"),
                "text": self._text(table, r["text_hash"], lang, "text"),
                "voice_id": r.get("voice_id"),
                "voice": r.get("voice", "unknown"),
            } if r else None
        return out

    def _mission_row(self, m, table, lang, meta):
        scripts = [
            {"source": sc["source"],
             "events": [self._event(table, e, lang) for e in sc["events"]]}
            for sc in m["scripts"]
        ]
        nodes = sum(1 for sc in scripts for e in sc["events"]
                    if e["kind"] in ("talk", "option"))
        self.per_lang[lang]["scripts"] += len(scripts)
        self.per_lang[lang]["dialog_nodes"] += nodes
        if not nodes:
            self.per_lang[lang]["missions_without_dialogue"] += 1
        return {
            "id": m["id"],
            "name": self._text(table, m["name_hash"], lang, "name"),
            "type": m["type"],
            "sub_type": m.get("sub_type"),
            "chapter_id": m.get("chapter_id"),
            "world_id": m.get("world_id"),
            "next": m["next"],
            "steps": [
                {
                    "sub_id": s["sub_id"],
                    "target": self._text(table, s["target_hash"], lang, "step"),
                    "desc": self._text(table, s["desc_hash"], lang, "step"),
                }
                for s in m["steps"]
            ],
            # 按脚本分组的**有序**事件流。顺序即剧情顺序；option 是分支选项，
            # 其 trigger 与后续 wait 事件的 custom_string 配对，构成分支图
            # （见 script.py）。
            "scripts": scripts,
            "upstream": meta,
        }

    def _dialogue_row(self, d, table, lang, meta):
        return {
            "id": d["id"],
            "bucket": d["bucket"],
            # 这批对话没有任务归属，能给的是"在哪儿"和"点的是谁/什么"
            "location": self._label(table, d.get("plane_name_hash"), lang, "location"),
            "floor_id": d.get("floor_id"),
            "interact_title": d.get("interact_title"),
            "group_id": d.get("group_id"),
            "events": [self._event(table, e, lang) for e in d["events"]],
            "upstream": meta,
        }

    def _message_row(self, g, table, lang, meta):
        sections = []
        for sec in g["sections"]:
            items = [{
                "id": it["id"],
                "sender": it["sender"],
                "item_type": it["item_type"],
                "text": self._text(table, it["text_hash"], lang, "message"),
                # 选项在消息列表里显示为按钮文字，正文另有一份
                "option_text": self._text(table, it["option_text_hash"],
                                          lang, "option"),
                "next": it["next"],
                # 短信没有配音这回事可查（上游不给短信挂语音），一律 unknown
                "voice": "unknown",
            } for it in sec["items"]]
            self.per_lang[lang]["message_lines"] += len(items)
            sections.append({"section_id": sec["section_id"],
                             "start": sec["start"], "items": items})
        return {
            "id": g["group_id"],
            "contact_id": g["contact_id"],
            "contact": self._text(table, g["contact_name_hash"], lang, "speaker"),
            "signature": self._text(table, g["signature_hash"], lang, "message"),
            "sections": sections,
            "upstream": meta,
        }

    def _sentence_row(self, s, table, lang, meta):
        """全量台词表的一行。文本查询另记一类（sentence），不混进 text 的未解析率——
        这张表包含从未被脚本引用的台词，基线和任务对话不同。"""
        return {
            "id": s["id"],
            "speaker": self._text(table, s["name_hash"], lang, "sentence_speaker"),
            "text": self._text(table, s["text_hash"], lang, "sentence"),
            "voice_id": s["voice_id"],
            "voice": s["voice"],
            # 引用这句的脚本（missions / dialogues 里的 source）。空 = 整个上游仓库里
            # 没有脚本 JSON 引用它，多为过场时间轴里的台词
            "sources": s["sources"],
            "upstream": meta,
        }

    def _term_row(self, text_hash, table, lang, meta):
        """短名词表的一行：TextMap 的 hash 就是出处（配上清单里的上游 commit 可以回查），
        不逐行带 upstream。本语种查不到写 null、计 `terms_missing`（缺译，基准语种一定有）。"""
        value = table.get(text_hash)
        if value is None:
            self.per_lang[lang]["terms_missing"] += 1
        return {"id": text_hash, "text": value}

    def _drop_unused_langs(self, kinds):
        """删掉不再产出的语种留下的旧文件。

        `--langs` 收窄之后，上一次跑出来的那些语种文件会留在语料目录里，看着像
        这次也产了——而且内容是**上一次**的。只清我们自己产的那批文件名，别乱删。
        """
        for kind in kinds:
            for lang in textmap.ALL_LANGS:
                if lang in textmap.LANGS:
                    continue
                base = os.path.join(self.out_dir,
                                    "%s_%s.jsonl" % (kind, lang.lower()))
                for path in (base, base + ".zst"):
                    if os.path.exists(path):
                        os.remove(path)
                        self.stats["stale_lang_files_removed"] += 1

    def _emit_set(self, name, rows, builder, tables, meta):
        """一份结构 × 多语种。各语种同一次遍历写出，行数与逐行 id 相同是结构保证。
        `rows` 是结构那一份的逐行（build/ 下的中间层，或 TextMap 挑出的 hash）。"""
        base = {lang: os.path.join(self.out_dir,
                                   "%s_%s.jsonl" % (name, lang.lower()))
                for lang in textmap.LANGS}
        for p in base.values():
            # 上一次可能是另一种形态；留着的话 open_read 会读到旧结果
            jsonl.cleanup_stale(p, self.compress)
        paths = {lang: jsonl.out_path(base[lang], self.compress)
                 for lang in textmap.LANGS}
        handles = {lang: jsonl.open_write(base[lang], self.compress)
                   for lang in textmap.LANGS}
        ids = {lang: [] for lang in textmap.LANGS}
        checkers = {lang: CONTRACTS.checker(name) for lang in textmap.LANGS}
        try:
            for row in rows:
                for lang in textmap.LANGS:
                    payload = builder(row, tables[lang], lang, meta)
                    self.per_lang[lang][name + "_rows"] += 1
                    ids[lang].append(payload["id"])
                    checkers[lang].check(payload)
                    handles[lang].write(json.dumps(payload, ensure_ascii=False) + "\n")
        finally:
            for h in handles.values():
                h.close()
        aligned = int(len({tuple(v) for v in ids.values()}) == 1)
        self.stats[name + "_aligned"] = aligned
        self.contract[name] = {lang: c.summary() for lang, c in checkers.items()}
        return paths

    def run(self) -> dict:
        path = os.path.join(self.build, "index", "textjoin.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self._textjoin = json.load(f)
        tables = {lang: TextMap.load(self.upstream, lang) for lang in textmap.LANGS}
        self._base = tables.get(BASE_LANG)
        for lang in textmap.LANGS:
            self.per_lang[lang]["textmap_entries"] = len(tables[lang])
            self.per_lang[lang]["textmap_shard_overlap"] = tables[lang].collisions

        meta = {"commit": self.snapshot.get("commit"),
                "version": self.snapshot.get("version")}

        paths = {}
        for name, src, builder in (
            ("missions", "assembled.jsonl", self._mission_row),
            ("dialogues", "assembled_dialogues.jsonl", self._dialogue_row),
            ("messages", "assembled_messages.jsonl", self._message_row),
            ("sentences", "assembled_sentences.jsonl", self._sentence_row),
        ):
            paths[name] = self._emit_set(
                name, _iter_jsonl(os.path.join(self.build, src)), builder, tables, meta)
        paths["terms"] = self._emit_set(
            "terms", (h for h, v in self._base.items() if is_term(v)), self._term_row, tables, meta)

        # 对话事件计数（各语种相同，取基准语种统计即可）
        for lang in textmap.LANGS:
            self.per_lang[lang]["rows"] = self.per_lang[lang]["missions_rows"]
        self.stats["aligned"] = int(all(
            self.stats.get(n + "_aligned") for n in OUTPUTS))
        self._drop_unused_langs(paths)
        self.stats["compress"] = self.compress
        self.stats["langs"] = list(textmap.LANGS)
        return {
            "paths": paths,
            "contract": self.contract,
            "stats": dict(self.stats),
            "per_lang": {k: dict(v) for k, v in self.per_lang.items()},
        }
