"""index 阶段：把上游快照归一成中间层，文本仍留 hash。

产物（都在 build/index/ 下）：
    talks.jsonl    每行一个 talk：talkId + 归一化的对话节点
    quests.jsonl   每行一个主任务：mainQuestId + 子任务 + 引用的 talkId
    voices.json    Dialog / DungeonReminder 的有配音 id 集合（Items ∪ Lut）
    reminders.jsonl 每行一条语音字幕链（ReminderExcelConfigData，按 nextReminderId 串）
    pronouns.jsonl 每行一个按性别取的键 + TextMapHash（ManualTextMapConfigData 里 INFO_MALE_* / INFO_FEMALE_* 那些）
    readables.jsonl 每行一条阅读面板长文本的出处：Readable/ 各语种的文件名，或配置表行的 TextMapHash
    unparsed.jsonl 所有推断/归一化失败的记录（这个在 build/ 下）

本模块懂业务（知道什么是任务、什么是对话），但**不碰混淆字段名** —— 字段角色
一律问 `infer`，它只认结构。见 docs/genshin/architecture.md 的流水线一节（模块与边界）。
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

from . import infer, readable, textmap, voice
from .textmap import TextMap


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _iter_json(dirpath):
    for name in sorted(os.listdir(dirpath)):
        if name.endswith(".json"):
            yield name, _load(os.path.join(dirpath, name))


# 推断字段路径时的采样上限。同一家族（见 `_key_families`）字段名一致，样本够多即可定论。
TEXT_LAYOUT_SAMPLE = 800


def _key_families(by_sig):
    """把 signature（顶层键集合）按"共享任一键"并成家族，返回 {家族键并集: [文件名]}。

    上游从 7.1.0 起序列化时省略取默认值的字段（空数组、空串、0、false），同一种
    schema 的文件因缺的字段不同而键集合各异：BinOutput/Quest 的 4417 个文件拆成
    1376 个 signature，多数只有个位数文件，推断凑不够样本，凑够的也只有一组被当成
    主格式、其余整批误判为遗留副本。不同 schema 的混淆名互不相交（7.0.0 的主格式与
    遗留格式没有一个共同的键），所以按共享键求连通分量就能把同 schema 的文件重新
    并到一起。这只对**混淆名**成立：7.1.0 起有些键是明文（`id`、`type`…），明文名天然
    跨 schema 共享，带同样明文键的遗留副本会和主格式并成一族——那时同一个 mainQuestId
    会出现两次，`index_quests` 把重复记为非预期失败。
    """
    parent = {}

    def find(k):
        while parent.setdefault(k, k) != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for sig in by_sig:
        for k in sig[1:]:
            parent[find(k)] = find(sig[0])
    groups = defaultdict(list)
    for sig in by_sig:
        groups[find(sig[0]) if sig else None].append(sig)
    return {
        tuple(sorted(set().union(*sigs))): sorted(n for s in sigs for n in by_sig[s])
        for sigs in groups.values()
    }


def _base(name):
    """去掉 "子目录/" 前缀。"""
    return name.split("/")[-1]


def _node_count(doc):
    found = infer.find_dialog_list(doc)
    return len(found[1]) if found else 0


def _stem(name):
    return name[:-5] if name.endswith(".json") else name


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


class Indexer:
    def __init__(self, upstream: str, build: str, lang: str = "CHS"):
        self.upstream = upstream
        self.build = build
        self.out_dir = os.path.join(build, "index")
        self.lang = lang
        os.makedirs(self.out_dir, exist_ok=True)
        self.textmap = TextMap.load(upstream, lang)
        self.failures = []
        self.stats = Counter()

    # ------------------------------------------------------------ talks

    def index_talks(self, subdirs=None):
        """归一化 BinOutput/Talk 下所有子目录的 talk。

        子目录不写死：逐个尝试推断，推不动的（`*Group` 那几个 talk 容器目录）
        整批记为失败进 unparsed.jsonl，不产出垃圾节点。
        """
        base = os.path.join(self.upstream, "BinOutput", "Talk")
        if subdirs is None:
            subdirs = sorted(
                d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
        docs = {}
        for sub in subdirs:
            for name, doc in _iter_json(os.path.join(base, sub)):
                docs["%s/%s" % (sub, name)] = doc
        self.stats["talk_files"] = len(docs)
        self.stats["talk_subdirs"] = len(subdirs)

        # 1) 每个文件的 talkId：顶层唯一的整数字段。实测绝大多数文件都只有一个。
        by_talk_id = defaultdict(list)
        no_int = []
        for name, doc in docs.items():
            ints = [
                v for v in doc.values() if isinstance(v, int) and not isinstance(v, bool)
            ]
            if len(ints) == 1:
                by_talk_id[ints[0]].append(name)
            elif _stem(_base(name)).isdigit():
                by_talk_id[int(_stem(_base(name)))].append(name)
                self.stats["talk_id_from_filename"] += 1
            elif not ints:
                no_int.append(name)
            else:
                self.failures.append(
                    infer.Failure(name, "talk_id", "顶层整数字段不唯一且文件名非数字",
                                  {"candidates": ints})
                )
        # 7.1.0 起上游省略取默认值的字段：talkId 为 0 的文件（Quest/GlobalDialog.json，
        # 7.0.0 里明写 0）于是一个顶层整数都没有。整数字段缺省即 0，但 talkId 为 0 的只该有
        # 一个；不止一个、或 0 已被某个带对话的文件明写占用时，说明是别的原因丢了 id，
        # 并进 talk 0 会把无关的对话混在一起。明写 0 的空文件不算占用：7.1.0 的
        # FurnitureGroup 里就有两个旧格式的空容器明写着 0，那只是占位。
        zero_taken = any(_node_count(docs[n]) for n in by_talk_id.get(0, ()))
        if len(no_int) == 1 and not zero_taken:
            by_talk_id[0].append(no_int[0])
            self.stats["talk_id_default_zero"] += 1
        else:
            for name in no_int:
                self.failures.append(
                    infer.Failure(name, "talk_id",
                                  "没有顶层整数字段、文件名非数字，且这样的文件不止一个或 talkId 0 已被带对话的文件占用",
                                  {"candidates": []}))

        # 2) 同一 talkId 可能对应多个文件（同目录内、以及跨子目录）。挑一份作主，
        #    其余留作补充，节点在第 4 步合并 —— 详见下面的注释与 `_merge_extras`。
        canonical = {}
        extras = {}
        for talk_id, names in by_talk_id.items():
            if len(names) == 1:
                canonical[talk_id] = names[0]
                continue
            # 同一 talkId 的多份文件内容并不相同（实测 FreeGroup 与 Quest 有 1796
            # 个同名文件，一份 4 个节点另一份 58 个），而且**各有独有节点** ——
            # 只取一份会丢数据（与旧爬虫交叉校验时实测丢了 1465 条台词）。
            # 所以取节点最多的那份作**主**文件（决定 schema 与来源），其余作
            # 补充，归一化后按 dialog_id 合并。
            exact = [n for n in names if _stem(_base(n)) == str(talk_id)]
            pool = sorted(exact or names, key=lambda n: (-_node_count(docs[n]), n))
            canonical[talk_id] = pool[0]
            extras[talk_id] = [n for n in names if n != pool[0]]
            self.stats["talk_duplicate_files"] += len(names) - 1

        # 3) 按 signature 分组推 schema
        by_sig = defaultdict(list)
        stubs = []
        for talk_id, name in canonical.items():
            sig, nodes, err = infer.signature_of(docs[name])
            if err:
                # 连一个 dict 数组都没有的文件是**空壳 talk**（只有 talkId 和一个
                # 类型串，如 {"talkId": 328, "type": "COOP"}），和 dialogList 为
                # 空的那批同类，不是解析失败，照空 talk 写出（任务会引用它们）。
                # 7.1.0 起上游省略空数组，空 talk 全成了空壳：6 → 482，空 dialogList 491 → 16。
                if not any(isinstance(v, (list, dict)) for v in docs[name].values()):
                    self.stats["talk_stub"] += 1
                    stubs.append((talk_id, name))
                    continue
                self.failures.append(infer.Failure(name, "signature", err))
                continue
            if not nodes:
                self.stats["talk_empty"] += 1
            by_sig[sig].append((talk_id, name, nodes))

        schemas = {}
        for sig, items in by_sig.items():
            schema, err = infer.infer_schema(
                sig, (n for _, _, n in items), lambda h: h in self.textmap
            )
            if err:
                for _, name, _ in items:
                    self.failures.append(infer.Failure(name, "schema", err))
                continue
            schemas[sig] = schema
        self.stats["talk_signatures"] = len(by_sig)

        # 4) 归一化并写出
        path = os.path.join(self.out_dir, "talks.jsonl")
        talk_ids = set()
        by_sub = Counter()
        with open(path, "w", encoding="utf-8") as f:
            for talk_id, name in stubs:
                # 主文件按"文件名等于 talkId"优先，可能选中空壳而副本带对话：照样合并副本
                nodes = self._merge_extras(talk_id, [], extras, docs, schemas)
                talk_ids.add(talk_id)
                self.stats["talk_nodes"] += len(nodes)
                by_sub[name.split("/")[0]] += 1
                f.write(json.dumps(
                    {"talk_id": talk_id, "source": name,
                     "subdir": name.split("/")[0], "dialog": nodes},
                    ensure_ascii=False) + "\n")
            for sig, items in by_sig.items():
                schema = schemas.get(sig)
                if not schema:
                    continue
                for talk_id, name, _ in items:
                    nodes, fail = infer.normalize_talk(docs[name], schema, name)
                    if fail:
                        self.failures.append(fail)
                        continue
                    nodes = self._merge_extras(talk_id, nodes, extras, docs, schemas)
                    talk_ids.add(talk_id)
                    self.stats["talk_nodes"] += len(nodes)
                    by_sub[name.split("/")[0]] += 1
                    f.write(json.dumps(
                        {"talk_id": talk_id, "source": name,
                         "subdir": name.split("/")[0], "dialog": nodes},
                        ensure_ascii=False) + "\n")
        self.stats["talks_written"] = len(talk_ids)
        self.stats["talks_by_subdir"] = dict(by_sub)

        # 整个子目录颗粒无收 ⇒ 那批文件根本不是对话（实测就是 `*Group` 这几个
        # talk 容器目录）。这是**结论**而非事故，标记为预期内失败；真正意外的
        # 是"能出数据的目录里仍然解不出来的个别文件"，那些必须让流水线红掉。
        barren = {s for s in subdirs if not by_sub.get(s)}
        self.stats["talk_barren_subdirs"] = sorted(barren)
        for fail in self.failures:
            if fail.source.split("/")[0] in barren:
                fail.expected_override = True
        return talk_ids

    def _merge_extras(self, talk_id, nodes, extras, docs, schemas):
        """把同一 talkId 其余副本里的**独有节点**并进来，按 dialog_id 去重。

        副本不是纯粹的冗余：交叉校验发现只取一份会丢掉 1465 条台词。主文件的
        节点顺序保持不变，独有节点追加在后面并标记来源。
        """
        known = {n["dialog_id"] for n in nodes}
        for other in extras.get(talk_id, ()):
            sig, other_nodes, err = infer.signature_of(docs[other])
            if err or not other_nodes:
                continue
            schema = schemas.get(sig)
            if not schema:
                continue
            more, fail = infer.normalize_talk(docs[other], schema, other)
            if fail:
                continue
            for node in more:
                if node["dialog_id"] in known:
                    continue
                known.add(node["dialog_id"])
                node["from_duplicate"] = True
                nodes.append(node)
                self.stats["talk_nodes_from_duplicates"] += 1
        return nodes

    # ----------------------------------------------------------- quests

    def index_quests(self, talk_ids):
        """归一化 BinOutput/Quest，建立 主任务 -> (子任务, talk) 的映射。

        字段路径靠 `infer.infer_id_paths` 用两个明文 id 宇宙锚定：
        主任务 id 来自 MainQuestExcelConfigData，talkId 来自上一步。
        """
        main_quests = {
            q["id"]: q
            for q in _load(os.path.join(
                self.upstream, "ExcelBinOutput", "MainQuestExcelConfigData.json"))
            if "id" in q
        }
        self.stats["excel_main_quests"] = len(main_quests)

        root = os.path.join(self.upstream, "BinOutput", "Quest")
        docs = dict(_iter_json(root))
        self.stats["quest_files"] = len(docs)

        by_sig = defaultdict(list)
        for name, doc in docs.items():
            by_sig[tuple(sorted(doc.keys()))].append(name)
        self.stats["quest_signatures"] = len(by_sig)
        by_family = _key_families(by_sig)
        self.stats["quest_families"] = len(by_family)

        universes = {"main_quest": set(main_quests), "talk": set(talk_ids)}
        layouts = {}
        for family, names in by_family.items():
            paths = infer.infer_id_paths(
                (docs[n] for n in names), universes, min_hit=0.95, min_count=10
            )
            # 主任务 id 是顶层标量（路径里没有数组段），文件内唯一
            mq_paths = [p for p in paths["main_quest"] if "[]" not in p["path"]]
            # talk 引用路径用贪心集合覆盖挑，别把碰巧命中的字段也收进来 ——
            # talk 宇宙有两万多个 id，语义无关的字段撞上几个是常态。
            talk_paths = infer.pick_reference_paths(paths["talk"])
            if not mq_paths:
                for n in names:
                    self.failures.append(
                        infer.Failure(n, "quest_layout", "定位不到顶层 mainQuestId 路径"))
                continue
            # 同家族的文件字段名一致，采样即可——全量走一遍要多花两分钟
            text = self._infer_text_layout(docs[n] for n in names[:TEXT_LAYOUT_SAMPLE])
            layouts[family] = {
                "main_quest_key": mq_paths[0]["path"],
                "talk_paths": [p["path"] for p in talk_paths],
                "text": text,
                "evidence": {
                    "main_quest": infer.summarize_paths(mq_paths[:2]),
                    "talk_picked": infer.summarize_paths(talk_paths),
                    "talk_rejected": infer.summarize_paths(paths["talk"][:6]),
                },
            }

        # 7.0.0 两个家族都能解出 mainQuestId，但实测旧格式那批（94 个）的
        # mainQuestId 全部与新格式重复、且不引用任何 talk。以引用到 talk 的
        # 那种布局为权威，另一种整批记为遗留副本。7.1.0 起旧格式不再出现。
        ranked = sorted(
            layouts.items(),
            key=lambda kv: (len(kv[1]["talk_paths"]), len(by_family[kv[0]])),
            reverse=True,
        )
        primary_family = ranked[0][0] if ranked else None

        seen = set()
        rows = []
        explicit_all = set()
        for family, layout in ranked:
            is_primary = family is primary_family
            for name in by_family[family]:
                doc = docs[name]
                mq = doc.get(layout["main_quest_key"])
                if not isinstance(mq, int):
                    self.failures.append(
                        infer.Failure(name, "quest_id", "该路径上取不到整数 mainQuestId"))
                    continue
                if not is_primary:
                    self.stats["quest_legacy_files"] += 1
                    if mq in seen:
                        self.stats["quest_legacy_duplicate"] += 1
                        continue
                    self.failures.append(
                        infer.Failure(name, "quest_legacy",
                                      "遗留格式且主任务未被主格式覆盖",
                                      {"main_quest_id": mq}))
                    continue
                if mq in seen:
                    self.failures.append(infer.Failure(
                        name, "quest_duplicate",
                        "主格式里 mainQuestId 重复，多半是遗留副本因共享明文键被并进了主格式",
                        {"main_quest_id": mq}))
                    continue
                refs = set()
                for p in layout["talk_paths"]:
                    refs.update(_collect_path(doc, p.split(".")))
                seen.add(mq)
                hit = refs & talk_ids
                self.stats["quest_talk_refs"] += len(refs)
                self.stats["quest_talk_hit"] += len(hit)
                self.stats["quest_talk_dangling"] += len(refs - talk_ids)
                explicit_all |= hit
                excel = main_quests.get(mq, {})
                text = layout.get("text") or {}
                steps = self._read_steps(doc, text, mq)
                self.stats["quest_steps"] += len(steps)
                self.stats["quest_steps_with_text"] += sum(
                    1 for s in steps if s["desc_hash"])
                # 标题/描述以 Excel 为主、BinOutput 为备：Excel 的 hash 有约
                # 3% 标题、16% 描述查不到文本，BinOutput 那份能补上。
                rows.append({
                    "main_quest_id": mq,
                    "source": name,
                    "title_hash": excel.get("titleTextMapHash"),
                    "desc_hash": excel.get("descTextMapHash"),
                    "title_hash_alt": doc.get(text.get("title_path")),
                    "desc_hash_alt": doc.get(text.get("desc_path")),
                    "steps": steps,
                    "chapter_id": excel.get("chapterId"),
                    "series": excel.get("series"),
                    "tag": excel.get("mainQuestTag"),
                    "talk_ids": sorted(hit),
                    "talk_refs_missing": sorted(refs - talk_ids),
                })

        inferred = self._infer_attribution(talk_ids - explicit_all, seen)
        path = os.path.join(self.out_dir, "quests.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                row["talk_ids_inferred"] = sorted(
                    inferred.get(row["main_quest_id"], ()))
                self.stats["quest_talk_inferred"] += len(row["talk_ids_inferred"])
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.stats["quests_written"] = len(seen)
        self.stats["quests_missing_from_excel"] = len(seen - set(main_quests))
        self.stats["excel_quests_not_in_binout"] = len(set(main_quests) - seen)
        return layouts

    # talkId 去掉 mainQuestId 前缀后的余数位数。实测在已确证的 21 960 对里，
    # 98.62% 的 talkId 以所属 mainQuestId 为前缀，余数是 2/3/4 位。
    ATTRIB_REMAINDER_LENS = (2, 3, 4)

    def _infer_attribution(self, orphan_talk_ids, quest_ids):
        """把没有任务显式引用的 talk，按编号前缀**推测**归属到主任务。

        这是**推测**，与 quest 文件里的显式引用严格分开存放（`talk_ids_inferred`），
        下游可自行取舍。歧义时取最长前缀匹配的主任务——`q_1000` 与 `q_10001` 都是
        `100001` 的前缀，只有最长的那个才对。
        """
        by_len = defaultdict(set)
        for q in quest_ids:
            by_len[len(str(q))].add(str(q))
        out = defaultdict(set)
        for talk_id in orphan_talk_ids:
            s = str(talk_id)
            for plen in sorted(by_len, reverse=True):  # 最长前缀优先
                if len(s) - plen not in self.ATTRIB_REMAINDER_LENS:
                    continue
                prefix = s[:plen]
                if prefix in by_len[plen]:
                    out[int(prefix)].add(talk_id)
                    break
        self.stats["talk_orphans"] = len(orphan_talk_ids)
        self.stats["talk_attributed_by_prefix"] = sum(len(v) for v in out.values())
        return out

    def _infer_text_layout(self, docs):
        """定位主任务标题/描述与子任务步骤文本在 BinOutput/Quest 里的位置。

        `QuestExcelConfigData.stepDescTextMapHash` 是死字段——17 814 条里只有 698
        条能查到文本，且解出来的是剧情简介而非步骤描述。真正的步骤文本在
        BinOutput/Quest 的子任务节点里，命中率 99.97%。

        标题和描述都是文本，靠**文本长度中位数**区分：标题短（中位 5 字），描述
        长（中位 32 字）。
        """
        rows = infer.infer_text_paths(list(docs), self.textmap.get)
        top = [r for r in rows if "[]" not in r["path"]]
        nested = [r for r in rows if "[]" in r["path"]]
        top.sort(key=lambda r: r["median_len"])
        step = max(nested, key=lambda r: r["count"], default=None)
        layout = {
            "title_path": top[0]["path"] if top else None,
            "desc_path": top[-1]["path"] if len(top) > 1 else None,
            "step_list_key": step["path"].split(".")[0] if step else None,
            "step_text_key": step["path"].split(".")[-1] if step else None,
            "evidence": rows[:6],
        }
        return layout

    def _read_steps(self, doc, layout, main_quest_id):
        """从子任务列表里取 (sub_id, 步骤文本 hash)。

        sub_id 的判据：整数字段且**十进制写法以 mainQuestId 开头** —— 实测
        31 045/31 045 成立，是这份数据里最稳的一条编号约定。
        """
        list_key = layout.get("step_list_key")
        text_key = layout.get("step_text_key")
        if not list_key:
            return []
        prefix = str(main_quest_id)
        out = []
        for entry in doc.get(list_key) or []:
            if not isinstance(entry, dict):
                continue
            sub_id = None
            for k, v in entry.items():
                if (isinstance(v, int) and not isinstance(v, bool)
                        and str(v).startswith(prefix) and len(str(v)) > len(prefix)):
                    sub_id = v
                    break
            out.append({
                "sub_id": sub_id,
                "desc_hash": entry.get(text_key) if text_key else None,
            })
        return out

    # -------------------------------------------------------- reminders

    # 说话人字段的最低命中率。系统提示（「容器がいっぱいだ…」）没有说话人，那一格的
    # hash 查不到文本——7.0.0 实测命中 83%。正文字段仍按 infer 的默认门槛 0.9。
    REMINDER_SPEAKER_MIN_HIT = 0.5

    def index_voices(self):
        """在已归一化的 Talk 与明文 Reminder id 集合上推断语音映射参数。"""
        dialog_ids = set()
        with open(os.path.join(self.out_dir, "talks.jsonl"), encoding="utf-8") as f:
            for line in f:
                dialog_ids.update(d["dialog_id"] for d in json.loads(line)["dialog"])
        reminders = _load(os.path.join(
            self.upstream, "ExcelBinOutput", "ReminderExcelConfigData.json"))
        self.voice_ids, stats, failures = voice.load(self.upstream, {
            "Dialog": dialog_ids, "DungeonReminder": {r["id"] for r in reminders}})
        for key, value in stats.items():
            self.stats[key] = value
        self.failures.extend(failures)
        with open(os.path.join(self.out_dir, "voices.json"), "w", encoding="utf-8") as f:
            json.dump({t: sorted(ids) for t, ids in self.voice_ids.items()}, f)

    # 表省略默认值时补回的值（见 `index_reminders`）。`style` 的缺省是 `Normal`：7.1.0 里
    # 显式的 `Normal` 一行都没有，缺 `style` 的行在 7.0.0 里正是 `Normal`。
    REMINDER_DEFAULTS = {"hasAudio": False, "style": "Normal", "showTime": 0, "delay": 0}

    def index_reminders(self):
        """`ReminderExcelConfigData`：边玩边说的语音字幕（派蒙在路上的吐槽、比赛里队友的
        对白、战斗喊话…），**不在任何 Talk 里**，但就在屏幕下方的字幕带上。

        明文字段只有 `id` / `nextReminderId`（链）/ `showTime` / `delay` / `hasAudio` /
        `style`；说话人与正文是两个混淆的 hash 字段，照 `_infer_text_layout` 的办法
        **按文本长度中位数区分**（正文长、说话人短），不认字段名。一条链是一段对白：
        链头 = 不被任何 `nextReminderId` 指向的 id。
        """
        path = os.path.join(self.upstream, "ExcelBinOutput", "ReminderExcelConfigData.json")
        rows = _load(path)
        self.stats["reminder_rows"] = len(rows)
        fields = infer.infer_text_paths(rows, self.textmap.get, min_hit=0.0)
        fields = [f for f in fields if "[]" not in f["path"] and "." not in f["path"]]
        content = [f for f in fields if f["hit_rate"] >= 0.9]
        content = max(content, key=lambda f: f["median_len"], default=None)
        speaker = [f for f in fields if f is not content
                   and f["hit_rate"] >= self.REMINDER_SPEAKER_MIN_HIT]
        speaker = min(speaker, key=lambda f: f["median_len"], default=None)
        # 否决规则：正文必须明显长于说话人，否则多半是认错了字段（两个都是正文、或者
        # 说话人字段消失了），宁可整张表判失败，也不产出一份说话人与正文颠倒的语料
        if not content or not speaker or content["median_len"] < 3 * max(1, speaker["median_len"]):
            self.failures.append(infer.Failure(
                "ExcelBinOutput/ReminderExcelConfigData.json", "reminder_layout",
                "推不出正文 / 说话人两个文本字段", {"candidates": fields[:6]}))
            self.stats["reminder_failed"] = 1
            # 照样写一份空的：不写的话 emit 会读到上一次跑剩下的 reminders.jsonl
            open(os.path.join(self.out_dir, "reminders.jsonl"), "w").close()
            return
        self.stats["reminder_fields"] = {"content": infer.summarize_paths([content]),
                                         "speaker": infer.summarize_paths([speaker])}
        by_id = {r["id"]: r for r in rows if isinstance(r.get("id"), int)}

        # 7.1.0 起这张表省略取默认值的字段（0、false、枚举首值 `Normal` 一概不写），整数也
        # 改写成浮点（`showTime: 3.0`）；7.0.0 及以前是写全的。整张表找不到一个显式默认值，
        # 就按省略处理：缺的字段补回默认值、整数值的浮点还原成整数。7.1.0 与 7.0.0 共有的
        # 18 332 行这样补完逐字段一致（只差 1 行上游真改了的）；不补的话 `style` 有
        # 13 893 行会从 "Normal" 变成 null。表里出现过显式默认值时缺字段不补、不猜。
        omits_default = not any(
            v in (0, False, "") for r in rows for v in r.values()
            if not isinstance(v, (list, dict)))
        self.stats["reminder_omits_defaults"] = int(omits_default)

        def field(r, key):
            v = r.get(key)
            if not omits_default:
                return v
            if v is None:
                v = self.REMINDER_DEFAULTS[key]
            return int(v) if isinstance(v, float) and v.is_integer() else v

        def voice(r):
            # Voice 的 DungeonReminder 映射是正证据；没命中再依 hasAudio（含默认值补全）。
            # 判不了 generic（泛用语音）：带 `soundEffect` 的只有 10 条，而且互不重复
            v = field(r, "hasAudio")
            return "voiced" if r["id"] in self.voice_ids["DungeonReminder"] or v is True else \
                "unvoiced" if v is False else "unknown"
        for r in by_id.values():
            self.stats["reminder_voice_" + voice(r)] += 1
            if r["id"] in self.voice_ids["DungeonReminder"] and field(r, "hasAudio") is not True:
                self.stats["reminder_voice_mapping_overrides"] += 1

        def nxt(r):
            # `next` 指向自己（7.0.0 有 4 条）当链尾，不当环
            n = r.get("nextReminderId")
            return None if not n or n == r.get("id") else n

        self.stats["reminder_self_next"] = sum(
            1 for r in rows if r.get("nextReminderId") and r.get("nextReminderId") == r.get("id"))
        pointed = {nxt(r) for r in rows} - {None}
        self.stats["reminder_dangling_next"] = len(pointed - set(by_id))
        heads = sorted(set(by_id) - pointed)
        # 两条链可以汇进同一段尾巴（7.0.0 有 32 个汇合点）：每条链各自走到底，只防环；
        # 用全局 seen 截断的话，后走的那条会静默少掉共用的尾巴
        self.stats["reminder_merge_points"] = sum(
            1 for k, v in Counter(nxt(r) for r in rows).items() if k and v > 1)

        def walk(start):
            chain, cur, seen = [], start, set()
            while cur in by_id and cur not in seen:
                seen.add(cur)
                r = by_id[cur]
                chain.append({
                    "reminder_id": cur,
                    "speaker_hash": r.get(speaker["path"]) or None,
                    "content_hash": r.get(content["path"]) or None,
                    "style": field(r, "style"),
                    "show_time": field(r, "showTime"),
                    "delay": field(r, "delay"),
                    "voice": voice(r),
                })
                cur = nxt(r)
            return chain, seen

        reached = set()
        out = os.path.join(self.out_dir, "reminders.jsonl")
        with open(out, "w", encoding="utf-8") as f:
            def write(start, **extra):
                chain, seen = walk(start)
                reached.update(seen)
                f.write(json.dumps({"id": start, "lines": chain, **extra},
                                   ensure_ascii=False) + "\n")
                self.stats["reminder_chains"] += 1
                self.stats["reminder_lines"] += len(chain)

            for head in heads:
                write(head)
            # 没有链头的环（7.0.0 有一对互指的）：从最小 id 起走一圈单独成链、标出来，
            # 不能因为"找不到开头"就整段丢掉。走完这一步**每个 id 都在某条链上**（从链头
            # 走不到的 id 只可能在无头的环里，而这里把它们都走了），所以不再另数"没走到的"——
            # 以前那个 `reminder_unreached` 在这之后恒为 0，挂在它上面的硬失败永远不会响
            # （下游项目的一次审计查出来的）；要看的是 `reminder_cycles`。
            for start in sorted(set(by_id) - reached):
                if start not in reached:
                    write(start, cyclic=True)
                    self.stats["reminder_cycles"] += 1

    # ----------------------------------------------------------- 称谓

    PRONOUN_KEY = re.compile(r"^INFO_(?:MALE|FEMALE)_\w+$")
    """台词里 `{PLAYERAVATAR#SEXPRO[甲|乙]}` / `{MATEAVATAR#SEXPRO[…]}` 引用的键（第一个键是那个角色为男时用的、第二个为女时，
    和键名无关）：称谓 `INFO_*_PRONOUN_*`，以及日文句尾 `INFO_*_PLAYER_END0x`。键是上游的明文值（不是字段名），按它认行。"""
    PRONOUN_MIN_ROWS = 10

    def index_pronouns(self):
        """`ManualTextMapConfigData`：键名 -> TextMapHash 的对照表，只取按性别取的那些键（7.1.0：称谓 62 个 + 句尾 16 个）。

        两个字段都不认字段名（不变量 1）：**键字段**是取值匹配 `PRONOUN_KEY` 的那个顶层字符串字段，
        **文本字段**是在这些行上 TextMap 命中率最高的顶层整数字段（`infer.infer_text_paths`）。
        否决：认不出键字段、或文本字段命中率不到 0.9，整张表判失败、写空表，不产出键和文本错配的对照。"""
        path = os.path.join(self.upstream, "ExcelBinOutput", "ManualTextMapConfigData.json")
        out = os.path.join(self.out_dir, "pronouns.jsonl")
        rows = _load(path)
        self.stats["manual_textmap_rows"] = len(rows)
        keys = Counter(k for r in rows for k, v in r.items()
                       if isinstance(v, str) and self.PRONOUN_KEY.match(v))
        key = max(keys, key=keys.get, default=None)
        mine = [r for r in rows if key and isinstance(r.get(key), str) and self.PRONOUN_KEY.match(r[key])]
        fields = infer.infer_text_paths(mine, self.textmap.get, min_hit=0.0, min_count=1) if mine else []
        fields = [f for f in fields if "[]" not in f["path"] and "." not in f["path"]]
        text = max(fields, key=lambda f: f["hit_rate"], default=None)
        if len(mine) < self.PRONOUN_MIN_ROWS or not text or text["hit_rate"] < 0.9:
            self.failures.append(infer.Failure(
                "ExcelBinOutput/ManualTextMapConfigData.json", "pronoun_layout",
                "推不出称谓键 / 文本两个字段", {"key_candidates": dict(keys), "text_candidates": fields[:6],
                                            "rows": len(mine)}))
            self.stats["pronoun_failed"] = 1
            open(out, "w").close()      # 写空表：不写的话 emit 会读到上一次跑剩下的
            return
        self.stats["pronoun_fields"] = {"text": infer.summarize_paths([text])}
        by_key = {}
        for r in mine:
            by_key.setdefault(r[key], r.get(text["path"]))
        self.stats["pronoun_keys"] = len(by_key)
        self.stats["pronoun_duplicate_keys"] = len(mine) - len(by_key)
        with open(out, "w", encoding="utf-8") as f:
            for k in sorted(by_key):
                f.write(json.dumps({"id": k, "hash": by_key[k]}, ensure_ascii=False) + "\n")

    # ----------------------------------------------------------- 阅读面板长文本

    def index_readables(self):
        """阅读面板的长文本（来源与对齐方式见 `readable` 模块）。写 `readables.jsonl`，每行一条：
        `Readable/` 的是 `{source, id, files: {语种: 文件名}}`（id 是 `LocalizationExcelConfigData` 的行 id），
        配置表的是 `{source, id, hash}`（id 是那张表这一行的 id，字段名见 `readable.TABLES`）。文本在 emit 里解引用。

        失败都计非预期（不变量 2）：快照里缺了某个要产出的语种的 `Readable/<语种>/` 目录（sparse 规则是后加的，
        老快照要带取数跑一次 snapshot 才有；漏的是非基准语种时，那个语种整列会是 null，看着像上游缺文本）、本地化表里一行指向 `Readable/` 的都没有、同一行同一语种给了两个不同的文件、
        配置表缺失或推不出正文字段、id 不是整数或重复。"""
        items = self._readable_files()
        self.stats["readable_tables"] = {}
        for table, id_key in readable.TABLES:
            items += self._readable_table(table, id_key)
        with open(os.path.join(self.out_dir, "readables.jsonl"), "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        self.stats["readable_items"] = len(items)

    def _readable_fail(self, source, reason, **detail):
        self.failures.append(infer.Failure(source, "readable_layout", reason, detail))

    def _readable_files(self):
        """`LocalizationExcelConfigData` 里值指向 `Readable/` 的行 → 各语种的文件名。"""
        source = "ExcelBinOutput/LocalizationExcelConfigData.json"
        root = os.path.join(self.upstream, readable.DIR)
        # 每个要产出的语种都要有目录：缺目录是取数缺口，不是上游缺文本，和个别文件不存在分开计
        missing = [lang for lang in textmap.LANGS if not os.path.isdir(os.path.join(root, lang))]
        self.stats["readable_dirs_missing"] = missing
        for lang in missing:
            self._readable_fail(readable.SOURCE_DIR, "快照里没有 %s/%s/：sparse 规则里的 Readable/ 是后加的，"
                                "带取数跑一次 snapshot" % (readable.DIR, lang))
        if self.lang in missing:
            return []
        rows = _load(os.path.join(self.upstream, source))
        items, conflicts = [], 0
        for r in rows:
            files = {}
            for v in r.values():
                hit = readable.parse_path(v)
                if hit and files.setdefault(*hit) != hit[1]:
                    conflicts += 1
            if not files:
                continue
            if not _is_int(r.get("id")):
                self._readable_fail(source, "指向 Readable/ 的行没有整数 id", row=r)
                continue
            items.append({"source": readable.SOURCE_DIR, "id": r["id"], "files": dict(sorted(files.items()))})
        if conflicts:
            self._readable_fail(source, "同一行同一语种给了两个不同的 Readable/ 文件", rows=conflicts)
        if not items:
            self._readable_fail(source, "一行指向 Readable/ 的都没有")
        items.sort(key=lambda it: it["id"])
        if len({it["id"] for it in items}) != len(items):
            self._readable_fail(source, "指向 Readable/ 的行 id 重复")
        self.stats["readable_localization_rows"] = len(rows)
        self.stats["readable_file_rows"] = len(items)
        # 各语种目录里没有本地化记录指向的文件：有正文却没有 id、也对不齐别的语种，不收，只计数
        on_disk, unreferenced = {}, {}
        for lang in sorted(os.listdir(root)):
            if not os.path.isdir(os.path.join(root, lang)):
                continue
            names = sorted(n[:-4] for n in os.listdir(os.path.join(root, lang)) if n.endswith(".txt"))
            named = {it["files"][lang] for it in items if lang in it["files"]}
            on_disk[lang] = len(names)
            unreferenced[lang] = [n for n in names if n not in named]
        self.stats["readable_files_on_disk"] = on_disk
        self.stats["readable_files_unreferenced"] = {k: len(v) for k, v in unreferenced.items()}
        self.stats["readable_files_unreferenced_sample"] = unreferenced.get(self.lang, [])[:10]
        return items

    def _readable_table(self, table, id_key):
        """一张阅读界面配置表 → 每行的正文 hash。正文字段按结构认：TextMap 命中率不低于
        `TEXT_MIN_HIT` 的顶层整数字段里，文本长度中位数最长的那个（标题、署名都短）。"""
        source = "ExcelBinOutput/%s.json" % table
        path = os.path.join(self.upstream, source)
        if not os.path.exists(path):
            self._readable_fail(source, "阅读界面的配置表不在快照里")
            return []
        rows = _load(path)
        fields = infer.infer_text_paths(rows, self.textmap.get, min_hit=readable.TEXT_MIN_HIT, min_count=1)
        fields = [f for f in fields if "[]" not in f["path"] and "." not in f["path"] and f["path"] != id_key]
        text = max(fields, key=lambda f: f["median_len"], default=None)
        if not text or text["median_len"] < readable.TEXT_MIN_MEDIAN:
            self._readable_fail(source, "推不出正文字段", candidates=fields[:6])
            return []
        items, no_hash = [], 0
        for r in rows:
            if not _is_int(r.get(id_key)):
                self._readable_fail(source, "行没有整数 id（%s）" % id_key, row=r)
            elif not r.get(text["path"]):
                no_hash += 1      # 这一行没有正文（字段省略或为 0）
            else:
                items.append({"source": table, "id": r[id_key], "hash": r[text["path"]]})
        items.sort(key=lambda it: it["id"])
        if len({it["id"] for it in items}) != len(items):
            self._readable_fail(source, "行 id 重复")
        self.stats["readable_tables"][table] = {
            "rows": len(rows), "with_text": len(items), "no_hash": no_hash,
            "field": infer.summarize_paths([text])[0]}
        return items

    # ----------------------------------------------------------- 汇总

    def finish(self):
        path = os.path.join(self.build, "unparsed.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for fail in self.failures:
                f.write(json.dumps(fail.as_dict(), ensure_ascii=False) + "\n")
        expected = sum(1 for f in self.failures if f.expected)
        self.stats["failures"] = len(self.failures)
        self.stats["failures_expected"] = expected
        self.stats["failures_unexpected"] = len(self.failures) - expected
        return dict(self.stats)


def _collect_path(node, parts):
    """按 infer.walk_ints 的路径写法取值，'[]' 表示遍历数组。"""
    if not parts:
        if isinstance(node, int) and not isinstance(node, bool):
            yield node
        return
    head, rest = parts[0], parts[1:]
    if head == "[]":
        if isinstance(node, list):
            for v in node:
                yield from _collect_path(v, rest)
    elif isinstance(node, dict) and head in node:
        yield from _collect_path(node[head], rest)
