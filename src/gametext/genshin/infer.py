"""结构推断：识别混淆 JSON 里各字段的语义角色。

BinOutput/** 的字段名是随机大写串，逐版本变化，因此不能硬编码（见
docs/genshin/data-source.md）。本模块只认结构特征，不认业务概念：谁是对话数组、
谁是 dialogId、谁是 next、谁是说话人、谁是文本 hash，全靠形状和引用关系推。

推断以 **schema signature 为单位**，不是逐文件：同一份快照里同一种 signature
的文件共用一套字段名，把证据在这些文件之间汇总，单节点文件也能沿用多节点
文件推出的结论。signature = 顶层 key 集合。

另一半是 `infer_id_paths`：BinOutput/Quest 的字段名同样混淆，但它引用的 id
（主任务 id、talkId）都能从别处独立拿到明文集合，于是"哪个路径的取值几乎全
落在某个已知集合里"就是可验证的判据。

失败一律返回 Failure 对象并附原因，绝不静默跳过 —— 见 AGENTS.md 不变量 2。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

# 混淆之中留下的明文锚点：说话人对象内部的枚举值
TALK_ROLE_PREFIX = "TALK_ROLE_"

# 文本 hash 是 uint32，实测最小的也在六位以上；dialogId 同样是大整数，
# 二者靠 TextMap 命中率区分，这里只用来先滤掉 0/1/枚举下标之类的小整数。
MIN_HASH = 100000

# 正文字段的最低得分（覆盖率 x TextMap 命中率）。低于此值就判定"这个数组不是
# 对话列表"。实测各子目录的最优文本字段得分：Quest 0.99、FreeGroup 0.98、
# 未混淆 schema 0.40、Cutscene 0.28，而 talk 容器目录（*Group）低于 0.01。
# 0.1 能干净地切开这两类。
MIN_CONTENT_SCORE = 0.1


@dataclass(frozen=True)
class Signature:
    """按**顶层 key 集合**分组。

    不把节点 key 纳入 signature：合法的空 talk（dialogList 为空）节点 key 集
    合是空的，若一并纳入就会被切成独立分组，反而推不出 schema。节点 key 记在
    evidence 里备查。
    """

    top: tuple

    def short(self) -> str:
        return "top[%d]:%s" % (len(self.top), ",".join(self.top))


@dataclass
class TalkSchema:
    """一种 signature 下各字段的语义角色。"""

    signature: Signature
    id_key: str
    next_key: str
    role_key: Optional[str]
    content_key: Optional[str]
    other_hash_keys: tuple = ()
    evidence: dict = field(default_factory=dict)


# 已定性、不视为异常的失败原因前缀。这类"失败"是结论而非事故：我们主动判定
# 这批文件不是对话列表，记录在案即可，不该让流水线红掉。
EXPECTED_FAILURE_PREFIXES = ("no text field",)


@dataclass
class Failure:
    source: str
    stage: str
    reason: str
    detail: dict = field(default_factory=dict)

    expected_override: bool = False

    @property
    def expected(self) -> bool:
        return self.expected_override or self.reason.startswith(
            EXPECTED_FAILURE_PREFIXES)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "stage": self.stage,
            "reason": self.reason,
            "expected": self.expected,
            "detail": self.detail,
        }


# ---------------------------------------------------------------- 结构探测


def find_dialog_list(doc: dict):
    """返回 (key, 节点列表)。取"元素全是 dict"的顶层数组，含说话人对象的优先。

    **空数组也算命中**：实测有一批 talk 文件是合法的空壳（只有 talkId 和一个
    空 dialogList），把它们当解析失败会污染失败计数。返回空列表由调用方区分。
    """
    candidates = [
        (k, v)
        for k, v in doc.items()
        if isinstance(v, list) and all(isinstance(x, dict) for x in v)
    ]
    if not candidates:
        return None
    scored = [
        (1 if v and _has_talk_role(v[0]) else 0, len(v), k, v) for k, v in candidates
    ]
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    _, _, key, nodes = scored[0]
    return key, nodes


def _has_talk_role(node: dict) -> bool:
    return find_role_key(node) is not None


def find_role_key(node: dict):
    """说话人字段：值是 dict，且其中某个值是 TALK_ROLE_* 明文枚举。"""
    for k, v in node.items():
        if isinstance(v, dict) and any(
            isinstance(x, str) and x.startswith(TALK_ROLE_PREFIX) for x in v.values()
        ):
            return k
    return None


def signature_of(doc: dict):
    """(signature, 节点列表, 失败原因)。nodes 可能是空列表——那是合法的空 talk。"""
    found = find_dialog_list(doc)
    if not found:
        return None, None, "no dialog list: 顶层没有元素全为 dict 的数组"
    _, nodes = found
    return Signature(tuple(sorted(doc.keys()))), nodes, None


# ---------------------------------------------------------------- 字段推断


def _int_list_keys(nodes) -> Counter:
    c = Counter()
    for n in nodes:
        for k, v in n.items():
            if isinstance(v, list) and v and all(isinstance(x, int) for x in v):
                c[k] += 1
    return c


def _int_keys(nodes) -> set:
    keys = set()
    for n in nodes:
        for k, v in n.items():
            if isinstance(v, int) and not isinstance(v, bool) and v >= MIN_HASH:
                keys.add(k)
    return keys


def _values_of(nodes, key) -> list:
    out = []
    for n in nodes:
        v = n.get(key)
        if isinstance(v, int) and not isinstance(v, bool):
            out.append(v)
    return out


def _id_by_uniqueness(all_nodes, in_textmap):
    """next 判据失效时的后备：id 是"逐节点唯一且不是文本"的整数字段。

    返回 (key, 失败原因)。评分 = 取值唯一率 x 覆盖率 x (1 - TextMap 命中率)。
    """
    total = len(all_nodes)
    best = None
    best_score = 0.0
    for key in _int_keys(all_nodes):
        vals = _values_of(all_nodes, key)
        if not vals:
            continue
        unique = len(set(vals)) / len(vals)
        coverage = len(vals) / total
        big = [v for v in vals if v >= MIN_HASH]
        text_rate = (
            sum(1 for v in big if in_textmap(v)) / len(big) if big else 0.0
        )
        score = unique * coverage * (1.0 - text_rate)
        if score > best_score:
            best, best_score = key, score
    if best is None or best_score < 0.5:
        return None, ("没有「逐节点唯一且非文本」的整数字段"
                      "（最佳得分 %.2f）" % best_score)
    return best, None


def infer_schema(
    signature: Signature,
    node_batches: Iterable,
    in_textmap: Callable[[int], bool],
):
    """汇总同一 signature 的多份节点列表，推出字段角色。

    node_batches: 若干份 nodes（每份来自一个文件）。
    in_textmap:   hash -> bool，用于判定"这个整数字段是文本 hash"。

    返回 (TalkSchema, None) 或 (None, 原因字符串)。
    """
    batches = [b for b in node_batches if b]
    if not batches:
        return None, "no nodes: 该 signature 下的文件全是空 talk，无从推断"

    all_nodes = [n for b in batches for n in b]
    node_keys = sorted({k for n in all_nodes for k in n})

    # 1) next: 唯一的整数数组字段。**可以不存在** —— 有的子目录（NpcOther）全是
    #    单节点对话，压根没有 next 字段，那不是解析失败。
    list_keys = _int_list_keys(all_nodes)
    next_key = list_keys.most_common(1)[0][0] if list_keys else None

    next_union = set()
    if next_key:
        for n in all_nodes:
            v = n.get(next_key)
            if isinstance(v, list):
                next_union.update(x for x in v if isinstance(x, int))

    # 2) id: 取值集合与 next 并集重合度最高的整数字段
    #    （对话是链/树，除根节点外每个节点都被恰好引用一次）
    int_keys = _int_keys(all_nodes)
    if not int_keys:
        return None, "no int fields: 节点里没有可作 id 的大整数字段"

    id_scores = {}
    for k in int_keys:
        vals = set(_values_of(all_nodes, k))
        if not vals:
            continue
        id_scores[k] = len(vals & next_union) / len(vals)
    if not id_scores:
        return None, "no id candidates"

    id_key = max(id_scores, key=lambda k: id_scores[k]) if id_scores else None
    id_basis = "next_overlap"
    if id_key is None or not next_union or id_scores[id_key] < 0.5:
        # 后备判据：next 用不上时（没有 next 字段，或 next 指向的是别的文件里的
        # 节点），改用"每个节点一个不同的值、且查不到文本"来认 id。
        # 文本 hash 的 TextMap 命中率接近 1，dialogId 接近 0，区分度很干净。
        id_key, reason = _id_by_uniqueness(all_nodes, in_textmap)
        id_basis = "uniqueness"
        if id_key is None:
            return None, "id ambiguous: %s" % reason

    # 3) 文本 hash: 用**覆盖率 × TextMap 命中率**打分，最高者为正文。
    #
    #    两个维度缺一不可，实测都有反例：
    #    - 只看命中率：主 schema 下正文、说话人名、头衔命中率都是 1.0，区分不开
    #      （正文覆盖 99.4% 的节点，人名只有 4.3%，头衔 0.9%）。
    #    - 只看覆盖率：hex-named schema 下人名字段覆盖率虽低但命中率高，而正文
    #      字段命中率只有 0.71（有一批文本已从 TextMap 移除），硬卡命中率阈值
    #      会把正文判成非文本，反而选中人名。
    total_nodes = len(all_nodes)
    hash_scores = {}
    coverage = {}
    for k in int_keys:
        if k == id_key:
            continue
        vals = [v for v in _values_of(all_nodes, k) if v >= MIN_HASH]
        if not vals:
            continue
        hash_scores[k] = sum(1 for v in vals if in_textmap(v)) / len(vals)
        coverage[k] = len(vals) / total_nodes

    text_score = {k: coverage[k] * hash_scores[k] for k in hash_scores}
    best_score = 0.0
    content_key = None
    if text_score:
        best = max(text_score, key=lambda k: text_score[k])
        best_score = text_score[best]
        if best_score >= MIN_CONTENT_SCORE:
            content_key = best

    # 正文字段太弱 ⇒ 这多半根本不是对话列表。实测 BinOutput/Talk 下的 `*Group`
    # 目录是 talk **容器**（一个文件列若干 talk），硬按对话解会产出两万多个几乎
    # 没有正文的节点 —— 比解析失败更糟，因为它看起来是成功的。
    # 宁可判失败进 unparsed.jsonl，也不要产出垃圾（AGENTS.md 不变量 2）。
    if content_key is None:
        return None, (
            "no text field: %d 个节点里最强的文本字段得分只有 %.4f（阈值 %.2f），"
            "该数组多半不是对话列表" % (len(all_nodes), best_score, MIN_CONTENT_SCORE)
        )
    other = sorted(
        (k for k, r in hash_scores.items() if k != content_key and r >= 0.5),
        key=lambda k: -coverage[k],
    )

    role_key = None
    for n in all_nodes:
        role_key = find_role_key(n)
        if role_key:
            break

    schema = TalkSchema(
        signature=signature,
        id_key=id_key,
        next_key=next_key,
        role_key=role_key,
        content_key=content_key,
        other_hash_keys=tuple(other),
        evidence={
            "files": len(batches),
            "nodes": len(all_nodes),
            "id_basis": id_basis,
            "id_overlap": round(id_scores.get(id_key, 0.0), 4),
            "id_runner_up": round(
                sorted(id_scores.values(), reverse=True)[1], 4
            )
            if len(id_scores) > 1
            else None,
            "textmap_hit": {k: round(v, 4) for k, v in hash_scores.items()},
            "coverage": {k: round(v, 4) for k, v in coverage.items()},
            "node_keys": node_keys,
        },
    )
    return schema, None


# ---------------------------------------------------------------- 归一化


def normalize_talk(doc: dict, schema: TalkSchema, source: str):
    """按推出的 schema 把一个 talk 文件展平成统一节点列表。

    返回 (nodes, failure)。文本仍是 hash，解引用留给 emit 阶段。
    """
    found = find_dialog_list(doc)
    if not found:
        return None, Failure(source, "normalize", "no dialog list")
    _, raw_nodes = found

    out = []
    for raw in raw_nodes:
        role = raw.get(schema.role_key) if schema.role_key else None
        role_out = None
        if isinstance(role, dict):
            # 说话人对象的键是明文：7.0.0 叫 `_id` / `_type`，7.1.0 改叫 `id` / `type`。
            # 7.1.0 起枚举首值 `TALK_ROLE_NONE` 作为默认值被省略（7.0.0 里它占 0.29%，
            # 7.1.0 缺 type 的也是 0.29%），对象在、类型缺，就是它。
            role_out = {
                "type": next(
                    (
                        v
                        for v in role.values()
                        if isinstance(v, str) and v.startswith(TALK_ROLE_PREFIX)
                    ),
                    TALK_ROLE_PREFIX + "NONE",
                ),
                # id 的默认值是空串，7.1.0 起上游可能省略它（陷阱清单第 11 条），缺键时补回空串
                "id": role.get("_id", role.get("id", "")),
            }
        nxt = raw.get(schema.next_key)
        out.append(
            {
                "dialog_id": raw.get(schema.id_key),
                "next": [x for x in nxt if isinstance(x, int)]
                if isinstance(nxt, list)
                else [],
                "role": role_out,
                "content_hash": raw.get(schema.content_key)
                if schema.content_key
                else None,
                "other_hashes": {
                    k: raw.get(k) for k in schema.other_hash_keys if raw.get(k)
                },
                "source": source,
            }
        )
    return out, None


# ------------------------------------------------- 用已知 id 宇宙定位字段路径


def walk_ints(node, path=()):
    """产出 (路径, 整数值)。路径里数组下标统一记作 '[]'。"""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk_ints(v, path + (k,))
    elif isinstance(node, list):
        for v in node:
            yield from walk_ints(v, path + ("[]",))
    elif isinstance(node, int) and not isinstance(node, bool):
        yield ".".join(path), node


def infer_id_paths(docs, universes, min_hit=0.9, min_count=10):
    """在一批同构文档里，找出各"已知 id 集合"分别落在哪个 JSON 路径上。

    这是结构推断的另一半：BinOutput/Quest 的字段名同样是混淆的，但它引用的
    id（主任务 id、talkId）都能从别处独立拿到明文集合，于是"哪个路径的取值
    几乎全都落在某个已知集合里"就成了可验证的判据。

    universes: {名字: 已知 id 的 set}。名字对本模块无意义，只是原样带回，
               业务含义由调用方负责——保持本模块不认识"任务""对话"。

    返回 {名字: [row, ...]}，row 含 path / hit_rate / count / values / coverage，
    按 coverage 降序。**coverage（该路径命中的不重复 id 占整个宇宙的比例）比
    hit_rate 更能区分真假**：宇宙动辄两万个 id 时，总有语义无关的字段碰巧全部
    命中，它们 hit_rate 也是 1.0，却只覆盖宇宙的零头。真正的引用字段覆盖率接近 1。
    选路径请用 `pick_reference_paths`，别直接吃整张表。
    """
    hit_values = defaultdict(lambda: defaultdict(set))
    hit_counts = defaultdict(Counter)
    totals = Counter()
    for doc in docs:
        for path, value in walk_ints(doc):
            totals[path] += 1
            for name, universe in universes.items():
                if value in universe:
                    hit_values[name][path].add(value)
                    hit_counts[name][path] += 1

    out = {}
    for name, universe in universes.items():
        size = len(universe) or 1
        rows = []
        for path, values in hit_values[name].items():
            n = totals[path]
            if n < min_count:
                continue
            rate = hit_counts[name][path] / n
            if rate < min_hit:
                continue
            rows.append({
                "path": path,
                "hit_rate": round(rate, 4),
                "count": n,
                "values": values,
                "coverage": round(len(values) / size, 4),
            })
        rows.sort(key=lambda r: (-r["coverage"], -r["count"]))
        out[name] = rows
    return out


def pick_reference_paths(rows, min_gain=0.005):
    """从 infer_id_paths 的结果里挑出真正的引用路径（贪心集合覆盖）。

    每轮选"能新增最多未覆盖 id"的路径，直到新增量低于 min_gain（占宇宙的比例）
    为止。真正的引用字段一两条就能覆盖绝大部分宇宙，巧合命中的字段加不出新东西，
    自然被挡在门外。
    """
    if not rows:
        return []
    size = max(1, round(len(rows[0]["values"]) / max(rows[0]["coverage"], 1e-9)))
    covered = set()
    picked = []
    pool = list(rows)
    while pool:
        best = max(pool, key=lambda r: len(r["values"] - covered))
        gain = len(best["values"] - covered) / size
        if picked and gain < min_gain:
            break
        picked.append(best)
        covered |= best["values"]
        pool.remove(best)
    return picked


def summarize_paths(rows):
    """去掉 values 集合，只留可序列化的证据，便于写进 report。"""
    return [{k: v for k, v in r.items() if k != "values"} for r in rows]


def infer_text_paths(docs, in_textmap, min_hit=0.9, min_count=20, min_value=MIN_HASH):
    """找出哪些 JSON 路径存的是 TextMapHash。

    判据和 `infer_id_paths` 同源，只是"已知集合"换成了 TextMap 本身：一个整数
    字段若绝大多数取值都能查到文本，它就是文本 hash。同时记录文本长度中位数 ——
    标题和描述都是文本，区分它们只能靠长度。
    """
    stat = defaultdict(lambda: {"n": 0, "hit": 0, "lens": []})
    for doc in docs:
        for path, value in walk_ints(doc):
            if value < min_value:
                continue
            row = stat[path]
            row["n"] += 1
            text = in_textmap(value)
            if text is not None:
                row["hit"] += 1
                if len(row["lens"]) < 500:
                    row["lens"].append(len(text))

    out = []
    for path, row in stat.items():
        if row["n"] < min_count:
            continue
        rate = row["hit"] / row["n"]
        if rate < min_hit:
            continue
        lens = sorted(row["lens"])
        out.append({
            "path": path,
            "hit_rate": round(rate, 4),
            "count": row["n"],
            "median_len": lens[len(lens) // 2] if lens else 0,
        })
    out.sort(key=lambda r: -r["count"])
    return out
