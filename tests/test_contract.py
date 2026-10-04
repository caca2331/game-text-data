"""内容契约的逐行检查与分布偏移（gametext.core.contract）。"""

from gametext.core.contract import DRIFT_ROWS, DRIFT_SHARE, Closed, Contracts, F, Open, Table, drift

CONTRACTS = Contracts("t", {
    "rows": Table(3, [
        F("id", "int", None, None, "主键"),
        F("name", "str", "查不到", None, "名字"),
        F("kind", "str", None, Closed({"a", "b"}), "封闭枚举"),
        F("style", "str", None, Open({"x"}), "开放枚举"),
        F("extra", "int", None, None, "可整个不出现", optional=True),
        F("next", "list", None, None, "标量列表"),
        F("next[]", "int", None, None, "后继 id"),
        F("lines", "list", None, None, "对象列表"),
        F("lines[].text", "str", None, None, "台词"),
    ], []),
})


def row(**kw):
    r = {"id": 1, "name": "n", "kind": "a", "style": "x", "next": [2], "lines": [{"text": "t"}]}
    r.update(kw)
    return r


def check(*rows):
    c = CONTRACTS.checker("rows")
    for r in rows:
        c.check(r)
    return c.summary()


def test_label():
    assert CONTRACTS.label("rows") == "t.rows/3"
    assert check(row())["contract"] == "t.rows/3"


def test_clean_rows_have_no_violations():
    s = check(row(), row(id=2, extra=5, name=None, kind="b"))
    assert s["violations"] == {} and s["new_values"] == {}


def test_each_violation_kind():
    bad = row(id=1, name=1, kind="c", undeclared=0, next=["x"], lines=[{"text": None}, "oops"])
    del bad["style"]
    v = check(row(), bad)["violations"]
    assert v == {
        "id: id 重复": 1,
        "undeclared: 没声明的键": 1,
        "style: 缺键": 1,
        "name: 类型应为 str": 1,
        "kind: 封闭枚举外的值": 1,
        "next[]: 类型应为 int": 1,
        "lines[].text: 从不为 null 却是 null": 1,
        "lines[]: 元素应为 object": 1,
    }


def test_open_enum_new_value_is_not_a_violation():
    s = check(row(style="y"), row(id=2, style="y"))
    assert s["violations"] == {}
    assert s["new_values"] == {"style": {"y": 2}}


def test_profile_counts_items_nulls_and_shares():
    p = check(row(next=[2, 3]), row(id=2, name=None, kind="b", lines=[]))["profile"]
    assert p["rows"] == 2
    assert p["items"] == {"lines": 1, "next": 3}
    assert p["null_rate"] == {"name": 0.5}
    assert p["enum_share"]["kind"] == {"a": 0.5, "b": 0.5}


def prof(rows=100, items=None, null=None, share=None):
    return {"rows": rows, "items": items or {}, "null_rate": null or {}, "enum_share": share or {}}


def test_drift_thresholds():
    base = {"rows": {"CHS": prof(share={"kind": {"a": 0.5, "b": 0.5}}, null={"name": 0.1}, items={"lines": 100})}}
    within = {"rows": {"CHS": prof(rows=100 * (1 + DRIFT_ROWS) - 1, items={"lines": 105},
                                   share={"kind": {"a": 0.5 + DRIFT_SHARE - 0.01, "b": 0.5 - DRIFT_SHARE + 0.01}},
                                   null={"name": 0.1 + DRIFT_SHARE - 0.01})}}
    assert drift(base, within) == []
    beyond = {"rows": {"CHS": prof(rows=80, items={"lines": 50}, share={"kind": {"a": 1.0}}, null={"name": 0.5})}}
    out = drift(base, beyond)
    assert any("行数 100 → 80" in x for x in out)
    assert any("lines 的元素数 100 → 50" in x for x in out)
    assert any("name 的 null 率" in x for x in out)
    assert any("kind = b 的占比" in x for x in out)


def test_drift_table_or_lang_on_one_side():
    base = {"rows": {"CHS": prof()}}
    assert drift(base, {"rows": {"CHS": prof(), "EN": prof()}}) == ["rows（EN） 基线里没有"]
    assert drift(base, {}) == ["rows（CHS） 这次没有了"]
