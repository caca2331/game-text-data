# 上游数据源：ZenlessData（绝区零）

本文记录上游的**实测事实**。数据于 **2026-09-09** 实测，快照 `e223d18a17`（3.2.0）。

## 仓库

| 项 | 值 |
| --- | --- |
| 主站 | `https://git.mero.moe/dimbreath/ZenlessData`（Gitea，分支 `master`） |
| 最近更新 | **2026-09-09**（当天，天级更新） |
| 数据版本 | `CNPRODWin3.2.0_R18779629_S18779629_D18761130` |
| 仓库大小 | 约 3 GB（只取 `TextMap` + `FileCfg`，本地 1.4 GB：工作区 923 MB + `.git` 500 MB） |
| 顶层目录 | `Data/`、`FileCfg/`、`TextMap/` |

### 托管在 Gitea，不是 GitHub / GitLab

**GitHub 上的 `Dimbreath/ZenlessData` 返回 `Repository access blocked`** —— 仓库存在但被
封锁。可用的是作者自建的 Gitea 实例。两个实际影响：

1. API 是 Gitea 那套：`https://git.mero.moe/api/v1/repos/dimbreath/ZenlessData/contents/<path>`，
   raw 是 `https://git.mero.moe/dimbreath/ZenlessData/raw/branch/master/<path>`。
2. **HTTP API / raw 对默认 UA 返回 403**，必须带浏览器 UA；`git clone` 不受影响。

单点风险比原神、崩铁都高：GitHub 那份已被封，只剩个人 Gitea 实例。上游存活检测在这里
尤其重要，阈值设为 30 天（上游常态是天级更新）。

## 最关键的一点：TextMap 的 key 是明文语义标识

这是绝区零和另外两个游戏最大的差异，也是首版方案能绕开混淆配置表的原因。

```json
{
  "Main_GalGame_Chapter000_1000003_001": "克里特空洞，旧地铁枢纽站某处。",
  "Main_GalGame_Chapter000_1000003_Name_001": "以骸",
  "QuestName_10010001": "兔与绳",
  "Side_Chat_031SecretRegion2_231463001_01": "嗯呢呱？（你说你刚才放了一只邦布进去？）"
}
```

统一形态：

```
<类别路径>_<场景数字>_[Name_]<序号>[变体字母]
```

- **类别、章节、场景、顺序全在 key 里**，剧情文本可以直接从 TextMap 提取并排序。
- **`_Name_` 后缀是场景的出场角色表**（第二版写的"与对话行靠「场景 + 序号」配对"是错的）：
  9438 个带名字的场景里，9419 个的名字序号严格 1..k 连续，9338 个名字互不重复、7988 个
  名字数少于台词行数。漏认它会把名字当成普通台词混进正文（第一版踩过）。
- 末尾字母是变体，实测 `F` / `M` 是主角性别分支（`MainChat_2_0001_03F`），保留不合并。

解析章节时有个坑：`Chapter` 后不能用 `\w+`，因为 `\w` **包含下划线**，会把
`Main_Chat_Chapter00` 拆成 category=`Main` / chapter=`Chat_Chapter00`。用 `[A-Za-z0-9]*`。

### key 的类别分布（438 193 条）

| 首段 | 条数 | | 首段 | 条数 |
| --- | ---: | --- | --- | ---: |
| `Activity` | 51 351 | | `Message` | 9 939 |
| `Main` | 50 387 | | `QuestTarget` | 9 600 |
| `PartnerTalk` | 48 974 | | `QuestName` | 7 008 |
| `PasserBy` | 23 223 | | `UIText` | 6 464 |
| `Tips` | 15 909 | | `MainChat` | 5 974 |
| `GalGame` | 15 865 | | `Item` | 3 583 |
| `Side` | 15 384 | | `NPCName` | 2 603 |
| `Companion` | 11 102 | | `Comic` | 2 451 |
| `QuestDesc` | 10 280 | | | |

## `Overwrite` 是覆盖层，不是并集

**这是实现前必须先验的一件事，验错了会静默拿到旧文本。**

每个语种有两份：`TextMap[_<LANG>]TemplateTb.json`（主表）与
`TextMap[_<LANG>]OverwriteTemplateTb.json`（覆盖表）。实测中文：

| 项 | 值 |
| --- | ---: |
| 主表 | 438 030 条 |
| 覆盖表 | 774 条 |
| key 与主表重叠 | 611 条（78.9%） |
| **重叠处值不同** | **611 条（全部）** |
| 覆盖表独有 | 163 条 |

重叠的 611 条值**全部不同**，且内容明显是修订版：

| key | 主表 | 覆盖表 |
| --- | --- | --- |
| `Side_Chat_320Shopkeeper2_232483003_Name_03` | 小萌 | 小簇 |
| `QuestTarget_601120307` | 根据声波信号寻找二号口的记号 | 寻找二号口的相关记号 |
| `ZKItem_4350106_Desc` | …大富豪商店-蓝图直售… | …大富豪商店-常驻商店-蓝图直售… |

所以合并顺序必须是**先主表、后覆盖**。

## 语种

**语言代码是 `JA` / `KO`**（不是原神/崩铁的 `JP` / `KR`），简体中文没有语言后缀。

| 语种 | 主表文件 | 大小 |
| --- | --- | ---: |
| CHS | `TextMapTemplateTb.json` | 44.0 MB |
| EN | `TextMap_ENTemplateTb.json` | 45.9 MB |
| JA | `TextMap_JATemplateTb.json` | 54.8 MB |
| KO | `TextMap_KOTemplateTb.json` | 50.3 MB |

另有 CHT / DE / ES / FR / ID / PT / RU / TH / VI，以及 `TextMap_Login[_<LANG>]TemplateTb.json`
（登录期 UI 文本，很小）。

## `FileCfg/`：文件名大多是明文，字段名才是混淆的

**首版这一节写错了。** 当时抽样只抽到 hash 命名的那批，得出"文件名与字段名双重混淆"
的结论。全量清点后（1721 个文件）：

| | 个数 |
| --- | ---: |
| **明文文件名**（`QuestConfigTemplateTb.json`） | **1499** |
| hash 文件名（`2162688849992516830.json`） | 222 |

所以**文件名是可用的锚点**，只有字段名需要推断：

```json
{ "IAEFFFFLKNB": [
    { "ODCODEPMLGG": 30101, "ANCOBODLNIK": "QuestName_30101",
      "MMPIPHLJPEI": "QuestDesc_30101", "EHFEGAHEGCA": "QuestTarget_30101" } ] }
```

顶层几乎总是单个 key（1697/1721），值是行数组；这个 key 自己也是混淆的，同一份快照内
跨文件稳定（三个文件都是 `IAEFFFFLKNB`）。按原神的经验，混淆名要假定逐版本变化。

推断的四条原语在 `src/gametext/zzz/filecfg.py`，最强的一条是**取值命中 TextMap 的明文 key**——
命中 `QuestName_30101` 同时证明了"这是文本字段"和"它是任务名"，比原神那边"命中数字
hash"多一层语义。

### 已解出身份的表

| 文件 | 行数 | 提供什么 |
| --- | ---: | --- |
| `PerformTemplateTb` | 30 335 | **主键就是 TextMap key 里的场景 id**（覆盖 81% 的长场景 id）；资源路径给出场景类型与分组 |
| `QuestConfigTemplateTb` | 19 194 | 任务的四个文本 key、前置/后继任务链 |
| `MessageConfigTemplateTb` | 12 002 | 短信：step 编号、两个选项与各自跳转目标 |
| `MessageGroupConfigTemplateTb` | 914 | 短信组 → 任务 |
| `MessageNPCTemplateTb` | 196 | 短信里的说话人 |
| `ArchiveFileQuestTemplateTb` | 295 | 任务 → 对话场景（主线/代理人档案，480 条边） |

### `PerformTemplateTb` 的资源路径

```
Data/ScriptConfig/Perform/Data/GalGame/Chapter00/GalGame_Chapter00_01.asset
Data/ScriptConfig/Perform/Data/Chat/Chapter00/Main_Chat_Chapter00_3000001.asset
```

`<Kind>` 实测取值：`Chat` 14 963、`Bubble` 7898、`BubbleStory` 3846、`GalGame` 2076，
另有 `BubbleNpc` / `ChatAudio` / `ChatPlus` 等零头，1221 行的路径不是这个形态（取不到就
留空，不猜）。

### 任务链的方向是推断出来的

`QuestConfig` 里有两个字段的取值大量落回本表 id 全集，且**每条边在对方字段里都有反向边
（5903/5903）**——这只能证明两者是同一关系的两个方向。定方向靠 id 序：**91.9%** 的边里，
前置字段指向更小的 id。置信度随 `report.json` 一起输出，方向要是翻了看得见。

### 撞见过的假桥

`KnowledgeConfigTemplateTb` 的**主键**有 60% 落在 Perform 的 id 全集里，纯属两个 id 空间
重叠。所以扫"场景↔任务"桥表时，一张表自己的主键不算对 Perform 的引用。任务侧不设这条
限制——`ArchiveFileQuest` 正是以任务 id 为主键的合法桥表。

## 上游边界：对话分支不在仓库里

`PerformTemplateTb` 只给资源路径，**`Data/ScriptConfig/` 这个目录在上游仓库里根本不存在**。
`Data/` 下只有四个子目录：

| 子目录 | 内容 |
| --- | --- |
| `JsonBytes/` | `ArcadeGame`、`AreaData`、`Audio`、`HollowEntity`、`NPCTransform` 等 |
| `WorldGraph/` | 只有 4 个文件，是主城节点图，**不是对话脚本** |
| `UI/` | 2 个文件 |
| `_unsorted/` | 技能/卡牌等散表 |

所以 GalGame / Chat 的选项与跳转**拿不到**，这是上游的边界，不是解析没做。
短信系统是唯一有完整分支图的对话，因为它的分支在 `FileCfg` 里而不在脚本里。

## 短信系统的分支语义（已人工核对）

以 group 1003 为例逐条对照中文文本核对过：

- 每条消息带一个 **step 编号**，同一 step 下可以有多条消息（连着发的几个气泡）。
- 带选项的那一行给出**两个选项文本 key**（`Option01_*` / `Option02_*`，另有
  `OptionLong01/02_*` 的长文本变体）与**各自的目标 step**。
- 选项与目标的配对靠**行内字段顺序**：每个选项 key 字段后面第一个"只出现在选项行上"的
  整数字段就是它的跳转目标。上游导出保持类定义顺序，比字段名跨版本稳定；这一条是推断。
- 实测 4661 条选项、4568 个分支节点、961 个组，**20 条跳转目标在同组里找不到**（上游自己
  的悬空引用），置空并计数。
- 消息类型不靠枚举字段判断，直接按"这一行带的是文本 key 还是选项 key"归类——少依赖
  一个混淆字段。

短信组里有 214 个能连到任务（`MessageGroupConfig` 的一个字段指向任务 id）。

## `Option01_*` 的归属已确定

首版记为"未纳入的 4550 条选项文本"。实测它们**全部属于短信系统**
（`MessageConfigTemplateTb` 里 2330 + 2331 条），现已随短信分支图产出。

## 场景→任务的补路：三条都不通（已查证）

| 尝试 | 实测 |
| --- | --- |
| `MainCityQuestTemplateTb` → Perform | 9504 行，无字段指向 Perform id 空间 |
| `MainCityQuest` → `MainCityObject` → Perform | 第一跳是实的（`GDNODKCFLAN`，5631 个取值 100% 落在 MainCityObject 主键里），但 MainCityObject 的 22 996 行里没有指向 Perform 的字段（最高 87/22201 = 0.4%，是 id 空间碰撞） |
| `InteractDataTemplateTb` → Perform | 13 297 行，同样只有 86/13296 = 0.01% 的碰撞 |
| 编号推断（样本 = 447 条已验证边） | 场景 id 8–9 位、任务 id 8 位；公共前缀长度 0/1/2/3 位分别 39/242/115/51 条，基本是巧合；"场景去尾 k 位 == 任务去尾 j 位"在 k,j∈[0,5] 内**零命中** |

结论：触发关系不在 FileCfg 里，应在 Perform 的脚本资源（`Data/ScriptConfig/`）里，
而那个目录不在上游仓库。与"对话分支拿不到"是同一个边界。

副产品（不值得单做，记一笔）：`MainCityObject` 的 `NNHMBDIKMKN` 给出对象的 NPC 名
（`NPCName0002` 之类，4152 条命中），`GKGCLLGGHCM` 给出日常问候语的 key
（`CommonDialogue_Lin_01`，3885 个对象引用）——但 `CommonDialogue_*` 全 TextMap 只有
**50 条**，是被大量复用的通用问候。

## 仍未纳入 / 未核实

- **`AutoEvent100000_26` 这类 key（10 689 条）在整个 FileCfg 里搜不到任何引用**，
  上游没有对应配置表，成不了场景；第三版起随 `loose_*` 输出（`group` / `seq` 取自 key）。
  漫画过场 `Comic_<32 位 hash>`（2451 条）同样没有引用、key 里也没有顺序，也在 `loose_*` 里。
- `QuestConfig` 有 19 194 行，比有文本的任务多；多出来的行引用的 TextMap key 在上游
  根本不存在（18 345 处），是废弃/未上线内容，不进产出。
- 场景↔任务的覆盖率低（531 条边 / 409 个场景）：只有少数几张表同时引用两者。
  `MainCityQuestTemplateTb`（9504 行的任务步骤表）没有直接指向 Perform 的字段，
  链路可能要经 `InteractDataTemplateTb` / `ConditionConfigTemplateTb` 再跳一层，未核实。
- `Data/WorldGraph/NodeConfig` 的结构（4 个文件）。
- 混淆字段名是否逐版本变化——按原神经验应假定会变，本仓库已按此设计，但尚未跨版本实测。
- 222 个 hash 命名的文件是什么，没查。

## 社区镜像

- `github.com/360NENZ/Dimbreath-ZenlessData` —— 搜索结果里出现过，API 查为 Not Found。
- `github.com/frintsq/ZZZData` —— 未核实。
- `github.com/ZZZure/ZenlessRes` —— 自述以 `Dimbreath/ZenlessData` 为源。

上游一旦失效，这几个是排查起点。全部**未经核实**。

## 第二来源：只剩玩家维基

交叉校验要的是**独立**来源，上面那几个镜像同源，对上了也证明不了什么。实测排查结果：

| 候选 | 结论 |
| --- | --- |
| 上游镜像（`ZZZure/ZenlessRes` 等） | 自述以 `Dimbreath/ZenlessData` 为源，**同源，不可用** |
| HuggingFace 语音数据集 | **没有**。崩铁那条 `simon3000/starrail-voice` 的路子在绝区零走不通 |
| `mrzjy/zenless_zone_zero_interknots_v1.0` | 只有绳网帖子、不到 1K 条、停在游戏 1.0，覆盖不到我们的语料 |
| **`zenless-zone-zero.fandom.com`** | **可用**。玩家从实机整理，与解包无关；MediaWiki API 可直接取分类成员 |

维基的两个限制：只有英文；只覆盖有人写过的条目，所以**回答不了"有没有漏"**。

校验结果与逐条分析见 [README 的"交叉校验"节](README.md)。一条值得记下的结论：
**维基用英文全名，游戏对话里用称呼，上游把两者存成不同的 key**——
`Avatar_Female_Size01_Lucy_En_FullName` = `Luciana de Montefio`，而对话里是 `Lucy`。
按全名比会误判成缺口。
