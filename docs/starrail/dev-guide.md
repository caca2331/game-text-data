# 开发指南

改代码、升上游版本、做回归时的做法。三款共用的部分（快照形态、`--purge`、槽里的快照、发布）在根[开发指南](../dev-guide.md)。

## 环境与命令

在仓库根运行。依赖只有 `orjson`（TextMap 数十 MB，标准库 json 慢一个量级）与 `zstandard`，`uv sync` 装好；解析没有自动化测试（`uv run pytest` 只测 core 与边界）。

```bash
uv sync
uv run gametext starrail all              # 全流程，首次会克隆上游（约 0.85 GB）
uv run gametext starrail all --no-fetch   # 用现有快照重跑，约 25 秒
uv run gametext starrail bundle           # 清单 + 产物包进仓库根的 out/
uv run gametext starrail release          # 发布：记进 releases/starrail/fingerprints.tsv 再打包；产出变了才 --bump --note
```

维护工具在 [`tools/`](../../tools/starrail/README.md)。

## 改代码之后

- 全量只要约 25 秒，改完就 `all --no-fetch` 全量重跑。看报告里的硬失败、台词未解析率（应约 0.01%、各语种一致）、台词覆盖率与悬空引用数（不应突然跳变）。
- 改了产出字段：先改内容契约 `src/gametext/starrail/contract.py`（没声明的键会让 emit 硬失败），版本规则见根架构说明的[内容契约](../architecture.md#内容契约)。
- 声称"产出没变"时拿内容指纹比（`corpus/starrail/manifest.json` 的 `fingerprint`），不要只看计数。
- 文档里的实测数字都标了版本；换了上游快照要重新核对再改数字（`tools/starrail/p0_probe.py` 可用于结构诊断）。

## 版本更新

`uv run gametext starrail all`：取数是增量的，解析是全量重跑。上游很活跃（几天一次提交），存活检测按数据提交年龄报警。

## 跨版本回归

把上游 `git checkout` 到 **3.8.0**（2025-12-30，比当前早 7 个小版本、8 个月），
**代码一行没改**重跑（当时的代码：还没补任务根目录下的活动 / 教程脚本，下表 4.5.0 一列也是那版代码的数）：

| 指标 | 3.8.0 | 4.5.0 |
| --- | ---: | ---: |
| 任务 | 1927 | 2166 |
| 对话事件 | 86 890 | 96 358 |
| 台词总数 | 196 549 | 240 488 |
| 台词覆盖率 | 70.3% | 67.4% |
| 任务外对话脚本 | 7170 | 9188 |
| 短信条数 | 11 961 | 13 651 |
| 选项带回答 | 24 842 | 29 922 |
| 硬失败 | 无 | 无 |

四语种未解析率 0.00%，完整性校验通过。上游存活检测正确报出「253 天前，超过 40 天」——
这正是它该有的反应。

崩铁的数据是明文的，本来就不指望字段名变化，所以这一轮验的是别的东西：**新加的三块
（字符串引用、任务外对话、短信）在旧版本上结构一样成立**，不是只对着当前版本调出来的。

做法与另外两款的结果见根开发指南的[跨版本回归](../dev-guide.md#跨版本回归)。

## 磁盘占用

`upstream/starrail/` 是 git 克隆（工作区 + `.git`），实测 1.99 GB（工作区 1.35 + `.git` 0.64）。跑完可以按需清掉：

```bash
uv run gametext starrail all --purge git   # 只删 .git，解析仍可离线重跑
uv run gametext starrail all --purge all   # 整个 upstream/starrail/ 都删
```

默认不删。详见根开发指南的[上游快照](../dev-guide.md#上游快照)。
