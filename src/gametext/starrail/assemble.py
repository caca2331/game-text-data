"""assemble 阶段：把 index 的中间层装配成任务树 / 闲聊脚本 / 短信图。

**刻意不解引用文本**，产物里存的仍是 TextMap hash。这样 emit 就是纯粹的
"一份结构 × 多张 TextMap"，多语种同源同序成了结构保证而不是约定
（AGENTS.md 不变量 2）。

四份产物：
    assembled.jsonl            任务树
    assembled_dialogues.jsonl  任务之外的对话脚本
    assembled_messages.jsonl   短信图
    assembled_sentences.jsonl  **全量台词表**：每句一行，带"被哪些脚本引用"
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

from .index import _event_sentences


def _iter_jsonl(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


class Assembler:
    def __init__(self, upstream: str, build: str):
        self.upstream = upstream
        self.build = build
        self.stats = Counter()
        self.sentences = {}

    # ---- 事件流 -----------------------------------------------------------

    def _sentence(self, sid):
        """台词 id -> hash 三件套；引用了台词表里没有的 id 就返回 None 并计数。"""
        if not isinstance(sid, int):
            return None
        s = self.sentences.get(sid)
        if s is None:
            self.stats["sentence_missing"] += 1
            return None
        return s

    def _events(self, events):
        """展开一串事件，保持顺序。控制事件也要留——分支图的边在它们身上。"""
        out = []
        for e in events:
            kind = e["kind"]
            if kind in ("talk", "option"):
                s = self._sentence(e.get("sentence_id"))
                if s is None:
                    continue
                row = {
                    "kind": kind,
                    "sentence_id": e["sentence_id"],
                    "text_hash": s["text_hash"],
                    "name_hash": s["name_hash"],
                    "voice_id": s["voice_id"],
                    "voice": s["voice"],
                    "carrier": e.get("carrier"),
                }
                if kind == "option":
                    row["trigger"] = e.get("trigger")
                    # 选中该选项后播的那句。第一版没有这个字段，导致选项对话
                    # 只有玩家的问、没有 NPC 的答。
                    #
                    # 但**多数选项的 trigger 指向的就是它自己那句**
                    # （TalkSentence_<自身 id>，只是"把这句念出来"的信号），
                    # 那种不是回答，记成 reply 会凭空复制一遍台词。
                    rid = e.get("reply_sentence_id")
                    if rid == e.get("sentence_id"):
                        self.stats["option_trigger_is_self"] += 1
                        rid = None
                    reply = self._sentence(rid)
                    if reply is not None:
                        row["reply"] = {
                            "sentence_id": rid,
                            "text_hash": reply["text_hash"],
                            "name_hash": reply["name_hash"],
                            "voice_id": reply["voice_id"],
                            "voice": reply["voice"],
                        }
                        self.stats["option_with_reply"] += 1
                out.append(row)
                self.stats["dialog_" + kind] += 1
            else:
                row = {"kind": kind, "custom_string": e["custom_string"]}
                s = self._sentence(e.get("sentence_id"))
                if s is not None:
                    # 自定义字符串本身就是一句台词（TalkSentence_<id>）
                    row["sentence_id"] = e["sentence_id"]
                    row["text_hash"] = s["text_hash"]
                    row["name_hash"] = s["name_hash"]
                    row["voice_id"] = s["voice_id"]
                    row["voice"] = s["voice"]
                    self.stats["control_events_with_text"] += 1
                out.append(row)
                self.stats["control_events"] += 1
        return out

    @staticmethod
    def _has_dialogue(events):
        return any(e["kind"] in ("talk", "option") or "text_hash" in e
                   for e in events)

    # ---- 三份产物 ---------------------------------------------------------

    def run(self) -> dict:
        idx = os.path.join(self.build, "index")
        self.sentences = {s["id"]: s for s in _iter_jsonl(
            os.path.join(idx, "sentences.jsonl"))}
        self.stats["sentences"] = len(self.sentences)

        paths = {
            "missions": self._missions(idx),
            "dialogues": self._dialogues(idx),
            "messages": self._messages(idx),
            "sentences": self._sentences(idx),
        }
        return paths

    def _sentences(self, idx):
        """台词表原样全量输出，每句带引用它的脚本（`sources`，可以为空）。

        为什么要这张表：任务 / 任务外对话两份产物只收**被脚本 JSON 引用到的**台词。
        剩下的三成多（4.5.0 实测 113 740 句里去掉本次补回的未归属脚本，仍有 7.8 万句）
        在整个上游仓库里都找不到引用——主体是过场演出：脚本里一个 `PlayTimeline`
        指向 `.playable` 时间轴，时间轴里念的台词只在 `VoiceConfig` 里出现过，而时间轴
        文件不在上游仓库。它们在屏幕上是有的（下游拿直播录像对台词时就缺这一块），
        而 id 和同一脚本里被引用的台词**连号**（`DS105430507` 的 153050701–703 在时间轴里，
        704–706 是它后面的选项）。

        这里**不做**"按 id 连号归到哪个脚本"的推断——那是猜测，交给下游；
        只保证一句不漏、并把已知的引用关系原样附上。"""
        sources = defaultdict(set)
        for m in _iter_jsonl(os.path.join(idx, "missions.jsonl")):
            for sc in m.get("scripts") or []:
                for sid in _event_sentences(sc["events"]):
                    sources[sid].add(sc["source"])
        for d in _iter_jsonl(os.path.join(idx, "dialogues.jsonl")):
            for sid in _event_sentences(d["events"]):
                sources[sid].add(d["source"])
        out_path = os.path.join(self.build, "assembled_sentences.jsonl")
        with open(out_path, "w", encoding="utf-8") as out:
            for sid in sorted(self.sentences):
                s = self.sentences[sid]
                src = sorted(sources.get(sid, ()))
                self.stats["sentence_rows"] += 1
                self.stats["sentence_rows_unreferenced"] += not src
                self.stats["sentence_sources_max"] = max(
                    self.stats["sentence_sources_max"], len(src))
                out.write(json.dumps({
                    "id": sid, "text_hash": s["text_hash"], "name_hash": s["name_hash"],
                    "voice_id": s["voice_id"], "voice": s["voice"], "sources": src,
                }, ensure_ascii=False) + "\n")
        return out_path

    def _missions(self, idx):
        out_path = os.path.join(self.build, "assembled.jsonl")
        with open(out_path, "w", encoding="utf-8") as out:
            for m in _iter_jsonl(os.path.join(idx, "missions.jsonl")):
                # 保留"按脚本分组的有序事件流"这个结构：顺序即剧情顺序，
                # option/trigger/wait 一起构成分支图，拍平就没了
                scripts = []
                for sc in m.get("scripts") or []:
                    events = self._events(sc["events"])
                    if self._has_dialogue(events):
                        scripts.append({"source": sc["source"], "events": events})
                self.stats["missions"] += 1
                self.stats["scripts"] += len(scripts)
                self.stats["dialog_nodes"] += sum(
                    1 for sc in scripts for e in sc["events"]
                    if e["kind"] in ("talk", "option"))
                if not scripts:
                    self.stats["missions_without_dialogue"] += 1
                self.stats["sub_missions"] += len(m["sub_missions"])
                out.write(json.dumps({
                    "id": m["main_mission_id"],
                    "type": m["type"],
                    "sub_type": m.get("sub_type"),
                    "chapter_id": m.get("chapter_id"),
                    "world_id": m.get("world_id"),
                    "name_hash": m["name_hash"],
                    "next": m["next"],
                    "steps": m["sub_missions"],
                    "scripts": scripts,
                }, ensure_ascii=False) + "\n")
        return out_path

    def _dialogues(self, idx):
        out_path = os.path.join(self.build, "assembled_dialogues.jsonl")
        with open(out_path, "w", encoding="utf-8") as out:
            for d in _iter_jsonl(os.path.join(idx, "dialogues.jsonl")):
                events = self._events(d["events"])
                if not self._has_dialogue(events):
                    self.stats["dialogues_empty_after_assemble"] += 1
                    continue
                self.stats["dialogues"] += 1
                self.stats["dialogue_nodes"] += len(events)
                out.write(json.dumps({
                    "id": d["source"],
                    "bucket": d["bucket"],
                    # 归属线索：区域名（由 FloorID 查得）与交互标题（由 ActPath 查得）
                    "floor_id": d.get("floor_id"),
                    "plane_name_hash": d.get("plane_name_hash"),
                    "interact_title": d.get("interact_title"),
                    "group_id": d.get("group_id"),
                    "events": events,
                }, ensure_ascii=False) + "\n")
        return out_path

    def _messages(self, idx):
        out_path = os.path.join(self.build, "assembled_messages.jsonl")
        with open(out_path, "w", encoding="utf-8") as out:
            for g in _iter_jsonl(os.path.join(idx, "messages.jsonl")):
                self.stats["message_groups"] += 1
                self.stats["message_lines"] += sum(
                    len(s["items"]) for s in g["sections"])
                out.write(json.dumps(g, ensure_ascii=False) + "\n")
        return out_path
