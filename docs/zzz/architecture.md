# 架构说明

为什么这样解析、推断结论、上游边界、怎么验过。上游实测与证据见 [data-source.md](data-source.md)，产出格式见 [manual.md](manual.md)。

## 两个来源，分工明确

| 来源 | 给什么 | 难点 |
| --- | --- | --- |
| `TextMap/` | **剧情文本本身** | 没有难点：key 是明文语义标识 |
| `FileCfg/` | **结构**：场景类型、任务链、短信分支 | 字段名混淆，靠锚点推断 |

**TextMap 的 key 是明文语义标识**，类别 / 章节 / 场景 / 顺序全编码在里面：

```
Main_GalGame_Chapter000_1000003_001        对话行
Main_GalGame_Chapter000_1000003_Name_001   ← 场景出场角色表的第 1 个（不是第 1 行的说话人）
QuestName_10010001 / QuestTarget_10010001
```

所以剧情文本能**直接从 TextMap 提取并排序**；"这段对话属于哪个任务""短信选项跳到哪"这些结构才要靠 `FileCfg`。

## `FileCfg`：文件名当锚点，字段名一律推断

全量清点 1721 个文件：**1499 个文件名是明文**（`QuestConfigTemplateTb.json`），只有 222 个是 hash（早先只抽样到 hash 那批，误判成"文件名和字段名双重混淆"）。

所以真正的分工是 **文件名当锚点，字段名一律推断**：

```json
{ "IAEFFFFLKNB": [
    { "ODCODEPMLGG": 30101, "ANCOBODLNIK": "QuestName_30101" } ] }
```

推断原语只有四条（`src/gametext/zzz/filecfg.py`）：

| 原语 | 判据 |
| --- | --- |
| `id_field` | 整数 + 每行都有 + 全表唯一 |
| `text_fields` | 取值大量命中 TextMap 的明文 key，按 key 前缀命名 |
| `ref_fields` | 取值大量命中某个已知 id 全集 |
| `order` | 行内字段顺序（来自上游类定义，跨版本比字段名稳定） |

`text_fields` 是最强的一条：命中 `QuestName_30101` **同时**证明了"这是文本字段"和
"它是任务名"——比原神那边"命中数字 hash"多一层语义。

每张表都带一条可独立验证的否决规则：`Perform` 主键必须覆盖 ≥40% 的场景 id、`Quest` 必须找得到 `QuestName_*` 字段、`Message` 必须推得出 step 字段。三张表任何一张推断失败都是**硬失败**——推断失败和推断出垃圾外观相同，必须让它显式暴露。

## 三个关键的推断结论

**① `PerformTemplateTb` 的主键就是 TextMap key 里的场景 id。** 覆盖 81% 的长场景 id。
它顺带给出资源路径 `.../Perform/Data/<Kind>/<Group>/<name>_<id>.asset`，于是 20 647 个
场景拿到了类型（`Chat` / `Bubble` / `BubbleStory` / `GalGame`）与分组。

**② 任务链的方向是推断出来的。** `QuestConfig` 有两个字段互为逆关系（每条边在对方字段
里都有反向边，5903/5903），这只能证明它们是同一关系的两个方向。定方向靠 id 序：91.9%
的边里前置字段指向更小的 id。置信度写进 `report.json`，方向要是翻了看得见。

**③ 撞见过一座假桥。** `KnowledgeConfigTemplateTb` 的主键有 60% 落在 Perform 的 id 全集
里，纯属两个 id 空间重叠。所以扫桥表时，一张表自己的主键不算对 Perform 的引用。

## 上游边界：对话分支拿不到

`PerformTemplateTb` 只给资源路径，而 **`Data/ScriptConfig/` 这个目录在上游仓库里根本
不存在**。所以 GalGame / Chat 的选项与跳转**不是没做，是上游没有**。

短信系统是唯一有完整分支图的对话，因为它的分支写在 `FileCfg` 里而不在脚本里——
step 编号、两个选项、各自的跳转目标齐全，已按 group 成图并人工核对过。`Option01_*` 选项文本全部属于短信，随分支图产出。

### 场景→任务：为什么补不上去

只有 409 个场景能连到任务。这不是"还没做"，三条可能的补路都试过了：

| 尝试 | 结果 |
| --- | --- |
| `MainCityQuestTemplateTb`（9504 个任务步骤）直接指向 Perform | **没有这样的字段** |
| 顺着 `MainCityQuest → MainCityObject`（5631 条边、100% 命中）再跳一层 | `MainCityObject` 22 996 行里**没有指向 Perform 的字段**；`InteractDataTemplateTb` 同样没有 |
| 从编号推断（拿 447 条**已验证**的边当样本） | 场景 id 与任务 id **毫无编号关系**：公共前缀长度集中在 1–2 位（纯属巧合），任何"去掉后 k 位相等"的规则都是 0 命中 |

所以触发关系应该写在 Perform 的脚本资源里，而**那部分不在上游仓库**——和"对话分支
拿不到"是同一个边界。没有桥表的场景 `quests` 就是空数组，不臆造关联。

顺带查到的东西不多但记一笔：`MainCityObject` 能给出任务步骤涉及的 NPC
（`NPCName*` 文本 key）和它的日常问候语（`CommonDialogue_*`）——但后者全 TextMap 只有
**50 条**（被 3885 个对象复用），不值得为它单开一条管线。

### 仍然拿不到什么

- **大部分场景连不到任务**（531 条边 / 409 个场景），见[场景→任务：为什么补不上去](#场景任务为什么补不上去)。
- **GalGame / Chat 的分支**与**逐行说话人**：都在 Perform 的脚本资源里，不在上游仓库。

都记在 [data-source.md](data-source.md) 与 `report.json` 的 `known_gaps` 里。

## 踩过的几个点（仍然成立）

**① `Overwrite` 是覆盖层，不是并集。** 覆盖表 774 条里 611 条与主表 key 重叠，**值全部
不同**且是修订版。合并顺序必须先主表后覆盖，反了会**静默拿到旧文本**。

**② `_Name_` 后缀是出场角色表，不是逐行说话人。** 第一版没识别它，一万多个名字被当成
普通台词混进正文；第二版把 `_Name_00i` 配给第 i 行当说话人——**这一步是错的**：3.2.0 实测
9438 个带名字的场景里，9419 个的名字序号严格是 1..k 连续，9338 个名字互不重复、7988 个
名字数少于台词行数。两个人来回说的对话，逐行说话人必然有重复；这是角色表。例如
`Main_GalGame_Chapter210_121000241` 有 21 行、6 个名字（ヴェリナ / リン / アキラ / ドラキナ /
ビリー / シーシィア），旧产物把第 2 行（ヴェリナ对アキラ说的话）标成 `リン`、第 3 行（主角台词）
标成 `アキラ`，第 7 行以后没有说话人。现在场景输出 `cast`，行上不给说话人——**逐行说话人
在 Perform 脚本里，而脚本不在上游仓库**（和剧情分支同一个边界，见[上游边界](#上游边界对话分支拿不到)）。

**③ 章节解析不能用 `\w`。** `\w` 包含下划线，会把 `Main_Chat_Chapter00` 拆成
category=`Main` / chapter=`Chat_Chapter00`，导致 12 305 条主线聊天归错组。用 `[A-Za-z0-9]*`。

**④ 槽位要用原样的序号串，不能按数值归一。** 同一场景里 `_01` 和 `_1` 是**两条不同的台词**
（3.2.0 实测 219 组，其中 183 组文本不同——有的是一串编号补零不一致，`…_10` 后面跟
`…_011`；有的是 `1..15` 与 `01..09` 两串并存）。第三版之前槽位写成 `"%d"`，每组静默丢
一条，**丢哪条随 `set` 的遍历顺序变**，于是两次运行的产物不一样。现在按原样串区分、
按数值排（同值再按位数，只为确定性——上游没有信息说谁先谁后），输出的 `slot` 仍是
数值形式，所以**同一场景里可能有两行 `slot` 相同**，要唯一标识一行请用 `key`。
报告里的 `slot_padding_collisions` 就是这个数。

## 上游的两个现实问题

1. **托管在 Gitea 不是 GitHub/GitLab。** GitHub 上的 `Dimbreath/ZenlessData` 返回
   `Repository access blocked`。只剩作者自建实例，而且 **HTTP API / raw 对默认 UA 返回
   403**（`git clone` 不受影响）。单点风险比另外两个游戏高，存活检测阈值设为 30 天。
2. **语言代码是 `JA` / `KO`**，不是原神/崩铁的 `JP` / `KR`；简体中文没有语言后缀。

## 流水线

下面的路径都在仓库根的 `upstream/zzz/`、`build/zzz/`、`corpus/zzz/` 之下。

```
 snapshot ──→ upstream/TextMap          Gitea sparse 浅克隆
         │    upstream/FileCfg
         │    build/snapshot.json       commit + 版本 + 存活检测结果
         ↓
 index ──────→ build/index/scenes.jsonl    33 282 个场景，带出场角色表与 Perform 元信息
         │     build/index/quests.jsonl    14 443 个任务，带前置/后继
         │     build/index/messages.jsonl  961 个短信组的分支图
         │     build/index/loose.jsonl     没进上面三份的全部 TextMap 条目
         │     build/unparsed.jsonl        结构不认识的 key
         ↓
 emit ───────→ corpus/{scenes,quests,messages,loose,terms}_{chs,en,ja}.jsonl.zst + report.json
```

没有 `assemble` 阶段：中间层已经是"场景 + 文本 key"，`emit` 直接展开即可。
各语种由同一次遍历写出，行数与逐行 id 相同是**结构保证**而非事后校验。文本查不到写
`null` 而非空串，并计数上报；报告区分"上游缺译"与"上游根本没这条"。

模块（快照、CLI、产物包、契约检查机制在三款共用的 `gametext.core`）：

```
src/gametext/zzz/
├── __init__.py   # 上游配置（仓库、sparse 目录、版本号写法）与各阶段的接线
├── textmap.py    # TextMap 装载（先主表后 Overwrite）
├── keys.py       # TextMap key 的切分：类别 / 章节 / 场景 / 序号 / 出场角色表
├── filecfg.py    # 推断原语：id_field / text_fields / ref_fields / order
├── tables.py     # Perform / Quest / Message 三张表的锚点推断与桥表扫描
├── index.py      # 场景、任务、短信、散条目的中间层
├── emit.py       # 逐语种展开
├── contract.py   # 各表的内容契约
└── report.py     # 完整性校验与报告
```

## 交叉校验

绝区零没有可按 id 全量对齐的第二来源，情况比另外两个游戏都差：上游的几个"镜像"自述
以 `Dimbreath/ZenlessData` 为源，**同源就不算独立**；HuggingFace 上没有绝区零的语音/
台词数据集（崩铁那条路子走不通），唯一沾边的 `mrzjy/zenless_zone_zero_interknots_v1.0`
只有绳网帖子、不到 1K 条、停在游戏 1.0。

所以外部来源用**玩家维基**（`zenless-zone-zero.fandom.com`）——条目是玩家从实机整理的，
与解包数据完全无关。代价是只有英文、只覆盖有人写过的条目。

```bash
uv run python tools/zzz/crosscheck.py
```

| 检查 | 结果 | 证明了什么 |
| --- | --- | --- |
| 委托名 vs 维基 Commissions 条目 | **1540 / 1580 = 97.5%** | 从 TextMap 取的英文任务名是对的，没整批漏掉某类委托 |
| 角色名 vs 维基 Agents 名单 | **58 / 62 = 93.5%** | 名字字段确实是角色名（**证明不了逐行配对**——那恰恰是错的，见[踩过的几个点](#踩过的几个点仍然成立)的 ②；这一项是按旧的逐行 speaker 跑的，改读 `cast` 后没重跑） |
| 场景类别 vs FileCfg 资源路径 | **99.69%** | key 的切分没切错（内部，另一条命名路径） |

第三项不是独立来源，但走的是上游里**另一条命名路径**：TextMap 的 key 段
（`Main_GalGame_...`）与 Perform 表的资源路径（`.../Perform/Data/GalGame/...`）由不同的
东西生成，20 633 个场景里 99.69% 落在本类别的众数资源类型上。

未命中的都看过了：

- 委托 40 条里，9 条是维基的**类型索引页**（`City Commission` 这种，不是具体委托），
  真正对不上 31 条（2.0%），多为活动限时委托与探索区域条目。
- 角色 4 条里，3 条是**维基用英文全名、游戏对话里用称呼**——上游把两者存成不同的 key
  （`Avatar_Female_Size01_Lucy_En_FullName` = `Luciana de Montefio`，对话里是 `Lucy`），
  Lucy / Tsubaki / Rina 都在我们的语料里。剩下的 `Corin` 确实不在场景说话人里：她的
  说话人 key 形如 `Arcade_Player_Name_131061` / `HSC_V4_Name_Story138`，不符合
  `<类别>_<场景>_[Name_]<序号>` 形态，属于已知的未纳入 key。

这个校验回答不了"有没有漏"：维基只收录有人写过的条目。

## 记录在案，不做

| 项 | 规模 | 为什么不做 |
| --- | --- | --- |
| `CommonDialogue_*`（NPC 日常问候） | **50 条** | 被 3885 个对象复用，全 TextMap 只有 50 条。为 50 句话单开一条管线不划算 |
| 场景→任务补到更高覆盖 | 409/20647 | 三条路都查证不通（见[场景→任务：为什么补不上去](#场景任务为什么补不上去)），触发关系在上游没给的脚本资源里 |
| GalGame / Chat 的分支结构 | — | `Data/ScriptConfig/` 不在上游仓库。是上游边界，不是没做 |
| 大小写冲突文件"修好" | 21 组（`e223d18a17`）/ 1 组（`1277ebca4b`） | 真要修得在每组里挑一边留，那是取舍不是修复。现在是检测并上报 |

## 与 genshin 的关系

**不要 import genshin 的代码**，但**要复用它的方法论** —— 这两款的核心难点最接近：
都是字段名混淆、都得靠可独立验证的锚点反推身份。已经照搬过来的思路：

- 用"取值大量命中某个已知集合"当判据（这里的已知集合是 TextMap 的明文 key）。
- **防止"成功地解析出垃圾"**：推断能力越强越要有否决规则。这里的否决规则是
  `Perform` 主键必须覆盖 ≥40% 的场景 id、`Quest` 必须找得到 `QuestName_*` 字段、
  `Message` 必须推得出 step 字段。
- 报告要区分"上游缺译"与"解析失败"，否则非中文语种的未解析率虚高，看着像流水线坏了。
