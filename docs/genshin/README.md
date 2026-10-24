# 原神（genshin）

从社区解包的游戏数据里离线提取原神任务的元数据与对话（外加边玩边说的语音字幕、书籍信件这类阅读面板的长文本），输出**多语言逐行对齐**的 JSONL 语料（默认 CHS / EN / JP，`--langs` 可选上游的其余语种，见[语种与压缩](manual.md#语种与压缩)）。

不抓网页。上游是一份完整快照，因此不存在"漏爬"；各语种取自同一条记录的同一个 TextMapHash，因此天然对齐；版本更新退化成 `git pull` + 全量重跑（约 40 秒）。

## 现状

| | |
| --- | --- |
| 游戏版本 | **7.1.0** |
| 上游 | `gitlab.com/Dimbreath/animegamedata2` @ `792978e550`（2026-10-01） |
| 输出 | 各语种 **4417** 行、**351 058** 个对话节点，逐行对齐 |
| 任务配音标记 | Voice 的 Dialog 映射命中 161409 / 351058 个产物 dialog 行（46.0%）；其余保留 unknown |
| 语音字幕 | **12 703** 条链 / **18 608** 行（`ReminderExcelConfigData`），`reminders_*` |
| 短名词 | **247 630** 条（TextMap 里 CHS ≤16 字的名词形短串），`terms_*` |
| 称谓 | **78** 个键（`ManualTextMapConfigData` 里 `INFO_MALE_*` / `INFO_FEMALE_*`：称谓 62、日文句尾 16，台词里按性别取的字查它），`pronouns_*` |
| 阅读面板长文本 | **6 636** 条（`Readable/` 书籍与故事 1878、邮箱信件 323、教程说明页 3456、活动来信 6、角色故事 973；与台词整段相同的 19 条不收），`readables_*` |
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

## 文档

| 文档 | 内容 |
| --- | --- |
| [manual.md](manual.md) | 产出的语料：文件、字段、各表的取舍、语种与压缩 |
| [architecture.md](architecture.md) | 为什么这样解析：结构推断的判据、两道否决、流水线、报告、交叉校验、不做的事 |
| [dev-guide.md](dev-guide.md) | 改代码后怎么验、版本更新、上游搬家、跨版本回归、磁盘 |
| [data-source.md](data-source.md) | 上游实测结构、字段样本、质量数字、陷阱清单 |

代码在 [`src/gametext/genshin/`](../../src/gametext/genshin/)，必须保持的不变量在它旁边的 [AGENTS.md](../../src/gametext/genshin/AGENTS.md)。

许可与用途见根 [README](../../README.md#许可)。
