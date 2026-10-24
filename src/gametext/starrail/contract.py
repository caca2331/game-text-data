"""starrail 产物的内容契约：每张表、每个字段的类型、能否为 null、取值范围与含义。

**这里是唯一来源**：`emit` 按它逐行检查，`manifest` 按它写各表的契约版本，人和下游
（FlowOCR）也直接读这一份。字段写法与检查规则见 `gametext.core.contract`；通用规则
（版本怎么升、违反算什么）见 docs/architecture.md 的「内容契约」一节。
"""

from __future__ import annotations

from ..core.contract import Closed, Contracts, F, Open, Table


VOICE = Closed({"voiced", "generic", "unvoiced", "unknown"})
KIND = Closed({"talk", "option", "trigger", "wait"})


def _events(p):
    """任务与任务外对话共用的事件流字段。事件按 kind 带不同的键，所以除 kind 外都是 optional：
    talk / option 带 sentence_id、speaker、text、voice_id、voice、carrier；option 另带 trigger、reply；
    trigger / wait 带 custom_string，若它编码了一句台词（`TalkSentence_<id>`）也带那句的 sentence_id 等。"""
    o = dict(optional=True)
    return [
        F(p, "list", None, None, "有序事件流，顺序即剧情顺序"),
        F(p + "[].kind", "str", None, KIND, "talk 台词 / option 分支选项 / trigger、wait 控制流锚点"),
        F(p + "[].sentence_id", "int", None, None, "台词 id（TalkSentenceConfig）", **o),
        F(p + "[].speaker", "str", "台词表没给说话人，或本语种查不到", None, "说话人", **o),
        F(p + "[].text", "str", "本语种查不到台词", None, "台词正文，原样保留占位与富文本标记", **o),
        F(p + "[].voice_id", "int", "这句没挂语音", None, "语音 id，上游原值", **o),
        F(p + "[].voice", "str", None, VOICE, "配音标记", **o),
        F(p + "[].carrier", "str", "上游脚本没给承载台词的容器类型", None,
          "承载台词的 $type，上游原样（种类多且随版本增加，含少量混淆名，按自由取值）", **o),
        F(p + "[].trigger", "str", "选项没有触发串", None,
          "option 的 TriggerCustomString，与后续 wait 的 custom_string 配对成分支边", **o),
        F(p + "[].reply", "object", "选项的触发串没编码台词", None, "选了这个选项之后 NPC 的回答", **o),
        F(p + "[].reply.sentence_id", "int", None, None, "回答的台词 id"),
        F(p + "[].reply.speaker", "str", "台词表没给说话人，或本语种查不到", None, "回答的说话人"),
        F(p + "[].reply.text", "str", "本语种查不到", None, "回答正文"),
        F(p + "[].reply.voice_id", "int", "没挂语音", None, "语音 id"),
        F(p + "[].reply.voice", "str", None, VOICE, "配音标记"),
        F(p + "[].custom_string", "str", None, None, "trigger / wait 的自定义串", **o),
    ]


UPSTREAM = [
    F("upstream", "object", None, None, "上游快照"),
    F("upstream.commit", "str", None, None, "上游 commit"),
    F("upstream.version", "str", "上游提交标题里找不到版本号", None, "游戏版本"),
]

CONTRACTS = Contracts("starrail", {
    "missions": Table(1, [
        F("id", "int", None, None, "MainMissionID"),
        F("name", "str", "本语种查不到任务名", None, "任务名"),
        F("type", "str", None, Open({"Branch", "Main", "Gap", "Daily", "Companion"}), "任务类型，上游枚举原样"),
        F("sub_type", "str", "上游没给", Open({"Activity", "Game", "System", "World", "Endmost", "Rogue"}),
          "任务子类型，上游枚举原样"),
        F("chapter_id", "int", "不属于任何章节", None, "章节 id"),
        F("world_id", "int", "上游没给", None, "所属世界 id"),
        F("next", "list", None, None, "后续任务"),
        F("next[]", "int", None, None, "后续任务的 MainMissionID"),
        F("steps", "list", None, None, "子任务"),
        F("steps[].sub_id", "int", None, None, "SubMissionID"),
        F("steps[].target", "str", "本语种查不到或上游没给", None, "子任务目标"),
        F("steps[].desc", "str", "本语种查不到或上游没给", None, "子任务描述"),
        F("scripts", "list", None, None, "归到这个任务的剧情脚本"),
        F("scripts[].source", "str", None, None, "脚本在上游的路径"),
    ] + _events("scripts[].events") + UPSTREAM, [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一",
    ]),
    "dialogues": Table(1, [
        F("id", "str", None, None, "脚本路径（任务外对话没有数字 id）"),
        F("bucket", "str", None, None, "来源目录，如 Config/Level/MunicipalChatConfig"),
        F("location", "str", "路径里没有 FloorID，或本语种查不到", None, "地点名（{TEXTJOIN#n} 已按默认值替换）"),
        F("floor_id", "int", "路径里没有 FloorID", None, "FloorID"),
        F("interact_title", "str", "不是由 DialogueNPC / DialogueProp 指向的脚本", None,
          "交互标题，上游的明文标签（如 NPCName_Normal_Adele）"),
        F("group_id", "int", "不是由 DialogueNPC / DialogueProp 指向的脚本", None, "交互所在的组"),
    ] + _events("events") + UPSTREAM, [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一",
    ]),
    "messages": Table(1, [
        F("id", "int", None, None, "短信组 id"),
        F("contact_id", "int", None, None, "联系人 id"),
        F("contact", "str", "本语种查不到", None, "联系人名"),
        F("signature", "str", "联系人没有签名，或本语种查不到", None, "联系人签名"),
        F("sections", "list", None, None, "分节"),
        F("sections[].section_id", "int", None, None, "分节 id"),
        F("sections[].start", "list", None, None, "起始消息"),
        F("sections[].start[]", "int", None, None, "起始消息 id"),
        F("sections[].items", "list", None, None, "消息"),
        F("sections[].items[].id", "int", None, None, "消息 id"),
        F("sections[].items[].sender", "str", None, Open({"NPC", "Player", "PlayerAuto", "System"}), "发送方"),
        F("sections[].items[].item_type", "str", None,
          Open({"Text", "Sticker", "Image", "Link", "Video", "Raid"}), "消息类型"),
        F("sections[].items[].text", "str", "非文本消息，或本语种查不到", None, "消息正文"),
        F("sections[].items[].option_text", "str", "不是玩家发的选项（只有 Sender == Player 的行有意义）",
          None, "选项按钮上的文字"),
        F("sections[].items[].next", "list", None, None, "后继消息；多于一个就是分支"),
        F("sections[].items[].next[]", "int", None, None, "后继消息 id"),
        F("sections[].items[].voice", "str", None, Closed({"unknown"}), "短信一律 unknown"),
    ] + UPSTREAM, [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一",
    ]),
    "sentences": Table(1, [
        F("id", "int", None, None, "TalkSentenceID"),
        F("speaker", "str", "台词表没给说话人，或本语种查不到", None, "说话人"),
        F("text", "str", "本语种查不到", None, "台词正文"),
        F("voice_id", "int", "没挂语音", None, "语音 id，上游原值"),
        F("voice", "str", None, VOICE, "配音标记"),
        F("sources", "list", None, None, "引用这句的脚本；空 = 整个上游仓库里没有脚本引用它"),
        F("sources[]", "str", None, None, "脚本路径（missions / dialogues 里的 source / id）"),
    ] + UPSTREAM, [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一，按 id 排序",
    ]),
    "terms": Table(1, [
        F("id", "int", None, None, "TextMapHash（64 位），配上清单里的上游 commit 可以回查"),
        F("text", "str", "本语种缺译（基准语种 CHS 一定有）", None, "短名词文本"),
    ], [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一",
    ]),
    "textjoins": Table(1, [
        F("id", "int", None, None, "TextJoinID：台词里 `{TEXTJOIN#n}` 的 n"),
        F("default", "int", "默认项不在候选里（上游没给或指向不存在的项）", None, "默认项在 items 里的下标"),
        F("items", "list", None, None, "候选（玩家可选的名字），按上游 TextJoinItemList 的顺序"),
        F("items[]", "str", "本语种查不到", None,
          "候选文本，原样保留富文本标记（`<unbreak>`）；「自定义名称N」这类是玩家自己起名的那一格"),
    ], [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一，按 id 排序；各语种同一行的 items 一样长",
    ]),
})
