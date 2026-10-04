# Game Text Data

一个**游戏文本数据提取仓库**。目标是把各款游戏的剧情 / 对话 / UI 文本，从各自的上游数据源（社区解包数据）抽成结构化、多语言对齐、可增量更新的语料。

不抓网页：上游是完整快照，不存在"漏爬"；各语种取自同一条记录的同一个 key，天然对齐；版本更新退化成 `git pull` + 全量重跑。

## 游戏

| 游戏 | 上游数据源 | 现状 |
| --- | --- | --- |
| [原神](docs/genshin/README.md)（`genshin`） | [Dimbreath/animegamedata2](https://gitlab.com/Dimbreath/animegamedata2) | **已跑通**。当前 7.1.0，4417 个任务 / 35.1 万个对话节点 + 1.27 万条语音字幕链，多语言逐行对齐（默认中英日） |
| [崩坏：星穹铁道](docs/starrail/README.md)（`starrail`） | [Dimbreath/turnbasedgamedata](https://gitlab.com/Dimbreath/turnbasedgamedata) | **已跑通**。当前 4.6.0，2184 个任务 / 9.6 万个对话事件（含分支）+ 13 890 个任务外对话脚本 + 774 组短信 + 全量台词表 24.4 万句，多语言逐行对齐（默认中英日） |
| [绝区零](docs/zzz/README.md)（`zzz`） | [dimbreath/ZenlessData](https://git.mero.moe/dimbreath/ZenlessData)（Gitea） | **已跑通**。当前 3.2.0，3.3 万个场景 / 24.1 万条台词 / 1.4 万个任务 / 961 组短信分支 + 13.8 万条散条目，多语言逐行对齐（默认中英日） |

每款游戏的产出、字段与取舍见上表链到的说明。

## 快速开始

要 [uv](https://docs.astral.sh/uv/)。在仓库根：

```bash
uv sync
uv run gametext genshin all      # 首次会 sparse 克隆上游到 upstream/genshin/；语料出在 corpus/genshin/
uv run gametext --help
```

## 文档

- [架构说明](docs/architecture.md)：设计取向（离线数据源优先、认结构不认字段名…）、三款数据的形态差异、代码结构、产物格式、产物包协议 `gtd-bundle/1`、指纹表与内容契约。
- [开发指南](docs/dev-guide.md)：上游快照与磁盘占用、语种、`--purge`、在 worktree 槽里开发、跨版本回归、发布、文档检查。
- `docs/<游戏>/`：每款游戏的说明、架构、开发指南与上游实测记录。
- [AGENTS.md](AGENTS.md)：给 coding agent 的入口，也是本仓库规则的正本（取数原则、提交与分支）。

## 相关项目

- [FlowOCR](https://github.com/caca2331/FlowOCR)：把视频里出现过的文字带时间戳读出来。它读本仓库的产物包，把游戏录像里 OCR 读到的对白换成原文并带上译文（[产物包协议](docs/architecture.md#产物包协议gtd-bundle1)是两边唯一的接口）。

## 许可

提取代码以 **GPL-3.0-or-later** 发布（[LICENSE](LICENSE)）。上游是社区解包数据，游戏文本的版权归原权利人；
`upstream/`、`corpus/`、`out/` 都不入库、不公开分发，产物包只供个人研究时私下传递，包里的 `NOTICE.txt` 写着这一条。

公开仓库只有 `main`，由 `dev_tools/publish.py` 从开发分支生成，每次发布一个快照提交。
