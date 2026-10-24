# 绝区零（zzz）

从社区解包的游戏数据里离线提取绝区零的剧情文本、任务元数据与短信分支图，输出多语言
逐行对齐的 JSONL 语料（默认 CHS / EN / JA，`--langs` 可选上游的 13 种，见[语种与压缩](manual.md#语种与压缩)）。

## 现状

**流水线已跑通，混淆的 `FileCfg` 已解。**

| 项 | 值 |
| --- | --- |
| 上游 | [`git.mero.moe/dimbreath/ZenlessData`](https://git.mero.moe/dimbreath/ZenlessData)（Gitea，分支 `master`） |
| 当前快照 | `350db42335`，版本 3.3.0（2026-10-21 的构建；取 `TextMap` + `FileCfg`） |
| 上游活跃度 | **很高**，天级更新 |
| 剧情 | 各语种 **34 090** 个场景 / **248 482** 条台词 |
| 任务 | **14 794** 个，带前置/后继任务链 |
| 短信 | **975** 组 / **4640** 个分支节点 / **4759** 条选项 |
| 散条目 | **142 364** 条没进上面三份的 TextMap 条目（漫画过场、AutoEvent、教程、UI…），`loose_*` |
| 短名词 | **129 461** 条（TextMap 里 CHS ≤16 字的名词形短串），`terms_*` |
| 台词未解析率 | 缺失文本查询数 / 正文文本查询总数（场景台词 + 短信正文）：CHS 65 / 257 772（0.025%）、EN 89 / 257 772（0.035%）、JA 80 / 257 772（0.031%）；其中 65 条各语种均无 |
| 完整性 | 中英日五类表逐行 id 对齐；内容契约零违反、无硬失败或告警，快照完整性检查通过；短信悬空跳转 20 处 |

## 快速开始

在仓库根运行：

```bash
uv sync
uv run gametext zzz all              # 全流程，首次克隆约 0.42 GB
uv run gametext zzz all --no-fetch   # 用现有快照重跑，约 23 秒
```

产出与字段说明见 [manual.md](manual.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [manual.md](manual.md) | 产出的语料：场景与出场角色表、任务、短信分支、散条目、短名词、语种与压缩 |
| [architecture.md](architecture.md) | 为什么这样解析：两个来源的分工、FileCfg 推断、上游边界、踩过的点、交叉校验、不做的事 |
| [dev-guide.md](dev-guide.md) | 改代码后怎么验、跨版本回归、快照完整性、磁盘 |
| [data-source.md](data-source.md) | 上游实测结构、key 形态、Overwrite 语义、FileCfg 各表身份、待核实清单 |

代码在 [`src/gametext/zzz/`](../../src/gametext/zzz/)，必须保持的不变量在它旁边的 [AGENTS.md](../../src/gametext/zzz/AGENTS.md)。

许可与用途见根 [README](../../README.md#许可)。
