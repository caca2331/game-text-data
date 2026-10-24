# 变更记录

写给使用本仓库代码或产物包的人：每条说用户看得见的变化，以及要不要做什么。

## 0.2.0（2026-10-24）

- 原神任务对话的配音标记 `dialog[].voice` 不再一律 `unknown`：按上游 `BinOutput/Voice/` 的事件映射补标，命中的（7.1.0 约 46% 的对话行）为 `voiced`，
  其余仍是 `unknown`（没映射不等于没配音）；语音字幕 `reminders_*` 的 `voice` 也先看这份映射，再看 `hasAudio`。字段和值域不变。
  取数的 sparse 规则多了 `BinOutput/Voice/`：已有的快照要带取数跑一次 `snapshot`，否则 `all` 报非预期失败。

- 原神的包多一张称谓表 `pronouns_*`（契约 `genshin.pronouns/1`）：台词里 `{PLAYERAVATAR#SEXPRO[…]}` / `{MATEAVATAR#SEXPRO[…]}` 引用的键 → 文本
  （称谓和日文的句尾），方括号里第一个键是那个角色为男时用的。其余三张表的内容不变；不读这张表的下游不用改。

- 原神的包多一张阅读面板长文本表 `readables_*`（契约 `genshin.readables/1`）：上游 `Readable/` 目录的书籍、武器 / 圣遗物故事、
  信件正文，加邮箱信件、教程说明页、活动来信、角色故事的正文，一行一篇全文（`id`、`source`、`text`），已在任务对话或语音字幕里的不收。
  其余表的内容不变。取数的 sparse 规则多了 `Readable/<语种>/`：已有的快照要带取数跑一次 `snapshot` 才有这个目录（约 22 MB），只 `--no-fetch` 会报非预期失败。

- 星铁的包多一张 `textjoins_*`（契约 `starrail.textjoins/1`）：台词里 `{TEXTJOIN#n}`（玩家给宠物、飞船、社团起的名字）的候选与默认项。其余五张表的内容不变。

- 绝区零的上游跟到 3.3.0，表和字段不变。

- `releases/<游戏>/fingerprints.tsv` 新记的语料：原神 7.1.0 `rev` 3（含上面三项）、星铁 4.6.0 `rev` 2（含 `textjoins`）、绝区零 3.3.0 `rev` 1。

## 0.1.0（2026-10-03，首次公开）

- 原神 7.1.0、崩坏：星穹铁道 4.6.0、绝区零 3.2.0 的提取代码，合在一个 Python 包 `gametext` 里：在仓库根 `uv run gametext <游戏> <阶段>`，依赖由根 `pyproject.toml` 管；GPL-3.0-or-later。
- 产物包协议 `gtd-bundle/1`：每款游戏一个自描述的 zip（清单、哈希、内容指纹），见 [docs/architecture.md](https://github.com/caca2331/game-text-data/blob/v0.1.0/docs/architecture.md#产物包协议gtd-bundle1)。
- 产物包清单的 `tables.<表>.contract`（如 `genshin.reminders/1`）记每张表的[内容契约](https://github.com/caca2331/game-text-data/blob/v0.1.0/docs/architecture.md#内容契约)版本：字段的类型、能否为 null、取值写在各游戏模块的 `contract.py` 里，产出方逐行检查，违反就不出包。下游应核对自己要求的契约主版本。
- `releases/<游戏>/fingerprints.tsv` 记发布过的语料：三款都是 `rev` 1，含对白表与短名词表 `terms_*`（FlowOCR 查名牌译名用）。
