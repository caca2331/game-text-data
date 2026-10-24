# 架构说明

为什么这样解析、流水线怎么分层、各判据的依据。上游数据本身的实测见 [data-source.md](data-source.md)，产出格式见 [manual.md](manual.md)。

## 为什么是这条路

前身是一个抓 HoneyHunterWorld 的网页爬虫（维护者的另一个项目），已经不可行：站点整站 403，且抓站天生靠图遍历逼近全集、无法证明没漏，四语种四次独立请求会静默不齐，改一次 parser 要重爬七小时。

换成离线解包数据后，这几类问题在结构上就不存在了：

| | 抓站 | 离线解包数据 |
| --- | --- | --- |
| 获取 | ~15 000 次请求 / 7 小时 / 现已 403 | 一次浅克隆，约 40 秒重跑 |
| 完整性 | 图遍历逼近，无法证明 | 全量快照，不存在漏爬概念 |
| 多语言 | 四次独立请求，会静默不齐 | 同一 hash 查四张表，天然对齐 |
| 增量 | 无 | `git pull` |
| 改 parser | 重爬 7 小时 | 本地重跑 |

上游是 [Dimbreath/animegamedata2](https://gitlab.com/Dimbreath/animegamedata2)，也是 HoneyHunterWorld 等第三方站点的共同数据源（原仓库因体积超限已废弃，见开发指南的[上游搬过一次家](dev-guide.md#上游搬过一次家)）。

旧爬虫的具体毛病（2026-09-09 实测）：站点全站 403（带完整浏览器头亦然）；5 条任务因单次请求超时被静默丢弃、2 条永久缺日文；旧数据 chs/en/ko 各 3818 行、ja 只有 3816 行；不落原始 HTML，改 parser 只能重爬。

## 核心难点：字段名每个版本全换一遍

上游 `BinOutput/` 下的 JSON 字段名是混淆过的随机大写串。取同一个文件 `BinOutput/Talk/Quest/1010061.json`，在四个版本上分别读顶层 key：

| 版本 | 顶层 key |
| --- | --- |
| 6.6.0 | `IOEDPLCPFFB, KFCNJPJOJLA, MEGMIMEDODJ` |
| 6.5.0 | `AADKDKPMGNO, GALIDJOEHOC, HAHEIAHBPEJ` |
| 6.4.0 | `DLPKMDPABFM, LBPGKDMGFBN, LOJEOMAPIIM` |
| 6.3.0 | `ADHLLDAPKCM, MOEOFGCKILF, PAINLIBBLDK` |

7.0.0 又换了一遍：`ALBFHGKNMLK, IOKNFDJFGDH, PFALHAKIILD`，dialogId 从 `GMOMCKNPBGE`
变成 `OIFGMOHKPOI`。7.1.0 再换一遍，而且 talkId 成了明文：`PCIAMAFDDAA, talkId`。

**每个版本无一重合。** 硬编码字段名的实现每个版本都会崩，而且是静默崩 —— 这也是社区
现有的几个提取器都 pin 死在某个旧版本的原因。

这条路线已经过一次真实检验：从 6.6.0 升到 7.0.0，**解析代码一行没改**，非预期失败仍
为 0，对话未解析率从 0.05%/0.79% 变成 0.04%/0.82%，交叉校验的逐字相同率纹丝不动
（96.23%）。

7.1.0 是第一次要改代码的升级，原因不在字段名，而在序列化：上游开始省略取默认值的字段，
同一种 schema 的文件键集合各不相同，按键集合分组的 Quest 推断只认出 319 / 4417 个主任务
（报告当场红掉，没有静默）。改法与另外四处同源的问题见 [data-source.md 的陷阱清单](data-source.md#陷阱清单)
第 11 条；改后的代码在 7.0.0 上重跑，产物只差一处：131 个对话节点补上了原先缺的说话人 `role.id`（见开发指南的[跨版本回归](dev-guide.md#跨版本回归)）。

所以本项目**不认字段名，只认结构**。所有解析代码自己写，没有用现成项目（调研记录见[与社区项目的关系](#与社区项目的关系)）。

## 流水线

下面的路径都在仓库根的 `upstream/genshin/`、`build/genshin/`、`corpus/genshin/` 之下。

```
        网络（只有这一步联网）
         │
 snapshot ──→ upstream/               animegamedata2 的 sparse 浅克隆
         │    build/snapshot.json     commit + 游戏版本
         ↓
 index ──────→ build/index/talks.jsonl    46535 个 talk，441510 个节点
         │     build/index/quests.jsonl   4417 个主任务 + talk 归属
         │     build/index/reminders.jsonl 12703 条语音字幕链（不经 assemble）
         │     build/index/voices.json     Dialog / DungeonReminder 的正向配音映射
         │     build/index/pronouns.jsonl  78 个称谓 / 句尾键 → TextMapHash（不经 assemble）
         │     build/index/readables.jsonl 阅读面板长文本的出处：Readable/ 各语种文件名或 TextMapHash（不经 assemble）
         │     build/unparsed.jsonl       所有失败，分预期 / 非预期
         ↓
 assemble ───→ build/assembled.jsonl      任务树，**文本仍是 hash**
         ↓
 emit ───────→ corpus/{quests,reminders,terms,pronouns,readables}_{chs,en,jp}.jsonl.zst + report.json
```

三条约束：

- **获取与解析分离。** `snapshot` 之外任何阶段都不联网。改 parser 永远不会触发重新下载。
- **`assemble` 刻意不解引用文本。** 产物里存的仍是 TextMapHash，于是 `emit` 就是纯粹的"一份任务树 × 四张 TextMap"。四语种逐行对齐因此是**结构保证**，不是靠事后校验。
- **每阶段产物落盘，可单独重跑。** 上游目录结构大改时（如 DialogExcel 那样被弃用）只需重做 index 层；孤儿 / 未解析计数会先报警。
- **内存**：TextMap 只保留实际用到的 hash 子集，index 层用 JSONL 流式写。

模块与边界（快照、CLI、产物包、契约检查机制在三款共用的 `gametext.core`）：

```
src/gametext/genshin/
├── __init__.py   # 上游配置（仓库、sparse 目录、版本号写法）与各阶段的接线
├── textmap.py    # TextMap 装载与 hash 查询
├── infer.py      # 结构推断：混淆 JSON -> 统一 schema；不认识"任务""对话"这些业务概念
├── index.py      # 遍历 BinOutput/Talk 与 BinOutput/Quest，产出规范化中间层
├── assemble.py   # 任务树装配（MainQuest / Quest / CodexQuest / Talk）；不碰混淆字段名
├── emit.py       # 逐语种展开与 JSONL 写出
├── voice.py      # Voice 触发映射，按结构与已知 id 集合推断参数字段
├── readable.py   # 阅读面板长文本：Readable/ 的路径与读法、阅读界面配置表的清单
├── contract.py   # 各表的内容契约
└── report.py     # 完整性校验与报告
```

## 结构推断

判据都是可独立验证的结构特征：

| 要认的东西 | 判据 |
| --- | --- |
| 对话数组 | 顶层"元素全为 dict 的数组"，含说话人对象的优先 |
| 说话人 | 值是 dict，其中某个值以 `TALK_ROLE_` 开头（混淆没覆盖枚举值） |
| `nextDialogs` | 值为整数数组的字段 |
| `dialogId` | 取值集合与 next 并集重合度最高（对话是链/树）；next 用不上时退到"逐节点唯一且查不到文本" |
| 正文 hash | 覆盖率 × TextMap 命中率最高（两个维度缺一不可，各有实测反例） |
| 说话人名 / 头衔 | 同样是文本字段，按覆盖率排在正文之后 |
| 任务 / talk 引用 | 用已知 id 集合当锚点反查 JSON 路径，再用贪心集合覆盖挑出真引用 |
| 标题 vs 描述 | 都是文本，靠**文本长度中位数**区分（标题中位 5 字，描述 32 字） |

对话按 schema signature 推，`BinOutput/Quest` 按 signature 并成的家族推，分述如下。

### 对话：按 schema signature 推

**推断单位是 schema signature，不是单个文件。** signature = 顶层 key 集合；同一 signature 的所有文件共用一套字段名，把证据在这些文件之间汇总再推断。这样做有两个好处：单节点、甚至零节点（空 talk）的文件能沿用同组多节点文件的结论；证据量大，判据更稳。实测 `Talk/Quest` 全部 22 339 个文件只归成 4 种 signature。

步骤：

1. **定位对话数组**：顶层「元素全为 dict 的数组」，含 talkRole 的优先，其次取最长。**空数组也算命中** —— 那是合法的空 talk，当失败会污染失败计数。
2. **talkRole**：值是 dict，且其中某个值以 `TALK_ROLE_` 开头。`_id`（7.1.0 起多为明文 `id`）即 NPC id；缺 `TALK_ROLE_` 值即 `TALK_ROLE_NONE`（7.1.0 起上游省略这个默认值）。
3. **nextDialogs**：值为「整数数组」的字段，取出现次数最多的那个。
4. **dialogId**：整数字段中，取值集合与 nextDialogs 并集重合度最高者（对话是链/树，除根节点外每个节点都被引用一次）。实测重合度 0.90–0.92，次优候选只有 0.0–0.17，区分度足够；低于 0.5 判为推断失败。
5. **文本 hash**：按 **覆盖率 × TextMap 命中率** 打分，最高者为正文。两个维度缺一不可，实测都有反例：
   - 只看命中率：schema 1 下正文、说话人名、头衔命中率都是 1.0，区分不开（覆盖率分别是 99.4% / 4.3% / 0.9%）。
   - 只看覆盖率：schema 2 的正文字段命中率只有 0.71（有一批文本已从 TextMap 移除），硬卡命中率阈值会把正文判成非文本，反而选中命中率 0.97 但只覆盖 4.8% 节点的说话人名。

   得分全为 0 时留空并上报，不硬指一个字段当正文（schema 4 就是这种情况）。其余命中率 ≥0.5 的字段按覆盖率排序作为附加文本字段（说话人名、头衔）。
6. **枚举字段**：值为 `DIALOG_UI_*` / `TALK_SHOW_*` 等明文串的原样保留，不猜语义。

`BinOutput/CodexQuest/` 走另一条更简单的路径：递归找同时含 hash 和明文语义 tag 的二元对象，按 tag 分派（全量 12 种 tag，见 [data-source.md](data-source.md)）。

`ExcelBinOutput/` 的字段基本明文，直接按名取；遇到混淆键忽略。

扩到 `BinOutput/Talk` 全部 15 个子目录时（原先只索引 `Talk/Quest`，留下 59 个真任务的对话在别处），dialogId 的判据需要后备：`FreeGroup` / `NpcGroup` 的 next 指向跨文件节点，`NpcOther` 干脆没有 next 字段。后备 `_id_by_uniqueness` 取**逐节点唯一且查不到文本**的整数字段（文本 hash 的 TextMap 命中率接近 1，dialogId 接近 0）。后备判据会造出垃圾，所以要有下面的[两道否决](#两道否决)。

同一 talkId 的多份文件**各有独有节点**：取一份作主、其余按 dialog_id 合并（"取节点最多的一份"在交叉校验里实测丢了 1465 条台词）。

### Quest 的家族

`BinOutput/Quest` 的推断单位是**家族**：把 signature 按"共享任一键"求连通分量。7.1.0 起上游省略取默认值的字段，同一种 schema 的文件因缺的字段不同而键集合各异（4417 个文件拆成 1376 个 signature）；不同 schema 的混淆名互不相交，按共享键合并不会把它们混成一族；明文键（`id` 等）会跨 schema 共享，所以主格式里 mainQuestId 重复时记非预期失败。7.0.0 的主格式与遗留格式因此仍是两族，7.1.0 只剩一族。

### 任务↔对话：用已知 id 当锚点

`BinOutput/Quest/` 的字段名同样混淆，但它引用的 id 都能从别处独立拿到明文集合，于是用**已知 id 宇宙当锚点**反推路径（`infer.infer_id_paths`）：主任务 id 来自 `MainQuestExcelConfigData`，talkId 来自上一步索引出的 talk。以 6.6.0 为例，推出的结果：

| 语义 | 路径 | 证据 |
| --- | --- | --- |
| mainQuestId | 顶层 `GMOMCKNPBGE` | 4075 个值 100% 落在 Excel 主任务集合里 |
| talk 引用 | `CIAOBJHFJJM.[].GMOMCKNPBGE` | 覆盖 talk 宇宙的 99.80% |

**选路径必须看覆盖率，不能只看命中率。** talk 宇宙有两万多个 id，总有语义无关的字段碰巧全部命中 —— 它们命中率也是 1.0，却只覆盖宇宙的零头。第一版只按命中率收，多收了 5748 条假引用。现在改成**贪心集合覆盖**（`infer.pick_reference_paths`）：每轮取新增覆盖最多的路径，新增量低于 0.5% 就停。结果只选中一条真路径，`quest_talk_refs == quest_talk_hit == 21960`，零悬空。

被拒的 `CIAOBJHFJJM.[].IDDOEGDAMJP.[]` 覆盖率 12.6% 但只带来 42 个新 id —— 它是 talk 内部的分支列表，不是新的 talk 引用，拒得对。

### 步骤文本与标题、描述

`QuestExcelConfigData` 的 `stepDescTextMapHash` / `guideTipsTextMapHash` 两个字段
17 814 条全都有值，但**只有 698 条能在 TextMap 里查到**，而且解出来的是剧情简介
而非步骤描述。真正的步骤文本在 `BinOutput/Quest` 的子任务节点里，命中率 99.97%。

定位方式和别处同源 —— `infer.infer_text_paths` 把"能在 TextMap 里查到"
当判据，再用**文本长度中位数**区分同为文本的几个字段：

| 路径 | 中位长度 | 判定 |
| --- | ---: | --- |
| 顶层 `ALLMCLJBBDM` | 5 | 主任务标题 |
| 顶层 `JDFENJAFCPF` | 32 | 主任务描述 |
| `IKECHKLEFFK.[].JDFENJAFCPF` | 9 | 子任务步骤描述 |

于是 Excel 只保留明文元数据（`order`、`failCondComb`），文本全部走 BinOutput。
步骤数也从 Excel 的 17 814 涨到 BinOutput 的 31 045。

标题和描述用**双源回落**：Excel 的 hash 优先，查不到时用 BinOutput 那份 —— 两处
存的是同一段文本的不同 hash，互相能补。

### 同一份数据的两个副本

上游同时保留了新旧两套 dump，不去重会重复计数（数字是 6.6.0 的）：

- **`BinOutput/Quest` 的 94 个遗留格式文件**：mainQuestId 全部与新格式重复，零独有，且不引用任何 talk。整批丢弃。
- **334 组重复 talkId**（328 组 hex+数字、6 组双数字）：其中 284 组内容完全一致，50 组不一致的**全是副本为空、正版有完整文本**。去重规则：**取文件名等于 talkId 的那个文件**，实测 334/334 恰好有唯一一个这样的文件。

这也解释了 hex schema 正文命中率只有 0.71 —— 它本来就是废弃副本。

### 两道否决

推断能力越强，越容易"成功地解析出垃圾"。这比解析失败危险得多，因为报告是绿的。所以有两道否决：

1. **文本字段得分低于阈值 ⇒ 判定这不是对话列表。** `BinOutput/Talk` 下的五个 `*Group` 目录是 talk **容器**（一个文件列若干 talk），早期版本"成功"解出 20 274 个节点，其中有正文的只有 3 个。加阈值后整批正确否决。
2. **失败要分级。** 整个子目录颗粒无收是**结论**不是事故（`failures_expected`）；能出数据的目录里个别文件解不出才是事故（`failures_unexpected`，让流水线以非零码退出）。当前非预期失败为 0。

`MIN_CONTENT_SCORE` 是 0.1：实测各真目录得分 0.28–0.99，容器目录低于 0.01。

### 配音映射

sparse 快照包含 `BinOutput/Voice/`。`voice.py` 只读 Items 与 Lut，按明文枚举值
`Dialog` / `DungeonReminder` 找触发字段，再按触发字段名聚合同一来源中的 schema。
将顶层正整数与已归一化的 Talk / Reminder id 集合对照，唯一命中率至少 0.9 的字段才是参数；
歧义、无候选、缺源目录都写入 `unparsed.jsonl` 并让报告硬失败，不沿用旧索引。
不硬编码混淆字段名。Items 还要求对象内存在 `.wem` 路径，排除无资源的事件占位。

两源取并集写 `build/index/voices.json`，emit 按 `dialog_id` 补任务对话的 `voiced`；
Reminder 按 `reminder_id` 优先补 `voiced`，未命中再依 `hasAudio`（含原来的默认值补全）。
任务对话缺映射保持 `unknown`；不把旅行者或其他说话人当作无配音判据，不推测 `generic`。
报告分别记来源文件 / 事件数、推断字段、两类 id 数及已知 id 命中数；任务覆盖按产物 dialog 行计，
reminder 补标按原始表行计，链汇合造成的产物重复行不混进表行计数。

### 阅读面板长文本

`readables_*` 有两类来源（上游事实见 [data-source.md 的 Readable 一节](data-source.md#readable阅读面板的正文)）：

- **`Readable/` 目录**：各语种文件名不同，对齐靠 `LocalizationExcelConfigData` 的同一行。那一行的列名中文是混淆串，
  所以不认列名，**按取值认**：值形如 `…/Readable/<语种>/<名>` 的就是那个语种的文件。同一行同一语种出现两个不同文件、
  或整张表一行都认不出，记非预期失败。**每个要产出的语种都要有 `Readable/<语种>/` 目录**，缺了也记非预期失败：
  sparse 规则漏掉某个语种时，那一列会整批写 `null`，行数、对齐、契约照样通过，不拦就会被当成上游缺文本。
  报告里"语种目录缺失"与"本地化记录指向的个别文件不存在"分开计。
- **阅读界面配置表**（`readable.TABLES`：信件、教程说明页、活动来信、角色故事，各带自己的行 id 字段）：正文字段按结构认，取 TextMap 命中率 ≥ 0.5 的顶层
  整数字段里**文本长度中位数最长**的那个（标题、署名都短）；否决：中位数不到 20 字就整张表判失败，不产出把标题当正文的表。

行集合只看基准语种（CHS）：CHS 没文本的不收；**CHS 文本与任务对话或语音字幕里某一句整段相同的也不收**（下游把这张表叠加到画面上，
同一段字两张表都认领会抢）。比较前两边都过 `readable.normalize`（字面量 `\n` 换成换行、去首尾空白）。

### 推断失败怎么办

**必须计数并落盘到 `build/genshin/unparsed.jsonl`，附文件路径与失败原因。** 静默跳过是本项目唯一不可接受的错误处理方式 —— 前身项目 29% 的任务对话为空，因为 parser 里一句 `except: pass`，事后已经无法判断有多少是 bug 造成的。

### 归属：显式与推测严格分开

没有任务显式引用的 talk 按 talkId 前缀推测归属（实测 98.62% 的 talkId 以所属
mainQuestId 为前缀），歧义时取最长前缀匹配。这类节点标 `attribution: "inferred"`，
与 quest 文件显式引用的 `"explicit"` 分开，下游可自行过滤。7.1.0 是 31.7 万显式 / 3.4 万推测，另有 1.7 万个 talk（NPC 闲聊等）不归属任何任务。

## 上游的坑

完整清单见 [data-source.md 的陷阱清单](data-source.md#陷阱清单)，最容易踩的三个：

1. **每个语种有两张 TextMap**（`TextMap<LANG>` 与 `TextMap_Medium<LANG>`），**key 空间完全不相交**，必须合并。只查前者会漏掉约 20% 的对话正文。
2. **`DialogExcelConfigData.json` 严重不完整**，不能当对话主源（抽样 31 条对话 0 条命中）。对话在 `BinOutput/Talk/`。
3. **`QuestExcelConfigData` 的 `stepDescTextMapHash` 是死字段**，17 814 条只有 698 条能查到文本。真正的步骤文本在 `BinOutput/Quest` 里，命中率 99.97%。

## 报告与校验

`corpus/genshin/report.json` 每次 `emit` 生成。硬性校验不过则 CLI 以非零码退出：任一份产物各语种行数或逐行 id 不一致、非预期解析失败非零（含语音字幕表的字段推断失败、Voice 映射缺源目录或推不出唯一参数字段）、输出主任务数少于上游。（语音字幕的无头环单独成链、计 `reminder_cycles`，结构上不会有"不在任何链上"的 id，所以那条判据删了。）

报告区分**上游缺译**与**解析失败**（6.6.0 实测：EN 缺的 1665 条标题里 93% 的中文原文就是 `$HIDDEN` / `(test)` / `$UNRELEASED`）：查不到文本时再查一次 CHS，CHS 有而本语种没有＝上游从未本地化（多为 `$HIDDEN` / `test` 内部字符串，EN 有 12 000 余条），记录但不报警；四语种都查不到＝上游根本没有这段文本，才值得报警。混在一起会让 EN/JP/KR 的未解析率虚高到 40%，看着像流水线坏了。

报告里还有这些计数，只告警、不让流水线失败：各语种 TextMapHash 未命中数、文本为 `null` 的节点数、悬空 `next`、空对话任务数、未被任务引用的 talk 数、任务引用了却不存在的 talk 数。告警阈值按基线略放宽，用途是**抓回归**而不是重复报告已知事实。

## 与旧爬虫的交叉校验

旧爬虫留下一份 3818 条的抓取结果（维护者本机，未入库），质量有问题，但它是**完全独立的第二来源**，用来验证没接错字段、没解错 TextMap。`q_XXXX` 就是 mainQuestId（3818 条里 3791 条命中上游主任务表、3788 条标题逐字一致；未命中的 27 条是 NPC 随机委托），所以两边能按 id 对齐，台词按 dialogId 对齐。脚本是 `tools/genshin/crosscheck.py`。

结果（6.6.0）：

| 共有 dialogId 268 963 条 | 条数 | 占比 |
| --- | ---: | ---: |
| 逐字相同 | 258 834 | 96.23% |
| 去掉富文本标记后相同 | 951 | 0.35% |
| 仅占位符差异 | 8 729 | 3.25% |
| **真不同** | **449** | **0.17%** |

占位符差异是新数据**更忠实**：上游写 `{NICKNAME}`，HoneyHunter 渲染成了"玩家"。
剩下 0.17% 抽样看也基本是同类差异，只是判据切分不准。

覆盖面对比：

- 任务：旧 3818 / 新 4075。仅旧有 27 条（全是 NPC 随机委托，在
  `RandomMainQuestExcelConfigData` 里，不纳入，见[记录在案，不做](#记录在案不做)）；**仅新有 284 条**，其中 201 条
  是真任务 —— 旧爬虫的漏爬量。
- 台词：旧 273 864 / 新 318 552。**仅新有 34 425 条**；仅旧有 4436 条，其中 2613 条
  只是归属到了别的任务，**真正缺失 1823 条（占旧台词 0.67%）**。
- 旧数据有 1117 个任务一条台词都没有，新方案给其中 **533 个补回了 8961 条台词** ——
  这就是旧 parser 那句贪婪正则加 `except: pass` 的实际损失面，World Quests 占 491 个。

## 记录在案，不做

都评估过，理由不是"没想到"而是"不划算"或"上游没有"。哪条的前提变了再说。

| 项 | 规模 | 为什么不做 |
| --- | --- | --- |
| NPC 随机委托（`RandomMainQuestExcelConfigData`） | 27 个任务 | 是随机拼装的模板文本，拼出来的组合不是"剧情"，纳入反而污染语料 |
| 40 个未混淆文件里 0.41 的文本命中 | 40 个文件 | 命中率太低，判据不足以确定它们是文本字段；强行纳入就是"成功地解析出垃圾" |
| 288 条悬空 `next` 引用 | 288 条 | 占对话节点总数的 0.08%，已计数上报，逐条查的收益太低 |
| 版本间 diff 工具 | — | 全量重跑只要 40 秒，diff 是"想看"不是"需要"；真要看可以直接比两份 `corpus/genshin/` |
| 说话人名补全（`NpcExcelConfigData`） | — | 现有说话人字段已经够用，补全属于锦上添花 |
| 不归属任何任务的 talk（NPC 闲聊 1.37 万个、Gadget、Coop、Activity…） | 1.67 万个 talk / 8.7 万节点 | `build/genshin/index/talks.jsonl` 里有。拿下游项目 flowocr 的五段原神直播录像量过：库里找不到的屏幕文字里，它们只多认出 11 条（整场两场合计 10）；那批文字大半是 UI。前提变了（要做 NPC 语料）再出产物 |

## 与社区项目的关系

解析代码**全部自己写**。调研过以下项目，都不适用：

| 项目 | 为什么没用 |
| --- | --- |
| [Grasscutter](https://github.com/Grasscutters/Grasscutter) | 用的是**已反混淆**的资源包，拿不到混淆名映射 |
| [WeedwackerPS/DataParser](https://github.com/WeedwackerPS/DataParser) | 停在 2022 年 |
| [Gongzhui/genshin-archon-quest-extractor](https://github.com/Gongzhui/genshin-archon-quest-extractor) | 只覆盖魔神任务，pin 在 5.5.0，硬编码混淆字段名 |
| [theBowja/GenshinData-scripts](https://github.com/theBowja/GenshinData-scripts) | 只处理 ExcelBinOutput（明文部分），不碰 BinOutput |
| [mrzjy/GenshinDialog](https://github.com/mrzjy/GenshinDialog) | 作者自述已过时 |

从它们身上得到的是方向而非代码：Grasscutter 的 `MainQuestData.java` 提示了 `BinOutput/Quest` 是任务与对话的连接点；Gongzhui 的说明提示了 `CodexQuest` 自带明文语义 tag。
