# 变更记录

写给使用本仓库代码或产物包的人：每条说用户看得见的变化，以及要不要做什么。

## 0.1.0（2026-10-03，首次公开）

- 原神 7.1.0、崩坏：星穹铁道 4.6.0、绝区零 3.2.0 的提取代码，合在一个 Python 包 `gametext` 里：在仓库根 `uv run gametext <游戏> <阶段>`，依赖由根 `pyproject.toml` 管；GPL-3.0-or-later。
- 产物包协议 `gtd-bundle/1`：每款游戏一个自描述的 zip（清单、哈希、内容指纹），见 [docs/architecture.md](https://github.com/caca2331/game-text-data/blob/v0.1.0/docs/architecture.md#产物包协议gtd-bundle1)。
- 产物包清单的 `tables.<表>.contract`（如 `genshin.reminders/1`）记每张表的[内容契约](https://github.com/caca2331/game-text-data/blob/v0.1.0/docs/architecture.md#内容契约)版本：字段的类型、能否为 null、取值写在各游戏模块的 `contract.py` 里，产出方逐行检查，违反就不出包。下游应核对自己要求的契约主版本。
- `releases/<游戏>/fingerprints.tsv` 记发布过的语料：三款都是 `rev` 1，含对白表与短名词表 `terms_*`（FlowOCR 查名牌译名用）。
