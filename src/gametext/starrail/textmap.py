"""TextMap 装载与查询。

崩铁的 TextMap 有三点和原神不同，都会咬人：

1. **hash 是 64 位无符号整数**（原神是 32 位）。
2. **部分语种被拆片**：韩语 `TextMapKR_0/1`、俄语 `TextMapRU_0/1`、泰语 `TextMapTH_0/1`。
   同一语种的分片必须全部装载，只读 `_0` 会静默丢掉一半文本。
3. **`TextMapMain<LANG>.json` 不是主表。** 名字容易误导：它只有 70–100 KB（主表 48–67 MB），
   内容是"网络连接中断""退出游戏"这类**启动器/登录期 UI 文本**，Main 指的是 main menu。
   对话正文全在主表里。这里仍然把它并进来（key 与主表基本不相交，有则补全），
   但**不要**把它当成原神那种"必须合并否则丢两成正文"的第二张表。
"""

from __future__ import annotations

import os
import re
from typing import Iterable

try:
    import orjson as _json

    def _load(path: str):
        with open(path, "rb") as f:
            return _json.loads(f.read())

except ImportError:  # 没装 orjson 也能跑通，只是慢
    import json as _json

    def _load(path: str):
        with open(path, encoding="utf-8") as f:
            return _json.load(f)


# 与 genshin 保持同样的语种口径
# 默认只出中英日三语。TextMap 是上游最大的一块（868 MB 里 619 MB 是我们不读的
# 语种），所以语种选择同时决定 snapshot **下载什么**。
LANGS = ("CHS", "EN", "JP")

# 上游实际提供的语种
ALL_LANGS = ("CHS", "CHT", "DE", "EN", "ES", "FR", "ID", "JP", "KR",
             "PT", "RU", "TH", "VI")

# 基准语种：用来区分"上游没做本地化"与"上游根本没这条"，永远要在列
BASE_LANG = "CHS"


def sparse_patterns(langs):
    """这些语种对应的 TextMap 文件，写成 git sparse-checkout 的 non-cone 规则。

    用 glob 覆盖分片（`TextMapKR_0.json`）——哪个语种被拆片会变，写死会静默漏片，
    这一点和 `shard_files` 的取舍一致。
    """
    out = []
    for lang in langs:
        out += ["/TextMap/TextMap%s.json" % lang,
                "/TextMap/TextMap%s_*.json" % lang,
                "/TextMap/TextMapMain%s.json" % lang]
    return out

# TextMapKR_0.json / TextMapRU_1.json 这类分片
_SHARD_RE = re.compile(r"^TextMap(?P<lang>[A-Z]+)(?:_(?P<shard>\d+))?\.json$")
_MAIN_RE = re.compile(r"^TextMapMain(?P<lang>[A-Z]+)\.json$")


def shard_files(base: str, lang: str) -> list:
    """列出某语种的全部文件：主表（可能多片）+ 启动期小表。

    宁可枚举目录也不拼文件名 —— 上游哪个语种被拆片是会变的，写死会静默漏片。
    """
    main, extra = [], []
    for name in sorted(os.listdir(base)):
        m = _SHARD_RE.match(name)
        if m and m.group("lang") == lang:
            main.append(name)
            continue
        m = _MAIN_RE.match(name)
        if m and m.group("lang") == lang:
            extra.append(name)
    return main + extra


class TextMap:
    """单一语种的 hash -> 文本 映射。"""

    def __init__(self, lang: str, table: dict, sources: list, collisions: int):
        self.lang = lang
        self._table = table
        self.sources = sources
        self.collisions = collisions

    @classmethod
    def load(cls, upstream_dir: str, lang: str) -> "TextMap":
        base = os.path.join(upstream_dir, "TextMap")
        files = shard_files(base, lang)
        if not files:
            raise FileNotFoundError("TextMap 里找不到语种 %s 的任何文件" % lang)
        table: dict = {}
        collisions = 0
        for name in files:
            part = _load(os.path.join(base, name))
            # 分片之间本应互不重叠；重叠了要计数上报而不是默默覆盖
            collisions += len(table.keys() & part.keys())
            table.update(part)
        return cls(lang, table, files, collisions)

    def __len__(self) -> int:
        return len(self._table)

    def __contains__(self, text_hash) -> bool:
        return str(text_hash) in self._table

    def get(self, text_hash):
        """查不到返回 None —— 与"文本是空串"是两回事，调用方必须区分。"""
        if text_hash is None:
            return None
        return self._table.get(str(text_hash))

    def items(self):
        """(hash:int, 文本) 全表遍历，按 hash 数值升序（产物要确定性的行序）。"""
        return sorted((int(k), v) for k, v in self._table.items())


def load_all(upstream_dir: str, langs: Iterable[str] = LANGS) -> dict:
    return {lang: TextMap.load(upstream_dir, lang) for lang in langs}
