# starrail：崩坏：星穹铁道的解析层

从社区解包数据（Dimbreath/turnbasedgamedata）离线提取崩铁的任务、任务外对话、短信、全量台词表与短名词，输出多语言逐行对齐的 JSONL。本目录只 import `gametext.core`（快照、CLI、产物包、契约检查机制），**不要 import genshin 的代码**（为什么见[与 genshin 的关系](../../../docs/starrail/architecture.md#与-genshin-的关系)）；仓库整体约定见根 [AGENTS.md](../../../AGENTS.md)。现状与数字见 [docs/starrail/README.md](../../../docs/starrail/README.md#现状)。

```text
snapshot → upstream/starrail/ ─index→ build/starrail/index/ ─assemble→ build/starrail/assembled*.jsonl（文本仍是 hash） ─emit→ corpus/starrail/
```

## 常用命令

在仓库根运行：

```bash
uv run gametext starrail all --no-fetch   # 用现有快照重跑，约 25 秒（槽里一律这样跑）
uv run gametext starrail all              # 带取数：只在主 checkout 升上游版本时用
uv run gametext starrail release          # 发布：记进 releases/starrail/fingerprints.tsv 再打包（要 owner 要求）
```

解析没有自动化测试：改前用旧代码跑一次 `all --no-fetch`，`corpus/starrail/` 就是基线；改完 `uv run python dev_tools/regress.py starrail` 比指纹，再按[改代码之后](../../../docs/starrail/dev-guide.md#改代码之后)看报告。

## 必须保持的不变量

代码注释里的"不变量 N"指这里的编号。依据都在 [docs/starrail/architecture.md 的上游的坑](../../../docs/starrail/architecture.md#上游的坑) 与 [data-source.md](../../../docs/starrail/data-source.md)。

1. **解析失败必须计数并落盘，不许静默跳过。**
2. **多语种同源同序。** 一次装配、多次展开，各语种 JSONL 行数相同、逐行 id 相同。
3. **获取与解析分离。** 只有 `snapshot` 阶段允许联网。
4. **上游版本与提取代码版本可追溯。** 每条输出记上游 commit 与游戏版本，报告另记 `extractor`。
5. **装载 TextMap 必须收全分片**（KR / RU / TH 拆成 `_0/_1`）：靠枚举目录匹配文件名收集，别写死。
6. **hash 是 64 位。**
7. **`Config/Level` 是对话引用的主体，不能漏。**
8. **台词归属按目录名走，子任务归属才用 SubMissionID 前 7 位。** 两者是不同的编号约定，别混。
9. **上游的字段名照抄，别"顺手修正"**（`SubMission` 的 `DescrptionText` 少个 i）。
10. **台词引用有两种形态**：`TalkSentenceID` 与自定义字符串里的 `TalkSentence_<id>`，只认前者会让选项只剩问、没有答。
11. **扫对话来源不要列白名单。**
12. **`MessageItemConfig.OptionText` 只在 `Sender == "Player"` 的行上有意义。**
13. **`{TEXTJOIN#n}` 只在标签里替换，对话正文一律保持原样。**
14. **悬空引用不是解析失败**，单独落在 `build/starrail/index/dangling.json`，别塞进 `unparsed.jsonl`。
15. **任务根目录下归不了属的脚本也要输出**（当任务外对话）："算进了被引用"不等于"进了产物"。
16. **全量台词表只附已知引用，不做连号推断。**

模块边界：`script.py` 是 LevelGraph 解析器，对话顺序与分支都靠它，别退回正则抽 id。模块地图见[流水线](../../../docs/starrail/architecture.md#流水线)。

## 按任务找入口

| 要做的事 | 先读 |
| --- | --- |
| 改解析、归属、报告 | [docs/starrail/architecture.md](../../../docs/starrail/architecture.md)，上游事实查 [docs/starrail/data-source.md](../../../docs/starrail/data-source.md) |
| 改产出字段或格式 | 先改内容契约 [contract.py](contract.py)，再看 [docs/starrail/manual.md](../../../docs/starrail/manual.md) 与根[内容契约](../../../docs/architecture.md#内容契约) |
| 升上游版本、做回归 | [docs/starrail/dev-guide.md](../../../docs/starrail/dev-guide.md) |
| 维护工具 | [tools/starrail/README.md](../../../tools/starrail/README.md) |
