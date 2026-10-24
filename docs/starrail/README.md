# 崩坏：星穹铁道（starrail）

从社区解包的游戏数据里离线提取崩铁的任务元数据与对话，输出多语言逐行对齐的 JSONL 语料。

## 现状

**流水线已跑通。** 实测结论见 [data-source.md](data-source.md)。

| 项 | 值 |
| --- | --- |
| 上游 | [`gitlab.com/Dimbreath/turnbasedgamedata`](https://gitlab.com/Dimbreath/turnbasedgamedata)（分支 `main`） |
| 当前快照 | `724b139d8c`，版本 4.6.0，约 0.85 GB（工作区 0.71 + `.git` 0.14） |
| 上游活跃度 | **很高**，几天一次提交（4.6.0 在 2026-09-28 至 09-30 之间提交了四次） |
| 任务 | 各语种 **2184** 个任务、**96 358** 个对话事件（含 32 202 个分支选项）；4.6.0 的上游还没导出新任务的 `Config/Level` 脚本，新增的 18 个任务暂时只有元数据 |
| 任务外对话 | **13 890** 个脚本 / **113 099** 个事件；4021 个带地点名，638 个带交互标题（含任务根目录下 666 个归不了属的活动/教程目录） |
| 短信 | **774** 组 / **13 766** 条 / **1163** 处分支，联系人 306 |
| 台词覆盖 | **66.3%**（162 072 / 244 379）被脚本引用；**全部 244 379 句**另见全量台词表 |
| 台词未解析率 | **0.01%**（各语种一致） |
| 短名词 | **118 528** 条（TextMap 里 CHS ≤16 字的名词形短串，见[短名词](manual.md#短名词-terms_)） |
| 玩家起名的占位 | **191** 个 `{TEXTJOIN#n}` 的候选与默认项（`TextJoinConfig` / `TextJoinItem`，见[玩家起名的占位](manual.md#玩家起名的占位-textjoins_)） |

## 快速开始

在仓库根运行：

```bash
uv sync
uv run gametext starrail all              # 全流程，首次会克隆上游（约 0.85 GB）
uv run gametext starrail all --no-fetch   # 用现有快照重跑，约 25 秒
uv run python tools/starrail/p0_probe.py           # 上游结构诊断
```

产出与字段说明见 [manual.md](manual.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [manual.md](manual.md) | 产出的语料：事件流与分支、全量台词表、任务外对话、短信、配音标记、短名词、玩家起名的占位、语种与压缩 |
| [architecture.md](architecture.md) | 为什么这样解析：上游的坑、流水线、覆盖率的边界、交叉校验、不做的事 |
| [dev-guide.md](dev-guide.md) | 改代码后怎么验、版本更新、跨版本回归、磁盘 |
| [data-source.md](data-source.md) | 上游实测结构、与原神的差异、对话链路、待核实清单 |

代码在 [`src/gametext/starrail/`](../../src/gametext/starrail/)，必须保持的不变量在它旁边的 [AGENTS.md](../../src/gametext/starrail/AGENTS.md)。

许可与用途见根 [README](../../README.md#许可)。
