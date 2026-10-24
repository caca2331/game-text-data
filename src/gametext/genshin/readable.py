"""阅读面板的长文本（`readables_*`）：上游 `Readable/` 目录的正文，加几张阅读界面配置表（信件、说明、角色故事）引用的正文。

两类来源，各语种都取自同一条上游记录（不变量 3）：

- **`Readable/<语种>/<名>.txt`**：书籍、武器 / 圣遗物故事、信件、告示等的正文，一个文件一篇。
  文件名各语种不同（`Book100.txt` / `Book100_EN.txt`），对齐靠 `LocalizationExcelConfigData`：
  它一行给出各语种的资源路径（`ART/UI/Readable/CHS/Book100`、`ART/UI/Readable/EN/Book100_EN`…），
  阅读界面（`DocumentExcelConfigData`）引用的就是这一行的 id。路径的列名有的是明文（`enPath`）、
  有的是混淆串（中文那列），所以**不认列名，按路径本身认语种**：值形如 `…/Readable/<语种>/<名>`。
- **TextMap**：`TABLES` 里那几张阅读界面配置表的正文字段。字段按结构认（不变量 1）：TextMap 命中率够高
  的顶层 hash 字段里文本长度中位数最长的那个，见 `Indexer.index_readables`。

文本的写法在 `normalize` 里统一：TextMap 里的换行是字面量 `\\n`，`Readable/` 文件是真换行，
这张表一律写真换行（段落之间的换行就是它）。占位与富文本标记原样保留。
"""

from __future__ import annotations

import os
import re

DIR = "Readable"
SOURCE_DIR = "Readable/"
"""`Readable/` 来源的行在产物里的 `source`。"""

TABLES = (
    ("MailExcelConfigData", "id"),
    ("TutorialDetailExcelConfigData", "id"),
    ("AlchemySimLetterExcelConfigData", "id"),
    ("FetterStoryExcelConfigData", "fetterId"),
)
"""阅读界面的配置表与它的行 id 字段（明文，Excel 表的 id 照名取），按这个顺序写出：

- `MailExcelConfigData`：邮箱里的信件（含生日信、系统邮件）；
- `TutorialDetailExcelConfigData`：教程说明页；
- `AlchemySimLetterExcelConfigData`：活动里的来信；
- `FetterStoryExcelConfigData`：角色资料里的角色故事（一行一篇，id 是 `fetterId`）。另有一个"变体正文"字段
  （7.1.0 只有 8 行查得到文本，如钟离的故事在剧情推进后的版本），命中率不到 `TEXT_MIN_HIT`、也没有自己的 id，不收。

书籍、角色写的信件、武器 / 圣遗物故事在 `Readable/` 里，不在这里重复。"""

PATH_RE = re.compile(r"(?:^|/)Readable/([A-Za-z]+)/([^/]+)$")
"""本地化路径里指向 `Readable/` 的值：第一组是语种目录（与 TextMap 的语种代码相同），第二组是文件名（不带 .txt）。"""

TEXT_MIN_HIT = 0.5
"""配置表里算"文本字段"的 TextMap 命中率下限（7.1.0：教程说明页 0.95，3645 条里 188 条查不到）。"""
TEXT_MIN_MEDIAN = 20
"""否决：选中的正文字段文本长度中位数不到这么多字，多半认错了字段（标题、署名），整张表判失败。
7.1.0 四张表的正文按 `infer_text_paths` 的取样中位 47 / 91 / 207 / 362 字；同表的标题、寄件人、署名、故事标题中位 14 / 11 / 2 / 5 字。"""


def sparse_patterns(langs):
    """这些语种的 `Readable/` 目录，写成 sparse-checkout 的 non-cone 规则（与 TextMap 一样按语种挑）。"""
    return ["/%s/%s/" % (DIR, lang) for lang in langs]


def parse_path(value):
    """本地化表里的一个取值 → (语种, 文件名)，不指向 `Readable/` 时是 None。"""
    if not isinstance(value, str):
        return None
    m = PATH_RE.search(value)
    return (m.group(1).upper(), m.group(2)) if m else None


def file_path(upstream, lang, name):
    return os.path.join(upstream, DIR, lang, name + ".txt")


def normalize(text):
    """统一换行、去掉首尾空白；空文本当作没有（None）。

    TextMap 的换行是字面量 `\\n`（7.1.0 的 CHS 里 2 万多条，没有一条真换行），`Readable/` 文件是
    真换行、可能带 `\\r\\n` 与 BOM。与台词去重时两边都过这一道，比的是同一种写法。"""
    if text is None:
        return None
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").replace("\\n", "\n").strip()
    return text or None


def read_file(upstream, lang, name):
    """读一篇 `Readable/` 正文：(文本, 文件在不在)。文本按 `normalize` 规范化，空文件是 None。"""
    path = file_path(upstream, lang, name)
    if not os.path.exists(path):
        return None, False
    with open(path, encoding="utf-8-sig") as f:
        return normalize(f.read()), True
