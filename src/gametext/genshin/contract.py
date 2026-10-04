"""genshin 产物的内容契约：每张表、每个字段的类型、能否为 null、取值范围与含义。

**这里是唯一来源**：`emit` 按它逐行检查，`manifest` 按它写各表的契约版本，人和下游
（FlowOCR）也直接读这一份。字段写法与检查规则见 `gametext.core.contract`；通用规则
（版本怎么升、违反算什么）见 docs/architecture.md 的「内容契约」一节。
"""

from __future__ import annotations

from ..core.contract import Closed, Contracts, F, Open, Table

VOICE = Closed({"voiced", "generic", "unvoiced", "unknown"})

CONTRACTS = Contracts("genshin", {
    "quests": Table(1, [
        F("id", "int", None, None, "mainQuestId"),
        F("name", "str", "本语种查不到任务名（多为 $HIDDEN / test 脚手架任务）", None, "任务名"),
        F("description", "str", "本语种查不到描述", None, "任务描述"),
        F("chapter_id", "int", "不属于任何章节", None, "章节 id"),
        F("chapter_title", "str", "不属于章节，或本语种查不到", None, "章节标题"),
        F("chapter_num", "str", "不属于章节，或本语种查不到", None, "章节序号文本，如「第二章 第三幕」"),
        F("series", "int", "上游没给", None, "任务系列 id"),
        F("tag", "str", "上游没给（MAINQUEST_TAG_NONE）",
          Open({"MAINQUEST_TAG_GUIDE", "MAINQUEST_TAG_RANK_ZERO_WQ", "MAINQUEST_TAG_ACTIVITY",
                "MAINQUEST_TAG_REPUTATION", "MAINQUEST_TAG_NATLAN_TRIBAL", "MAINQUEST_TAG_FLOWERLAND",
                "MAINQUEST_TAG_THESPIA", "MAINQUEST_TAG_ANECDOTE", "MAINQUEST_TAG_RESIDENT_ACTIVITY",
                "MAINQUEST_TAG_SNEZ_QUEEN"}),
          "任务标签，上游枚举原样"),
        F("steps", "list", None, None, "子任务，按上游顺序"),
        F("steps[].sub_id", "int", None, None, "子任务 id"),
        F("steps[].order", "int", "子任务只在 BinOutput 里、Excel 没有", None, "Excel 给的顺序号"),
        F("steps[].desc", "str", "本语种查不到步骤描述", None, "步骤描述"),
        F("steps[].fail_cond", "str", "上游没给", Open({"QUEST_HIDDEN"}), "失败条件组合，上游枚举原样"),
        F("dialog", "list", None, None, "对话节点：扁平列表 + next 边，不拍平成线性剧本"),
        F("dialog[].talk_id", "int", None, None, "所属 talk"),
        F("dialog[].attribution", "str", None, Closed({"explicit", "inferred"}),
          "explicit = 任务文件显式引用了这个 talk；inferred = 按 talkId 前缀推测"),
        F("dialog[].dialog_id", "int", None, None, "节点 id（游戏内编号）"),
        F("dialog[].role", "object", "节点没有说话人对象（上游没给或整个省略）", None, "说话人对象"),
        F("dialog[].role.type", "str", None,
          Open({"TALK_ROLE_NPC", "TALK_ROLE_PLAYER", "TALK_ROLE_BLACK_SCREEN", "TALK_ROLE_NONE",
                "TALK_ROLE_NEED_CLICK_BLACK_SCREEN", "TALK_ROLE_MATE_AVATAR", "TALK_ROLE_GADGET",
                "TALK_ROLE_CONSEQUENT_NEED_CLICK_BLACK_SCREEN", "TALK_ROLE_CONSEQUENT_BLACK_SCREEN"}),
          "说话人类型，上游枚举原样；上游省略时为 TALK_ROLE_NONE"),
        F("dialog[].role.id", "str", None, None,
          "说话人 id（NPC 时是 NpcExcelConfigData 的 id），上游原样；上游没给时是空串"),
        F("dialog[].speaker", "str", "上游没给独立的人名字段（多数节点），说话人要靠 role.id 反查",
          None, "说话人显示名"),
        F("dialog[].text", "str", "本语种查不到正文", None, "台词正文，原样保留占位与富文本标记"),
        F("dialog[].next", "list", None, None, "后继节点的 dialog_id"),
        F("dialog[].next[]", "int", None, None, "后继节点的 dialog_id"),
        F("dialog[].source", "str", None, None, "上游文件路径，便于定位"),
        F("dialog[].voice", "str", None, VOICE, "配音标记；任务对话一律 unknown"),
        F("upstream", "object", None, None, "上游快照"),
        F("upstream.commit", "str", None, None, "上游 commit"),
        F("upstream.version", "str", "上游提交标题里找不到版本号", None, "游戏版本"),
    ], [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一",
    ]),
    "reminders": Table(1, [
        F("id", "int", None, None, "链头的 reminder_id"),
        F("cyclic", "bool", None, Closed({True}),
          "只在链头不存在、上游 next 互指成环时出现，值恒为 true", optional=True),
        F("lines", "list", None, None, "链上的各行，按 next 顺序"),
        F("lines[].reminder_id", "int", None, None, "这一行的 reminder_id"),
        F("lines[].speaker", "str", "这一行没有说话人（系统提示），或本语种查不到", None, "名牌上的说话人"),
        F("lines[].text", "str", "本语种查不到正文", None, "字幕正文"),
        F("lines[].style", "str", None,
          Open({"Normal", "Banner", "CombatChat", "MoonInfoReminder", "DialogueWithPortrait",
                "WhiteMessage", "SpecialReminderOnTop", "TpsGlassesChat", "PenumbraStory",
                "EventPromptDown", "AbyssWarReminder", "SpecialReminderOnBottom", "RoleCombatBanner",
                "BottomLine", "WxycReminder", "DrillBattleReminder", "AbyssVsLunarisOnTop", "NoText",
                "InteractionPromptUI", "InfoTextDialog", "InstituteHomeInfo", "WitchNicoleReminder",
                "TradeShowBonus", "SpecialReminderV2OnTop", "VarkaReminderBottom",
                "InstituteHomeWarning", "VarkaReminder", "HerculesBattle", "EscoffierCookingChat",
                "AbyssWhisper", "VaultDungeonRadio", "PenumbraMiniStory", "SpecialReminderV2OnBottom",
                "WeaponQuestSnezhnayaTop", "InLevelTowerOfHanoiReminder", "SpecialFocusAttackReminder",
                "AbyssVsLunarisOnBottom", "RobotAbyssalNarrate", "RobotAbyssalNarrateBroken",
                "CommonSpecialReminderNormal", "MarionetteTeaTimeReminder", "RankedMatchFeverReminder",
                "PenumbraTarget", "PenumbraInfo", "CommonSpecialReminderWarning", "RobotAbyssalWarning",
                "VarkaReminderLocked", "SneakLEReminder", "NarrationChat", "RedBanner"}),
          "上屏样式，上游枚举原样；Normal 是屏幕下方的字幕带"),
        F("lines[].show_time", "number", None, None, "显示时长（秒）"),
        F("lines[].delay", "number", None, None, "出现前的延迟（秒）"),
        F("lines[].voice", "str", None, VOICE, "配音标记：hasAudio true → voiced、false → unvoiced"),
        F("upstream", "object", None, None, "上游快照"),
        F("upstream.commit", "str", None, None, "上游 commit"),
        F("upstream.version", "str", "上游提交标题里找不到版本号", None, "游戏版本"),
    ], [
        "各语种行数相同、逐行 id 相同",
        "reminder_id 不唯一：汇合的几条链各带一份共用的尾巴，唯一标识一行用 (id, reminder_id)",
    ]),
    "terms": Table(1, [
        F("id", "int", None, None, "TextMapHash，配上清单里的上游 commit 可以回查"),
        F("text", "str", "本语种缺译（基准语种 CHS 一定有）", None, "短名词文本"),
    ], [
        "各语种行数相同、逐行 id 相同",
        "id 全表唯一",
    ]),
})
