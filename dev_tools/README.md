# dev_tools/

仓库级的维护工具，不是流水线的一部分。在仓库根运行。

| 工具 | 用途 |
| --- | --- |
| `regress.py` | 回归：用当前代码离线重跑几款游戏（并行，默认 4 个），内容指纹与现有语料比，不同就逐表列出；`--seeds` 换 `PYTHONHASHSEED`。做法见[跨版本回归](../docs/dev-guide.md#跨版本回归) |
| `check_docs.py` | 文档检查：链接与锚点、公开文档不指进私有路径、plan 有状态块。见[文档检查](../docs/dev-guide.md#文档检查)（约定工具的副本） |
| `publish.py` | 代码发布：从 `dev` 生成公开的 `main`。见[发布](../docs/dev-guide.md#发布)（约定工具的副本） |
