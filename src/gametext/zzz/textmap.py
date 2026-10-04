"""TextMap 装载与查询。

绝区零的 TextMap 和另外两个游戏最大的不同：**key 是明文语义字符串，不是数字 hash**。

    "Main_GalGame_Chapter000_1000003_001": "克里特空洞，旧地铁枢纽站某处。"
    "QuestName_10010001": "兔与绳"
    "Side_Chat_031SecretRegion2_231463001_01": "嗯呢呱？（你说你刚才放了一只邦布进去？）"

类别、场景、序号全在 key 里，所以剧情文本可以直接从 TextMap 提取并排序，不必先
解析混淆的 FileCfg。

**`Overwrite` 是覆盖层，不是并集。** 实测（3.2.0）：`TextMapOverwriteTemplateTb.json`
774 条，其中 611 条（78.9%）的 key 与主表重叠，**且值全部不同** —— 内容是修订版
（"小萌" -> "小簇"、任务目标措辞调整、商店路径写得更详细）。所以必须**先主表、后
覆盖**；顺序搞反会静默拿到旧文本。另有 163 条是覆盖表独有的新增条目。
"""

from __future__ import annotations

import os
from typing import Iterable

try:
    import orjson as _json

    def _load(path):
        with open(path, "rb") as f:
            return _json.loads(f.read())

except ImportError:
    import json as _json

    def _load(path):
        with open(path, encoding="utf-8") as f:
            return _json.load(f)


# 语种代码用上游的写法：**JA / KO**（不是原神的 JP/KR，也不是崩铁的 JP/KR）。
# 简体中文没有语言后缀，文件就叫 TextMapTemplateTb.json。
# 默认只出中英日三语。上游其实带 13 个语种，但 TextMap 是最大的一块
# （718 MB 里 518 MB 是我们不读的语种），所以语种选择同时决定**下载什么**。
LANGS = ("CHS", "EN", "JA")

# 上游实际提供的语种。用来校验 --langs，也用来生成 sparse 规则。
ALL_LANGS = ("CHS", "CHT", "DE", "EN", "ES", "FR", "ID", "JA", "KO",
             "PT", "RU", "TH", "VI")

# 基准语种：用来区分"上游没做本地化"与"上游根本没这条"，永远要在列。
BASE_LANG = "CHS"

_MAIN = {"CHS": "TextMapTemplateTb.json"}
_OVERWRITE = {"CHS": "TextMapOverwriteTemplateTb.json"}


def sparse_patterns(langs):
    """这些语种对应的 TextMap 文件，写成 git sparse-checkout 的 non-cone 规则。"""
    out = []
    for lang in langs:
        main, over = files_for(lang)
        out.append("/TextMap/" + main)
        if over:
            out.append("/TextMap/" + over)
    return out


def files_for(lang: str):
    """返回 (主表文件名, 覆盖表文件名)。覆盖表可能不存在。"""
    if lang in _MAIN:
        return _MAIN[lang], _OVERWRITE.get(lang)
    return ("TextMap_%sTemplateTb.json" % lang,
            "TextMap_%sOverwriteTemplateTb.json" % lang)


class TextMap:
    """单一语种的 key -> 文本 映射。"""

    def __init__(self, lang, table, overwritten, added):
        self.lang = lang
        self._table = table
        self.overwritten = overwritten  # 被覆盖表改写的条目数
        self.added = added              # 覆盖表新增的条目数

    @classmethod
    def load(cls, upstream_dir: str, lang: str) -> "TextMap":
        base = os.path.join(upstream_dir, "TextMap")
        main_name, ovr_name = files_for(lang)
        main_path = os.path.join(base, main_name)
        if not os.path.exists(main_path):
            raise FileNotFoundError("缺 %s" % main_path)
        table = _load(main_path)

        overwritten = added = 0
        if ovr_name:
            ovr_path = os.path.join(base, ovr_name)
            if os.path.exists(ovr_path):
                ovr = _load(ovr_path)
                for key, value in ovr.items():
                    if key in table:
                        # 覆盖：值必然与主表不同（实测 611/611），这才是它存在的意义
                        overwritten += 1
                    else:
                        added += 1
                    table[key] = value
        return cls(lang, table, overwritten, added)

    def __len__(self):
        return len(self._table)

    def __contains__(self, key):
        return key in self._table

    def get(self, key):
        """查不到返回 None —— 与"文本是空串"是两回事。"""
        return self._table.get(key)

    def keys(self):
        return self._table.keys()

    def items(self):
        return self._table.items()


def load_all(upstream_dir: str, langs: Iterable[str] = LANGS) -> dict:
    return {lang: TextMap.load(upstream_dir, lang) for lang in langs}
