# 开发指南

改代码、升上游版本、做回归时的做法。三款共用的部分（快照形态、`--purge`、槽里的快照、发布）在根[开发指南](../dev-guide.md)。

## 环境与命令

在仓库根运行。依赖只有 `orjson`（TextMap 是 20–25 MB 的 JSON，四语种反复装载，标准库 `json` 慢一个量级）与 `zstandard`，`uv sync` 装好；解析没有自动化测试（`uv run pytest` 只测 core 与边界）。

```bash
uv run gametext genshin all                  # 全流程；首次会克隆上游（sparse，约数百 MB）
uv run gametext genshin all --no-fetch       # 用现有快照重跑，不联网
uv run gametext genshin index                # 单独重跑某一阶段（snapshot / index / assemble / emit）
uv run gametext genshin bundle               # 清单 + 产物包进仓库根的 out/
uv run gametext genshin release              # 发布：记进 releases/genshin/fingerprints.tsv 再打包；产出变了才 --bump --note
```

维护工具在 [`tools/`](../../tools/genshin/README.md)。

## 改代码之后

- 全量只要约 40 秒，改完就 `all --no-fetch` 全量重跑，看三个数：`failures_unexpected`（应为 0）、对话正文未解析率（不应突然飙高）、`talk_barren_subdirs`（原本能出数据的目录不应突然进这个列表）。
- 改了产出字段：先改内容契约 `src/gametext/genshin/contract.py`（没声明的键会让 emit 硬失败），版本规则见根架构说明的[内容契约](../architecture.md#内容契约)。
- 声称"产出没变"时拿内容指纹比（`corpus/genshin/manifest.json` 的 `fingerprint`），不要只看计数。
- 文档里的实测数字都标了版本或快照 commit；改了上游快照，要重跑 `tools/genshin/p0_probe.py` 核对再改数字。

## 版本更新

```bash
uv run gametext genshin all
```

获取端是增量的（`git fetch --depth 50`），**处理端是全量重跑，而且应该是**：字段名每版本全变，schema 必须整批重推；基于旧 schema 做增量解析必然产出那种"看起来成功"的错误。全量只要 40 秒，不值得为增量增加这个风险。

更新后重点看的就是[改代码之后](#改代码之后)那三个数。

**sparse 规则改了的那次**（如加了 `Readable/<语种>/`）：规则在每次带取数的 `snapshot` 里重设，所以主 checkout 带取数跑一次就跟上；
只 `--no-fetch` 的老快照没有新目录，`index` 会把缺的目录记成非预期失败、整条流水线红掉，不会静默少一张表。
槽里的 worktree 快照不带取数，要手动按代码里的规则重设一次（`gametext.core.snapshot._set_sparse(UPSTREAM, <快照目录>, textmap.LANGS)`，
它会按需下载新目录的文件；别在 Git Bash 里手敲 `git sparse-checkout set /Readable/...`，以 `/` 开头的参数会被改写成 Windows 路径）。

尚未实现：版本间 diff（新版本加了哪些任务、改了哪些台词）。

### 上游搬过一次家

原仓库 `gitlab.com/Dimbreath/AnimeGameData` 因**体积超限被弃用**，README 只剩一行指向
`animegamedata2`，数据停在 6.6.0。新仓库默认分支是 `main`（不是 `master`）。
GitHub 的 `DimbreathBot/AnimeGameData` 是同一份数据的镜像（commit sha 一致），但它的
`master` 分支是旧仓库的残留、`main` 才是新的 —— **别追错分支**。

`snapshot` 会检测本地快照的 origin 是否指向已废弃的地址，是就自动重建；否则继续 pull
旧地址会永远停在 6.6.0 而毫无提示。

上游万一被下架：本地快照记着 commit，GitHub 镜像 `DimbreathBot/AnimeGameData`（`main` 分支）可作备份。但它在 `__init__.py` 的废弃列表里（它的 `master` 是旧仓库的残留）：**别直接把快照的 origin 改成镜像**，`snapshot` 会先删掉整个快照再去克隆 `UPSTREAM.repo`。要切到镜像，改 `UPSTREAM.repo`、把镜像移出 `legacy_repos`，分支仍是 `main`。

### 跨版本回归

6.6.0 → 7.0.0 那次是**被动**赶上的。后来把上游 `git checkout` 退回 **6.7.0**
（2026-06-29，早 2 个小版本）代码一行不改重跑：

| 指标 | 6.7.0 | 7.0.0 |
| --- | ---: | ---: |
| 任务 | 4177 | 4372 |
| 对话节点 | 333 623 | 345 041 |
| `failures_unexpected` | **0** | **0** |

升到 7.1.0 时改了解析代码，于是又拿 7.0.0 回归了一次：新旧代码在 7.0.0 上的产物只差 131 个
对话节点的 `role.id`。那是旧代码的缺陷：说话人对象的键在未混淆的那批 talk 里叫 `id`、混淆的
那批叫 `_id`，旧代码只认 `_id`，未混淆的 talk 的说话人 id 一直是 null；7.1.0 大部分改叫 `id`，
缺陷才暴露成几乎整列 null。现在两种键名都认。其余逐字段相同。

做法与另外两款的结果见根开发指南的[跨版本回归](../dev-guide.md#跨版本回归)。那一轮在绝区零上抓到了
一个真问题（判据只卡比率、被版本变化推过线），值得一并看。

## 磁盘占用

`upstream/genshin/` 是 git 克隆（工作区 + `.git`），实测 2.81 GB（工作区 2.08 + `.git` 0.74）。跑完可以按需清掉：

```bash
uv run gametext genshin all --purge git   # 只删 .git，解析仍可离线重跑
uv run gametext genshin all --purge all   # 整个 upstream/genshin/ 都删
```

默认不删。详见根开发指南的[上游快照](../dev-guide.md#上游快照)。
