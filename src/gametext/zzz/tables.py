"""把 FileCfg 的几张关键表解析成结构：场景元信息、任务表、短信分支图、场景↔任务边。

**文件名是锚点，字段名一律推断**（见 filecfg.py）。每张表都带一条否决规则：推断出的
结果必须能被一个独立事实验证，验不过就记失败、不产出——错误解析看起来是绿的，比失败
更危险（genshin 的教训）。

三个实测事实决定了这里的结构：

1. `PerformTemplateTb` 的主键**就是 TextMap key 里的场景 id**（20 431/25 218 命中）。
   它顺带给出资源路径 `.../Perform/Data/<Kind>/<Group>/<name>_<id>.asset`，
   于是每个场景能拿到"是 GalGame 还是 Chat/Bubble"和所属分组。
2. **对话分支不在上游**：`Data/ScriptConfig/` 整个目录不在仓库里，Perform 表只给
   资源路径，脚本本身没有。所以 GalGame/Chat 的选项与跳转拿不到——这是上游的边界，
   不是解析没做。
3. **短信系统是唯一有完整分支图的对话**：`MessageConfigTemplateTb` 自带 step 编号、
   两个选项及各自的跳转目标，全在 FileCfg 里。
"""

from __future__ import annotations

from collections import Counter, defaultdict

from . import filecfg

PERFORM = "PerformTemplateTb.json"
QUEST = "QuestConfigTemplateTb.json"
MESSAGE = "MessageConfigTemplateTb.json"
MESSAGE_GROUP = "MessageGroupConfigTemplateTb.json"
MESSAGE_NPC = "MessageNPCTemplateTb.json"

# 资源路径形如 Data/ScriptConfig/Perform/Data/<Kind>/<Group>/<name>_<id>.asset
_PERFORM_ANCHOR = "/Perform/Data/"


class Failure(Exception):
    """推断被否决。调用方负责计数并落盘，不许静默跳过。"""


def _split_asset(path):
    """从资源路径里取 (kind, group)。取不到就 (None, None)，不猜。"""
    if not path or _PERFORM_ANCHOR not in path:
        return None, None
    tail = path.split(_PERFORM_ANCHOR, 1)[1]
    parts = [p for p in tail.split("/") if p]
    if len(parts) < 2:
        return None, None
    return parts[0], parts[-2] if len(parts) >= 3 else None


class Perform:
    """场景元信息：id -> 类型 / 分组 / 资源路径 / 标题与简介的文本 key。"""

    def __init__(self, upstream, text_keys, scene_ids):
        _, rows = filecfg.load(upstream, PERFORM)
        if not rows:
            raise Failure("%s 不存在或不是行数组" % PERFORM)
        self.id_field = filecfg.id_field(rows)
        if not self.id_field:
            raise Failure("%s 推不出主键（没有唯一整数字段）" % PERFORM)

        ids = {str(r[self.id_field]) for r in rows}
        # 否决规则：主键必须真的是"对话场景 id"。推错字段时这个覆盖率会立刻塌掉。
        big = {s for s in scene_ids if len(s) >= 6}
        self.scene_coverage = len(ids & big) / len(big) if big else 0.0
        if self.scene_coverage < 0.40:
            raise Failure("%s 的主键 %s 只覆盖 %.1f%% 的场景 id，判定推断失败"
                          % (PERFORM, self.id_field, 100 * self.scene_coverage))

        # 资源路径字段：取值最常带 Perform 资源路径锚点的那个
        counts = Counter()
        for field in filecfg.order(rows):
            for r in rows:
                v = r.get(field)
                if isinstance(v, str) and _PERFORM_ANCHOR in v:
                    counts[field] += 1
        self.asset_field = counts.most_common(1)[0][0] if counts else None

        tf = filecfg.text_fields(rows, text_keys)
        prefixes = filecfg.by_prefix(tf)
        self.title_field = prefixes.get("Title")
        self.intro_field = prefixes.get("Intro")

        self.by_id = {}
        kinds = Counter()
        for r in rows:
            asset = r.get(self.asset_field) if self.asset_field else None
            kind, group = _split_asset(asset if isinstance(asset, str) else None)
            kinds[kind or "?"] += 1
            self.by_id[str(r[self.id_field])] = {
                "perform_id": str(r[self.id_field]),
                "kind": kind,
                "group": group,
                "asset": asset or None,
                "title_key": r.get(self.title_field) or None if self.title_field else None,
                "intro_key": r.get(self.intro_field) or None if self.intro_field else None,
            }
        self.kinds = dict(kinds.most_common())
        self.ids = ids

    def stats(self):
        return {
            "rows": len(self.by_id),
            "id_field": self.id_field,
            "asset_field": self.asset_field,
            "title_field": self.title_field,
            "intro_field": self.intro_field,
            "scene_id_coverage": round(self.scene_coverage, 4),
            "kinds": self.kinds,
        }


class Quests:
    """任务表：id -> 文本 key + 前置/后继任务。

    比只看 TextMap 多出来的东西：任务链（前置/后继）、游戏里实际显示的标题（子任务的
    配置名指向父任务），以及"配置表引用了但 TextMap 根本没有的 key"——那是上游的废弃
    内容，计数上报但不往下传。
    """

    def __init__(self, upstream, text_keys):
        _, rows = filecfg.load(upstream, QUEST)
        if not rows:
            raise Failure("%s 不存在或不是行数组" % QUEST)
        self.id_field = filecfg.id_field(rows)
        if not self.id_field:
            raise Failure("%s 推不出主键" % QUEST)

        tf = filecfg.text_fields(rows, text_keys)
        prefixes = filecfg.by_prefix(tf)
        self.fields = {
            "name": prefixes.get("QuestName"),
            "desc": prefixes.get("QuestDesc"),
            "target": prefixes.get("QuestTarget"),
            "finish": prefixes.get("QuestFinishDec"),
        }
        if not self.fields["name"]:
            raise Failure("%s 找不到指向 QuestName_* 的字段" % QUEST)

        self.ids = {str(r[self.id_field]) for r in rows}
        self.prev_field, self.next_field, self.chain = self._infer_chain(rows)

        self.by_id = {}
        self.dangling = 0
        for r in rows:
            qid = str(r[self.id_field])
            entry = {
                "quest_id": qid,
                "prev_quests": filecfg.refs(r, self.prev_field) if self.prev_field else [],
                "next_quests": filecfg.refs(r, self.next_field) if self.next_field else [],
            }
            for label, field in self.fields.items():
                key = r.get(field) if field else None
                if key and key not in text_keys:
                    # 配置表引用了 TextMap 里根本没有的 key（废弃/未上线内容）。
                    # 计数上报，但不往下传——传下去只会变成一堆解析不出的空文本。
                    self.dangling += 1
                    key = None
                entry[label + "_key"] = key or None
            self.by_id[qid] = entry

    def _infer_chain(self, rows):
        """任务链：两个互为逆关系的自引用字段，一个前置一个后继。

        实测（3.2.0）表里恰有两个字段的取值大量落回本表 id 全集，且**每一条边在对方
        字段里都有反向边**（5903/5903）。互逆只能证明"这两个字段是同一关系的两个方向"，
        定不了谁是前置——方向靠 id 序：92% 的边里，前置字段指向更小的 id。

        这条判据是推断，不是上游明说的；置信度随统计一起写进报告，方向要是翻了看得见。
        """
        cand = filecfg.ref_fields(rows, self.ids, min_rate=0.5, min_hits=100,
                                  exclude={self.id_field})
        fields = sorted(cand, key=lambda f: -cand[f][0])[:2]
        if len(fields) < 2:
            return (fields[0] if fields else None), None, {"paired": False}

        a, b = fields
        by_id = {r[self.id_field]: r for r in rows}
        inverse = total = 0
        older = {a: 0, b: 0}
        for r in rows:
            me = r[self.id_field]
            for f, other in ((a, b), (b, a)):
                for x in filecfg.scalars(r.get(f)):
                    if not isinstance(x, int):
                        continue
                    total += 1
                    if x < me:
                        older[f] += 1
                    peer = by_id.get(x)
                    if peer and me in (filecfg.scalars(peer.get(other))):
                        inverse += 1
        share = {f: older[f] / max(1, sum(1 for r in rows
                                          for x in filecfg.scalars(r.get(f))
                                          if isinstance(x, int)))
                 for f in (a, b)}
        prev_f = a if share[a] >= share[b] else b
        next_f = b if prev_f is a else a
        return prev_f, next_f, {
            "paired": True,
            "inverse_edge_rate": round(inverse / total, 4) if total else 0.0,
            "prev_points_to_smaller_id_rate": round(share[prev_f], 4),
        }

    def stats(self):
        return {
            "rows": len(self.by_id),
            "id_field": self.id_field,
            "text_fields": dict(self.fields),
            "prev_field": self.prev_field,
            "next_field": self.next_field,
            "chain_inference": self.chain,
            "text_keys_absent_from_textmap": self.dangling,
        }


class Messages:
    """短信系统：group -> 按 step 分节的消息与二选一分支。

    分支语义（实测 group 1003 人工核对过）：每条消息带一个 step 编号；带选项的那行
    给出两个选项文本 key 与各自的目标 step。选项与目标的配对靠**行内字段顺序**——
    上游导出保持类定义顺序，比字段名跨版本稳定；这一条是推断，记在报告里。
    """

    def __init__(self, upstream, text_keys):
        _, rows = filecfg.load(upstream, MESSAGE)
        if not rows:
            raise Failure("%s 不存在或不是行数组" % MESSAGE)
        _, grows = filecfg.load(upstream, MESSAGE_GROUP)
        _, nrows = filecfg.load(upstream, MESSAGE_NPC)

        self.id_field = filecfg.id_field(rows)
        if not self.id_field:
            raise Failure("%s 推不出主键" % MESSAGE)

        tf = filecfg.text_fields(rows, text_keys)
        prefixes = filecfg.by_prefix(tf)
        self.text_field = prefixes.get("Message")
        if not self.text_field:
            raise Failure("%s 找不到指向 Message_* 的字段" % MESSAGE)
        # Option01 / Option02 / OptionLong01 / OptionLong02，按行内顺序排
        row_order = filecfg.order(rows)
        opt_fields = [f for f in row_order
                      if f in tf and tf[f][0].startswith("Option")]
        self.short_opts = [f for f in opt_fields if "Long" not in tf[f][0]]
        self.long_opts = {f: tf[f][0] for f in opt_fields if "Long" in tf[f][0]}
        if not self.short_opts:
            raise Failure("%s 找不到指向 Option* 的字段" % MESSAGE)

        # 分组字段：取值落在 MessageGroupConfig 的主键全集里
        self.group_field = self.group_ids = None
        self.group_quests = {}
        if grows:
            g_id = filecfg.id_field(grows)
            if g_id:
                gids = {str(r[g_id]) for r in grows}
                cand = filecfg.ref_fields(rows, gids, min_rate=0.9, min_hits=100,
                                          exclude={self.id_field}, min_len=1)
                if cand:
                    self.group_field = max(cand, key=lambda f: cand[f][0])
                self.group_ids = gids

        # NPC 字段：取值落在 MessageNPC 的主键全集里；说话人名字在 NPC 表的文本字段
        self.npc_field = self.npc_name_field = None
        self.npc_by_id = {}
        if nrows:
            n_id = filecfg.id_field(nrows)
            if n_id:
                nids = {str(r[n_id]) for r in nrows}
                cand = filecfg.ref_fields(rows, nids, min_rate=0.9, min_hits=100,
                                          exclude={self.id_field}, min_len=1)
                if cand:
                    self.npc_field = max(cand, key=lambda f: cand[f][0])
                ntf = filecfg.text_fields(nrows, text_keys)
                nprefix = filecfg.by_prefix(ntf)
                self.npc_name_field = (nprefix.get("Message_NPC")
                                       or (sorted(ntf)[0] if ntf else None))
                for r in nrows:
                    self.npc_by_id[str(r[n_id])] = (
                        r.get(self.npc_name_field) if self.npc_name_field else None)

        by_group = defaultdict(list)
        for r in rows:
            g = str(r.get(self.group_field)) if self.group_field else "?"
            by_group[g].append(r)

        self.step_field = self._infer_step_field(rows, by_group, row_order)
        if not self.step_field:
            raise Failure("%s 推不出 step 字段（组内不构成 1..k 的连续编号）" % MESSAGE)
        self.goto_fields = self._infer_goto_fields(rows, row_order)
        if len(self.goto_fields) < len(self.short_opts):
            raise Failure("%s 选项 %d 个，但只推出 %d 个跳转字段"
                          % (MESSAGE, len(self.short_opts), len(self.goto_fields)))

        # 组 -> 任务：短信组配置里指向任务 id 的字段，交给 build() 时外部补
        self.rows = rows
        self.by_group = by_group
        self.grows = grows
        self.dangling_goto = 0

    @staticmethod
    def _infer_step_field(rows, by_group, row_order):
        """step 字段：组内取值构成 1..k 连续编号的那个整数字段。

        判据取**相对压倒**而非绝对阈值：实测正确字段只有 0.79 的组是严格连续的
        （上游自己留了空号，如 [1,2,3,4,6,7,8,9]），但其余每个整数字段都是 0.00，
        区分度极大。所以要求"最高分 ≥0.5 且至少是次高分的 3 倍"。
        """
        scores = {}
        for field in row_order:
            vals = [r.get(field) for r in rows]
            if any(isinstance(v, bool) or not isinstance(v, int) for v in vals):
                continue
            if len(set(vals)) == len(rows):     # 唯一 => 是主键不是 step
                continue
            good = 0
            for grows in by_group.values():
                s = sorted({r.get(field) for r in grows})
                if s and s == list(range(1, len(s) + 1)):
                    good += 1
            scores[field] = good / len(by_group)
        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        best, top = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else 0.0
        if top < 0.5 or (runner and top < 3 * runner):
            return None
        return best

    def _infer_goto_fields(self, rows, row_order):
        """跳转字段：非零取值几乎只出现在"有选项的行"上、且覆盖了大部分选项行。

        两个条件缺一不可。只要"几乎只出现在选项行"的话，一个只填了 155 行的杂项字段
        也会混进来（实测确有一个），配对时就可能顶掉真正的跳转字段。
        """
        opt_rows = {id(r) for r in rows if any(r.get(f) for f in self.short_opts)}
        out = []
        for field in row_order:
            nz = [r for r in rows
                  if isinstance(r.get(field), int) and not isinstance(r.get(field), bool)
                  and r.get(field)]
            if len(nz) < 100 or len(nz) < 0.5 * len(opt_rows):
                continue
            share = sum(1 for r in nz if id(r) in opt_rows) / len(nz)
            if share >= 0.95:
                out.append(field)
        return out

    def build(self, quest_ids):
        """产出每组一条记录；同时把组关联的任务 id 带上（如果配置表里有）。"""
        quest_field = None
        if self.grows and quest_ids:
            g_id = filecfg.id_field(self.grows)
            cand = filecfg.ref_fields(self.grows, quest_ids, min_rate=0.9,
                                      min_hits=50, exclude={g_id} if g_id else ())
            if cand:
                quest_field = max(cand, key=lambda f: cand[f][0])
                g_id_field = g_id
                for r in self.grows:
                    self.group_quests[str(r[g_id_field])] = filecfg.refs(r, quest_field)
        self.quest_field = quest_field

        row_order = filecfg.order(self.rows)
        # 选项 -> 跳转：按行内顺序，每个选项 key 字段配它后面第一个未被占用的跳转字段
        pairing = {}
        remaining = list(self.goto_fields)
        for field in row_order:
            if field in self.short_opts:
                nxt = [g for g in remaining if row_order.index(g) > row_order.index(field)]
                if nxt:
                    pairing[field] = nxt[0]
                    remaining.remove(nxt[0])
        self.pairing = pairing

        out = []
        for gid, rows in sorted(self.by_group.items(),
                                key=lambda kv: (len(kv[0]), kv[0])):
            steps = {r.get(self.step_field) for r in rows}
            nodes = defaultdict(lambda: {"messages": [], "options": []})
            for r in sorted(rows, key=lambda x: (x.get(self.step_field),
                                                 x[self.id_field])):
                step = r.get(self.step_field)
                node = nodes[step]
                text_key = r.get(self.text_field) or None
                if text_key:
                    npc = (str(r.get(self.npc_field)) if self.npc_field
                           and r.get(self.npc_field) else None)
                    node["messages"].append({
                        "message_id": str(r[self.id_field]),
                        "text_key": text_key,
                        "npc": npc,
                        "npc_name_key": self.npc_by_id.get(npc) if npc else None,
                    })
                for opt in self.short_opts:
                    key = r.get(opt)
                    if not key:
                        continue
                    goto = r.get(self.pairing.get(opt))
                    if goto and goto not in steps:
                        self.dangling_goto += 1
                        goto = None
                    node["options"].append({
                        "text_key": key,
                        "goto_step": goto or None,
                    })
            out.append({
                "group_id": gid,
                "quests": self.group_quests.get(gid, []),
                "nodes": [{"step": s, **nodes[s]} for s in sorted(nodes)],
            })
        return out

    def stats(self):
        return {
            "rows": len(self.rows),
            "groups": len(self.by_group),
            "id_field": self.id_field,
            "group_field": self.group_field,
            "step_field": self.step_field,
            "text_field": self.text_field,
            "option_fields": self.short_opts,
            "goto_fields": self.goto_fields,
            "option_to_goto": getattr(self, "pairing", {}),
            "npc_field": self.npc_field,
            "group_quest_field": getattr(self, "quest_field", None),
            "dangling_goto_steps": self.dangling_goto,
        }


def scene_quest_edges(upstream, perform_ids, quest_ids, min_rate=0.3, min_hits=30,
                      min_abs_hits=150):
    """全表扫描找"桥表"：同一行里既有指向 Perform 的字段又有指向 Quest 的字段。

    不写死是哪几张表——版本更新新增了桥表也能自动接上。代价是要过一遍 204 MB。
    """
    edges = []
    sources = []
    for name, _top, rows in filecfg.iter_tables(upstream):
        # 一张表自己的主键不是"对 Perform 的引用"——两个 id 空间重叠就会撞出假桥
        # （实测 KnowledgeConfig 的主键有 60% 落在 Perform id 里，纯属巧合）。
        # 任务侧不设这条：ArchiveFileQuest 正是以任务 id 为主键的合法桥表。
        own_id = filecfg.id_field(rows)
        pf = filecfg.ref_fields(rows, perform_ids, min_rate, min_hits,
                                exclude={own_id} if own_id else (),
                                min_abs_hits=min_abs_hits)
        if not pf:
            continue
        qf = filecfg.ref_fields(rows, quest_ids, min_rate, min_hits,
                                min_abs_hits=min_abs_hits)
        qf = {f: v for f, v in qf.items() if f not in pf}
        if not qf:
            continue
        p_field = max(pf, key=lambda f: pf[f][0])
        q_field = max(qf, key=lambda f: qf[f][0])
        n = 0
        for r in rows:
            ps = [p for p in filecfg.refs(r, p_field) if p in perform_ids]
            qs = [q for q in filecfg.refs(r, q_field) if q in quest_ids]
            for p in ps:
                for q in qs:
                    edges.append({"perform_id": p, "quest_id": q, "via": name})
                    n += 1
        if n:
            sources.append({"table": name, "perform_field": p_field,
                            "quest_field": q_field, "edges": n})
    return edges, sources
