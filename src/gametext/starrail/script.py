"""LevelGraph 脚本解析：把演出脚本还原成**有序的对话事件流**。

崩铁的对话顺序信息全在脚本的数组顺序里，正则抽 `TalkSentenceID` 只能拿到一个
集合，下游没法还原剧情顺序，也看不出分支。这里按 JSON 的自然顺序递归遍历，
产出事件序列。

承载台词的容器（实测 4001 个任务脚本的全量统计）：

| 容器 `$type` | 次数 | 形态 |
| --- | ---: | --- |
| `PlayAndWaitSimpleTalk` | 8626 | `SimpleTalkList: [{TalkSentenceID, ProtectTime}]` 线性 |
| `PlayOptionTalk` | 2299 | `OptionList: [{$type: OptionTalkInfo, TalkSentenceID, TriggerCustomString}]` **分支** |
| `PlaySimpleTalk` | 1195 | 同 SimpleTalkList |
| `PlayMissionTalk` | 619 | |
| `PlayNPCBubbleTalk` | 98 | 气泡 |
| `BattlePlayTalk` | 57 | 战斗中 |
| `PlayFullScreenTransfer` | 34 | 全屏转场文字 |

分支的边靠 `TriggerCustomString` / `WaitCustomString` 配对：选项被选中后触发一个
自定义字符串，别处的 `WaitCustomString` 等待它。因此除了台词，还要收集这两类控制
事件，下游才能把分支接回去。

**自定义字符串里还编码着台词 id**，形如 `TalkSentence_815111011`。第一版只认数字
字段 `TalkSentenceID`，把这一整类引用漏了：全上游 107 021 处，其中 103 020 处能对上
台词表。承载它的地方按数量排是 `WaitCustomString`(44 984) / `OptionTalkInfo` 的
`TriggerCustomString`(42 021) / `TriggerCustomString`(17 812)。

漏掉它不只是少统计——**选项对话（Discussion）里只剩玩家的选项、没有 NPC 的回答**，
因为回答是由选项的 `TriggerCustomString: TalkSentence_<id>` 指出来的。
"""

from __future__ import annotations

import re
from typing import Iterator

# 事件里保留的控制流锚点。选项跳转就靠这两个配对。
TRIGGER_TYPES = {
    "RPG.GameCore.TriggerCustomString": "trigger",
    "RPG.GameCore.WaitCustomString": "wait",
}

# 选项元素的 $type
OPTION_TYPE = "RPG.GameCore.OptionTalkInfo"

# 自定义字符串里编码的台词 id
SENTENCE_STR = re.compile(r"^TalkSentence_(\d+)$")


def sentence_of(custom_string):
    """`TalkSentence_815111011` -> 815111011；不是这个形态就返回 None。"""
    if not isinstance(custom_string, str):
        return None
    m = SENTENCE_STR.match(custom_string)
    return int(m.group(1)) if m else None


def _short(type_name):
    return type_name.rsplit(".", 1)[-1] if type_name else None


def iter_events(node, carrier=None) -> Iterator[dict]:
    """按 JSON 的自然顺序产出对话事件。

    事件形如：
        {"kind": "talk",    "sentence_id": 102120925, "carrier": "PlayAndWaitSimpleTalk"}
        {"kind": "option",  "sentence_id": 102120928, "trigger": "TalkSentence_102120931",
                            "reply_sentence_id": 102120931}
        {"kind": "trigger", "custom_string": "TalkSentence_815111011",
                            "sentence_id": 815111011}
        {"kind": "wait",    "custom_string": "OptionA", "sentence_id": None}

    dict 与 list 都按插入/下标顺序遍历，所以事件顺序 = 脚本执行顺序。
    """
    if isinstance(node, dict):
        node_type = node.get("$type")

        if node_type in TRIGGER_TYPES:
            value = node.get("CustomString")
            # CustomString 可能是裸串，也可能包一层 {"Value": ...}
            if isinstance(value, dict):
                value = value.get("Value")
            if value:
                yield {"kind": TRIGGER_TYPES[node_type], "custom_string": value,
                       "sentence_id": sentence_of(value)}

        if "TalkSentenceID" in node:
            sid = node.get("TalkSentenceID")
            if isinstance(sid, int):
                if node_type == OPTION_TYPE:
                    trigger = node.get("TriggerCustomString")
                    if isinstance(trigger, dict):
                        trigger = trigger.get("Value")
                    yield {"kind": "option", "sentence_id": sid,
                           "trigger": trigger or None,
                           # 选中这个选项后播的那句——选项对话的"回答"在这里
                           "reply_sentence_id": sentence_of(trigger),
                           "carrier": _short(carrier)}
                else:
                    yield {"kind": "talk", "sentence_id": sid,
                           "carrier": _short(carrier)}

        for key, value in node.items():
            if key == "$type":
                continue
            yield from iter_events(value, node_type or carrier)

    elif isinstance(node, list):
        for item in node:
            yield from iter_events(item, carrier)


def parse(doc) -> list:
    """整份脚本 -> 事件列表。"""
    return list(iter_events(doc))
