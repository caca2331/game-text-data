"""TextMap key 的结构解析。

绝区零的 key 是明文语义标识，类别 / 场景 / 序号全编码在里面，所以剧情文本能直接从
TextMap 提取并排序，**不必先解析混淆的 FileCfg**。

统一形态（实测覆盖绝大多数剧情类 key）：

    <类别路径>_<场景数字>_[Name_]<序号>[变体字母]

    Main_GalGame_Chapter000_1000003_001        对话行
    Main_GalGame_Chapter000_1000003_Name_001   ← 场景**出场角色表**的第 1 个
    Main_Chat_Chapter00_30000006_01
    Main_OngoingLevel_Chapter090_110901001_01
    Side_GalGame_RAB_100000006_001
    Activity_Chat_SayItWithFlowers_35160001_01
    Message_200014_01
    MainChat_2_0001_03F                        末尾 F/M 是主角性别分支

**`_Name_` 是场景的出场角色表**（序号 1..k 连续、名字互不重复），**不是**同序号那一行的
说话人——别把 `_Name_00i` 配给第 i 行（AGENTS.md 不变量 6，第二版就这么配错了）。
但它必须被认出来：漏了会把一万多个名字当成普通对话混进正文（第一版踩过）。

类别路径的末段若形如 `ChapterNNN`，拆出来作为章节。

不匹配上面形态的 key（`Option01_100304`、`Message_100000101`、`Tips_*`、`UIText_*`
这类只有单个数字段或纯 UI 的）由调用方按需处理，本模块只负责识别，不做取舍。
"""

from __future__ import annotations

import re

# <类别路径>_<场景>_[Name_]<序号><变体>
LINE_RE = re.compile(
    r"^(?P<cat>.+?)_(?P<scene>\d+)_(?P<name>Name_)?(?P<seq>\d+)(?P<variant>[A-Za-z]*)$"
)

# 类别路径末段的章节标记，如 Chapter000 / Ch01。
# 章节名里**不能含下划线**——`\w` 是包含下划线的，用它会把
# `Main_Chat_Chapter00` 拆成 category=Main / chapter=Chat_Chapter00。
CHAPTER_RE = re.compile(r"^(?P<rest>.*?)_(?P<chapter>(?:Chapter|Ch)[A-Za-z0-9]*)$")

# 任务元数据
QUEST_PATTERNS = {
    "name": re.compile(r"^QuestName_(?P<id>\d+)$"),
    "target": re.compile(r"^QuestTarget_(?P<id>\d+)$"),
    "desc": re.compile(r"^QuestDesc_(?P<id>\d+)$"),
    # 完成语。首版漏了这一类——是解析 FileCfg 时从 QuestConfig 的字段里看到的，
    # TextMap 里数量不多（几百条），但属于任务元数据的一部分。
    "finish": re.compile(r"^QuestFinishDec_(?P<id>\d+)$"),
}


def parse_line(key: str):
    """key -> {category, chapter, scene, seq, seq_raw, variant, is_speaker}；不匹配返回 None。

    `seq_raw` 是 key 里原样的序号串。**同一场景里 `_01` 和 `_1` 是两条不同的台词**
    （3.2.0 实测 219 组，183 组文本不同），按数值归一会让它们撞在一起、丢掉一条。"""
    m = LINE_RE.match(key)
    if not m:
        return None
    cat = m.group("cat")
    chapter = ""
    cm = CHAPTER_RE.match(cat)
    if cm:
        chapter = cm.group("chapter")
        cat = cm.group("rest") or cat
    return {
        "category": cat,
        "chapter": chapter,
        "scene": m.group("scene"),
        "seq": int(m.group("seq")),
        "seq_raw": m.group("seq"),
        "variant": m.group("variant") or "",
        "is_speaker": bool(m.group("name")),
    }


def parse_quest(key: str):
    """key -> (字段名, quest_id)；不是任务元数据就返回 None。"""
    for field, pattern in QUEST_PATTERNS.items():
        m = pattern.match(key)
        if m:
            return field, m.group("id")
    return None


def category_of(key: str) -> str:
    """粗分类，用于统计与报告：取首段并把数字归一。"""
    head = key.split("_", 1)[0]
    return re.sub(r"\d+", "N", head)
