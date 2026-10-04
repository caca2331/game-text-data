# 使用说明：产出的语料

`uv run gametext starrail all` 产出的东西长什么样、各字段什么意思。怎么跑见 [README](README.md#快速开始)。

每个字段的类型、能否为 null、取值范围以内容契约 [`src/gametext/starrail/contract.py`](../../src/gametext/starrail/contract.py) 为准（规则见根架构说明的[内容契约](../architecture.md#内容契约)），本文讲各表的来历与取舍。

## 输出

```
corpus/starrail/
├── missions_{chs,en,jp}.jsonl.zst    任务：元数据 + 按脚本分组的对话事件流
├── dialogues_{chs,en,jp}.jsonl.zst   任务外对话：按来源目录分桶
├── messages_{chs,en,jp}.jsonl.zst    短信
├── sentences_{chs,en,jp}.jsonl.zst   全量台词表：每句一行，带 sources
├── terms_{chs,en,jp}.jsonl.zst       短名词
├── report.json                          完整性报告
└── manifest.json                        清单（产物包协议）
```

各表各语种行数相同、逐行 id 相同（`--compress none` 出 `.jsonl`）。清单与打包的协议见根[架构说明](../architecture.md#产物包协议gtd-bundle1)：`uv run gametext starrail bundle` 打包进仓库根的 `out/`，发布用 `release`、记进 `releases/starrail/fingerprints.tsv`。

崩铁的本地化是完整的：四语种 TextMap 条目数几乎相同，"上游缺译"计数为 0，各语种未解析率完全一致。

## 对话是有序事件流，带分支

不是一个台词列表 —— 顺序即剧情顺序，选项与跳转都在里面：

```
talk    [受伤的云骑] 帝弓庇佑，你们不是「药王秘传」的人……
talk    [三月七] 你可别再乱动了，让咱看看有什么办法能让你快点好起来。
option  →「（提供治疗）」 trigger=TalkSentence_102120928
option  →「（暂时放弃）」 trigger=TalkSentence_102120930
wait    TalkSentence_102120928        ← 选「提供治疗」走这条
talk    [三月七] 来吧，服下这个，对快速恢复有帮助的。
wait    TalkSentence_102120930        ← 选「暂时放弃」走这条
talk    [三月七] 咱们手头竟然没有可以救急的东西吗？
```

事件按脚本分组（`scripts[].events[]`），四种 `kind`：`talk`（台词）、`option`
（分支选项，带 `trigger` 与 `reply`）、`trigger` / `wait`（控制流锚点）。**分支的边靠
`option.trigger` 与后续 `wait.custom_string` 配对**还原。

台词引用有两种形态：数字字段 `TalkSentenceID`，和编码在自定义字符串里的 `TalkSentence_<数字>`。`option.reply` 就是选项 `TriggerCustomString` 指向的那句回答（"选了之后 NPC 说什么"）；`trigger` / `wait` 事件若编码了台词也一并展开。承载台词的容器有 7 种 `$type`（`PlayAndWaitSimpleTalk` 最多，其次 `PlayOptionTalk`），解析见 [`src/gametext/starrail/script.py`](../../src/gametext/starrail/script.py)。

## 全量台词表 `sentences_*`

`TalkSentenceConfig` 的每句台词一行，按 id 排序，带说话人、语音 id 与 `sources`（引用它的脚本，没人引用就是空数组），一句不漏。约三分之一的台词没有任何脚本引用（多是过场演出的配音，为什么见[架构说明](architecture.md#没人引用的台词)），但它们在屏幕上是有的，所以单出这张表（下游 FlowOCR 实测：两段 10 分钟切片里能在语料中找到的屏幕文字，从 47 条涨到 204 条）。

**这张表不做"按 id 连号归到哪个脚本"的推断。** 例子摆在那里：`DS105430507` 先
`PlayTimeline`，时间轴里念的 153050701–703 没人引用，紧接着的选项 153050704–706 引用在
这个脚本里——id 连号，要不要据此归组是下游的判断，这里只保证不漏、并附上已知的引用。

## 任务外对话 `dialogues_*`

`Config/Level` 与 `Story` 下除任务目录之外的全部脚本，加上任务根目录下目录名不是 MainMissionID 的活动 / 教程脚本。没有任务归属，按来源目录分桶（4.5.0 的脚本数）：

| 来源 | 脚本数 | | 来源 | 脚本数 |
| --- | ---: | --- | --- | ---: |
| `Mission`（任务根目录下归不了属的活动/教程目录） | 5103 | | | |
| `MunicipalChatConfig` | 2488 | | `NPC` | 416 |
| `GroupGraph` | 2046 | | `SubLevelGraph` | 316 |
| `PropDialogue` | 1235 | | `Maze` | 141 |
| `Rogue` | 767 | | `LevelInstanceGraph` | 129 |
| `RogueDialogue` | 581 | | `CrowdBubble` | 122 |
| `NPCDialogue` | 578 | | 其余 10 类 | 369 |

### 地点与交互标题

这批对话本来就不属于任何任务，但有两条**查得证**的线索，都不用猜：

| 线索 | 怎么来的 | 覆盖 |
| --- | --- | ---: |
| `location` | 路径里的 `F<FloorID>` 段（`.../MunicipalChatConfig/F10001001/...`）→ `MazePlane` 的 `PlaneName` | 4021 / 13 890 = **28.9%**（活动/教程脚本的路径里没有 FloorID） |
| `interact_title` | `DialogueNPC` / `DialogueProp` 的 **`ActPath` 直接指向脚本文件**，顺带给出交互标题 | 638（产物行数口径） |

```
location=观景车厢 / Parlor Car
   [系统] 您有一条跨星际通讯信息，请及时查收。

interact_title=NPCName_Normal_Adele
   [阿德勒] 又见面了，最近你有没有发现什么新奇的小生物呢？
```

两条线索基本不重叠：带 FloorID 的是场景/城区脚本，带 ActPath 的是 NPC/物件交互。
查不到就留空，不猜。

`{TEXTJOIN#n}`（玩家选的飞船名之类的动态占位符）**只在标签里解**：实测有 449 个区域名就是 `{TEXTJOIN#87}`，用 `TextJoinConfig` 的 `DefaultItem` 替换（87 → 晖长石号）。**对话正文一律保持原样**：占位符本身是信息（玩家的选择），要不要替换是下游的事。

## 短信 `messages_*`

`MessageItemConfig` 等四张表，全明文，不需要推断：

```
组 10002  联系人 黑塔 / Herta
  NPC        嘿，{NICKNAME}，我是黑塔，有好事找你
  NPC        速来我的办公室！等你！
  PlayerAuto ？
  选项        可你就在我旁边啊          ← NextItemIDList 有多个后继就是分支
  选项        你直接说不就行了
  NPC        [自动回复]您好，我现在有事不在，一会也不会和您联系
```

结构是 `MessageGroupConfig`（组 → 联系人 + 分节）→ `MessageSectionConfig`（分节 →
起始消息）→ `MessageItemConfig`（消息 → `NextItemIDList`）。分支就是后继多于一个。

**`OptionText` 只在玩家发的那条上有意义。** NPC / System / PlayerAuto 行也带这个字段，
但值是查不到的残留 hash（1157 条）。照单全收会凭空造出 26% 的"未解析率"，还会给 NPC
消息安上一个不存在的选项标签。

## 配音标记 `voice`

每句台词（`missions` / `dialogues` 的事件、选项的回答、`sentences` 的每一行）带一个四态字段，
下游用它区分"这句屏幕上的字有没有对应的语音"（比如拿 ASR 结果去重时）：

| 取值 | 判据 |
| --- | --- |
| `voiced` | 语音 id（`VoiceID` 并上 `TalkSentenceMultiVoice` 的多段语音）在 `VoiceConfig` 里查得到，且至少一段是**这句自己的**语音（资源路径非空、类型不是 `NoVoice`、不是泛用语音） |
| `generic` | 有语音，但挂的全是**泛用语音**：几段通用短语配给大量写着不同台词的对话框（支线、广播、生物叫声；JRPG 常见做法），播出来的和字幕内容对不上 |
| `unvoiced` | 没有任何语音 id；或挂着的语音类型全是 `NoVoice` / 路径为空 |
| `unknown` | 挂着语音 id 但 `VoiceConfig` 里一个都查不到；**短信一律 `unknown`** |

**泛用语音**的判据：同一段资源路径被 ≥2 句台词共用，而这些台词的中文去掉 `<…>` 标记、`{…}` 占位符与标点之后，
两两相似度有一对低于 0.6。只数"文本 hash 不同"是不够的——同一句带不带 `<color=…>` 是两个 hash、却是同一句话。
4.5.0 实测 191 段泛用语音、614 句 `generic`（例：`vo_ambient_wX_v420_broadcast_maomaogao_101` 被 27 句毫不相干的台词共用）。

`voice_id` 照旧保留（上游原值）。`unvoiced` 是按"上游只给录了音的台词挂语音"推的，
不是逐句听过；分布见 `report.json` 的 `index.sentence_voice_*`。

## 短名词 `terms_*`

TextMap 里"像名词"的短串逐条照搬，一个 TextMapHash 一行（`{"id": <hash>, "text": ...}`），给下游按屏幕上的字查译名用——
名牌上的人名、称号、任务目标这类短文本，常常不在任何台词的说话人字段里。口径和 genshin 相同：

- **只按形状收**（`emit.is_term`，只看 CHS 那份，所以各语种的行集合天然相同）：CHS ≤ 16 字
  （4.5.0 全量台词表里去重后的说话人中文名 5722 个，长度 P99 = 13）、含汉字或假名、不带句读 / 换行 /
  占位与富文本标记（`{TEXTJOIN#…}`、`<…>`）/ `test`。上游没有"这条是人名"的标记，所以不按"被哪张表引用"去筛。
- **出处**就是 `id`（TextMapHash），配上清单里的上游 commit 可以回查；行上不重复带 `upstream`。
- **不去重、不消歧**：同一个日文串可能对应几个 hash、几种中文，怎么取是下游的事。
- 本语种查不到写 `null`，计进报告的 `terms_missing`（4.5.0：EN 1 / JP 0）。

## 语种与压缩

默认出**中英日三语**、产物 **zstd 压缩**：

```bash
uv run gametext starrail all --langs chs,en,jp --compress zstd   # 这就是默认
uv run gametext starrail all --langs chs                  # 只要中文
uv run gametext starrail all --compress none              # 出原始 .jsonl
```

- 语种同时决定 `snapshot` **下载什么**：TextMap 里装着全部语种，只取需要的
  从 868 MB 降到 170 MB。**收窄只对下一次取数生效**，已有快照要重新克隆才变小。
- 产物是 JSONL（UTF-8，一行一个 JSON 对象）；压缩后 `*.jsonl.zst`，234 MB → **21 MB**。
  读端一律走 `jsonl.open_read`，先找 `.zst` 再找原始文件，对下游透明。
- 基准语种 CHS 永远在列 —— 少了它就分不开"上游缺译"和"上游根本没这条"。

依据与取舍（为什么是 zstd level 3、为什么 `corpus/starrail/` 里分文件压）见根架构说明的
[产物格式](../architecture.md#产物格式jsonl--zstd)。
