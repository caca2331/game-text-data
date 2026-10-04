# tools/genshin/

genshin 的维护用脚本，不进流水线。在仓库根用 `uv run python tools/genshin/<脚本>` 运行。

| 脚本 | 状态 | 用途 | 谁在引用 |
| --- | --- | --- | --- |
| `p0_probe.py` | 可用（7.1.0 上实跑过） | 上游结构诊断：快照信息、CodexQuest 的语义 tag 全集、`Talk/Quest` 结构推断的成功率与失败样本；`--old-data` 给了旧爬虫数据时再验 `q_XXXX == mainQuestId`。结果写 `build/genshin/p0_report.json`。换了上游快照、要核对文档里的实测数字时跑 | [docs/genshin/dev-guide.md](../../docs/genshin/dev-guide.md#改代码之后) |
| `crosscheck.py` | 可用，但要 `--old` 指向旧爬虫的 `quests_chs.jsonl`（维护者本机，未入库） | 与旧爬虫按 mainQuestId / dialogId 逐条比对，验证没接错字段、没解错 TextMap | [docs/genshin/architecture.md](../../docs/genshin/architecture.md#与旧爬虫的交叉校验) |

```bash
uv run python tools/genshin/p0_probe.py --limit 0              # 全量（约 15 秒）；默认只抽 500 个文件
uv run python tools/genshin/crosscheck.py --old <旧爬虫的 quests_chs.jsonl>
```
