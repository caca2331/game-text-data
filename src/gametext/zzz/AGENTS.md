# zzz：绝区零的解析层

从社区解包数据（dimbreath/ZenlessData，Gitea）离线提取绝区零的剧情场景、任务、短信分支图、散条目与短名词，输出多语言逐行对齐的 JSONL。本目录只 import `gametext.core`（快照、CLI、产物包、契约检查机制），不 import 别的游戏；仓库整体约定见根 [AGENTS.md](../../../AGENTS.md)。现状与数字见 [docs/zzz/README.md](../../../docs/zzz/README.md#现状)。

两个来源分工：**TextMap 给文本**（key 是明文语义标识，剧情直接提取并排序），**FileCfg 给结构**（场景类型、任务链、短信分支；字段名混淆，靠锚点推断）。

```text
snapshot → upstream/zzz/{TextMap,FileCfg} ─index→ build/zzz/index/ ─emit→ corpus/zzz/（没有 assemble 阶段）
```

## 常用命令

在仓库根运行：

```bash
uv run gametext zzz all --no-fetch   # 用现有快照重跑，约 23 秒（槽里一律这样跑）
uv run gametext zzz all              # 带取数：只在主 checkout 升上游版本时用（首次克隆约 0.42 GB）
uv run gametext zzz release          # 发布：记进 releases/zzz/fingerprints.tsv 再打包（要 owner 要求）
```

解析没有自动化测试：改前用旧代码跑一次 `all --no-fetch`，`corpus/zzz/` 就是基线；改完 `uv run python dev_tools/regress.py zzz` 比指纹，再按[改代码之后](../../../docs/zzz/dev-guide.md#改代码之后)看报告。**改了 index 要加 `--seeds 1 2`**（换两个 `PYTHONHASHSEED` 各跑一次）。

## 必须保持的不变量

代码注释里的"不变量 N"指这里的编号。依据见 [docs/zzz/architecture.md](../../../docs/zzz/architecture.md) 与 [data-source.md](../../../docs/zzz/data-source.md)。

1. **推断 / 解析失败必须计数并落盘，不许静默跳过。** `FileCfg` 三张表任何一张推断失败都是硬失败。
2. **多语种同源同序。** 同一次遍历写出各语种，行数相同、逐行 id 相同。
3. **获取与解析分离。** 只有 `snapshot` 阶段允许联网。
4. **上游版本与提取代码版本可追溯。** 每条输出记上游 commit 与游戏版本，报告另记 `extractor`。
5. **`Overwrite` 是覆盖层，合并必须先主表后覆盖。** 顺序反了会静默拿到旧文本。
6. **`_Name_` 后缀是场景的出场角色表，不是逐行说话人。** 输出成场景的 `cast`，别配给行。
7. **解析章节不能用 `\w`**（它含下划线），用 `[A-Za-z0-9]*`。
8. **访问上游要带浏览器 UA**（HTTP API / raw 对默认 UA 返回 403）。
9. **`FileCfg` 里文件名可以当锚点，字段名绝不硬编码。** 每张表都要带一条可独立验证的否决规则。
10. **两个 id 空间重叠会撞出假关联。** 扫桥表时排除表自身主键；短场景号（`Chat|Chapter1|13`）只在本类别内唯一，所以联接 Perform 时要求场景 id 至少 6 位。
11. **拿不准语义就不要命名**（`QuestConfig` 的两个自引用字段是互为逆关系的前置 / 后继链，方向由 id 序推断、置信度进报告）。
12. **判据不能只卡比率。** `ref_fields` 除比率外并联一条绝对命中数判据；凡是靠阈值分类的地方，都要想一想"版本变化会不会把它推过线"。
13. **快照工作区可能不等于它记录的 commit**（Windows 上大小写冲突）。`snapshot.check_integrity` 只检测并上报，不要试图"修好"它。
14. **没进产物的 TextMap 条目一律进 `loose`**，不许只记在 unparsed 里。
15. **槽位用 key 里原样的序号串，不按数值归一**（`_01` 与 `_1` 是两条台词）。

## 按任务找入口

| 要做的事 | 先读 |
| --- | --- |
| 改解析、推断、桥表、报告 | [docs/zzz/architecture.md](../../../docs/zzz/architecture.md)，上游事实查 [docs/zzz/data-source.md](../../../docs/zzz/data-source.md) |
| 改产出字段或格式 | 先改内容契约 [contract.py](contract.py)，再看 [docs/zzz/manual.md](../../../docs/zzz/manual.md) 与根[内容契约](../../../docs/architecture.md#内容契约) |
| 升上游版本、做回归、快照完整性 | [docs/zzz/dev-guide.md](../../../docs/zzz/dev-guide.md) |
| 维护工具 | [tools/zzz/README.md](../../../tools/zzz/README.md) |
