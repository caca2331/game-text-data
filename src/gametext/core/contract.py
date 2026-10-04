"""内容契约的机制：字段声明的写法、逐行检查与分布摘要、与上次发布比分布。

各游戏的声明在 `gametext.<游戏>.contract`（`CONTRACTS = Contracts("<游戏>", {表: Table(...)})`），
那里是各表字段的唯一来源；`emit` 按它逐行检查，`manifest` 按它写各表的契约版本。通用规则
（版本怎么升、违反算什么）见 docs/architecture.md 的「内容契约」一节。

字段写法 `F(路径, 类型, null, 取值, 含义)`：

- 路径：`lines[].style` 这样，`[]` 表示列表的每个元素。
- 类型：int / number（int 或 float）/ str / bool / list / object。
- null：`None` 表示从不为 null；否则是一句话，说明 null 的含义。
- 取值：`None` 自由取值；`Closed(...)` 封闭枚举，出现别的值是硬失败；`Open(...)` 开放枚举，
  列的是已知值，出现新值只告警。
- `optional=True`：这个键可以整个不出现（不出现 ≠ null）。

行里出现没声明的键也是硬失败：加字段先在声明里加。表达不了"某种 kind 的事件必须带某个键"这类
跨字段规则：随 kind 变化的键一律标 optional，这是在简单与严格之间有意的取舍。
"""

from __future__ import annotations

from collections import Counter, defaultdict

class Closed(frozenset):
    """封闭枚举：取值全集。出现别的值 = 契约被破坏。"""


class Open(frozenset):
    """开放枚举：已知取值。出现新值只告警（上游加一种样式是常事）。"""


class F:
    __slots__ = ("path", "type", "null", "values", "meaning", "optional")

    def __init__(self, path, type_, null, values, meaning, optional=False):
        self.path, self.type, self.null = path, type_, null
        self.values, self.meaning, self.optional = values, meaning, optional


class Table:
    """`invariants` 是给人读的说明；其中 "id 全表唯一" 由 `unique_id` 实际检查，
    "各语种行数相同、逐行 id 相同" 由 emit / report 检查。"""

    def __init__(self, version: int, fields: list, invariants: list, unique_id: bool = True):
        self.version, self.fields, self.invariants = version, fields, invariants
        self.unique_id = unique_id


class Contracts(dict):
    """一款游戏的全部表：{表名: Table}。契约版本写成 `<游戏>.<表>/<版本>`。"""

    def __init__(self, game: str, tables: dict):
        super().__init__(tables)
        self.game = game

    def label(self, table: str) -> str:
        return "%s.%s/%d" % (self.game, table, self[table].version)

    def checker(self, table: str) -> "Checker":
        return Checker(self[table], self.label(table))


_TYPES = {
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "str": lambda v: isinstance(v, str),
    "bool": lambda v: isinstance(v, bool),
    "list": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}
ENUM_PROFILE_MAX = 64     # 开放枚举的直方图最多记这么多种取值，再多就是该当自由取值了


def _compile(fields):
    """路径表 → 嵌套的检查树：{键: (F, 子树)}；列表元素的子树挂在 "[]" 下。"""
    root = {}
    for f in fields:
        node = root
        parts = f.path.replace("[]", ".[]").split(".")
        for i, p in enumerate(parts):
            last = i == len(parts) - 1
            entry = node.get(p)
            if entry is None:
                entry = node[p] = [None, {}]
            if last:
                entry[0] = f
            node = entry[1]
    return root


class Checker:
    """一张表、一个语种的逐行检查与分布摘要。"""

    def __init__(self, spec: Table, label: str):
        self.spec, self.label = spec, label
        self.tree = _compile(self.spec.fields)
        self.rows = 0
        self.ids = set()
        self.violations = Counter()          # "路径: 问题" -> 次数
        self.samples = {}                    # "路径: 问题" -> 第一个出问题的值
        self.new_values = defaultdict(Counter)
        self.seen = Counter()                # 路径 -> 出现次数（含 null）
        self.nulls = Counter()
        self.items = Counter()               # 列表路径 -> 元素总数（对话节点、台词行…）
        self.enums = defaultdict(Counter)

    def check(self, row: dict) -> None:
        self.rows += 1
        if self.spec.unique_id:
            rid = row.get("id")
            if rid in self.ids:
                self._bad("id", "id 重复", rid)
            self.ids.add(rid)
        self._obj(row, self.tree, "")

    def _bad(self, path, what, value):
        key = "%s: %s" % (path or "<行>", what)
        self.violations[key] += 1
        self.samples.setdefault(key, repr(value)[:80])

    def _obj(self, obj, tree, prefix):
        for k in obj:
            if k not in tree:
                self._bad(prefix + k, "没声明的键", obj[k])
        for k, (f, sub) in tree.items():
            if k not in obj:
                if not f.optional:
                    self._bad(prefix + k, "缺键", None)
                continue
            self._value(obj[k], f, sub, prefix + k)

    def _value(self, v, f, sub, path):
        self.seen[f.path] += 1
        if v is None:
            self.nulls[f.path] += 1
            if f.null is None:
                self._bad(path, "从不为 null 却是 null", v)
            return
        if not _TYPES[f.type](v):
            self._bad(path, "类型应为 %s" % f.type, v)
            return
        if f.values is not None:
            if v not in f.values:
                if isinstance(f.values, Closed):
                    self._bad(path, "封闭枚举外的值", v)
                else:
                    self.new_values[f.path][v] += 1
            if len(self.enums[f.path]) < ENUM_PROFILE_MAX or v in self.enums[f.path]:
                self.enums[f.path][v] += 1
        if f.type == "object":
            self._obj(v, sub, path + ".")
        elif f.type == "list":
            self.items[f.path] += len(v)
            if "[]" not in sub:
                return
            ef, esub = sub["[]"]
            for x in v:
                if ef is not None:              # 标量元素，如 next[]
                    self._value(x, ef, esub, path + "[]")
                elif isinstance(x, dict):       # 对象元素：只声明它的各个键
                    self._obj(x, esub, path + "[].")
                else:
                    self._bad(path + "[]", "元素应为 object", x)

    def summary(self) -> dict:
        """写进 report.json：违反（硬失败）、开放枚举的新值（告警）、分布摘要（供 release 比较）。"""
        return {
            "contract": self.label,
            "violations": dict(self.violations),
            "violation_samples": self.samples,
            "new_values": {p: dict(c.most_common(20)) for p, c in self.new_values.items()},
            "profile": {
                "rows": self.rows,
                "items": dict(sorted(self.items.items())),
                "null_rate": {p: round(self.nulls[p] / n, 6) for p, n in sorted(self.seen.items())
                              if self._field(p).null is not None},
                "enum_share": {p: {str(v): round(c / self.seen[p], 6) for v, c in cnt.most_common()}
                               for p, cnt in sorted(self.enums.items())},
            },
        }

    def _field(self, path):
        for f in self.spec.fields:
            if f.path == path:
                return f
        raise KeyError(path)


# ---- 与上次发布比分布（release 用） ----

DRIFT_SHARE = 0.05
"""null 率或枚举取值占比变化超过 5 个百分点算偏移。"""
DRIFT_ROWS = 0.10
"""行数、嵌套列表的元素数（对话节点、台词行…）相对变化超过 10% 算偏移：管"均匀少了一半、各占比都不变"那种缺口。"""


def profiles(report: dict) -> dict:
    """report.json → {表: {语种: 分布摘要}}。"""
    return {t: {lang: s["profile"] for lang, s in c["langs"].items()}
            for t, c in (report.get("contract") or {}).items()}


def drift(base: dict, cur: dict) -> list:
    """两份 {表: {语种: 摘要}} 之间超过门槛的变化，一条一句。表或语种只在一边出现也算一条（加表、加语种后的第一次发布要人过目）。"""
    out = []
    for table in sorted(set(base) | set(cur)):
        for lang in sorted(set(base.get(table) or {}) | set(cur.get(table) or {})):
            b, p = (base.get(table) or {}).get(lang), (cur.get(table) or {}).get(lang)
            where = "%s（%s）" % (table, lang)
            if b is None or p is None:
                out.append("%s %s" % (where, "基线里没有" if b is None else "这次没有了"))
                continue
            if b["rows"] and abs(p["rows"] - b["rows"]) / b["rows"] > DRIFT_ROWS:
                out.append("%s 行数 %d → %d" % (where, b["rows"], p["rows"]))
            for path in sorted(set(p.get("items", {})) | set(b.get("items", {}))):
                x, y = b.get("items", {}).get(path, 0), p.get("items", {}).get(path, 0)
                if x and abs(y - x) / x > DRIFT_ROWS or not x and y:
                    out.append("%s %s 的元素数 %d → %d" % (where, path, x, y))
            for path in sorted(set(p["null_rate"]) | set(b["null_rate"])):
                x, y = b["null_rate"].get(path, 0), p["null_rate"].get(path, 0)
                if abs(y - x) > DRIFT_SHARE:
                    out.append("%s %s 的 null 率 %.1f%% → %.1f%%" % (where, path, 100 * x, 100 * y))
            for path in sorted(set(p["enum_share"]) | set(b["enum_share"])):
                bv, pv = b["enum_share"].get(path, {}), p["enum_share"].get(path, {})
                for v in sorted(set(bv) | set(pv)):
                    x, y = bv.get(v, 0), pv.get(v, 0)
                    if abs(y - x) > DRIFT_SHARE:
                        out.append("%s %s = %s 的占比 %.1f%% → %.1f%%" % (where, path, v, 100 * x, 100 * y))
    return out
