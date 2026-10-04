"""TextMap 装载与查询。

上游 TextMap/*.json 是 hash -> 文本 的扁平字典，**key 是字符串**，而配置文件
里的 hash 是整数，查表前必须转。这里统一在 lookup 内部处理。
"""

from __future__ import annotations

import os
from typing import Iterable

try:
    import orjson as _json

    def _load(path: str):
        with open(path, "rb") as f:
            return _json.loads(f.read())

except ImportError:  # 允许在没装 orjson 的环境里跑通，只是慢
    import json as _json

    def _load(path: str):
        with open(path, encoding="utf-8") as f:
            return _json.load(f)


# 上游的语言代码，注意是 JP / KR 而不是 ja / ko
# 默认只出中英日三语。TextMap 是上游最大的一块（1235 MB 里 942 MB 是我们不读的
# 语种），所以语种选择同时决定 snapshot **下载什么**。
LANGS = ("CHS", "EN", "JP")

# 上游实际提供的语种
ALL_LANGS = ("CHS", "CHT", "DE", "EN", "ES", "FR", "ID", "IT", "JP", "KR",
             "PT", "RU", "TH", "TR", "VI")

# 基准语种：用来区分"上游没做本地化"与"上游根本没这条"，永远要在列
BASE_LANG = "CHS"


def sparse_patterns(langs):
    """这些语种对应的 TextMap 文件，写成 git sparse-checkout 的 non-cone 规则。

    每个语种两张表（主表 + Medium），且都可能被拆片（`TextMapRU_0.json`），
    所以四条 glob 都要给——漏了 Medium 会丢掉约 20% 的对话正文。
    """
    out = []
    for lang in langs:
        out += ["/TextMap/TextMap%s.json" % lang,
                "/TextMap/TextMap%s_*.json" % lang,
                "/TextMap/TextMap_Medium%s.json" % lang,
                "/TextMap/TextMap_Medium%s_*.json" % lang]
    return out


class TextMap:
    """单一语种的 hash -> 文本 映射。

    每个语种有两张表：`TextMap<LANG>.json` 与 `TextMap_Medium<LANG>.json`。
    实测（6.6.0）两张表的 **key 空间完全不相交**，内容互有重叠（同一句话在两
    边各有一个不同的 hash），Medium 反而更大：CHS 分别是 246 111 / 546 797 条。
    只查其中一张会漏掉约 20% 的对话正文，所以这里合并两张表 —— key 不相交，
    合并无冲突。
    """

    def __init__(self, lang: str, table: dict):
        self.lang = lang
        self._table = table

    @classmethod
    def load(cls, upstream_dir: str, lang: str) -> "TextMap":
        base = os.path.join(upstream_dir, "TextMap")
        table = _load(os.path.join(base, "TextMap%s.json" % lang))
        medium_path = os.path.join(base, "TextMap_Medium%s.json" % lang)
        if os.path.exists(medium_path):
            medium = _load(medium_path)
            collisions = table.keys() & medium.keys()
            if collisions:
                # key 空间本应不相交；真撞上了说明上游变了，必须让调用方知道
                raise ValueError(
                    "TextMap%s 与 Medium 有 %d 个 key 冲突，合并策略需要重新确认"
                    % (lang, len(collisions))
                )
            table.update(medium)
        return cls(lang, table)

    def __len__(self) -> int:
        return len(self._table)

    def __contains__(self, text_hash) -> bool:
        return str(text_hash) in self._table

    def get(self, text_hash):
        """查不到返回 None —— 与"文本为空串"是两回事，调用方必须区分。"""
        return self._table.get(str(text_hash))

    def items(self):
        """(hash:int, 文本) 全表遍历，按 hash 数值升序（产物要确定性的行序）。"""
        return sorted((int(k), v) for k, v in self._table.items())

    def hit_rate(self, hashes: Iterable) -> float:
        hashes = list(hashes)
        if not hashes:
            return 0.0
        return sum(1 for h in hashes if str(h) in self._table) / len(hashes)


def load_all(upstream_dir: str, langs: Iterable[str] = LANGS) -> dict:
    return {lang: TextMap.load(upstream_dir, lang) for lang in langs}
