"""index 阶段：把 TextMap 的 key 归一成中间层，再用 FileCfg 的配置表补上结构。

两个来源分工明确：

- **TextMap** 给剧情文本本身。它的 key 是明文语义标识（`<类别>_<场景>_[Name_]<序号>`），
  剧情能直接提取并排序，这是 zzz 解析层首版就跑通的部分。
- **FileCfg** 给结构：场景是什么类型、属于哪个任务、短信怎么分支。字段名混淆，
  靠 `tables.py` 的锚点推断，不硬编码（AGENTS.md 不变量 9）。

产物（build/index/ 下）：
    scenes.jsonl    每行一个场景：类别 + 章节 + 场景 id + 有序的行 + **出场角色表**（cast），
                    以及来自 Perform 表的类型/分组与关联任务
    quests.jsonl    每行一个任务：quest id + name/target/desc/finish 的 key + 前置/后继
    messages.jsonl  每行一个短信组：按 step 分节的消息与二选一分支
    loose.jsonl     **没进上面三份的全部 TextMap 条目**（漫画过场、AutoEvent、教程、UI…），
                    一条一行，能从 key 读出分组/序号的带上
    unparsed.jsonl  结构不认识的 key
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

from . import keys as keymod
from . import tables as tablemod
from .textmap import TextMap

# 非剧情的类别前缀：UI、提示、道具、成就之类。计数上报但不进场景。
# 判据是首段（数字归一后），宁可少排除也不要把剧情排掉。
NON_STORY_HEADS = {
    "Tips", "UIText", "Item", "Avatar", "Buddy", "Weapon", "Equip",
    "Achievement", "Medal", "Battle", "Monster", "Enemy", "Card",
    "Skill", "Buff", "Shop", "Mail", "Notice", "Loading", "Tutorial",
}

# 场景 id 短于这个长度就不与 Perform 表联接：像 Chat|Chapter1|13 这种两位数
# "场景号"只在自己类别里唯一，硬联会撞出假关联。
MIN_JOINABLE_SCENE_ID = 6

# 散条目里能从 key 读出"哪一组、第几条"的形态。`AutoEvent1022103_11`：事件 1022103 的第 11 句
# （场景形态 `<类别>_<场景>_<序号>` 解析不了它，因为类别和事件号之间没有下划线）。
LOOSE_GROUPED = re.compile(r"^(?P<head>AutoEvent)(?P<group>\d+)_(?P<seq>\d+)$")


class Indexer:
    def __init__(self, upstream: str, build: str, base_lang: str = "CHS"):
        self.upstream = upstream
        self.build = build
        self.out_dir = os.path.join(build, "index")
        os.makedirs(self.out_dir, exist_ok=True)
        self.base_lang = base_lang
        self.failures = []
        self.stats = Counter()
        self.cfg = {}

    def fail(self, key, stage, reason):
        self.failures.append({"key": key, "stage": stage, "reason": reason})

    def run(self):
        """以基准语种的 key 全集建索引；其他语种在 emit 阶段按同一批 key 取值。"""
        tm = TextMap.load(self.upstream, self.base_lang)
        self.stats["textmap_entries"] = len(tm)
        self.stats["textmap_overwritten"] = tm.overwritten
        self.stats["textmap_added_by_overwrite"] = tm.added
        text_keys = set(tm.keys())

        # (category, chapter, scene) -> {seq_variant: 文本 key}
        scenes = defaultdict(dict)
        # (category, chapter, scene) -> {seq_variant: 名字 key}——出场角色表，不是逐行说话人
        casts = defaultdict(dict)
        quests = defaultdict(dict)
        reasons = {}              # 没进场景 / 任务的 key -> 原因（loose.jsonl 用）
        by_category = Counter()
        skipped = Counter()

        for key in text_keys:
            quest = keymod.parse_quest(key)
            if quest:
                field, qid = quest
                quests[qid][field] = key
                self.stats["quest_keys"] += 1
                continue

            head = keymod.category_of(key)
            if head in NON_STORY_HEADS:
                skipped[head] += 1
                self.stats["keys_non_story"] += 1
                reasons[key] = "non_story"
                continue

            parsed = keymod.parse_line(key)
            if not parsed:
                # 结构不认识：单数字段的（Message_100301、AutoEvent100000_26）、
                # 纯 UI 串等。计数并落盘，别静默丢。短信那批由 FileCfg 另行成图。
                skipped[head] += 1
                self.stats["keys_unmatched"] += 1
                self.fail(key, "parse", "不符合 <类别>_<场景>_[Name_]<序号> 形态")
                reasons[key] = "unmatched"
                continue

            group = (parsed["category"], parsed["chapter"], parsed["scene"])
            # 槽位用**原样的序号串**：`_01` 和 `_1` 在同一场景里是两条不同的台词。第三版之前
            # 按数值归一（"%d"），撞在一起的 219 组每组静默丢一条，丢哪条还随 set 的遍历顺序变
            # ——两次运行的产物不一样。输出里的 `slot` 仍是数值形式（见 _write_scenes）
            slot = parsed["seq_raw"] + parsed["variant"]
            if parsed["is_speaker"]:
                casts[group][slot] = key
                self.stats["cast_keys"] += 1
            else:
                scenes[group][slot] = key
                self.stats["dialogue_keys"] += 1
                by_category[parsed["category"]] += 1

        scene_ids = {scene for _, _, scene in scenes}
        perform, quest_cfg, messages = self._load_config(text_keys, scene_ids)
        quest_by_scene = self._link(perform, quest_cfg)

        used = set()
        used |= self._write_scenes(scenes, casts, perform, quest_by_scene)
        used |= self._write_quests(quests, quest_cfg)
        used |= self._write_messages(messages, quest_cfg)
        self._write_loose(text_keys - used, reasons)

        self.stats["dialogue_by_category"] = dict(by_category.most_common(15))
        self.stats["skipped_by_head"] = dict(skipped.most_common(15))
        self.stats["filecfg"] = self.cfg
        return dict(self.stats)

    # ---- FileCfg ----------------------------------------------------------

    def _load_config(self, text_keys, scene_ids):
        """三张表各自独立推断：一张推断失败不影响另外两张，但都要记账。"""
        out = []
        for label, ctor in (
            ("perform", lambda: tablemod.Perform(self.upstream, text_keys, scene_ids)),
            ("quests", lambda: tablemod.Quests(self.upstream, text_keys)),
            ("messages", lambda: tablemod.Messages(self.upstream, text_keys)),
        ):
            try:
                obj = ctor()
            except tablemod.Failure as exc:
                self.fail(label, "filecfg", str(exc))
                self.cfg[label] = {"failed": str(exc)}
                out.append(None)
                continue
            self.cfg[label] = obj.stats()
            out.append(obj)
        return out

    def _link(self, perform, quest_cfg):
        """场景 -> 任务。全表扫桥表，不写死是哪几张。"""
        if perform is None or quest_cfg is None:
            self.cfg["scene_quest_edges"] = {"skipped": "缺少 Perform 或 Quest 表"}
            return {}
        edges, sources = tablemod.scene_quest_edges(
            self.upstream, perform.ids, quest_cfg.ids)
        by_scene = defaultdict(list)
        for e in edges:
            entry = {"quest_id": e["quest_id"], "via": e["via"]}
            if entry not in by_scene[e["perform_id"]]:
                by_scene[e["perform_id"]].append(entry)
        self.cfg["scene_quest_edges"] = {
            "edges": len(edges),
            "scenes_linked": len(by_scene),
            "sources": sorted(sources, key=lambda s: -s["edges"]),
        }
        return by_scene

    # ---- 落盘 -------------------------------------------------------------

    def _write_scenes(self, scenes, casts, perform, quest_by_scene):
        """返回写进产物的全部 TextMap key（loose.jsonl 要排除它们）。

        **`_Name_NNN` 是出场角色表，不是逐行说话人**（AGENTS.md 不变量 6）。第二版把
        `_Name_00i` 配给第 i 行（第一版连 `_Name_` 都没认出来）：3.2.0 实测 9438 个带名字的场景里，9419 个的名字序号严格是
        1..k 连续，9338 个名字互不重复、7988 个名字数少于台词行数——两个人来回说的对话，
        逐行说话人必然有重复。于是前几行说话人是错的、后面的行没有说话人。逐行说话人在
        Perform 脚本里，而那部分不在上游仓库（和剧情分支同一个边界）。"""
        used = set()
        path = os.path.join(self.out_dir, "scenes.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for group in sorted(set(scenes) | set(casts)):
                category, chapter, scene = group
                slots = scenes.get(group, {})
                lines = [{"slot": _slot_norm(slot), "key": slots[slot]}
                         for slot in sorted(slots, key=_slot_sort)]
                self.stats["slot_padding_collisions"] += len(lines) - len(
                    {ln["slot"] for ln in lines})
                cast_slots = casts.get(group, {})
                cast = [cast_slots[slot] for slot in sorted(cast_slots, key=_slot_sort)]
                if not lines:
                    # 只有名字没有台词：名字留给 loose，不单独成场景
                    self.stats["scenes_empty"] += 1
                    continue
                used.update(ln["key"] for ln in lines)
                used.update(cast)
                self.stats["scenes"] += 1
                self.stats["scene_lines"] += len(lines)
                self.stats["scenes_with_cast"] += bool(cast)

                meta = None
                links = []
                if perform is not None and len(scene) >= MIN_JOINABLE_SCENE_ID:
                    meta = perform.by_id.get(scene)
                    if meta:
                        self.stats["scenes_with_perform"] += 1
                        used.update(k for k in (meta.get("title_key"), meta.get("intro_key")) if k)
                        links = quest_by_scene.get(scene, [])
                        if links:
                            self.stats["scenes_with_quest"] += 1
                f.write(json.dumps({
                    "category": category, "chapter": chapter, "scene": scene,
                    "lines": lines, "cast": cast, "perform": meta, "quests": links,
                }, ensure_ascii=False) + "\n")
        return used

    def _write_quests(self, quests, quest_cfg):
        """行集合仍以"有文本的任务"为准；配置表只补结构，不凭空造出没文本的任务。"""
        used = set()
        path = os.path.join(self.out_dir, "quests.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for qid in sorted(quests, key=lambda x: (len(x), x)):
                row = {"quest_id": qid, **quests[qid]}
                used.update(quests[qid].values())
                cfg = quest_cfg.by_id.get(qid) if quest_cfg else None
                if cfg:
                    self.stats["quests_with_config"] += 1
                    row.setdefault("finish", cfg.get("finish_key"))
                    row["prev_quests"] = cfg.get("prev_quests") or []
                    row["next_quests"] = cfg.get("next_quests") or []
                    # 配置表指的名字常常**不是**这一行自己的名字：子任务 3020101 的
                    # 配置名指向父任务 QuestName_30201，季节任务另有 ZKSeasonQuestName_*。
                    # 所以它不是"对不上"，而是"游戏里实际显示的标题"，单独出一列。
                    name_key = cfg.get("name_key")
                    if name_key and name_key != row.get("name"):
                        row["display_name"] = name_key
                        self.stats["quests_display_name_differs"] += 1
                else:
                    row["prev_quests"] = []
                    row["next_quests"] = []
                self.stats["quests"] += 1
                used.update(row[k] for k in ("finish", "display_name") if row.get(k))
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if quest_cfg:
            self.stats["quests_config_only"] = len(
                quest_cfg.ids - set(quests))
        return used

    def _write_messages(self, messages, quest_cfg):
        used = set()
        path = os.path.join(self.out_dir, "messages.jsonl")
        rows = []
        if messages is not None:
            rows = messages.build(quest_cfg.ids if quest_cfg else set())
            self.cfg["messages"] = messages.stats()
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                self.stats["message_groups"] += 1
                self.stats["message_nodes"] += len(row["nodes"])
                self.stats["message_lines"] += sum(
                    len(n["messages"]) for n in row["nodes"])
                self.stats["message_options"] += sum(
                    len(n["options"]) for n in row["nodes"])
                if row["quests"]:
                    self.stats["message_groups_with_quest"] += 1
                for n in row["nodes"]:
                    used.update(k for m in n["messages"]
                                for k in (m.get("text_key"), m.get("npc_name_key")) if k)
                    used.update(o["text_key"] for o in n["options"] if o.get("text_key"))
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return used

    def _write_loose(self, keys, reasons):
        """没进 scenes / quests / messages 的全部 TextMap 条目，一条一行。

        此前这些不进产物：key 形态不认识的只记进 unparsed.jsonl（`AutoEvent*` 1 万多条、
        漫画过场 `Comic_*` 2451 条……），按前缀排除的非剧情条目（Tips / UIText…）只计数——而它们在屏幕上是有的（下游拿直播录像对台词时，
        一段漫画过场里 37 句都只在这里）。能从 key 读出分组和序号的（`AutoEvent<事件>_<序号>`）
        带上 group / seq，其余没有结构可依（`Comic_<32 位 hash>` 在整个 FileCfg 里没有引用），
        就是无序散句——不硬拼顺序。"""
        path = os.path.join(self.out_dir, "loose.jsonl")
        rows = []
        for key in keys:
            m = LOOSE_GROUPED.match(key)
            rows.append({
                "key": key, "head": keymod.category_of(key),
                "reason": reasons.get(key, "unused"),
                "group": m.group("group") if m else None,
                "seq": int(m.group("seq")) if m else None,
            })
        rows.sort(key=lambda r: (r["head"], r["group"] or "", r["seq"] or 0, r["key"]))
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.stats["loose"] = len(rows)
        self.stats["loose_by_reason"] = dict(Counter(r["reason"] for r in rows))
        self.stats["loose_grouped"] = sum(1 for r in rows if r["group"])
        self.stats["loose_by_head"] = dict(Counter(r["head"] for r in rows).most_common(15))

    def finish(self):
        with open(os.path.join(self.build, "unparsed.jsonl"), "w",
                  encoding="utf-8") as f:
            for fail in self.failures:
                f.write(json.dumps(fail, ensure_ascii=False) + "\n")
        self.stats["failures"] = len(self.failures)
        return dict(self.stats)


def _slot_sort(slot):
    """'012F' -> (12, 3, 'F')：按序号的数值排，而不是字典序。

    同一数值的 `_01` 与 `_1` 并存时（见 index 里槽位的说明）再按位数排，**只为确定性**——
    上游没有信息说明两串谁先谁后（有的场景是一串编号补零不一致，`10` 后面跟 `011`，
    按数值排正好对；有的是 `1..15` 和 `01..09` 两串交错，排出来是穿插的）。"""
    num = "".join(c for c in slot if c.isdigit())
    suffix = "".join(c for c in slot if not c.isdigit())
    return (int(num) if num else 0, len(num), suffix)


def _slot_norm(slot):
    """'012F' -> '12F'：输出里的 `slot` 保持数值形式（与第二版的产物一致）。"""
    num = "".join(c for c in slot if c.isdigit())
    suffix = "".join(c for c in slot if not c.isdigit())
    return "%d%s" % (int(num) if num else 0, suffix)
