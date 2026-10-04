# 上游数据源：AnimeGameData

本文记录上游数据源的**实测事实**，供 [architecture.md](architecture.md) 的设计依赖。

> 全部数据于 **2026-09-09** 实测。表格里的**具体数字与字段名取自 6.6.0 快照**
> （commit `433284d2`），当时的上游还是旧仓库。之后已升到 7.0.0（`26df1dfbdf`），
> 字段名如期全变、数量随之增长，但**结构性结论一条没变**，解析代码一行没改。
> 再升到 7.1.0（`792978e5`）时上游改了序列化方式（见[陷阱清单](#陷阱清单)第 11 条），
> 解析代码为此改过一次；7.0.0 上的产出因此只多补了 131 个说话人 id（旧代码的缺陷）。
> 上游字段名逐版本变化，本文的具体字段名会过期，**结构性结论不会**。
> 复现方式：`uv run gametext genshin all --no-fetch` 出全量数字；
> `uv run python tools/genshin/p0_probe.py --limit 0` 出 `Talk/Quest` 单目录的结构诊断。

## 仓库

| 项 | 值 |
| --- | --- |
| 主站 | `https://gitlab.com/Dimbreath/animegamedata2`（分支 `main`） |
| GitHub 镜像 | `https://github.com/DimbreathBot/AnimeGameData`（分支 `main`，sha 与主站一致） |
| 当前快照 | `792978e5503ecfba73dcb3562ed44a0d35a2abe2`（2026-10-01） |
| 数据版本 | `CNRELWin7.1.0` |
| 已废弃的旧仓库 | `gitlab.com/Dimbreath/AnimeGameData`（分支 `master`），因**仓库体积超限**弃用，停在 6.6.0；其 README 只剩一行指向新仓库。GitHub 镜像的 `master` 分支是它的残留 |
| 顶层目录 | `BinOutput/`、`ExcelBinOutput/`、`Readable/`、`Subtitle/`、`TextMap/` |

这是 HoneyHunterWorld 等第三方站点的共同上游。历史上叫 `Dimbreath/GenshinData`（GitHub），因 DMCA 迁到 GitLab 并改名，旧教程里的 GitHub 路径基本都失效了。

取数用 sparse checkout，只拉需要的目录（全量克隆没必要）：

```bash
git clone --depth 50 --filter=blob:none --sparse --branch main https://gitlab.com/Dimbreath/animegamedata2.git upstream
cd upstream && git sparse-checkout set ExcelBinOutput TextMap BinOutput/Talk BinOutput/Quest BinOutput/CodexQuest
```

单文件 raw：`https://gitlab.com/Dimbreath/animegamedata2/-/raw/main/<path>`
目录列举：`https://gitlab.com/api/v4/projects/Dimbreath%2Fanimegamedata2/repository/tree?path=<path>&ref=main&per_page=100&page=N`，响应头 `x-total` 给总数。

## TextMap

`TextMap/` 是 `hash -> 文本` 的扁平字典，所有文本都从这里解引用。

```json
{
  "9852": "与斯万对话",
  "30458": "它从一开始就不可能失控好吗？"
}
```

**key 是字符串，而配置文件里的 hash 是整数**，查表前要转。

### 每个语种有两张表，必须合并

这是最容易踩的一个坑：除了 `TextMap<LANG>.json`，还有一份 `TextMap_Medium<LANG>.json`，**两张表的 key 空间完全不相交**（实测交集为 0），内容互有重叠 —— 同一句「与斯万对话」在 plain 里 hash 是 `9852`，在 Medium 里是 `1648170132`，是两套独立的 hash 命名空间。

| 语种 | plain | Medium | 合并后 |
| --- | ---: | ---: | ---: |
| CHS | 246 111 | 546 797 | 792 908 |
| EN | 237 812 | 528 862 | 766 674 |
| JP | 237 729 | 528 830 | 766 559 |
| KR | 237 858 | 528 878 | 766 736 |

**只查 plain 会漏掉约 20% 的对话正文**（实测 `BinOutput/Talk/Quest` 的正文 hash 在 plain 单表命中率 80.2%，合并后 99.99%）。因为 key 不相交，合并没有冲突风险；`src/gametext/genshin/textmap.py` 在合并时会断言这一点，真撞上说明上游改了模型，必须停下来重新确认。

**语言代码是 `CHS` / `EN` / `JP` / `KR`**，不是 ja / ko。另有 CHT、DE、ES、FR、ID、IT、PT、TR、VI，以及被拆成两片的 `TextMapRU_0/1`、`TextMapTH_0/1`。

文本里含**未转义的 `\n` 字面量**（源 JSON 里是 `\\n`）以及 `{RUBY#[D]...}`、`#{M#郎君}{F#女侠}`、`{param9:P}` 之类的富文本/占位标记，是否清洗留给下游决定。

不是所有 hash 都能查到文本，详见下面的实测数字。**查不到必须计数上报，不能当成空字符串静默吞掉。**

## ExcelBinOutput

2038 个文件，字段名**大部分是明文**，只有少数被混淆成随机大写串。

### `MainQuestExcelConfigData.json`（5 MB，4075 条）

主任务定义。明文字段：`id`、`chapterId`、`series`、`titleTextMapHash`、`descTextMapHash`、`activeMode`、`mainQuestTag`、`repeatable`、`recommendLevel`、`rewardIdList`、`luaPath`。

**`id` 就是 HoneyHunterWorld 的 `q_XXXX`** —— 已用旧抓取数据交叉验证：3791/3818 的 id 命中，其中 3788 条标题逐字一致（3 条不一致全是 `$HIDDEN` 后缀或半角/全角破折号的差异）。

### `QuestExcelConfigData.json`（7 MB）

子任务（步骤）定义，通过 `mainId` 挂到主任务上。字段全明文：`subId`、`mainId`、`order`、`stepDescTextMapHash`、`guideTipsTextMapHash`、`failCondComb`。

### `RandomMainQuestExcelConfigData.json` / `RandomQuestExcelConfigData.json`

**NPC 随机委托单独一张表**，不在 `MainQuestExcelConfigData` 里。旧抓取数据里 27 条「上游查无此 id」的任务（`q_30000`–`q_30033`，"帕拉德的困境""琳的苦恼"这类）全部属于这一类。首版若要覆盖它们，需要额外读这两张表。

### `DialogExcelConfigData.json`（89 MB，203 908 条）

对话节点。字段几乎全明文，只有 id 被混淆成 `GFLDJMJKIKE`：

```json
{
  "GFLDJMJKIKE": 1000,
  "nextDialogs": [],
  "talkRole": { "type": "TALK_ROLE_NPC", "id": "1005" },
  "talkContentTextMapHash": 4157164819,
  "talkRoleNameTextMapHash": 1035328076,
  "talkTitleTextMapHash": 3918602051
}
```

**这个文件严重不完整，不能作为对话的唯一来源。** 实测从 `BinOutput/Talk/Quest/` 抽 6 个文件共 31 条对话，**0 条**出现在其中。它是旧版遗留的聚合表，新内容只落在 `BinOutput/Talk/`。把它当主源会静默丢掉大量近版本对话。

### `ReminderExcelConfigData.json`（18 332 条）—— 边玩边说的语音字幕

不在 Talk 里的对白：派蒙在路上的吐槽、比赛里队友喊话、战斗喊话。明文字段 `id` /
`nextReminderId`（串成链）/ `showTime` / `delay` / `hasAudio`（7.0.0：`true` 4284、`false` 14 048，没有缺字段的；
7.1.0 起这张表省略默认值，`false`、`delay: 0`、`style: Normal` 都不再出现，`showTime` 也写成 `3.0` 这样的浮点，
index 按整张表判断后补回默认值，见[陷阱清单](#陷阱清单)第 11 条）/
`soundEffect`（语音资源名，只有 10 条非空、互不重复——看不出泛用语音）/ `style`；说话人与正文是两个
混淆的整数 hash 字段（另各有一个同值的字符串副本，走 `walk_ints` 时不计）。7.0.0 实测：

| 项 | 值 |
| --- | --- |
| 正文字段 | 命中 99.6%，文本中位 20 字 |
| 说话人字段 | 命中 83.4%，文本中位 2 字（系统提示没有说话人） |
| 链头 / 汇合点 / 自指 / 无头环 / 悬空 next | 12 556 / 32 / 4 / 1 对 / 13 |
| `style` | `Normal` 13 802、`Banner` 1 681、`CombatChat` 802、`MoonInfoReminder` 560、`DialogueWithPortrait` 308… |

`ReminderIndexExcelConfigData`（4 行）只是几个 id 列表，不是索引。

### 已经不存在的文件

老代码和老教程常引用，现在都是 404：`TalkExcelConfigData.json`、`DialogUnparentedExcelConfigData.json`。

## BinOutput

### `BinOutput/Quest/`（4169 个文件）—— 任务与对话的连接点

文件名是 8 位 hex。这就是 Grasscutter 的 `MainQuestData` 所对应的目录：一个主任务一份，里面带 `subQuests` 列表和 **talk 引用列表**，是把 `BinOutput/Talk/*` 归属到具体任务的依据。字段名全混淆，但和 `Talk` 的 hex-named 变体共用同一套混淆名（例如 `GALIDJOEHOC`、`HAHEIAHBPEJ` 在两边都出现），且 `HAHEIAHBPEJ` 在各级嵌套里稳定持有明文枚举（`QUEST_CONTENT_COMPLETE_TALK`、`QUEST_GUIDE_NONE` 等），可作类型判别锚点。

### `BinOutput/Talk/`（对话主源）

按场景分子目录：

| 子目录 | 文件数 | 性质 |
| --- | ---: | --- |
| `Quest/` | 22 339 | 任务对话 |
| `Npc/` | 16 012 | NPC 闲聊 |
| `FreeGroup/` | 3 508 | 自由对话 |
| `NpcGroup/` | 3 528 | **容器** |
| `Activity/` | 2 068 | 活动 |
| `Gadget/` | 1 430 | 场景物件 |
| `Coop/` | 1 287 | 邀约/协同 |
| `NpcOther/` | 1 225 | 其他 NPC |
| `GadgetGroup/` | 619 | **容器** |
| `Blossom/` `BlossomGroup/` | 310 / 302 | 对话 / **容器** |
| `Storyboard/` `StoryboardGroup/` | 210 / 110 | 对话 / **容器** |
| `ActivityGroup/` | 90 | **容器** |
| `Cutscene/` | 36 | 过场 |

标"容器"的五个 `*Group` 目录**不是对话列表**，而是一个文件列若干 talk。按对话硬解
会产出两万多个没有正文的空节点 —— 比解析失败更危险，因为报告看起来是绿的。推断层
用文本字段得分阈值把它们整批否决，见 [architecture.md 的两道否决](architecture.md#两道否决)。

#### 字段名混淆的真实形态：少数几种 schema，不是逐文件随机

以 `Talk/Quest` 为例，**全部 22 339 个文件**做顶层 key 聚类只有 4 种 signature
（全部 15 个子目录合计 18 种）：

| # | 顶层 key | 文件数 | 文件名形态 |
| ---: | --- | ---: | --- |
| 1 | `IOEDPLCPFFB, KFCNJPJOJLA, MEGMIMEDODJ` | 21 961 | 数字 |
| 2 | `AADKDKPMGNO, GALIDJOEHOC, HAHEIAHBPEJ` | 337 | 8 位 hex |
| 3 | `dialogList, talkId` | 40 | 混合 |
| 4 | `KJNKFMPAGAA, PBAEPDPNKEJ` | 1 | 数字 |

第 3 种**完全没有混淆**（`id`、`nextDialogs`、`talkRole`、`talkContentTextMapHash`），说明上游的 dump 里混着不同来源的产物。

各 schema 推断出的字段角色（算法见 [architecture.md 的结构推断](architecture.md#结构推断)）：

| 语义 | schema 1 | schema 2 | schema 3 | schema 4 |
| --- | --- | --- | --- | --- |
| 对话数组 | `IOEDPLCPFFB` | `GALIDJOEHOC` | `dialogList` | `KJNKFMPAGAA` |
| dialogId | `GMOMCKNPBGE` | `NFIEHACCECI` | `id` | `JOLEJEFDNJJ` |
| nextDialogs | `JDAPCNPEAEH` | `GBLICFDCPCK` | `nextDialogs` | `CLMNEDLMAJL` |
| talkRole | `DGGDDIMMIDO` | `PIBKEGJOJHN` | `talkRole` | `IFAOOKCBDGD` |
| 正文 hash | `HJJLLECCCPI` | `AIGJBMCHCJG` | `talkContentTextMapHash` | `EMKCOIBADBJ` |
| 说话人名 hash | `GMENEADIGBP` | `BMFGJJJPBBC` | — | — |
| 头衔 hash | `OIDNCDGMBPP` | — | — | — |

**混淆名跨文件是稳定的**（同 schema 内），但**跨 schema 不通用**，更关键的是**跨版本必变**。

#### 跨版本实测：字段名每个版本全换一遍

取同一个文件 `BinOutput/Talk/Quest/1010061.json`，在四个版本的 commit 上分别读顶层 key：

| 版本 | commit | 顶层 key |
| --- | --- | --- |
| 7.1.0 | `792978e550` | `PCIAMAFDDAA, talkId`（talkId 成了明文） |
| 7.0.0 | `26df1dfbdf` | `ALBFHGKNMLK, IOKNFDJFGDH, PFALHAKIILD` |
| 6.6.0 | `4d9593eb73` | `IOEDPLCPFFB, KFCNJPJOJLA, MEGMIMEDODJ` |
| 6.5.0 | `f9a2140673` | `AADKDKPMGNO, GALIDJOEHOC, HAHEIAHBPEJ` |
| 6.4.0 | `b761e4d2e9` | `DLPKMDPABFM, LBPGKDMGFBN, LOJEOMAPIIM` |
| 6.3.0 | `a7624301c8` | `ADHLLDAPKCM, MOEOFGCKILF, PAINLIBBLDK` |

**五个版本无一重合。** 任何硬编码字段名的实现每个版本都会崩，而且是静默崩。这就是
本项目坚持结构推断的全部理由。

这条路线已经受过一次真实检验：6.6.0 → 7.0.0 换上游、换分支、字段名全变，**解析代码
一行没改**，非预期失败仍为 0（dialogId 从 `GMOMCKNPBGE` 变成 `OIFGMOHKPOI`，推断照样认出）。
7.0.0 → 7.1.0 字段名照样全换，推断也都认出来了；要改代码是因为上游改了序列化方式
（[陷阱清单](#陷阱清单)第 11 条），不是字段名。

顺带解释了上面那张 schema 表：6.5.0 的字段名正是 6.6.0 里的 **schema 2**（hex 命名
那批）。也就是说 6.6.0 快照里那 337 个 hex 文件是**上一版本遗留的旧 dump**，上游没有
重新导出它们 —— 这解释了它们为什么正文命中率只有 0.71（部分文本已从新 TextMap 移除），
以及为什么和数字命名文件成对重复。`BinOutput/Quest` 里那 94 个"旧格式"文件同理。

节点样本（schema 1）：

```json
{
  "DGGDDIMMIDO": { "_id": "1425", "_roleId": 0, "_type": "TALK_ROLE_NPC" },
  "JDAPCNPEAEH": [ 101006102 ],
  "GMOMCKNPBGE": 101006101,
  "HJJLLECCCPI": 4035856019,
  "IMEKKPMAIBN": "DIALOG_UI_NONE",
  "KNBLFLMPABH": "TALK_SHOW_DEFAULT"
}
```

**混淆之中留下的明文锚点**（推断算法就靠这些）：

- `_type` / `_id` / `_roleId`：talkRole 对象内部是明文，`_type` 取 `TALK_ROLE_NPC`、`TALK_ROLE_PLAYER`、`TALK_ROLE_BLACK_SCREEN` 等
- 字符串枚举值本身是明文：`DIALOG_UI_NONE`、`TALK_SHOW_DEFAULT`、`UI_Icon_Quest_Once`
- dialogId 与 nextDialogs 之间的引用关系是强结构信号
- 文本 hash 能在合并后的 TextMap 里命中，是强判别信号

#### 空 talk 是合法状态

全部子目录合计 474 个文件是空壳：只有 talkId 和一个**空的** dialogList。另有 6 个
文件连 dialogList 都没有（如 `{"talkId": 328, "type": "COOP"}`）。两者都是正常数据，
不是解析失败 —— 把它们当失败会污染失败计数。

### `BinOutput/CodexQuest/`（483 个文件）

任务图鉴视角的章节组织，文件名就是 chapterId。字段名全混淆，**但每个文本节点自带明文语义 tag**：

```json
{
  "LEMPMANEBOB": { "OPKOJIEHJAE": 1076121409, "JAJHEIKBFAF": "DialogNormal" },
  "KDDMHACHOGH": { "OPKOJIEHJAE": 1356474581, "JAJHEIKBFAF": "SpeakerKnown" }
}
```

递归找同时含 hash 和 tag 的二元对象即可，无需认识外层随机 key。**全量枚举出的 tag 共 12 种**：

| tag | 出现次数 | tag | 出现次数 |
| --- | ---: | --- | ---: |
| `DialogNormal` | 100 398 | `ChapterTitle` | 483 |
| `SpeakerKnown` | 88 636 | `MainQuestDesp` | 483 |
| `SpeakerPlayer` | 9 104 | `ChapterNum` | 483 |
| `SubQuestTitle` | 4 690 | `MainQuestTitle` | 483 |
| `Narratage` | 2 670 | `IPCustomizedWhole` | 190 |
| `Aside` | 892 | `IPCustomizedPartial` | 64 |

hash 载体字段是 `OPKOJIEHJAE`（206 636 次）与 `BKGOAJFIHCO`（1940 次）。

CodexQuest 只覆盖进了任务图鉴的 483 章，**不是全量任务**，只能作为章节组织与展示顺序的来源，对话仍要走 `BinOutput/Talk/Quest/`。

### 其他可能有用的目录

`Readable/`（书籍、信件正文）、`Subtitle/`（过场字幕）、`BinOutput/Story/`、`BinOutput/Cutscene/`、`BinOutput/Voice/`。首版不做，schema 里预留位置即可。

## 数据质量实测（`BinOutput/Talk` 全部 15 个子目录）

| 指标 | 数值 |
| --- | ---: |
| 文件数 | 53 074 |
| 写出 talk / 对话节点 | 43 600 / 414 145 |
| schema signature 数 | 18 |
| 空 talk（dialogList 为空） | 474 |
| 空壳 talk（连 dialogList 都没有） | 6 |
| 重复 talkId 的多余文件 | 5342（节点按 dialog_id 合并，找回 10 612 个独有节点） |
| **非预期解析失败** | **0** |
| 预期内失败（`*Group` 容器目录整批） | 4126 |
| 未被任务引用的 talk | 21 644，其中 6111 可按编号前缀推测归属 |

各子目录写出的 talk 数：Quest 21 715、Npc 15 556、Activity 2016、FreeGroup 1852、
Gadget 1394、Coop 473、Blossom 246、Storyboard 209、NpcOther 109、Cutscene 30。
颗粒无收的是 `ActivityGroup` / `BlossomGroup` / `GadgetGroup` / `NpcGroup` /
`StoryboardGroup` —— 它们是 talk 容器，不是对话列表。

最终语料的文本解析率见 `corpus/genshin/report.json`：对话正文未解析 CHS 0.05%、EN/JP/KR 约 0.79%。

## 陷阱清单

1. **`TextMap` 与 `TextMap_Medium` 是两套不相交的 hash 空间，必须合并查询。** 只查 plain 会漏掉约 20% 的对话正文。
2. `DialogExcelConfigData.json` 不完整（实测抽样 0/31 命中），不能当对话主源，用 `BinOutput/Talk/`。
3. `BinOutput/Talk/Quest` 有 4 种 schema，其中 1 种完全未混淆。混淆名同 schema 内稳定、跨 schema 不通用、跨版本不保证 —— 结构推断，别硬编码。
4. 空 dialogList 是合法的空 talk（222 个），不是解析失败。
5. `next` 数组里混有 `0`、`30`、`108` 这类非 dialogId 的小整数占位，要过滤。
6. TextMap key 是字符串，配置里是整数。
7. 语言代码是 JP / KR，不是 ja / ko；RU / TH 被拆片。
8. NPC 随机委托在 `RandomMainQuestExcelConfigData.json`，不在 `MainQuestExcelConfigData.json`。
9. `TalkExcelConfigData.json`、`DialogUnparentedExcelConfigData.json` 已不存在。
10. 上游随时可能被 DMCA 下架，本地快照要留存并记录 commit。
11. **7.1.0 起上游序列化时省略取默认值的字段**（空数组、空串、0、false、枚举首值），部分字段名
    也换回了明文（`id`、`talkId`、`questId`…）。受影响的五处：
    - `BinOutput/Quest`：同一种 schema 的文件键集合各不相同，4417 个文件拆成 1376 个顶层键集合，
      按键集合分组推断的旧做法只认出 319 个主任务、其余整批误判为遗留副本。现在按"共享任一键"
      并成家族再推断。不同 schema 的**混淆名**互不相交，并不到一起；明文键会跨 schema 共享，
      所以主格式里 mainQuestId 重复时记非预期失败。
    - 空 talk：空的对话数组不再写出，空 talk 只剩 `{talkId}`（空壳 6 → 482、空数组 491 → 16），
      照空 talk 写出，否则任务对它们的引用全成悬空（实测 4 → 235）。它们也参与按编号前缀的
      归属推测，所以"未归属 talk"的计数里含空 talk。
    - talkId 为 0 的 `Talk/Quest/GlobalDialog.json` 没有了顶层整数，按缺省 0 处理（只在恰好一个
      文件这样、且 0 没被带对话的文件占用时；FurnitureGroup 里有两个明写 0 的旧格式空容器，不算占用）。
    - `ReminderExcelConfigData` 缺的字段，在整张表找不到显式默认值时补回默认值（与 7.0.0 共有的
      18 332 行补完逐字段一致）。
    - 对话节点的说话人对象：键大部分从 `_id` / `_type` 改叫 `id` / `type`（7.0.0 里未混淆的那批 talk
      已经叫 `id`；7.1.0 仍有约 1.7 万个节点用旧键），代码两种键名都认；枚举首值 `TALK_ROLE_NONE` 被省略，对象在、类型缺时就是它（两版都占 0.29%）。

    其余用到的 Excel 表在 7.0.0 就已经省略默认值，读法不受影响。
