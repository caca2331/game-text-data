# 架构说明

为什么这样解析、覆盖率的边界在哪、怎么验过。上游实测与证据见 [data-source.md](data-source.md)，产出格式见 [manual.md](manual.md)。

## 比原神简单的地方

崩铁的数据**没有字段名混淆**，还带 `$type` 明文类型标记：

```json
{ "$type": "RPG.GameCore.LevelPerformanceInitialize",
  "CreateCharacterList": [
    { "CharacterUniqueName": "Kafka_00_C00", "AvatarID": "NPC_Avatar_Lady_Kafka_00" }
  ] }
```

所以 **genshin 那套结构推断（`infer.py`）在这里完全用不上** —— 按字段名
直接取即可。这也是两款的解析层各写各的根本原因：核心难点不同。

对话链路三跳，全明文：

```
Story/Mission/<MainMissionID>/Story*.json     剧情脚本，含 TalkSentenceID
      ↓
ExcelOutput/TalkSentenceConfig.json           台词表（说话人 + 台词的 hash）
      ↓
TextMap/TextMap<LANG>.json + TextMapMain<LANG>.json
```

而且 `Story/Mission/` 的子目录名就是 `MainMissionID`，**任务与剧情的归属是现成的**，
不需要像原神那样反查引用路径。

## 上游的坑

都是摸底时实测踩出来的，证据见 [data-source.md](data-source.md)：

1. **`Config/Level` 才是对话引用的主体。** 只扫 `Story/` 的话，24 万条台词里仅 6.57% 找得到引用；把 `Config/Level` 加进来后升到 65%（`Config/Level/Mission` 一处贡献 14 万条）。
2. **TextMap 有分片，`TextMapMain<L>` 却是冗余的。** KR / RU / TH 被拆成 `TextMap<L>_0/_1`，只读 `_0` 会静默丢一半文本，所以靠枚举目录收全分片。`TextMapMain<L>` 只有 1118 条启动器 UI 文本，key 全部已在主表中。
3. **hash 是 64 位**，比原神宽，别用 32 位类型接。
4. **归属按目录名走，不用编号前缀。** 试过原神那套 TalkSentenceID 前缀匹配，只覆盖 9.21%；三个引用源都以 MainMissionID 作目录名，归属是现成的。子任务例外：`SubMission` 没有 MainMissionID 字段，只能靠 SubMissionID 前 7 位匹配（99.66%）。
5. **台词引用有两种形态。** 除了数字字段 `TalkSentenceID`，还有编码在自定义字符串里的 `TalkSentence_<数字>`（全上游 107 021 处，103 020 处能对上台词表）。只认数字字段时，选项对话只剩玩家的问、没有 NPC 的答（29 922 个选项受影响）。
6. **扫对话来源不列白名单。** `Config/Level` 与 `Story` 下除任务目录外全部要扫；列白名单会在上游新增目录时静默漏掉（第一版就停在 51.2% 的覆盖率）。顶层不在 sparse 里的 `Stages/`（3469 个文件）实测引用台词 0 条。
7. **任务根目录下归不了属的脚本也要输出。** 目录名不是 MainMissionID 的 666 个（活动 / 教程）当任务外对话写出。第一版只记了台词 id、脚本没进产物，3.5 万句静默丢失，而报告的覆盖率照样是 67.4%——**"算进了被引用"不等于"进了产物"**。

## 流水线

沿用 genshin 验证过的四阶段流水线与产出原则（分阶段落盘、装配阶段不解引用文本、报告区分"上游缺译"与"解析失败"、上游存活检测），解析层自己写；快照、CLI、产物包、契约检查机制在三款共用的 `gametext.core`：

```
src/gametext/starrail/
├── __init__.py   # 上游配置（仓库、sparse 目录、版本号写法）与各阶段的接线
├── textmap.py    # TextMap 装载（收全分片）
├── script.py     # LevelGraph 解析器：对话顺序与分支都靠它，别退回正则抽 id
├── index.py      # 台词表全量索引 + 按目录归属到任务、配音标记、悬空引用
├── assemble.py   # 装配（文本仍是 hash）
├── emit.py       # 逐语种展开
├── contract.py   # 各表的内容契约
└── report.py     # 完整性校验与报告
```

## 覆盖率的边界

4.6.0 被脚本引用的台词占 66.3%（162 072 / 244 379）；4.6.0 的上游还没导出新任务的 `Config/Level` 脚本，新增的 18 个任务只有元数据。

归属到任务的（4.5.0 实测）：102 363 条台词引用归到 1299 个主任务，2166 个任务中 885 个没有对话。

### 没人引用的台词

4.5.0 实测：`TalkSentenceConfig` 有 240 488 条，我们能找到引用的是 162 064 条（67.4%；第二版 162 067）。剩下的
78 424 条**在整个上游仓库里都搜不到任何引用**。这一版把它定性了：

| 证据 | 结论 |
| --- | --- |
| 44.8% 的语音类型是 `StoryNew`（有引用的那批只占 5.7%） | 是过场演出的配音台词 |
| 58% 带 `VoiceID`，即**真的录了音** | 多数是上线内容，不是废稿 |
| **92.5%** 的 id 与某条已引用台词同前缀（去掉后 3 位） | 属于我们已经拿到的那些场景 |
| 脚本里驱动它们的是 `PlayTimeline` → `.playable` | **`.playable` 文件不在上游仓库里** |

所以这不是"我们漏扫了目录"，而是**上游边界**：过场演出由时间轴资源驱动，而上游只导出
了配置表和 LevelGraph，没有时间轴。性质与绝区零缺 `Data/ScriptConfig/` 相同。

### 悬空引用

脚本引用了 `TalkSentenceConfig` 里没有的 id。补回活动 / 教程目录后是 6683 个 / 7170 次；下面的定性做在先前数到的 3852 个（4214 次）上，多出来的 2831 个没做跨版本对照：

- 把上游退回 **3.8.0** 查同一批 id——**一个都不存在**；
- 而台词表是**只增不删**的：3.8.0 有 196 549 条、4.5.0 有 240 488 条，
  **旧有新无 0 条**。

所以不是"被删掉的内容"，而是**上游的脚本引用了从未发布过的台词**（多半是上线前砍掉、
脚本没跟着清）。旁证：43% 的悬空 id 与真实台词共享场景前缀，也就是说它们就嵌在我们
已经拿到的那些场景里。

明细（每个 id 的引用次数与来源文件）落在 `build/starrail/index/dangling.json`。**不进
`unparsed.jsonl`**——那会让报告变红，但这是上游的属性，不是我们的解析失败。

## 交叉校验

崩铁**没有可按 id 全量对齐的第二来源**：`Dimbreath/StarRailData`（GitHub）返回
`Repository access blocked`，`mrzjy/StarrailDialog` 只有 6–10 KB 样本且停在 2.x。
唯一可用的是 HuggingFace 的 [`simon3000/starrail-voice`](https://huggingface.co/datasets/simon3000/starrail-voice)
（40 万条语音记录，从语音文件那条**完全不同的路径**提取）。

```bash
uv run python tools/starrail/crosscheck.py --samples 3000
```

两个实测出来的限制：它按 `.wem` 文件名索引、**没有 TalkSentenceID**，只能按文本内容比；
`transcription` 字段**只有中文**（`language` 说的是音频语言，标 Japanese/English 的行
转录也是中文），所以四语种对齐用它验不了。

结果（抽 2589 条，与早先同一抽样口径）：

| 指标 | 早先（只认数字引用、无任务外对话） | 现在 |
| --- | ---: | ---: |
| 文本命中 | 891（34.4%） | **1180（45.6%）** |
| 命中者的说话人一致 | 782/850 = 92.0% | 1027/1138 = 90.2% |

命中率涨了三分之一，来自补上的字符串引用与任务外对话。说话人一致率的 1.8 个点回落
不是数据变差：不一致的那些**全部**是 `player_m` / `player_f` vs `{NICKNAME}`（主角的
两种表示法），以及「那么……」这类**短句被多个角色说过**而按文本比对取了首个匹配——
语料变大以后这类碰撞自然变多，是比对方法的局限。

凡是命中的句子都逐字一致（否则不会命中），**说明 TextMap 解引用没接错**。这个校验
回答不了"有没有漏"：语音只覆盖有配音的台词。

## 记录在案，不做

| 项 | 规模 | 为什么不做 |
| --- | --- | --- |
| 任务外对话剩下 54.9% 拿不到地点 | 4891 个脚本 | 它们的路径里根本没有 FloorID（`Rogue`、`NPCDialogue` 这类）。要补得逐个桶去翻文件内容找别的线索，收益不确定 |
| `interact_title` 没解析成真名 | 767 条 | 上游存的是明文标签 `NPCName_Normal_Adele`（不是 hash），全库只有 `DialogueNPC.json` 用这种写法。标签本身已经可读，解析成真名要另找映射 |
| `MessageItemTextOverride` 的条件表达式 | 26 条 | 形如 `[FinishMainMission:1043710]`，要实现一个条件求值器才能用；26 条不值得。短信输出取默认正文，已记进 `known_gaps` |
| 悬空引用逐条追 | 6683 个 id | 已定性为"上游脚本引用了从未发布的台词"，明细在 `build/starrail/index/dangling.json`。再往下追要的是上游没给的东西 |

## 与 genshin 的关系

**不要 import genshin 的代码。** 崩铁的数据没有字段名混淆（还带 `$type` 明文类型标记），
那边的结构推断在这里完全用不上；两者共用的只有 `gametext.core` 里的协议与机制（快照、产物包、
契约检查、报告骨架），解析层各写各的。

可以借鉴的是**做法**：分阶段落盘、装配阶段不解引用文本（保 hash 到 emit 才展开，让多语种
对齐成为结构保证）、报告区分"上游缺译"与"解析失败"、上游存活检测。
