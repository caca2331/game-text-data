"""emit 阶段：一份中间层 × 各语种 TextMap，展开成逐语种 JSONL。

三份产物：`quests_*`（任务树，来自 assemble）、`reminders_*`（边玩边说的语音字幕链，
index 直接给出，没有要装配的）与 `terms_*`（短名词对照表，直接取自 TextMap，见 `is_term`）。
每份的各语种文件由**同一次遍历、同一个顺序**写出，
所以行数相同、逐行 id 相同是结构保证，不是靠事后校验（AGENTS.md 不变量 3）。
校验仍然做，但那是防呆。

文本查不到时写 `null` 而不是空字符串 —— 两者语义不同，且必须计数上报。

每一行写出前按内容契约（`contract.py`）检查，违反计入 report 的硬失败；同时攒下分布摘要，
供 `release` 与上次发布比较。
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

OUTPUTS = ("quests", "reminders", "terms")

TERM_MAX_CHARS = 16
"""短名词的"短"：基准语种（CHS）≤ 16 字。依据是 7.0.0 任务对话里去重后的说话人中文名
（1642 个）长度 P99 = 15；任务步骤 P50 = 10，约七成也在内。"""
TERM_REJECT = re.compile(r"[。！？!?；;…\r\n{}<>#$|\\]|test", re.IGNORECASE)
"""带句读 / 换行 / 占位与富文本标记（`{NICKNAME}`、`<color>`、`#`、`$UNRELEASED`）/ 测试串的不收：
那是句子或模板，不是名词。"""
TERM_NEED = re.compile(r"[぀-ヿ㐀-鿿]")


def is_term(chs) -> bool:
    """TextMap 的一条是不是"短名词"：只看基准语种（CHS）那份文本，所以各语种的行集合天然相同。

    上游没有"这条是人名 / 称号"的标记——画面上的人名可以只被一张无关的表引用（7.0.0 的「施拉姆」
    只出现在 DreamBookPhotoAvatar 里，任务 / 对话数据都不引用它），按引用它的表去筛会漏，
    所以这里只按形状收：短、有汉字或假名、不是句子或模板。用它的下游按自己的查询键去重、消歧。"""
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
        self._chs = None  # 基准语种，用于区分"缺译"与"上游无此文本"

    def _text(self, table: TextMap, text_hash, lang: str, kind: str = "meta"):
        """kind 区分统计口径：对话正文与元数据（标题、步骤描述等）的解析率
        差得很远，混在一个计数里会把对话的质量数字污染掉。"""
        if text_hash is None:
            return None
        if text_hash == 0:
            # 字段在但值为 0：黑屏、占位，本来就没有正文，不算未解析
            self.per_lang[lang][kind + "_zero"] += 1
            return None
        self.per_lang[lang][kind + "_lookups"] += 1
        value = table.get(text_hash)
        if value is None:
            self.per_lang[lang][kind + "_unresolved"] += 1
            # 区分两种缺失：CHS 查得到而本语种查不到 = 上游没做这条的本地化
            # （多为 $HIDDEN / test 之类从未翻译的内部字符串，我们无能为力）；
            # 四语种都查不到 = 上游根本没有这段文本。只有后者才值得报警。
            if self._chs is not None and self._chs.get(text_hash) is not None:
                self.per_lang[lang][kind + "_untranslated"] += 1
            else:
                self.per_lang[lang][kind + "_absent_upstream"] += 1
        return value

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

    def run(self) -> dict:
        tables = {lang: TextMap.load(self.upstream, lang) for lang in textmap.LANGS}
        self._chs = tables.get("CHS")
        for lang in textmap.LANGS:
            self.per_lang[lang]["textmap_entries"] = len(tables[lang])

        meta = {
            "commit": self.snapshot.get("commit"),
            "version": self.snapshot.get("version"),
        }
        paths = {}
        paths["quests"] = self._write(
            "quests", _iter_jsonl(os.path.join(self.build, "assembled.jsonl")),
            lambda q, table, lang: self._quest_row(q, table, lang, meta), tables)
        paths["reminders"] = self._write(
            "reminders", _iter_jsonl(os.path.join(self.build, "index", "reminders.jsonl")),
            lambda r, table, lang: self._reminder_row(r, table, lang, meta), tables)
        paths["terms"] = self._write(
            "terms", (h for h, v in self._chs.items() if is_term(v)), self._term_row, tables)
        self._drop_unused_langs(OUTPUTS)
        self.stats["compress"] = self.compress
        self.stats["langs"] = list(textmap.LANGS)
        return {
            "paths": paths,
            "contract": self.contract,
            "stats": dict(self.stats),
            "per_lang": {k: dict(v) for k, v in self.per_lang.items()},
        }

    def _write(self, kind, items, make_row, tables) -> dict:
        """一份产物的各语种文件：同一次遍历写出，顺带比逐行 id。"""
        base = {lang: os.path.join(self.out_dir, "%s_%s.jsonl" % (kind, lang.lower()))
                for lang in textmap.LANGS}
        for path in base.values():
            # 上一次可能是另一种形态；留着的话 open_read 会读到旧结果
            jsonl.cleanup_stale(path, self.compress)
        handles = {lang: jsonl.open_write(base[lang], self.compress)
                   for lang in textmap.LANGS}
        ids_per_lang = {lang: [] for lang in textmap.LANGS}
        checkers = {lang: CONTRACTS.checker(kind) for lang in textmap.LANGS}
        try:
            for item in items:
                self.stats[kind] += 1
                for lang in textmap.LANGS:
                    row = make_row(item, tables[lang], lang)
                    ids_per_lang[lang].append(row["id"])
                    checkers[lang].check(row)
                    handles[lang].write(json.dumps(row, ensure_ascii=False) + "\n")
        finally:
            for h in handles.values():
                h.close()
        self.stats[kind + "_aligned"] = int(len({tuple(v) for v in ids_per_lang.values()}) == 1)
        self.contract[kind] = {lang: c.summary() for lang, c in checkers.items()}
        return {lang: jsonl.out_path(base[lang], self.compress) for lang in textmap.LANGS}

    def _quest_row(self, quest, table, lang, meta):
        row = {
            "id": quest["id"],
            "name": self._text_fallback(
                table, quest["title_hash"], quest.get("title_hash_alt"), lang, "title"),
            "description": self._text_fallback(
                table, quest["desc_hash"], quest.get("desc_hash_alt"), lang, "desc"),
            "chapter_id": quest["chapter_id"],
            "chapter_title": self._text(table, quest["chapter_title_hash"], lang),
            "chapter_num": self._text(table, quest["chapter_num_hash"], lang),
            "series": quest["series"],
            "tag": quest["tag"],
            "steps": [
                {
                    "sub_id": s["sub_id"],
                    "order": s["order"],
                    "desc": self._text(table, s["desc_hash"], lang, "step"),
                    "fail_cond": s["fail_cond"],
                }
                for s in quest["steps"]
            ],
            "dialog": [
                {
                    "talk_id": d["talk_id"],
                    "attribution": d.get("attribution", "explicit"),
                    "dialog_id": d["dialog_id"],
                    "role": d["role"],
                    "speaker": self._speaker(table, d, lang),
                    "text": self._text(table, d["content_hash"], lang, "dialog"),
                    "next": d["next"],
                    "source": d["source"],
                    # 任务对话有没有配音，上游在 BinOutput/Voice（sparse 快照没取），一律 unknown
                    "voice": "unknown",
                }
                for d in quest["dialog"]
            ],
            "upstream": meta,
        }
        self.per_lang[lang]["rows"] += 1
        self.per_lang[lang]["dialog_nodes"] += len(row["dialog"])
        if not row["dialog"]:
            self.per_lang[lang]["quests_without_dialog"] += 1
        return row

    def _reminder_row(self, chain, table, lang, meta):
        """一条语音字幕链。说话人查不到**不算**未解析（系统提示本来就没有说话人），
        单独计 `reminder_speaker_*`，不进 report 的阈值。"""
        lines = []
        for ln in chain["lines"]:
            lines.append({
                "reminder_id": ln["reminder_id"],
                "speaker": (table.get(ln["speaker_hash"]) or None) if ln["speaker_hash"] else None,
                "text": self._text(table, ln["content_hash"], lang, "reminder"),
                "style": ln["style"],
                "show_time": ln["show_time"],
                "delay": ln["delay"],
                "voice": ln["voice"],
            })
            if lines[-1]["speaker"]:
                self.per_lang[lang]["reminder_speaker_resolved"] += 1
        self.per_lang[lang]["reminders_rows"] += 1
        self.per_lang[lang]["reminder_lines"] += len(lines)
        row = {"id": chain["id"], "lines": lines, "upstream": meta}
        if chain.get("cyclic"):
            row["cyclic"] = True    # 上游 next 互指成环、没有链头，从最小 id 起走的一圈
        return row

    def _term_row(self, text_hash, table, lang):
        """短名词表的一行：TextMap 的 hash 就是出处（配上清单里的上游 commit 可以回查），
        不逐行带 upstream。本语种查不到写 null、计 `terms_missing`（缺译，基准语种一定有）。"""
        value = table.get(text_hash)
        self.per_lang[lang]["terms_rows"] += 1
        if value is None:
            self.per_lang[lang]["terms_missing"] += 1
        return {"id": text_hash, "text": value}

    def _text_fallback(self, table, primary, alt, lang, kind):
        """Excel 的 hash 优先，查不到就用 BinOutput 那份。

        两处存的是同一段文本的不同 hash，Excel 那份有约 3% 标题、16% 描述在
        TextMap 里查不到，BinOutput 那份能补上，反之亦然。回落次数计入报告。
        """
        value = self._text(table, primary, lang, kind)
        if value is not None or not alt:
            return value
        value = self._text(table, alt, lang, kind + "_alt")
        if value is not None:
            self.per_lang[lang][kind + "_from_fallback"] += 1
        return value

    def _speaker(self, table, node, lang):
        """说话人显示名。index 阶段把人名/头衔一并收在 other_hashes 里，
        这里取第一个能解出文本的。"""
        for h in (node.get("other_hashes") or {}).values():
            value = table.get(h) if h else None
            if value:
                return value
        return None
