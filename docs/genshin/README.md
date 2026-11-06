# 原神（genshin）

从社区解包的游戏数据里离线提取原神任务的元数据与对话（外加边玩边说的语音字幕、书籍信件这类阅读面板的长文本），输出**多语言逐行对齐**的 JSONL 语料（默认 CHS / EN / JP，`--langs` 可选上游的其余语种，见[语种与压缩](manual.md#语种与压缩)）。

不抓网页。上游是一份完整快照，因此不存在"漏爬"；各语种取自同一条记录的同一个 TextMapHash，因此天然对齐；版本更新退化成 `git pull` + 全量重跑（约 40 秒）。

## 现状

| | |
| --- | --- |
| 游戏版本 | **7.2.0** |
| 上游 | `gitlab.com/Dimbreath/animegamedata2` @ `d54f6f0d42`（2026-11-04） |
| 输出 | 各语种 **4543** 行、**360 121** 个对话节点，逐行对齐 |
| 任务配音标记 | Voice 的 Dialog 映射命中 165530 / 360121 个产物 dialog 行（46.0%）；其余保留 unknown |
| 语音字幕 | **13 331** 条链 / **19 433** 行（`ReminderExcelConfigData`），`reminders_*` |
| 短名词 | **255 677** 条（TextMap 里 CHS ≤16 字的名词形短串），`terms_*` |
| 称谓 | **78** 个键（`ManualTextMapConfigData` 里 `INFO_MALE_*` / `INFO_FEMALE_*`：称谓 62、日文句尾 16，台词里按性别取的字查它），`pronouns_*` |
| 阅读面板长文本 | **6 771** 条（`Readable/` 书籍与故事 1905、邮箱信件 333、教程说明页 3538、活动来信 6、角色故事 989；与台词整段相同的 18 条不收），`readables_*` |
| 对话正文未解析率 | CHS 0.04% / EN·JP 约 0.80% |
| 非预期解析失败 | **0** |

与旧爬虫（独立第二来源，27 万条台词）按 dialogId 对齐比对：**共有台词 99.83% 一致**，
新方案多出 6 万条台词、581 个任务。

## 快速开始

在仓库根运行：

```bash
uv sync
uv run gametext genshin all
```

首次会 sparse 克隆上游（几百 MB）到 `upstream/genshin/`，之后每次约 40 秒；语料在 `corpus/genshin/`。

```bash
uv run gametext genshin all --no-fetch                # 用现有快照重跑，不联网
uv run gametext genshin index                         # 单独重跑某一阶段
uv run python tools/genshin/crosscheck.py             # 与旧爬虫结果交叉校验
uv run python tools/genshin/p0_probe.py --limit 0     # 上游结构诊断
```

### 打包原神 7.2.0

默认取数会跟上游最新提交。要复现已登记的 7.2.0 rev 3，请从 [game-text-data 发布页](https://github.com/caca2331/game-text-data/releases)
找到首次支持原神 7.2.0 的版本，检出它的发布标签，然后在仓库根运行：

```bash
uv run gametext genshin snapshot --upstream upstream/genshin-7.2.0 --build build/genshin-7.2.0
git -C upstream/genshin-7.2.0 switch --detach d54f6f0d423ded9d055bb740a3e5f3aa8f2667f1
uv run gametext genshin all --no-fetch --upstream upstream/genshin-7.2.0 --build build/genshin-7.2.0 --out corpus/genshin-7.2.0
uv run gametext genshin bundle --out corpus/genshin-7.2.0 --bundle-dir out/genshin-7.2.0
```

如果浅克隆里没有这个提交，先按[跨版本回归](../dev-guide.md#跨版本回归)给 `upstream/genshin-7.2.0` 补取历史，再切换到指定提交。
默认中、英、日三语应生成 `out/genshin-7.2.0/genshin-7.2.0-c95edd4bc412.zip`；在[原神指纹表](../../releases/genshin/fingerprints.tsv)核对 7.2.0 那一行。
快照、中间产物和文本包都用独立目录，默认目录里给旧录像用的文件会保留。
把 zip 放进 FlowOCR 数据目录的 `gametext/`，同一款游戏只留要用的版本。文本包自行生成，不随代码发布。

## 文档

| 文档 | 内容 |
| --- | --- |
| [manual.md](manual.md) | 产出的语料：文件、字段、各表的取舍、语种与压缩 |
| [architecture.md](architecture.md) | 为什么这样解析：结构推断的判据、两道否决、流水线、报告、交叉校验、不做的事 |
| [dev-guide.md](dev-guide.md) | 改代码后怎么验、版本更新、上游搬家、跨版本回归、磁盘 |
| [data-source.md](data-source.md) | 上游实测结构、字段样本、质量数字、陷阱清单 |

代码在 [`src/gametext/genshin/`](../../src/gametext/genshin/)，必须保持的不变量在它旁边的 [AGENTS.md](../../src/gametext/genshin/AGENTS.md)。

许可与用途见根 [README](../../README.md#许可)。
