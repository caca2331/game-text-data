# 使用说明：产出的语料

`uv run gametext zzz all` 产出的东西长什么样、各字段什么意思。怎么跑见 [README](README.md#快速开始)。

每个字段的类型、能否为 null、取值范围以内容契约 [`src/gametext/zzz/contract.py`](../../src/gametext/zzz/contract.py) 为准（规则见根架构说明的[内容契约](../architecture.md#内容契约)），本文讲各表的来历与取舍。

## 输出

```
corpus/zzz/
├── scenes_{chs,en,ja}.jsonl.zst     剧情场景：出场角色表 cast + 有序台词
├── quests_{chs,en,ja}.jsonl.zst     任务：名称、目标、前置 / 后继任务链
├── messages_{chs,en,ja}.jsonl.zst   短信：按组的分支图
├── loose_{chs,en,ja}.jsonl.zst      散条目：没进上面三份的 TextMap 条目
├── terms_{chs,en,ja}.jsonl.zst      短名词
├── report.json                         完整性报告
└── manifest.json                       清单（产物包协议）
```

各表各语种行数相同、逐行 id 相同（`--compress none` 出 `.jsonl`）。清单与打包的协议见根[架构说明](../architecture.md#产物包协议gtd-bundle1)：`uv run gametext zzz bundle` 打包进仓库根的 `out/`，发布用 `release`、记进 `releases/zzz/fingerprints.tsv`。语言代码是 `JA` / `KO`（不是原神 / 崩铁的 `JP` / `KR`），简体中文没有语言后缀。

## 剧情场景 `scenes_*`

剧情场景（`Main_GalGame|Chapter210|121000241`，21 行）。**行上没有说话人**，场景给的是
出场角色表 `cast`（为什么见[架构说明的踩过的几个点](architecture.md#踩过的几个点仍然成立)）：

```
cast: ヴェリナ / リン / アキラ / ドラキナ / ビリー / シーシィア
  1  リンさん、ビリーさん、聞こえるかしら？指定のポイントには到着したと思うけれど…
  2  アキラさん、ビリーさん、聞こえるかしら？…        ← 两位主角的两种说法，库里相邻
  3  {M#僕は何ともない}{F#私は何ともないよ}
```

行的顺序取自 TextMap key 里的序号。**同一场景里可能有两行 `slot` 相同**（上游 `_01` 与 `_1` 是两条不同的台词，`slot` 输出的是数值形式），要唯一标识一行请用 `key`；报告里的 `slot_padding_collisions` 就是这个数。

约 81% 的长场景 id 能在 `PerformTemplateTb` 里找到，带上场景类型（`Chat` / `Bubble` / `BubbleStory` / `GalGame`）与分组。只有 409 个场景连得到任务；没有桥表的场景 `quests` 是空数组，不臆造关联。GalGame / Chat 的选项与跳转拿不到（上游没有，见[架构说明的上游边界](architecture.md#上游边界对话分支拿不到)）。

## 任务 `quests_*`

任务名、目标、描述等文本来自 TextMap（`QuestName_*` / `QuestTarget_*` 这类 key），前置 / 后继任务链（`prev_quests` / `next_quests`）来自 `QuestConfig`；链的方向是按 id 序推断的，置信度写在 `report.json` 里。

## 短信 `messages_*`

短信分支（group 1003，`quests: ["10030103"]`）：

```
step 1  [Suuuuri] 我的宝箱大约只有一个糖果盒大小
        [Suuuuri] 外壳有一些磨损，并且有一定年头了
        > 只有这些信息吗？        -> step 2
        > 那…你的宝箱具体在哪呢？  -> step 3
step 2  [Suuuuri] 对不起对不起，只有这些信息了，因为并不是一个看起来过于特殊的盒子
step 3  [Suuuuri] 宝箱具体位置的话…
```

短信是唯一有完整分支图的对话：step 编号、选项、各自的跳转目标齐全。

## 散条目 `loose_*`

没进 `scenes` / `quests` / `messages` 的全部 TextMap 条目（漫画过场、AutoEvent、教程、UI…），一个 key 一行。无序，但下游拿直播录像对台词时用得上。能从 key 读出事件号与序号的（如 `AutoEvent100000_26` 这类，上游没有对应配置表）带 `group` / `seq`，读不出的不硬拼顺序。

## 短名词 `terms_*`

TextMap 里"像名词"的短串逐条照搬，一个 key 一行（`{"id": <TextMap key>, "text": ...}`），
给下游按屏幕上的字查译名用（场景行上没有说话人，名牌上的名字只能按字形查）。口径和 genshin / starrail 相同：
只看 CHS 那份文本，≤ 16 字（出场角色表里去重后的中文名 3197 个，长度 P99 = 9）、含汉字或假名、
不带句读 / 换行 / 占位与富文本标记 / `test`（`emit.is_term`）；和 `loose_*` 按 key 形态分不同，它按文本形状收，
出场角色的名字也在内。不去重、不消歧（同一个日文串对几种中文是下游的事）；本语种查不到写 `null`，
计进报告的 `terms_missing`（3.2.0 `1277ebca4b`：EN 3354 / JA 3343）。

## 语种与压缩

默认出**中英日三语**、产物 **zstd 压缩**：

```bash
uv run gametext zzz all --langs chs,en,ja --compress zstd   # 这就是默认
uv run gametext zzz all --langs chs                  # 只要中文
uv run gametext zzz all --compress none              # 出原始 .jsonl
```

- 语种同时决定 `snapshot` **下载什么**：TextMap 里装着全部语种，只取需要的
  从 718 MB 降到 149 MB。**收窄只对下一次取数生效**，已有快照要重新克隆才变小。
- 产物是 JSONL（UTF-8，一行一个 JSON 对象）；压缩后 `*.jsonl.zst`，227 MB → **28 MB**。
  读端一律走 `jsonl.open_read`，先找 `.zst` 再找原始文件，对下游透明。
- 基准语种 CHS 永远在列 —— 少了它就分不开"上游缺译"和"上游根本没这条"。

依据与取舍（为什么是 zstd level 3、为什么 `corpus/zzz/` 里分文件压）见根架构说明的
[产物格式](../architecture.md#产物格式jsonl--zstd)。
