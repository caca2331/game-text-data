# Game Text Data

**游戏文本数据提取仓库**：把各款游戏的剧情 / 对话 / UI 文本，从各自的上游数据源抽成结构化、多语言对齐、可增量更新的语料。

一个 Python 包 `gametext`：协议与通用机制（快照、JSONL、产物包与发布、内容契约、报告骨架、CLI）在 `src/gametext/core/`，每款游戏的解析层各是一个模块。

```text
上游解包仓库 ─snapshot→ upstream/<游戏>/ ─解析→ build/<游戏>/ ─emit→ corpus/<游戏>/（语料 + manifest.json） ─bundle→ out/<游戏>-<版本>-<指纹>.zip
```

| 游戏 | 名字 | 上游数据源 | 解析层 |
| --- | --- | --- | --- |
| 原神 | `genshin` | Dimbreath/animegamedata2 | [src/gametext/genshin](src/gametext/genshin/) |
| 崩坏：星穹铁道 | `starrail` | Dimbreath/turnbasedgamedata | [src/gametext/starrail](src/gametext/starrail/) |
| 绝区零 | `zzz` | dimbreath/ZenlessData（Gitea） | [src/gametext/zzz](src/gametext/zzz/) |

**改某款游戏前，先读 `src/gametext/<游戏>/AGENTS.md`**：它的不变量与入口都写在那里。

## 常用命令

在本 checkout 的根运行（每个 worktree 槽各有自己的 `.venv`，第一次 `uv run` 自动建；别拿主 checkout 的 venv 跑槽里的代码）：

```bash
uv run gametext <游戏> all --no-fetch            # 解析 + 产出，不联网（槽里一律这样跑）
uv run gametext <游戏> all                       # 带取数：只在主 checkout 升上游版本时用
uv run gametext <游戏> release                   # 语料发布：记进 releases/<游戏>/fingerprints.tsv 再打包，之后提交 releases/<游戏>/
uv run pytest                                    # 提交前：core 的测试、import 边界、文档检查
uv run python dev_tools/regress.py [游戏…]       # 回归：当前代码离线重跑、指纹与 corpus/ 比（并行，三款约 1 分钟）
python dev_tools/check_docs.py --public          # 只查文档（pytest 也会跑它）
python dev_tools/publish.py check                # 代码发布（推公开的 main）前预演；publish.py publish 才发布
```

"发布"有两种：语料发布是 `release`，代码发布是 `publish.py`；owner 没说清是哪种就问。两种都要 owner 明确要求，都在主 checkout 的 `dev` 上、工作区干净时做；`release` 只发当前 HEAD 产的语料，所以先重跑一次 `all`，带不带取数问 owner。`--bump`、`--accept-drift` 什么时候用见[发布](docs/dev-guide.md#发布)。

## 护栏

- 游戏模块之间不 import，只用 `core`；`core` 不 import 游戏模块（CLI 按名字加载）。协议与通用机制进 `core`，解析层各写各的：三款的核心难点完全不同，重复优于耦合只在解析层成立，为什么见[三款数据的形态差异](docs/architecture.md#三款数据的形态差异)。一个包，一套风格。
- 一次任务原则上只改一个游戏模块（加上它用到的 `core` 改动）；同时改两个游戏模块先跟用户确认。
- 改产物的字段、含义或格式前先跟 owner 确认：下游 FlowOCR 在读这些包。
- 运行时目录（`upstream/`、`build/`、`corpus/`、`out/`）不入库；跑出新语料本身不产生提交。升了上游版本要提交的是文档里的现状数字（根 README 那款游戏的一行与 `docs/<游戏>/README.md` 的现状一节），`release` 另会改追踪的 `releases/<游戏>/`。
- 仓库级工具在根 `dev_tools/`（`publish.py`、`check_docs.py`、`regress.py`）。测试只有 `tests/` 一个入口，只测 `core` 与边界、不测解析；改了解析靠 `regress.py` 比指纹。
- 回归按需跑，别每步都跑：预期产出不变的改动（重构、改文档、改报告措辞）做完一批再跑一次；会改产出的改动，改前先用旧代码出一份 `corpus/` 作基线，改完跑一次、说清每一处差异。

### 取数原则

本仓库存在的理由，任何游戏都不要绕过。论证与实例见[设计取向](docs/architecture.md#设计取向)。

1. **离线数据源优先于网页爬虫。** 只有确实没有离线源时才抓站，且落原始响应。
2. **获取与解析分离。** 先把上游原始数据落盘，解析是纯本地的一步；改 parser 不许触发重新获取。唯一的例外是用户显式要省磁盘的 `--purge`；**默认是 none，不要擅自改默认值**。
3. **多语言必须同源对齐。** 各语种取自同一条上游记录的同一个 key，禁止每种语言各取一次。
4. **产出必须自带完整性报告。** 每次生成语料后打印：各语种条目数是否一致、多少条目缺文本、多少引用指向不存在的记录。静默的数据缺口是本仓库最主要的失败模式。
5. **上游版本与提取代码版本都可追溯。** 输出记录上游快照的版本号 / commit，并校验快照工作区确实等于那个 commit；`report.json` 的 `extractor` 记本仓库 HEAD 与有无未提交改动（同一份上游、不同版本的提取代码会产出不同语料：zzz 槽位修复前后台词差 219 条）。
6. **判据不要只卡比率，并定期拿旧版本回归一次**：改了解析代码，就在上一版快照上用改动前后的代码各跑一次、比指纹。步骤见[跨版本回归](docs/dev-guide.md#跨版本回归)。
7. **产物要能自证版本。** `corpus/<游戏>/` 带 `manifest.json`（协议 `gtd-bundle/1`，实现在 `core`）；产物不公开分发，包只供私下传递。协议、指纹表与 `rev` 见[产物包协议](docs/architecture.md#产物包协议gtd-bundle1)。

## 项目约定

- 规模：复杂。一个包装三款游戏；约定只取合用的部分（owner 2026-10-02），下面几条是本仓库自己的规定。
- 目录：`upstream/<游戏>/` 是上游快照（嵌套的 git 仓库，`snapshot` 会改写它），`build/<游戏>/` 是中间产物，可整目录删（例外：快照被 `--purge git` 清过之后，`build/<游戏>/snapshot.json` 是上游身份的唯一记录），`corpus/<游戏>/` 是语料（清单所在），`out/` 只放产物包 zip（FlowOCR 扫 `out/` 找包，语料放进去会被当成候选），都不入库。路径只从 `src/gametext/paths.py` 解析。追踪的发布记录在 `releases/<游戏>/`；维护工具在 `tools/<游戏>/`，有 `README.md` 清单。
- Python：src 布局，依赖只写 `pyproject.toml`，uv 管本 checkout 根的 `.venv`。
- 文档：根 `docs/` 管全仓库的事（[架构说明](docs/architecture.md)、[开发指南](docs/dev-guide.md)），`docs/<游戏>/` 是那款游戏的（`README.md` 现状与快速开始、`manual.md` 使用说明、`architecture.md`、`dev-guide.md`、`data-source.md` 实测附录）。计划都在 `docs/plans/`，文件名 `<主题>-plan.md`，只属于一款游戏的带游戏前缀，开头是状态块；`docs/plans/` 是私有的，发布时剥离。
- 新加游戏：`src/gametext/<游戏>/`（解析层、`contract.py` 契约、`__init__.py` 里的上游配置与 `GAME = Game(...)`，接线照抄 genshin 的 `__init__.py`；`AGENTS.md` 写这款的不变量，`CLAUDE.md` 只有一行 `@AGENTS.md`）→ `core/cli.py` 的 `GAMES` 加上它（随新游戏同一提交；import 边界测试按 `GAMES` 自动覆盖）→ `docs/<游戏>/`（至少 `README.md` 的现状一节）、`tools/<游戏>/README.md`（有工具才建）→ 第一次 `release` 前先 `release --baseline-from corpus/<游戏>`，用第一次要发布的那份语料建分布基线 → 本文件、根 README 的游戏表与根架构说明的[形态差异表](docs/architecture.md#三款数据的形态差异)各加一行。字段名混淆的上游参照 genshin 的思路（结构推断、防"成功地解析出垃圾"的否决规则），明文的参照 starrail。
- worktree 槽里所有目录都留在本槽，不解析回主 checkout：语料是产物、`upstream/` 会被改写。
- 若仓库根有 `CLAUDE.local.md`（维护者的私有补充，公开仓库里没有），开工前先读。

## 提交与分支

- commit message 用 `type(scope): summary`，scope 是游戏名（`genshin` / `starrail` / `zzz`）或 `core`：`src/gametext/<游戏>/`、`docs/<游戏>/`、`tools/<游戏>/`、`releases/<游戏>/` 算那款游戏；`src/gametext/core/`、`paths.py`、`tests/`、`pyproject.toml`、`uv.lock` 算 `core`；只动根文件（根 `docs/`、`dev_tools/`、入口文件）不写 scope，但根文件里某款游戏的那一行（根 README 的游戏表等）随那款游戏的提交、用它的 scope；新加游戏时 `GAMES` 那一行同样随游戏提交。一个提交只含一个 scope 的改动，同时动了多个就拆开；例外是文档随它描述的代码同一提交（改 `core` 连带改了游戏文档，就进 `core` 的提交）。代码 2026-10 从 `<游戏>/<旧包>/` 搬进了 `src/gametext/`，看之前的历史用 `git log --follow`。
- 日常开发在 `dev` 上（不公开）；特性分支带游戏名前缀（跨游戏或改 `core` 的用 `repo/`），合回 `dev`。
- 公开的 `main` 只由 `dev_tools/publish.py` 从 `dev` 生成，不手工提交、不把 `dev` 合进 `main`；外部 PR 以 `main` 为目标，合并后 `git merge main` 回 `dev`。发布（尤其 `--push`）要 owner 明确要求（owner 2026-09-25）。
- 并行开发用 `.worktrees/<槽位>/`（`git worktree add .worktrees/<槽位> -b <分支> dev`）；槽里没有快照和产物，怎么开见[槽里的快照](docs/dev-guide.md#槽里的快照)。升上游版本在主 checkout 里带 fetch 跑；槽里一律 `--no-fetch`（带 fetch 会把槽里那份快照重置到上游最新，并对共享对象库执行 gc）。

## 按任务找入口

| 要做的事 | 先读 |
| --- | --- |
| 改某款游戏的解析 | `src/gametext/<游戏>/AGENTS.md` |
| 改 `core`（快照、产物包、契约机制、CLI） | [架构说明](docs/architecture.md)。不该改变产出的改动：一批改完跑一次 `regress.py`（三款）；会改变产物内容、字段、含义，或清单、指纹、包的算法的：先问 owner（见护栏），验证改为逐表比 `content_sha256` |
| 上游出了新版本 | 在主 checkout 带 fetch 跑（要改解析的话，再按[槽里的快照](docs/dev-guide.md#槽里的快照)给新 commit 开快照，在槽里改）；`docs/<游戏>/dev-guide.md` 的版本更新，要提交的现状数字见上面护栏；快照、回归、磁盘与 `--purge` 在根[开发指南](docs/dev-guide.md) |
| 新加游戏 | 上面「项目约定」的新加游戏一条，参照 genshin |
| 改产物格式、清单、指纹、`release` | [产物包协议](docs/architecture.md#产物包协议gtd-bundle1)与[内容契约](docs/architecture.md#内容契约) |
| 发布到 `main` | [发布](docs/dev-guide.md#发布) |

## Claude Code

在 worktree 槽里工作时，会话留在主 checkout。槽里的分支改过入口文件时，自动加载的主 checkout 版本是旧的，以槽里那份为准。

> 会话在主 checkout、改的是槽时，注意环境的区别：相对路径、Bash 的 cwd、Grep / Glob 的默认搜索范围和自动加载的入口文件，都是主 checkout 的。
> - 读改槽里的文件用槽内绝对路径；搜索给 `path=<槽>`。不给时，Grep 只搜主 checkout（`.worktrees/` 被 `.gitignore` 挡着，槽里的文件搜不到）；Glob 则把主 checkout 和槽里的同名文件一起列出来。两种情况下都别把主 checkout 的文件当成槽里的。
> - git 用 `git -C <槽>`。
> - 要在槽里跑的命令写成 `(cd <槽> && …)`。括号让 `cd` 只在这一条命令里生效；不带括号时，harness 会把会话的主工作目录切进槽，之后删槽可能报 Permission denied。
