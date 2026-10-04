"""zzz 产物的内容契约：每张表、每个字段的类型、能否为 null、取值范围与含义。

**这里是唯一来源**：`emit` 按它逐行检查，`manifest` 按它写各表的契约版本，人和下游
（FlowOCR）也直接读这一份。字段写法与检查规则见 `gametext.core.contract`；通用规则
（版本怎么升、违反算什么）见 docs/architecture.md 的「内容契约」一节。
"""

from __future__ import annotations

from ..core.contract import Closed, Contracts, F, Open, Table


UPSTREAM = [
    F("upstream", "object", None, None, "上游快照"),
    F("upstream.commit", "str", None, None, "上游 commit"),
    F("upstream.version", "str", "上游提交标题里找不到版本号", None, "游戏版本"),
]

CONTRACTS = Contracts("zzz", {
    "scenes": Table(1, [
        F("id", "str", None, None, "<类别>|<章节>|<场景>，取自 TextMap key"),
        F("category", "str", None, None, "类别，如 Main"),
        F("chapter", "str", None, None, "章节段，如 GalGame_Chapter210 里的章节"),
        F("scene", "str", None, None, "场景 id"),
        F("kind", "str", "没匹配上 Perform 表",
          Open({"Chat", "Bubble", "BubbleStory", "GalGame", "BubbleNpc", "ChatAudio", "ChatPlus", "13"}),
          "场景类型：Perform 资源路径里的目录名，上游原样"),
        F("group", "str", "没匹配上 Perform 表", None, "Perform 资源分组"),
        F("title", "str", "没匹配上 Perform 表、上游没给，或本语种查不到", None, "场景标题"),
        F("intro", "str", "没匹配上 Perform 表、上游没给，或本语种查不到", None, "场景简介"),
        F("quests", "list", None, None, "连得到的任务；没有桥表的场景是空数组，不臆造关联"),
        F("quests[].quest_id", "str", None, None, "任务 id"),
        F("quests[].via", "str", None,
          Open({"ArchiveFileQuestTemplateTb.json", "ActivityBattleQuestTemplateTb.json"}), "经由哪张桥表连上"),
        F("cast", "list", None, None, "出场角色表（_Name_NNN 按序号），不是逐行说话人"),
        F("cast[]", "str", "本语种查不到这个名字", None, "角色名"),
        F("lines", "list", None, None, "台词，按 key 里的序号排"),
        F("lines[].slot", "str", None, None, "序号的数值形式；同一场景里可能有两行相同（_01 与 _1），唯一标识用 key"),
        F("lines[].text", "str", "本语种查不到", None, "台词正文，原样保留占位"),
        F("lines[].key", "str", None, None, "TextMap key，唯一标识一行"),
    ] + UPSTREAM, [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一",
    ]),
    "quests": Table(1, [
        F("id", "str", None, None, "任务 id"),
        F("name", "str", "上游没给或本语种查不到", None, "任务名"),
        F("display_name", "str", "游戏里显示的标题与 name 相同（多数）", None, "子任务实际显示的标题"),
        F("target", "str", "上游没给或本语种查不到", None, "任务目标"),
        F("description", "str", "上游没给或本语种查不到", None, "任务描述"),
        F("finish", "str", "上游没给或本语种查不到", None, "完成语"),
        F("prev_quests", "list", None, None, "前置任务（方向按 id 序推断，置信度见 report.json）"),
        F("prev_quests[]", "str", None, None, "任务 id"),
        F("next_quests", "list", None, None, "后继任务"),
        F("next_quests[]", "str", None, None, "任务 id"),
    ] + UPSTREAM, [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一",
    ]),
    "messages": Table(1, [
        F("id", "str", None, None, "短信组 id"),
        F("quests", "list", None, None, "关联的任务"),
        F("quests[]", "str", None, None, "任务 id"),
        F("nodes", "list", None, None, "按 step 排的分支节点"),
        F("nodes[].step", "int", None, None, "step 编号"),
        F("nodes[].messages", "list", None, None, "这一步的消息"),
        F("nodes[].messages[].message_id", "str", None, None, "消息的 TextMap key"),
        F("nodes[].messages[].speaker", "str", "上游没给或本语种查不到", None, "发送方"),
        F("nodes[].messages[].text", "str", "本语种查不到", None, "消息正文"),
        F("nodes[].options", "list", None, None, "这一步的选项"),
        F("nodes[].options[].text", "str", "本语种查不到", None, "选项文字"),
        F("nodes[].options[].goto_step", "int", "上游没给跳转目标", None, "选了跳到哪个 step"),
    ] + UPSTREAM, [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一",
    ]),
    "loose": Table(1, [
        F("id", "str", None, None, "TextMap key"),
        F("head", "str", None, None, "key 的类别前缀（如 Tips、AutoEventN），种类上千，按自由取值"),
        F("reason", "str", None, Closed({"non_story", "unmatched", "unused"}),
          "non_story = 按类别前缀排除的非剧情条目；unmatched = key 形态不是 <类别>_<场景>_<序号>；"
          "unused = 形态认得、但没进任何产物"),
        F("group", "str", "从 key 里读不出分组", None, "事件号等分组"),
        F("seq", "int", "从 key 里读不出序号", None, "组内序号"),
        F("text", "str", "本语种查不到", None, "文本"),
    ] + UPSTREAM, [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一",
    ]),
    "terms": Table(1, [
        F("id", "str", None, None, "TextMap key（明文），配上清单里的上游 commit 可以回查"),
        F("text", "str", "本语种缺译（基准语种 CHS 一定有）", None, "短名词文本"),
    ], [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一",
    ]),
})
