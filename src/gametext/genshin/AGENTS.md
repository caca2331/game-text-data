# genshin：原神的解析层

从社区解包数据（Dimbreath/animegamedata2）离线提取原神任务的元数据与对话、语音字幕、短名词、称谓、阅读面板长文本，输出多语言逐行对齐的 JSONL。本目录只 import `gametext.core`（快照、CLI、产物包、契约检查机制），不 import 别的游戏；仓库整体约定见根 [AGENTS.md](../../../AGENTS.md)。现状与数字见 [docs/genshin/README.md](../../../docs/genshin/README.md#现状)。

```text
snapshot → upstream/genshin/ ─index→ build/genshin/index/ ─assemble→ build/genshin/assembled.jsonl（文本仍是 hash） ─emit→ corpus/genshin/
```

## 常用命令

在仓库根运行：

```bash
uv run gametext genshin all --no-fetch       # 用现有快照重跑，不联网（槽里一律这样跑）
uv run gametext genshin all                  # 带取数：只在主 checkout 升上游版本时用
uv run gametext genshin index                # 单独重跑某一阶段
uv run gametext genshin release              # 发布：记进 releases/genshin/fingerprints.tsv 再打包（要 owner 要求）
```

解析没有自动化测试：改前用旧代码跑一次 `all --no-fetch`，`corpus/genshin/` 就是基线；改完 `uv run python dev_tools/regress.py genshin` 比指纹，再按[改代码之后](../../../docs/genshin/dev-guide.md#改代码之后)看报告。改了 `index_reminders`：7.1.0 起这张表省略取默认值的字段，代码按 `REMINDER_DEFAULTS` 补回，要在省略默认值之前的最后一版（7.0.0）与当前快照上都按[跨版本回归](../../../docs/dev-guide.md#跨版本回归)比（关掉补全时 `style` 会硬失败、`voice` 会在 `release` 时报偏移）。

## 必须保持的不变量

本项目正确性的地基，改动时不要"顺手优化"掉。代码注释里的"不变量 N"指这里的编号。

1. **绝不硬编码上游的混淆字段名。** 混淆名同 schema 内稳定、跨 schema 不通用、跨版本不保证；靠结构特征推断字段角色，每次快照重新推一遍。判据见[结构推断](../../../docs/genshin/architecture.md#结构推断)。
2. **推断失败必须计数并落盘，不许静默跳过。** 未解析的文件 / 节点写进 `build/genshin/unparsed.jsonl` 并计入 report。
3. **多语种同源同序。** 一次装配、逐语种展开，各 JSONL 行数相同、逐行 id 相同；禁止每种语言各跑一遍流水线。
4. **获取与解析分离。** `snapshot` 之外的任何阶段都不许联网；改 parser 不能触发重新下载。
5. **上游版本与提取代码版本可追溯。** 每条输出记 `upstream.commit` 与 `upstream.version`；report 另记 `extractor`。
6. **看起来成功的错误解析比失败更危险。** `infer` 的两道否决（文本得分阈值、失败分级）不能去掉，见[两道否决](../../../docs/genshin/architecture.md#两道否决)。
7. **显式归属与推测归属必须分开**（`attribution: "explicit"` / `"inferred"`），永远不要混成一个字段。
8. **报告必须区分「上游缺译」与「解析失败」**，见[报告与校验](../../../docs/genshin/architecture.md#报告与校验)。
9. **上游地址会变，别硬追一个分支。** `snapshot` 识别已废弃的 origin 并自动重建，见[上游搬过一次家](../../../docs/genshin/dev-guide.md#上游搬过一次家)。
10. **`upstream/genshin/`、`corpus/genshin/` 和根 `out/` 不入库**；`bundle` 出的包只供私下传递。

模块边界：`infer.py` 只做结构识别、不认识"任务""对话"；`assemble.py` 不碰混淆字段名；只有 `gametext.core.snapshot` 联网，本目录的 `__init__.py` 只给它上游配置。

## 按任务找入口

| 要做的事 | 先读 |
| --- | --- |
| 改解析、推断判据、报告 | [docs/genshin/architecture.md](../../../docs/genshin/architecture.md)，上游事实查 [docs/genshin/data-source.md](../../../docs/genshin/data-source.md)（尤其[陷阱清单](../../../docs/genshin/data-source.md#陷阱清单)） |
| 改产出字段或格式 | 先改内容契约 [contract.py](contract.py)，再看 [docs/genshin/manual.md](../../../docs/genshin/manual.md) 与根[内容契约](../../../docs/architecture.md#内容契约) |
| 升上游版本、做回归 | [docs/genshin/dev-guide.md](../../../docs/genshin/dev-guide.md) |
| 维护工具 | [tools/genshin/README.md](../../../tools/genshin/README.md) |

文档里的实测数字都标了版本或快照 commit；只把仍然成立的写进去，不要往本文件搬细节。
