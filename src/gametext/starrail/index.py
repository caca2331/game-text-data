"""index 阶段：把上游快照归一成中间层，文本仍留 hash。

产物（build/index/ 下）：
    sentences.jsonl  台词表：TalkSentenceID -> 台词/说话人 hash
    missions.jsonl   主任务 + 其引用到的 TalkSentenceID（按目录归属）
    dialogues.jsonl  **不属于任务**的对话脚本（NPC 闲聊、物件、模拟宇宙…），按来源分桶
    messages.jsonl   短信系统：联系人 -> 分节 -> 消息图（自带分支）
    unparsed.jsonl   所有解析失败的记录

崩铁的数据是明文的，所以这里没有 genshin 那套结构推断 —— 直接按字段名取。
但**归属**要小心：三个引用源都以 MainMissionID 作目录名（见 docs/starrail/data-source.md），
按目录走，不要用编号前缀（试过，只覆盖 9.21%）。

**任务之外还有一大批对话。** 第一版只扫三个任务目录，台词覆盖率 51.2%。把
`Config/Level` 与 `Story` 下其余目录也扫进来（不写死是哪几个，除任务目录外全收），
覆盖率到 67.4%。剩下的 32.6% 见 docs/starrail/data-source.md 的定性结论。

**唯一读文本的地方是配音标记**（`_voice_states`）：判"泛用语音"要比共用同一段语音的台词像不像，
只比 hash 不够（同一句带不带 `<color=…>` 是两个 hash）。读的是基准语种一张表，产物里仍然只留 hash。
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

import orjson

from . import script, textmap

# 对话脚本的三个来源，都以 MainMissionID 作为目录名。
# 路径 -> 从相对路径里取第几段作为任务 id。
DIALOGUE_ROOTS = [
    ("Config/Level/Mission", 0),
    ("Story/Mission", 0),
    ("Story/Discussion/Mission", 0),
]

# 任务之外的对话来源：这两棵树下除去上面三个目录的**全部**内容。
# 刻意不列白名单——列了就会在上游新增目录时静默漏掉（第一版就是这么漏的）。
OTHER_ROOTS = ["Config/Level", "Story"]

# 任务外对话的两条归属线索，都能查证：
#   路径里的 F<FloorID>（`.../MunicipalChatConfig/F10001001/...`）-> MazePlane 的区域名
#   DialogueNPC / DialogueProp 的 ActPath 直指脚本文件 -> InteractTitle（交互标题）
FLOOR_IN_PATH = re.compile(r"/F(\d+)/")
PLANE_TABLE = "MazePlane.json"
# 上游文本里的动态占位符 {TEXTJOIN#87}：TextJoinConfig 给出候选项，DefaultItem 是默认值
TEXTJOIN_TABLES = ("TextJoinConfig.json", "TextJoinItem.json")
ACTPATH_TABLES = ("DialogueNPC.json", "DialogueProp.json")

# 短信系统的四张表。全明文，不需要推断。
MESSAGE_TABLES = {
    "items": "MessageItemConfig.json",
    "sections": "MessageSectionConfig.json",
    "groups": "MessageGroupConfig.json",
    "contacts": "MessageContactsConfig.json",
}


def _load(path):
    with open(path, "rb") as f:
        return orjson.loads(f.read())


def _hash(row, field):
    return (row.get(field) or {}).get("Hash")


class Indexer:
    def __init__(self, upstream: str, build: str):
        self.upstream = upstream
        self.build = build
        self.out_dir = os.path.join(build, "index")
        os.makedirs(self.out_dir, exist_ok=True)
        self.failures = []
        self.stats = Counter()
        self.referenced = set()
        # 归到了某个主任务的脚本目录。index_dialogues 只跳过**这些**，其余一律按任务外
        # 对话输出（见那边的说明）
        self.mission_dirs = set()

    def fail(self, source, stage, reason, detail=None):
        self.failures.append({"source": source, "stage": stage,
                              "reason": reason, "detail": detail or {}})

    # -------------------------------------------------------- 台词表

    def _voice_tables(self):
        """`VoiceConfig`（语音 id -> 类型 / 资源路径）与 `TalkSentenceMultiVoice`（一句多段语音）。"""
        cfg = {r["VoiceID"]: r for r in _load(os.path.join(self.upstream, "ExcelOutput", "VoiceConfig.json"))
               if r.get("VoiceID") is not None}
        multi = {r["TalkSentenceID"]: list(r.get("VoiceIDList") or [])
                 for r in _load(os.path.join(self.upstream, "ExcelOutput", "TalkSentenceMultiVoice.json"))
                 if r.get("TalkSentenceID") is not None}
        return cfg, multi

    GENERIC_VOICE_SIM = 0.6
    """共用同一段语音的两句台词，归一化后相似度低于这个就算"不同的台词"（docs/starrail/manual.md「配音标记」）。"""

    def _voice_states(self, entries, cfg, multi) -> dict:
        """每句台词的配音标记，四态（见 docs/starrail/manual.md「配音标记」）：

        * 没有任何语音 id → `unvoiced`（上游只给真录了音的台词挂 `VoiceID`，docs/starrail/data-source.md）；
        * 语音 id 在 `VoiceConfig` 里一个都查不到 → `unknown`（不猜）；
        * 查到了、但没有一段是有效语音（类型 `NoVoice` / 路径为空）→ `unvoiced`；
        * 有效语音**全是泛用语音** → `generic`：同一段资源路径被 ≥2 句**不同的**台词共用
          （几段通用短语配给大量写着不同台词的对话框——支线、广播、生物叫声）；
        * 否则 → `voiced`。

        `entries` = [(sid, row)]；返回 {sid: 状态}，并把 `generic_voice_clips` 记进 stats。"""
        from difflib import SequenceMatcher
        chs = textmap.TextMap.load(self.upstream, textmap.BASE_LANG)

        def norm(t):
            return re.sub(r"[\W_]+", "", re.sub(r"<[^>]*>|\{[^}]*\}", "", t or ""))

        ids_of, clips_of = {}, {}
        clip_texts = defaultdict(set)
        for sid, row in entries:
            vids = ([row["VoiceID"]] if row.get("VoiceID") is not None else []) + multi.get(sid, [])
            ids_of[sid] = vids
            clips = [cfg[v]["VoicePath"] for v in vids
                     if v in cfg and cfg[v].get("VoicePath") and cfg[v].get("VoiceType") != "NoVoice"]
            clips_of[sid] = clips
            t = norm(chs.get((row.get("TalkSentenceText") or {}).get("Hash")))
            for c in clips:
                if t:
                    clip_texts[c].add(t)

        def differs(texts):
            # 只和组里第一句比（线性，不做两两比）：和第一句都像，就是同一句话的标记变体。
            # 4.5.0 上共用最多的资源也只有 43 句，整个配音标记耗时约 3 秒（cProfile），index 的大头是 8 万个脚本文件的读盘
            first, *rest = sorted(texts)
            return any(SequenceMatcher(None, first, t, autojunk=False).ratio() < self.GENERIC_VOICE_SIM
                       for t in rest)
        generic = {c for c, ts in clip_texts.items() if len(ts) >= 2 and differs(ts)}
        self.stats["generic_voice_clips"] = len(generic)

        out = {}
        for sid, _ in entries:
            vids, clips = ids_of[sid], clips_of[sid]
            if not vids:
                out[sid] = "unvoiced"
            elif not any(v in cfg for v in vids):
                out[sid] = "unknown"
            elif not clips:
                out[sid] = "unvoiced"
            elif all(c in generic for c in clips):
                out[sid] = "generic"
            else:
                out[sid] = "voiced"
        return out

    def index_sentences(self) -> set:
        path = os.path.join(self.upstream, "ExcelOutput",
                            "TalkSentenceConfig.json")
        rows = _load(path)
        ids = set()
        entries = []
        for row in rows:
            sid = row.get("TalkSentenceID")
            if sid is None:
                if not row:
                    # 上游表里混着空对象 {}，是数据本身的杂质，不是解析失败
                    self.stats["sentence_empty_row"] += 1
                else:
                    self.fail("TalkSentenceConfig.json", "sentence",
                              "条目缺 TalkSentenceID", {"keys": sorted(row)})
                continue
            if sid in ids:
                self.stats["sentence_duplicate"] += 1
                continue
            ids.add(sid)
            entries.append((sid, row))
        voice = self._voice_states(entries, *self._voice_tables())
        out_path = os.path.join(self.out_dir, "sentences.jsonl")
        with open(out_path, "w", encoding="utf-8") as f:
            for sid, row in entries:
                # hash 包在 {"Hash": ...} 里，不是裸整数
                text = (row.get("TalkSentenceText") or {}).get("Hash")
                name = (row.get("TextmapTalkSentenceName") or {}).get("Hash")
                if text is None:
                    self.stats["sentence_no_text_hash"] += 1
                if name is None:
                    self.stats["sentence_no_name_hash"] += 1
                self.stats["sentence_voice_" + voice[sid]] += 1
                f.write(json.dumps({
                    "id": sid,
                    "text_hash": text,
                    "name_hash": name,
                    "voice_id": row.get("VoiceID"),
                    "voice": voice[sid],
                }, ensure_ascii=False) + "\n")
        self.stats["sentences"] = len(ids)
        return ids

    # -------------------------------------------------------- 引用与归属

    def index_missions(self, sentence_ids: set):
        """扫三个来源，按目录名把台词引用归属到主任务。"""
        main_rows = _load(os.path.join(self.upstream, "ExcelOutput",
                                       "MainMission.json"))
        mains = {m["MainMissionID"]: m for m in main_rows
                 if "MainMissionID" in m}
        self.stats["excel_main_missions"] = len(mains)

        # SubMission **没有 MainMissionID 字段**，靠编号前缀归属：SubMissionID
        # 是 9 位，前 7 位就是 MainMissionID，实测命中 14746/14796 = 99.66%。
        # （注意：台词归属不能这么干，那样只有 9.21%——两者是不同的编号约定。）
        sub_rows = _load(os.path.join(self.upstream, "ExcelOutput",
                                      "SubMission.json"))
        subs = defaultdict(list)
        for s in sub_rows:
            sid = s.get("SubMissionID")
            if sid is None:
                self.fail("SubMission.json", "sub_mission", "条目缺 SubMissionID")
                continue
            prefix = str(sid)[:7]
            if len(str(sid)) > 7 and int(prefix) in mains:
                subs[int(prefix)].append(s)
            else:
                self.stats["sub_mission_unattributed"] += 1
        self.stats["excel_sub_missions"] = len(sub_rows)

        by_mission = defaultdict(list)
        by_source = Counter()
        unattributed_scripts = []
        for rel_root, _seg in DIALOGUE_ROOTS:
            base = os.path.join(self.upstream, *rel_root.split("/"))
            if not os.path.isdir(base):
                self.fail(rel_root, "root", "目录不存在（sparse 配置漏了？）")
                continue
            for entry in sorted(os.listdir(base)):
                sub_path = os.path.join(base, entry)
                if not os.path.isdir(sub_path):
                    continue
                scripts = self._scan_dir(sub_path, rel_root)
                if not scripts:
                    continue
                by_source[rel_root] += sum(len(s["events"]) for s in scripts)
                if entry.isdigit() and int(entry) in mains:
                    by_mission[int(entry)].extend(scripts)
                    self.mission_dirs.add(os.path.normpath(sub_path))
                else:
                    # 目录名不是已知的 MainMissionID：4.5.0 实测 666 个这类目录带对话脚本
                    # （活动/教程的独立编号空间）。不硬塞给某个任务——它们由
                    # index_dialogues 当任务外对话输出。
                    self.stats["dir_not_a_mission"] += 1
                    unattributed_scripts.extend(scripts)

        def sentence_ids_of(scripts):
            out = set()
            for s in scripts:
                out.update(_event_sentences(s["events"]))
            return out

        attributed = set()
        for scripts in by_mission.values():
            attributed |= sentence_ids_of(scripts)
        unattributed = sentence_ids_of(unattributed_scripts)

        self.stats["talk_refs_attributed"] = len(attributed)
        self.stats["talk_refs_unattributed"] = len(unattributed)
        self.stats["missions_with_dialogue"] = len(by_mission)
        self.stats["events_by_source"] = dict(by_source)

        referenced = attributed | unattributed
        self.referenced |= referenced
        self.stats["talk_refs_dangling"] = len(referenced - sentence_ids)
        self.stats["mission_refs"] = len(referenced & sentence_ids)

        out_path = os.path.join(self.out_dir, "missions.jsonl")
        with open(out_path, "w", encoding="utf-8") as f:
            for mid in sorted(mains):
                m = mains[mid]
                scripts = by_mission.get(mid, [])
                f.write(json.dumps({
                    "main_mission_id": mid,
                    "type": m.get("Type"),
                    "sub_type": m.get("SubType"),
                    "chapter_id": m.get("ChapterID"),
                    "world_id": m.get("WorldID"),
                    # 只有 1396/2166 个主任务带 Name，其余是无名任务
                    "name_hash": (m.get("Name") or {}).get("Hash"),
                    "next": m.get("NextMainMissionList") or [],
                    "sub_missions": [
                        {
                            "sub_id": s.get("SubMissionID"),
                            "target_hash": (s.get("TargetText") or {}).get("Hash"),
                            # 上游把 Description 拼成了 Descrption，别"顺手修正"
                            "desc_hash": (s.get("DescrptionText") or {}).get("Hash"),
                        }
                        for s in sorted(subs.get(mid, ()),
                                        key=lambda s: s.get("SubMissionID") or 0)
                    ],
                    # 按脚本分组保留**有序**事件流，而不是一个台词 id 集合 ——
                    # 顺序和分支都在这里面（见 script.py）
                    "scripts": scripts,
                }, ensure_ascii=False) + "\n")
        self.stats["missions_written"] = len(mains)

    # -------------------------------------------------------- 任务之外的对话

    def _dialogue_context(self):
        """任务外对话的两条归属线索：楼层 -> 区域名、脚本路径 -> 交互标题。"""
        floor_to_plane = {}
        planes = os.path.join(self.upstream, "ExcelOutput", PLANE_TABLE)
        if os.path.exists(planes):
            for plane in _load(planes):
                for fid in plane.get("FloorIDList") or []:
                    floor_to_plane[fid] = _hash(plane, "PlaneName")
        else:
            self.fail(PLANE_TABLE, "dialogue", "表不存在，任务外对话拿不到区域名")

        by_actpath = {}
        for name in ACTPATH_TABLES:
            path = os.path.join(self.upstream, "ExcelOutput", name)
            if not os.path.exists(path):
                self.fail(name, "dialogue", "表不存在，任务外对话拿不到交互标题")
                continue
            for row in _load(path):
                act = (row.get("ActPath") or "").replace("\\", "/")
                if act:
                    by_actpath.setdefault(act, row)
        self.stats["dialogue_floors_known"] = len(floor_to_plane)
        self.stats["dialogue_actpaths_known"] = len(by_actpath)
        return floor_to_plane, by_actpath

    def index_textjoin(self):
        """`{TEXTJOIN#n}` -> 默认取值的文本 hash（`textjoin.json`，emit 换标签用），以及每个 n 的全部候选（`textjoins.jsonl`，出 `textjoins_*` 表）。

        崩铁的文本里有这种动态占位符（玩家给宠物 / 飞船 / 社团起的名字，从几个候选里选、有的还能自定义）。**对话正文保持原样**
        （占位符本身是信息，下游要不要替换是下游的事），但地点这类**标签**里留着
        占位符就没法用了——实测有 449 个区域名是 `{TEXTJOIN#87}`。下游要按视频认出玩家选的是哪个，所以候选整张给出。
        """
        cfg_path, item_path = (os.path.join(self.upstream, "ExcelOutput", n)
                               for n in TEXTJOIN_TABLES)
        if not (os.path.exists(cfg_path) and os.path.exists(item_path)):
            self.fail("TextJoin*", "textjoin", "表不存在，占位符无法解析")
            open(os.path.join(self.out_dir, "textjoins.jsonl"), "w").close()   # 写空表：别让 emit 读到上一次剩下的
            return
        items = {r["TextJoinItemID"]: _hash(r, "TextJoinText")
                 for r in _load(item_path) if "TextJoinItemID" in r}
        out = {}
        rows = []
        for row in _load(cfg_path):
            default = items.get(row.get("DefaultItem"))
            if default is not None:
                out[str(row["TextJoinID"])] = default
            ids = list(row.get("TextJoinItemList") or [])
            if row.get("DefaultItem") is not None and row["DefaultItem"] not in ids:
                ids.insert(0, row["DefaultItem"])
                self.stats["textjoin_default_not_in_list"] += 1
            dangling = [i for i in ids if i not in items]
            self.stats["textjoin_item_dangling"] += len(dangling)
            ids = [i for i in ids if i in items]
            rows.append({"id": row["TextJoinID"],
                         "default": ids.index(row["DefaultItem"]) if row.get("DefaultItem") in ids else None,
                         "items": [items[i] for i in ids]})
        self.stats["textjoin_entries"] = len(out)
        self.stats["textjoin_rows"] = len(rows)
        with open(os.path.join(self.out_dir, "textjoin.json"), "w",
                  encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        with open(os.path.join(self.out_dir, "textjoins.jsonl"), "w", encoding="utf-8") as f:
            for r in sorted(rows, key=lambda r: r["id"]):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def index_dialogues(self, sentence_ids: set):
        """扫 Config/Level 与 Story 下除"已归到主任务的目录"之外的全部脚本。

        这些对话没有任务归属（NPC 闲聊、场景物件、模拟宇宙、市政广播…），
        按来源目录分桶输出，不硬塞给任何任务。但有两条**查得证**的归属线索，
        见 `_dialogue_context`：路径里的 FloorID 给出区域名（4.5.0 覆盖约三成），
        `DialogueNPC`/`DialogueProp` 的 ActPath 给出交互标题。查不到就留空，不猜。

        **跳过的只是 `index_missions` 归了属的那些目录**，不是三个任务根目录整棵。
        第一版整棵跳过，于是任务根目录下 666 个目录名不是 MainMissionID 的（活动 /
        教程的独立编号空间）脚本——解析了、台词也算进了"被引用"——**哪个产物都没进**，
        3.5 万句台词静默丢失，报告的覆盖率（67.4%）和产物里实际有的（52.7%）对不上。
        """
        floor_to_plane, by_actpath = self._dialogue_context()
        skip = self.mission_dirs
        by_bucket = Counter()
        refs = set()
        out_path = os.path.join(self.out_dir, "dialogues.jsonl")
        n = 0
        with open(out_path, "w", encoding="utf-8") as f:
            for root in OTHER_ROOTS:
                base = os.path.join(self.upstream, *root.split("/"))
                if not os.path.isdir(base):
                    self.fail(root, "root", "目录不存在（sparse 配置漏了？）")
                    continue
                for dirpath, dirnames, filenames in os.walk(base):
                    if os.path.normpath(dirpath) in skip:
                        dirnames[:] = []
                        continue
                    for name in sorted(filenames):
                        if not name.endswith(".json"):
                            continue
                        full = os.path.join(dirpath, name)
                        rel = os.path.relpath(full, self.upstream).replace("\\", "/")
                        self.stats["other_scripts_scanned"] += 1
                        events = self._parse_file(full, rel)
                        if events is None or not _event_sentences(events):
                            continue
                        bucket = _bucket_of(rel)
                        by_bucket[bucket] += 1
                        refs |= _event_sentences(events)
                        n += 1
                        m = FLOOR_IN_PATH.search("/" + rel + "/")
                        floor = int(m.group(1)) if m else None
                        plane = floor_to_plane.get(floor) if floor else None
                        act = by_actpath.get(rel) or {}
                        if plane:
                            self.stats["dialogue_with_plane"] += 1
                        if act:
                            self.stats["dialogue_with_interact_title"] += 1
                        f.write(json.dumps({
                            "bucket": bucket, "source": rel, "events": events,
                            "floor_id": floor,
                            "plane_name_hash": plane,
                            # InteractTitle 是明文标签（NPCName_Normal_Lila），
                            # 不是 hash——上游只在 DialogueNPC 里用这种写法
                            "interact_title": act.get("InteractTitle"),
                            "group_id": act.get("GroupID"),
                        }, ensure_ascii=False) + "\n")
        self.stats["dialogue_scripts"] = n
        self.stats["dialogue_scripts_by_bucket"] = dict(by_bucket.most_common(20))
        self.stats["dialogue_refs"] = len(refs)
        self.referenced |= refs
        return refs

    # -------------------------------------------------------- 短信系统

    def index_messages(self):
        """短信：联系人 -> 分节 -> 消息图。分支就是 NextItemIDList 有多个后继。"""
        base = os.path.join(self.upstream, "ExcelOutput")
        tables = {}
        for label, fname in MESSAGE_TABLES.items():
            path = os.path.join(base, fname)
            if not os.path.exists(path):
                self.fail(fname, "message", "表不存在")
                return 0
            tables[label] = _load(path)

        items_by_section = defaultdict(list)
        for it in tables["items"]:
            items_by_section[it.get("SectionID")].append(it)
        sections = {s["ID"]: s for s in tables["sections"] if "ID" in s}
        contacts = {c["ID"]: c for c in tables["contacts"] if "ID" in c}

        self.stats["message_items"] = len(tables["items"])
        self.stats["message_sections"] = len(sections)
        self.stats["message_contacts"] = len(contacts)

        used_sections = set()
        out_path = os.path.join(self.out_dir, "messages.jsonl")
        with open(out_path, "w", encoding="utf-8") as f:
            for g in sorted(tables["groups"], key=lambda x: x.get("ID") or 0):
                contact = contacts.get(g.get("MessageContactsID"))
                secs = []
                for sid in g.get("MessageSectionIDList") or []:
                    used_sections.add(sid)
                    sec = sections.get(sid)
                    if sec is None:
                        self.stats["message_section_dangling"] += 1
                        continue
                    items = []
                    for it in sorted(items_by_section.get(sid, ()),
                                     key=lambda x: x.get("ID") or 0):
                        nxt = it.get("NextItemIDList") or []
                        if len(nxt) > 1:
                            self.stats["message_branches"] += 1
                        # OptionText 只在**玩家发的**那条上有意义（3108/3113 能查到）。
                        # NPC / System / PlayerAuto 行上也带这个字段，但值全是查不到
                        # 的残留 hash（967+57+98 条）——照单全收会凭空造出 26% 的
                        # "未解析"，还会给 NPC 消息安上一个不存在的选项标签。
                        is_option = it.get("Sender") == "Player"
                        if not is_option and _hash(it, "OptionText"):
                            self.stats["message_vestigial_option_text"] += 1
                        items.append({
                            "id": it.get("ID"),
                            "sender": it.get("Sender"),
                            "item_type": it.get("ItemType"),
                            "text_hash": _hash(it, "MainText"),
                            "option_text_hash": (_hash(it, "OptionText")
                                                 if is_option else None),
                            "next": nxt,
                        })
                    self.stats["message_lines"] += len(items)
                    secs.append({
                        "section_id": sid,
                        "start": sec.get("StartMessageItemIDList") or [],
                        "items": items,
                    })
                if not secs:
                    self.stats["message_groups_empty"] += 1
                    continue
                self.stats["message_groups"] += 1
                f.write(json.dumps({
                    "group_id": g.get("ID"),
                    "contact_id": g.get("MessageContactsID"),
                    "contact_name_hash": _hash(contact, "Name") if contact else None,
                    "signature_hash": (_hash(contact, "SignatureText")
                                       if contact else None),
                    "sections": secs,
                }, ensure_ascii=False) + "\n")
        self.stats["message_sections_unused"] = len(set(sections) - used_sections)
        return self.stats["message_groups"]

    # --------------------------------------------------------

    def _parse_file(self, full: str, rel: str):
        try:
            doc = _load(full)
        except (OSError, ValueError) as e:
            self.fail(rel, "script", "读不了或不是合法 JSON: %s" % e)
            return None
        return script.parse(doc)

    def _scan_dir(self, path: str, rel_root: str) -> list:
        """解析目录下所有脚本，返回 [{source, events}]，保持脚本内的事件顺序。

        用 `script.parse` 而不是正则：顺序和分支都在数组结构里，正则只能拿到
        一个无序集合，下游没法还原剧情。
        """
        out = []
        for dirpath, _dirnames, filenames in os.walk(path):
            for name in sorted(filenames):
                if not name.endswith(".json"):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, self.upstream).replace("\\", "/")
                self.stats["scripts_scanned"] += 1
                events = self._parse_file(full, rel)
                if events is None or not _event_sentences(events):
                    continue
                self.stats["scripts_with_dialogue"] += 1
                out.append({"source": rel, "events": events})
        return out

    # -------------------------------------------------------- 汇总

    def dump_dangling(self, sentence_ids: set):
        """把"脚本引用了、台词表里却没有"的 id 落盘，别只留一个计数。

        已定性（见 docs/starrail/data-source.md）：这些 id 在 3.8.0 的台词表里**也不存在**，
        而台词表是只增不删的（8 个月里 0 条被删）。所以不是被删的内容，是上游的脚本
        引用了从未发布过的台词。**不进 unparsed.jsonl**——那会让报告变红，但这是上游
        的属性，不是我们的解析失败。
        """
        out = {}
        for name in ("missions.jsonl", "dialogues.jsonl"):
            path = os.path.join(self.out_dir, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    groups = ([(sc["source"], sc["events"])
                               for sc in row.get("scripts") or []]
                              if "scripts" in row else [(row["source"], row["events"])])
                    for src, events in groups:
                        for sid in _event_sentences(events):
                            if sid not in sentence_ids:
                                entry = out.setdefault(sid, {"refs": 0, "sources": []})
                                entry["refs"] += 1
                                if len(entry["sources"]) < 3:
                                    entry["sources"].append(src)
        self.stats["dangling_sentence_ids"] = len(out)
        self.stats["dangling_refs"] = sum(v["refs"] for v in out.values())
        with open(os.path.join(self.out_dir, "dangling.json"), "w",
                  encoding="utf-8") as f:
            json.dump({str(k): v for k, v in sorted(out.items())}, f,
                      ensure_ascii=False, indent=2)

    def coverage(self, sentence_ids: set):
        """台词覆盖率：任务 + 非任务两个来源合起来算，剩下的才叫"无人引用"。"""
        seen = self.referenced & sentence_ids
        self.stats["sentences_referenced"] = len(seen)
        self.stats["sentences_unreferenced"] = len(sentence_ids - seen)
        self.stats["sentence_coverage"] = round(
            len(seen) / len(sentence_ids), 4) if sentence_ids else 0.0

    def finish(self) -> dict:
        with open(os.path.join(self.build, "unparsed.jsonl"), "w",
                  encoding="utf-8") as f:
            for fail in self.failures:
                f.write(json.dumps(fail, ensure_ascii=False) + "\n")
        self.stats["failures"] = len(self.failures)
        return dict(self.stats)


def _event_sentences(events) -> set:
    """一串事件里提到的全部台词 id。

    除了 talk/option 自己的 sentence_id，还包括**自定义字符串里编码的**那些：
    选项的 reply_sentence_id、trigger/wait 的 sentence_id。漏掉后者会把
    选项对话的回答整批丢掉（见 script.py）。
    """
    out = set()
    for e in events:
        for key in ("sentence_id", "reply_sentence_id"):
            v = e.get(key)
            if isinstance(v, int):
                out.add(v)
    return out


def _bucket_of(rel: str) -> str:
    """按来源目录分桶：Config/Level/<X> 或 Story/<X>。"""
    parts = rel.split("/")
    if parts[0] == "Config" and len(parts) > 2:
        return "Config/Level/" + parts[2]
    if len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]
