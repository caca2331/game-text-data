"""FileCfg 装载与**字段身份推断**。

`FileCfg/` 是游戏的配置表导出，1721 个文件。实测形态（3.2.0）：

- **文件名 1499 个是明文**（`QuestConfigTemplateTb.json`），只有 222 个是 hash。
  首版 data-source.md 写的"文件名与字段名双重混淆"是抽样抽偏了，只对 hash 那 222 个成立。
- **字段名全部混淆**（`PFOAJKNPCHL`），且按 genshin 的经验必须假定逐版本变化。
- 顶层几乎总是单个 key（1697/1721），值是行数组；这个 key 本身也是混淆的。

所以本模块的分工是：**文件名当锚点，字段名一律推断**（AGENTS.md 不变量 9）。
推断原语只有四个，都要求判据可独立验证：

    id_field      唯一 + 每行都有 + 整数
    text_fields   取值大量命中 TextMap 的明文 key，按 key 前缀命名
    ref_field     取值大量命中某个已知 id 全集
    order         行内字段顺序（来自上游类定义，跨版本比字段名稳定）

`text_fields` 是最强的一条：绝区零的 TextMap key 是明文语义标识，命中 `QuestName_30101`
既证明了"这是文本字段"，也证明了"它是任务名"——比原神那边"命中数字 hash"多一层语义。
"""

from __future__ import annotations

import os
import re
from collections import Counter

import orjson

# 值形如 QuestName_30101 / Message_NPC990 / Option01_100304，取其"前缀"即语义标签
_TAIL_NUM = re.compile(r"_\d+$")
_TRAIL_DIGITS = re.compile(r"\d+$")


def key_prefix(value: str) -> str:
    """把一个 TextMap key 归到它的语义前缀。

    QuestName_30101 -> QuestName；Message_NPC990 -> Message_NPC；Item_Coin -> Item_Coin
    """
    stripped = _TAIL_NUM.sub("", value)
    if stripped == value:
        stripped = _TRAIL_DIGITS.sub("", value)
    return stripped.rstrip("_") or value


def load(upstream: str, name: str):
    """读一张表，返回 (顶层 key, 行数组)。文件不存在或形态不对时返回 (None, [])。"""
    path = os.path.join(upstream, "FileCfg", name)
    if not os.path.exists(path):
        return None, []
    with open(path, "rb") as f:
        doc = orjson.loads(f.read())
    if not isinstance(doc, dict):
        return None, []
    for k, v in doc.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return k, v
    return None, []


def iter_tables(upstream: str):
    """遍历 FileCfg 下所有表，产出 (文件名, 顶层 key, 行数组)。"""
    root = os.path.join(upstream, "FileCfg")
    if not os.path.isdir(root):
        return
    for name in sorted(os.listdir(root)):
        if not name.endswith(".json"):
            continue
        top, rows = load(upstream, name)
        if rows:
            yield name, top, rows


def order(rows) -> list:
    """行内字段顺序。上游导出保持类定义顺序，跨版本比字段名本身稳定得多。"""
    seen = {}
    for r in rows[:64]:
        for k in r:
            seen.setdefault(k, len(seen))
    return sorted(seen, key=seen.get)


def scalars(value):
    if isinstance(value, list):
        for x in value:
            yield from scalars(x)
    elif not isinstance(value, bool):
        yield value


def id_field(rows, min_len: int = 1):
    """推断主键：整数、每行都有、全表唯一；并列时取行内最靠前的那个。"""
    n = len(rows)
    for field in order(rows):
        vals = []
        for r in rows:
            v = r.get(field)
            if isinstance(v, bool) or not isinstance(v, int):
                vals = None
                break
            vals.append(v)
        if vals is None or len(vals) != n:
            continue
        if len(set(vals)) != n:
            continue
        if min_len > 1 and any(len(str(v)) < min_len for v in vals):
            continue
        return field
    return None


def text_fields(rows, text_keys, min_rate: float = 0.5, min_hits: int = 5):
    """取值命中 TextMap key 的字段 -> {字段: (主前缀, 前缀占比, 命中数)}。"""
    out = {}
    for field in order(rows):
        hits = 0
        total = 0
        prefixes = Counter()
        for r in rows:
            v = r.get(field)
            if not isinstance(v, str) or not v:
                continue
            total += 1
            if v in text_keys:
                hits += 1
                prefixes[key_prefix(v)] += 1
        if total and hits >= min_hits and hits / total >= min_rate:
            prefix, count = prefixes.most_common(1)[0]
            out[field] = (prefix, count / hits, hits)
    return out


def by_prefix(fields, min_purity: float = 0.5, min_modal_hits: int = 20):
    """把 text_fields 的结果按语义前缀反查：{前缀: 字段}。

    纯度门槛只要求"主前缀占多数"，不要求压倒性——实测 `QuestConfig` 的任务名字段
    纯度只有 0.68（长尾里混着 `ActivityTeamTrial_QuestName`、小写 `questname` 等
    上游自己的命名不一致）。同前缀有多个候选时取命中数最多的那个。
    """
    out = {}
    for field, (prefix, purity, hits) in fields.items():
        if purity < min_purity or purity * hits < min_modal_hits:
            continue
        prev = out.get(prefix)
        if prev is None or fields[prev][2] < hits:
            out[prefix] = field
    return out


def ref_fields(rows, universe, min_rate: float = 0.3, min_hits: int = 20,
               exclude=(), min_len: int = 5, min_abs_hits: int = None,
               rate_floor: float = 0.05):
    """取值命中给定 id 全集的字段 -> {字段: (命中数, 命中率)}。

    命中率是对"该字段所有非平凡取值"算的，不是对行数——列表字段一行可能有多个引用。
    `min_len` 把过短的取值排除在外，免得 0/1/2 这种平凡值和 id 全集撞出假命中；
    但全集本身就是短 id（短信的组号是四位）时要显式放开。

    **只卡命中率会被版本变化打穿。** 跨版本回归实测：`ArchiveFileQuest` 指向 Perform
    的那个字段，3.2.0 命中率 0.32、2.7.0 只有 0.20（命中数 261，一点没少，是分母里的
    悬空引用变多了）。门槛 0.3 于是让整张桥表在旧版本上**静默消失**。所以再给一条
    并联的判据：`min_abs_hits` —— 命中数足够大时，允许命中率低到 `rate_floor`。
    """
    out = {}
    for field in order(rows):
        if field in exclude:
            continue
        hits = total = 0
        for r in rows:
            for x in scalars(r.get(field)):
                if not isinstance(x, (int, str)) or not x:
                    continue    # 0 / "" 是这些表里的"无"，不算一次引用
                s = str(x)
                if len(s) < min_len:
                    continue
                total += 1
                if s in universe:
                    hits += 1
        if not total or hits < min_hits:
            continue
        rate = hits / total
        ok = rate >= min_rate
        if not ok and min_abs_hits is not None:
            ok = hits >= min_abs_hits and rate >= rate_floor
        if ok:
            out[field] = (hits, rate)
    return out


def refs(row, field):
    """把一个字段的取值统一成 id 字符串列表（标量与列表都能吃）。"""
    return [str(x) for x in scalars(row.get(field))
            if isinstance(x, (int, str)) and str(x)]
