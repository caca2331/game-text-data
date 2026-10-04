# 开发指南

改代码、升上游版本、做回归时的做法。三款共用的部分（快照形态、`--purge`、槽里的快照、发布）在根[开发指南](../dev-guide.md)。

## 环境与命令

在仓库根运行。依赖只有 `orjson` 与 `zstandard`，`uv sync` 装好；解析没有自动化测试（`uv run pytest` 只测 core 与边界）。

```bash
uv sync
uv run gametext zzz all              # 全流程，首次克隆约 0.42 GB
uv run gametext zzz all --no-fetch   # 用现有快照重跑，约 23 秒
uv run gametext zzz bundle           # 清单 + 产物包进仓库根的 out/
uv run gametext zzz release          # 发布：记进 releases/zzz/fingerprints.tsv 再打包；产出变了才 --bump --note
```

维护工具在 [`tools/`](../../tools/zzz/README.md)。

## 改代码之后

- 全量只要约 23 秒，改完就 `all --no-fetch` 全量重跑。看报告的硬失败、台词未解析率、三张 FileCfg 表的推断结果与桥表边数（不应突然跳变）。
- **改了 index，换两个 `PYTHONHASHSEED` 各跑一次、比内容指纹**（`uv run python dev_tools/regress.py zzz --seeds 1 2`）：槽位那类"丢哪条随 set 遍历顺序变"的不确定性，报告看不出来。
- 3.2.0 上实测过：两次运行（不同 `PYTHONHASHSEED`）产物逐字节相同。
- 改了产出字段：先改内容契约 `src/gametext/zzz/contract.py`（没声明的键会让 emit 硬失败），版本规则见根架构说明的[内容契约](../architecture.md#内容契约)。
- 声称"产出没变"时同样拿内容指纹比，不要只看计数。
- 访问上游要带浏览器 UA：`git.mero.moe` 对默认 UA 的 HTTP API / raw 返回 403（`git clone` 不受影响）。

## 版本更新

`uv run gametext zzz all`：取数是增量的，解析是全量重跑。上游天级更新，托管在作者自建的 Gitea 上，单点风险高，存活检测阈值 30 天。升完版本更新 [README](README.md#现状) 的状态表与根 README 的游戏表。

## 跨版本回归

「认结构不认字段名」是 zzz 解析层的立项理由，但一直没实测过。这次把上游 checkout 到
**2.7.0**（2026-03-24，比当前早 5 个小版本、约半年），**代码一行没改**重跑：

| 推断项 | 2.7.0 | 3.2.0 |
| --- | --- | --- |
| Perform 主键 | `HHPGHOAKJJO` | `PFOAJKNPCHL` |
| Perform 资源路径字段 | `DFIALENMNBA` | `BCKKFAEFDPP` |
| Quest 主键 | `OCHLPBBDODN` | `ODCODEPMLGG` |
| Quest 任务名 | `AOOHHPNDOFP` | `ANCOBODLNIK` |
| Message step | `DHPINMDJEGK` | `HBPLELJNAEA` |
| Message 选项→跳转 | `PFIGFCDDBGG`→`LIILCGKGMCP` | `FNOKFPDDECI`→`HFEPEHJGIAN` |

**混淆字段名一个都没重合，推断全部命中**：Perform 主键对场景 id 的覆盖率
2.7.0 是 81.1%、3.2.0 是 81.0%。产出 27 432 场景 / 201 253 台词 / 12 025 任务 /
902 短信组，完整性校验通过。存活检测也正确报了「170 天前」。

顺带证实了一件事：**混淆名的变化频率比"逐版本"还高**。上游 2026-09-09 当天发布 →
revert → 重发，前后两次提交的混淆名就完全不同。

### 回归测试抓到的一个真问题

`ArchiveFileQuest` 指向 Perform 的那个字段，命中数 261 在两个版本上一样，但**命中率**
3.2.0 是 0.32、2.7.0 只有 0.20（分母里的悬空引用变多了）。判据门槛是 0.3，于是整张桥表
在旧版本上**静默消失**——报告依然全绿，只是"场景↔任务边"变成 0。

修法是给 `ref_fields` 并联一条绝对命中数判据（命中数够大时允许命中率低到 0.05）。
改完 2.7.0 恢复出 261 条边，3.2.0 仍是 531 条、两张桥表，没有多出假关联。

教训写进了 zzz 的 [AGENTS.md](../../src/gametext/zzz/AGENTS.md) 不变量 12：**凡是靠阈值分类的地方，都要想一想"版本变化会不会把它推过线"。**

## 快照完整性：Windows 上装不下这份上游

3.2.0 `e223d18a17` 的树里有 **21 组只差大小写的同名文件**（`BPLevelVersionTemplateTb.json` 与
`BpLevelVersionTemplateTb.json`、`InterKnotConfigTemplateTb.json` 与
`InterknotConfigTemplateTb.json`…），其中 **20 组内容不同**。

Windows 文件系统大小写不敏感，每组只能落一个，落哪个取决于 git 最后写的是谁。后果：

- 这些文件的解析结果**不可复现**；
- `git status` 永远不干净，`git checkout` 到别的 commit 会直接失败（要 `-f`）；
- 更要紧的是，**工作区可能不等于它记录的那个 commit**——而"上游版本可追溯"是本仓库
  的取数原则之一，只把 commit 写进输出并不足以保证这一点。

`snapshot.check_integrity` 现在会检测并上报这两件事（脏工作区 + 大小写冲突），走
`report.json` 的 `warnings`。**它只报不改**：真要修得在每组里挑一边留，那是取舍不是修复。
好消息是这 21 组都不在我们具名解析的表里（Perform / Quest / Message），只被"扫全表找桥"
那一趟读到过。原神与崩铁的上游各有 0 组冲突。

当前快照 `1277ebca4b` 只剩 **1 组**（`Data/_unsorted/Zhenzhen_CardS3_Base_01_ZenKov.json` 与 `…_Zenkov.json`），
两边是同一个 blob、也不在 sparse 检出范围里，不影响解析。同名冲突的检测只看 sparse 实际检出的文件，
所以它不再上报，清单里 `integrity_checked` 是 `true`（2026-10 之前扫整棵树，这一组让它一直是 `false`）。

## 磁盘占用

`upstream/zzz/` 是 git 克隆（工作区 + `.git`），实测 1.15 GB（工作区 0.90 + `.git` 0.25）。跑完可以按需清掉：

```bash
uv run gametext zzz all --purge git   # 只删 .git，解析仍可离线重跑
uv run gametext zzz all --purge all   # 整个 upstream/zzz/ 都删
```

默认不删。详见根开发指南的[上游快照](../dev-guide.md#上游快照)。
