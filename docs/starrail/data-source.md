# 上游数据源：turnbasedgamedata（崩坏：星穹铁道）

本文记录上游的**实测事实**。数据于 **2026-09-09** 实测，快照 `8dc7843723`（4.5.0）。

## 仓库

| 项 | 值 |
| --- | --- |
| 主站 | `https://gitlab.com/Dimbreath/turnbasedgamedata`（分支 `main`） |
| 建库时间 | 2024-10-16 |
| 最近更新 | **2026-09-09**（当天，几天一更，比原神勤得多） |
| 数据版本 | `OSPRODWin4.5.0_D16445860_A16307208_L16320302` |
| 顶层目录 | `Config/`、`ExcelOutput/`、`Stages/`、`Story/`、`TextMap/` |

和原神同属 Dimbreath 维护，但**目录结构与数据形态完全不同**，不要照搬原神的经验。

sparse checkout 取 `ExcelOutput`、`Story`、`TextMap`、`Config/Level`，快照约 **2.0 GB**。
不要整个 `Config`（会涨到 2.9 GB，其余子目录几乎不含台词引用）；也不要漏 `Config/Level`
（漏了会只拿到 6.6% 的对话，见下）。

## 与原神的关键差异

| | 原神 | 崩铁 |
| --- | --- | --- |
| 字段名 | **混淆，且逐版本全变** | **全明文**，还带 `$type` 类型标记 |
| TextMap hash | 32 位 | **64 位** |
| 语种分片 | 少数语种拆片 | KR / RU / TH 拆片 |
| 对话组织 | 一 talk 一文件，talk 内含正文 | **台词表与引用分离**：脚本只存 `TalkSentenceID`，正文在 `TalkSentenceConfig` |
| 解析难度 | 需要整套结构推断 | **不需要推断**，按字段名直接取 |

**崩铁不需要 `infer.py` 那一套。**

## 对话链路

```
Config/Level/Mission/<MainMissionID>/**.json      对话脚本主体（14 万条引用）
Story/Mission/<MainMissionID>/**.json             剧情演出
Story/Discussion/Mission/<MainMissionID>/**.json  剧情讨论
        ↓  "TalkSentenceID": <9 位整数>
ExcelOutput/TalkSentenceConfig.json               台词表，240 488 条
        ↓  {"Hash": <64 位整数>}
TextMap/TextMap<LANG>*.json                       文本
```

### `ExcelOutput/TalkSentenceConfig.json`（240 488 条）

```json
{
  "TalkSentenceID": 802410001,
  "VoiceID": 802410001,
  "TextmapTalkSentenceName": { "Hash": 9653990880419140742 },
  "TalkSentenceText": { "Hash": 14237384574797792360 }
}
```

hash 被包在 `{"Hash": ...}` 对象里，不是裸整数 —— 崩铁数据的通用写法。

实测解析率：**台词 99.83%** 能查到文本（四语种一致），**说话人名只有 71.52%**
（`TextmapTalkSentenceName` 本身有大量缺失，不是查不到）。

### 引用源分布 —— `Config/Level` 是主体

这是 P0 摸底最重要的发现。按目录统计引用到的不重复 `TalkSentenceID`：

| 路径 | 含台词的文件 | 引用不重复台词 |
| --- | ---: | ---: |
| **`Config/Level`** | **24 766** | **140 983** |
| `Story/Discussion` | 2 847 | 14 379 |
| `Story/Mission` | 312 | 1 394 |
| `Config/Gameplays` | 210 | 1 004 |
| 其余（ConfigAbility / BattlePerformance / ConfigAnimEvents 等） | 21 | 113 |
| **合计** | | **156 325（65.00%）** |

这张表是在**整个 `Config` 都拉下来**时测的。正式的 sparse 只取 `Config/Level`（省 900 MB），
代价是丢掉 `Config/Gameplays` 等处的约 1100 条引用，覆盖率 65.00% → **64.58%**。
这是有意的取舍：0.42% 的覆盖换 900 MB。

另有被引用却在配置表里不存在的 TalkSentenceID（悬空引用；当时数到 5971 个，补回活动 / 教程目录后是 6683 个），定性见[悬空引用](#悬空引用3852-个-id-指向从未发布的台词)。

**只看 `Story/` 会严重误判**：那样只能覆盖 15 794 条，占 6.57%。第一版 sparse 配置漏了
`Config/`，得出的结论完全是错的。

> 这张表是 P0 摸底时的口径，只统计数字字段 `TalkSentenceID`。补上字符串形态的引用
> （见下文"台词引用的第二种形态"）之后，实际覆盖率是 **67.4%**；剩下 32.6% 已定性，
> 见"无人引用的台词：定性结论"。

### 归属：全部按任务 id 分目录

三个引用源都按**目录名 = MainMissionID** 组织，归属是现成的，不需要像原神那样反查引用路径：

| 目录 | 子目录数 | 命中 MainMissionID |
| --- | ---: | ---: |
| `Config/Level/Mission/` | 2 838 | **2 159** |
| `Story/Discussion/Mission/` | 557 | 538 |
| `Story/Mission/` | 301 | 296 |

`MainMission.json` 共 2166 条，其中只有 **7 条**在 `Config/Level/Mission/` 下没有目录。
`Config/Level/Mission/` 里另有 666 个目录名既不是 MainMissionID 也不是 SubMissionID
（`10000`、`100035`…），推测是活动/教程的独立编号空间，待定性。

**编号前缀不能用来归属。** 试过按"TalkSentenceID 去掉后 N 位命中 MainMissionID"归属，
只能覆盖 9.21% —— 崩铁不像原神那样用编号前缀编码归属，老老实实按目录走。

### `Config/Level/` 的其他子目录

| 子目录 | json 文件数 | 说明 |
| --- | ---: | --- |
| `Mission` | 32 156 | **任务对话主体**（其余目录现已全部纳入，产出到 dialogues_*.jsonl） |
| `GroupGraph` | 11 577 | |
| `NPCDialogue` | 7 711 | NPC 闲聊 |
| `PropDialogue` | 3 440 | 场景物件对话 |
| `MunicipalChatConfig` | 2 488 | |
| `Rogue` | 1 984 | 模拟宇宙 |
| `Tutorial` | 1 439 | |
| `Maze` | 977 | |

### 脚本里的 `$type`

`RPG.GameCore.*` 明文类名。已见到与对话相关的：`PlayOptionTalk`、`OptionTalkInfo`、
`LevelPerformanceInitialize`、`PlayTimeline`、`TriggerCustomString`、`WaitCustomString`、
`EndPerformance`、`FinishLevelGraph`、`WaitPerformanceEnd`。

`PlayOptionTalk` / `OptionTalkInfo` 意味着**有分支选项**，和原神一样不该在提取阶段拍平。
另有 `OptionList`、`SimpleTalk` 等字段承载对话结构。

## TextMap

`hash -> 文本` 扁平字典，**hash 是 64 位**：

```json
{ "12518437936274253375": "拍摄「巨树」" }
```

### 分片：KR / RU / TH 被拆成两片

实测四语种（各含 `TextMapMain` 小表）：

| 语种 | 文件 | 合计条目 |
| --- | --- | ---: |
| CHS | `TextMapCHS.json`(49.1 MB) + `TextMapMainCHS.json`(0.1 MB) | 465 910 |
| EN | `TextMapEN.json`(55.4 MB) + Main(0.1 MB) | 465 914 |
| JP | `TextMapJP.json`(64.8 MB) + Main(0.1 MB) | 465 915 |
| KR | **`TextMapKR_0.json`(38.5 MB) + `TextMapKR_1.json`(41.2 MB)** + Main(0.1 MB) | 465 906 |

**只读 `TextMapKR_0` 会静默丢掉一半韩文。** 代码里靠枚举目录匹配 `TextMap<LANG>(_N)?.json`
来收全分片，不写死文件名 —— 哪个语种被拆片是会变的。

### `TextMapMain<LANG>.json` 不是"主表"，而且完全冗余

名字极具误导性。实测：

- 只有 **1118 条**（主表 465 910 条，差 400 倍）
- 内容是「网络连接中断，请检查网络…」「退出游戏」这类**启动器/登录期 UI 文本**，
  `Main` 指的是 main menu
- **1118 条 key 全部已存在于主表中**（交集 = 1118 = 它的全部条目）

也就是说**合并它零收益**，与原神 `TextMap_Medium`（不合并会丢 20% 正文）完全不是一回事。
代码里仍然并入（无害，且万一上游改了模型能兜住），但分片重叠计数会稳定显示 1118 ——
那是正常值，不是异常。

> 本文档的上一版曾写"两张表基本不相交、必须合并"，那是**错的**：当时只各取前 60 KB 抽样，
> 没注意到体积差 400 倍。记录在此以免重蹈。

## 任务表

| 文件 | 条数 | 说明 |
| --- | ---: | --- |
| `MainMission.json` | 2 166 | `MainMissionID`(7 位)、`Type`、`Name.Hash`、`NextMainMissionList` |
| `SubMission.json` | 14 796 | `SubMissionID` 是 9 位 |
| `MissionChapterConfig.json` | — | 章节 |

`MainMission.Type` 分布：`Branch` 1542、`Main` 356、`Gap` 106、`Daily` 95、`Companion` 67。

## 台词引用的**第二种形态**：编码在自定义字符串里

第一版只认数字字段 `TalkSentenceID`，覆盖率停在 51.2%。实测还有一整类引用写成字符串：

```json
{ "$type": "RPG.GameCore.TriggerCustomString",
  "CustomString": { "Value": "TalkSentence_815111011" } }
```

全上游 `<名字>_<数字>` 形态的字符串里，前缀 `TalkSentence` 出现 **107 021** 次，其中
**103 020 次**能对上 `TalkSentenceConfig` 的 id（96.3%）。承载它的位置：

| `$type` | 次数 | 命中 |
| --- | ---: | ---: |
| `RPG.GameCore.WaitCustomString` | 44 984 | 43 293 |
| `RPG.GameCore.OptionTalkInfo`（的 `TriggerCustomString` 字段） | 42 021 | 40 355 |
| `RPG.GameCore.TriggerCustomString` | 17 812 | 17 223 |
| `RPG.GameCore.PlayRogueOptionTalk` | 1846 | 1800 |

**后果不只是少统计。** `OptionTalkInfo.TriggerCustomString` 指的正是"选了这个选项之后
播哪一句"，漏掉它等于选项对话只剩玩家的问、没有 NPC 的答。实测受影响的选项 29 922 个。

一个反例要留意：**约 2283 个选项的 trigger 指向的就是它自己那句**（只是"把这句念出来"
的信号），那种不是回答，当成 reply 会凭空复制一遍台词。

其余前缀（`Mission_` 19 421、`SubMission_` 17 882、`Talk_` 9035）命中率只有三成上下，
更像是编号空间碰巧重叠，**没有当作台词引用**。

## 无人引用的台词：定性结论

`TalkSentenceConfig` 240 488 条，能在上游找到引用的 162 064 条（67.4%）。剩下 78 424 条
（32.6%）**在整个上游仓库里搜不到任何引用**（第二版重跑是 162 067 / 78 421：补扫了任务根
目录下的散文件）。第二版起它们随**全量台词表** `sentences_*.jsonl` 输出，`sources` 为空。四条证据：

| 证据 | 数字 |
| --- | --- |
| 语音类型是 `StoryNew` | 44.8%（有引用的那批只占 5.7%） |
| 带 `VoiceID`（真的录了音） | 58.0% |
| id 去掉后 3 位后，同前缀处有已引用台词 | **92.5%** |
| 带说话人 / 中文查得到 | 79 031 / 90 823 |

抽样看内容也全是正经剧情（藿藿、素裳、桂乃芬的成段对白），不是废稿。

结论：**是上游边界，不是我们漏扫。** 脚本里驱动这类演出的是
`PlayTimeline → "Story/.../DS80151040201.playable"`，而 **`.playable` 文件不在上游仓库里**
（`git ls-tree` 全库 0 个）。上游只导出配置表与 LevelGraph，没导时间轴。

## 配音：`VoiceConfig` 与 `TalkSentenceMultiVoice`（4.5.0 实测）

| 表 / 项 | 值 |
| --- | --- |
| `TalkSentenceConfig` 带 `VoiceID` / 不带 | 83 181 / 157 308 |
| 其中 `VoiceID` 在 `VoiceConfig` 里查不到 | 53（产物标 `unknown`） |
| `VoiceConfig` 88 685 条，`VoiceType` 17 种 | `StoryNew` 44 300、空 37 391、`Archive` 1814、`NPC_Normal` 1788、`SystemReverb1` 1652、`Cutscene` 711、**`NoVoice` 329**（资源路径全为空）… |
| 挂着 `VoiceID` 但类型 `NoVoice` / 路径为空的台词 | 272 / 274（产物标 `unvoiced`） |
| `TalkSentenceMultiVoice`（一句多段语音） | 1035 条，1000 句在台词表里，**其中只有 3 句自己带 `VoiceID`**——不并上这张表，这 997 句会被错标成没有配音 |

17 种 `VoiceType` 全是播放方式（远近、混响、是否压低背景音），没有"泛用语音"这一类。
但**泛用语音在资源路径上看得出来**：几段通用短语被大量不同台词共用。按资源路径数被多少句**不同的**台词引用
（中文去 `<…>` / `{…}` / 标点后比，两两相似度有低于 0.6 的算不同）：

| 共用的不同台词数 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | ≥10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 资源路径数 | 137 | 5 | 17 | 1 | 9 | 6 | 3 | 1 | 12 |

合计 191 段，614 句台词挂的全是这类（另 4 句既有自己的语音、又挂了泛用的，算 `voiced`）。
被共用却**不算**泛用的 37 段，是同一句话的标记变体（`（这句话好像不太对劲……）` 与带 `<color=#dbc291ff>` 的同一句）。
典型：`side1_ytzx_trotter_normal`（29 句不同的 `哼哼…`）、`vo_ambient_wX_v420_broadcast_maomaogao_101..105`（各 21–27 句毫不相干的广播台词）。
性质与绝区零缺 `Data/ScriptConfig/` 相同。

顺带排除：上游顶层的 `Stages/`（3469 个文件，不在 sparse 里）实测引用台词 **0 条**。

## 短信系统（崩铁独有）

| 文件 | 条数 | 作用 |
| --- | ---: | --- |
| `MessageItemConfig.json` | 13 664 | 消息本体，`NextItemIDList` 即分支 |
| `MessageSectionConfig.json` | 779 | 分节 → 起始消息 |
| `MessageGroupConfig.json` | 767 | 组 → 联系人 + 分节列表 |
| `MessageContactsConfig.json` | 305 | 联系人名字与签名 |

`Sender` 分布：`NPC` 8869、`Player` 3158、`PlayerAuto` 1040、`System` 597。
`ItemType`：`Text` 12 953、`Sticker` 625、`Image` 77、`Link` 4、`Video` 3、`Raid` 2。
`NextItemIDList` 长度：1 → 11 478，0 → 1033，2 → 756，3 → 397。**长度大于 1 就是分支**，
后继指向的是 `Sender=Player` 的选项行。

**`OptionText` 只在 `Sender == "Player"` 的行上有意义**：

| Sender | 有 OptionText 且查得到 | 有但查不到 |
| --- | ---: | ---: |
| `Player` | 3108 | 5 |
| `NPC` | 1 | 967 |
| `PlayerAuto` | 32 | 98 |
| `System` | 2 | 57 |

非玩家行上的那 1157 条是残留 hash。照单全收会凭空造出 26% 的"未解析率"，还会给 NPC
消息安上一个不存在的选项标签。

`MessageItemTextOverride`（26 条）按任务进度替换正文，条件形如
`[FinishMainMission:1043710]`，**未解析**，输出取默认正文。

## 任务外对话的两条归属线索

| 线索 | 表 / 字段 | 覆盖 |
| --- | --- | ---: |
| 地点 | 路径里的 `F<FloorID>` → `MazePlane.FloorIDList` → `PlaneName` | 4021 / 8912 |
| 交互标题 | `DialogueNPC` / `DialogueProp` 的 **`ActPath`**（直接是脚本文件路径）→ `InteractTitle` | 767 |

`DialogueNPC` 共 1691 条 `ActPath`，其中 976 条落在任务目录里（那部分由任务侧处理），
命中任务外脚本的是 484 条；`DialogueProp` 377 条里命中 283 条。

`InteractTitle` 是**明文字符串**（`NPCName_Normal_Lila`），不是 `{"Hash": ...}`——
上游只在这张表里用这种写法，全库搜只有 `DialogueNPC.json` 出现。没有解析成真名。

## `{TEXTJOIN#n}`：上游的动态文本占位符

```json
TextJoinConfig: {"TextJoinID": 87, "DefaultItem": 870, "TextJoinItemList": [870,871,872,873]}
TextJoinItem:   870 -> 晖长石号 / 871 -> 开拓之尾号 / 872 -> 塔塔洛夫号 / 873 -> 飞翔时针号
```

185 组配置、527 个候选项。实测有 **449 个区域名就是 `{TEXTJOIN#87}`**（玩家选的飞船名）。
本仓库**只在标签里按 `DefaultItem` 替换，对话正文保持原样**。

## 悬空引用：3852 个 id 指向从未发布的台词

> **第二版补回任务根目录下 666 个活动/教程目录的脚本之后，悬空 id 是 6683 个 / 7170 次。**
> 下面的定性做在第一版数到的 3852 个上；多出来的 2831 个**没做跨版本对照**，别直接套用结论。

脚本引用了 `TalkSentenceConfig` 里没有的 id，3852 个、4214 次。定性用的是跨版本对照：

| 检查 | 结果 |
| --- | --- |
| 这批 id 在 3.8.0 的台词表里存在吗 | **0 个** |
| 台词表是否会删条目 | **不会**：3.8.0 → 4.5.0 旧有新无 **0 条**（196 549 → 240 488） |
| 与真实台词共享场景前缀（去掉后两位） | 1666 / 3852 = 43% |
| 承载位置 | talk 2957、wait 1058、option.reply 942、option 724、trigger 462 |
| 来源 top | `Story/Discussion/Mission` 1108、`Config/Level/Mission/1040204` 265 |

结论：不是被删的内容，是**上游脚本引用了从未发布过的台词**（上线前砍掉、脚本没跟着清）。
它们出现在 `SubMission.json`、`Performance*.json` 等表里的那些命中是编号空间碰撞，
不构成反证。明细在 `build/starrail/index/dangling.json`。

## 尚未核实

- `Config/Level/Mission/` 里 666 个非 MainMissionID 的目录是什么（活动/教程的独立编号
  空间）。第二版起它们当任务外对话输出（bucket 是所在的任务根目录），但**归属哪个活动**没查。
- 任务外对话还有 54.9% 拿不到地点（路径里没有 FloorID，如 `Rogue`、`NPCDialogue`），
  没查它们的文件内容里有没有别的线索。
- `MessageItemTextOverride` 的条件表达式。
- 说话人名缺失的 28.48% 是否能从别处（如 `CharacterUniqueName` → NPC 表）补全。
