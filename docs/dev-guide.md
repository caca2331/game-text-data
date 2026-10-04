# 开发指南

全仓库的做法：上游快照、跨版本回归、在 worktree 槽里开发、发布、文档检查。各款游戏自己的流程见 `docs/<游戏>/dev-guide.md`。

## 上游快照

每款游戏的 `upstream/<游戏>/` 是一个 **git 克隆**（嵌套在本仓库里、被忽略），三个修饰都用上了：

```
git clone --depth 50 --filter=blob:none --sparse   # 浅 + 惰性拉 blob + 稀疏检出
```

所以它 = **工作区文件** + 一个 `.git`（提交/树的元数据，加上"曾经检出过的每个 blob"）。
实测占用：

| | 工作区 | `.git` | 小计 | 语料 | `build/` |
| --- | ---: | ---: | ---: | ---: | ---: |
| genshin | 2.08 GB | 0.74 GB | 2.81 GB | 0.38 GB | 0.16 GB |
| starrail | 1.35 GB | 0.64 GB | 1.99 GB | 0.23 GB | 0.09 GB |
| zzz | 0.90 GB | 0.25 GB | 1.15 GB | 0.22 GB | 0.04 GB |
| **合计** | **4.32 GB** | **1.62 GB** | **5.95 GB** | 0.83 GB | 0.29 GB |

这张表是早先的快照量的；2026-10-02 按默认的中英日三语重新克隆，三款解开的文件是 0.90 / 0.71 / 0.37 GB。

**刚克隆或新开 worktree 快照后，第一次解析要慢几分钟**（原神 index 实测 301 s、星铁 318 s，平常各几十秒）：Windows 的实时防护
（Defender）对**新写入的文件第一次被打开时**逐个扫描，约 4 ms 一个，而原神要读约 6 万个小文件、星铁的 `Config/Level` 也是几万个。
扫过一次就快了，所以只是第一次的代价。2026-10-03 实测：把原神 `BinOutput/Talk`（5.6 万个文件）复制一份，刚复制完（数据在内存缓存里）
读一遍 248 s、第二遍 5 s，原快照里同一批文件 5 s。

`upstream/`、`build/`、`corpus/`、`out/` 都不入库。

### `.git` 会悄悄变胖

`--filter=blob:none` 是惰性拉取，**每次 fetch 新开一个 pack，旧版本的 blob 也一直留着**。
zzz 实测一度攒到 **56 个 pack / 638 MB**，`git gc --prune=now` 之后是 **2 个 pack / 258 MB**。
所以 `snapshot` 的"更新已有快照"这条路径末尾会跑一次 `git gc --auto --prune=now`——
`--auto` 让 git 自己判断该不该动，真动的时候顺手把不可达对象清掉。

### 语种：默认中英日三语，而且它决定下载什么

`TextMap` 是上游最大的一块，而里面装的是**全部语种**（十几个）。我们只读三种，
所以语种选择同时决定 `snapshot` **下载什么** —— sparse-checkout 按文件挑，
不整目录拉（要用 non-cone 模式，cone 模式只能按目录选）。

```bash
uv run gametext zzz all --langs chs,en,ja   # 默认
uv run gametext zzz all --langs chs         # 只要中文
uv run gametext zzz all --langs chs,en,ja,ko
```

| | TextMap 全量 | 默认三语 | 省 |
| --- | ---: | ---: | ---: |
| genshin | 1235 MB | 219 MB | 82% |
| starrail | 868 MB | 170 MB | 80% |
| zzz | 718 MB | 149 MB | 79% |

基准语种（CHS）**永远在列**，少了它就分不开"上游缺译"和"上游根本没这条"，
报告会把两者混成一个虚高的未解析率。

> **收窄只对下一次取数生效。** 已经拉下来的快照不会自己变小，要重新克隆才收窄——
> 而 `.git` 清理过之后，下次取数本来就是全量重克隆。

### 想更省：`--purge`

```bash
uv run gametext zzz all --purge git     # 跑完整条流水线，然后只删 .git
uv run gametext zzz all --purge all     # 跑完，然后整个 upstream/zzz/ 都删
uv run gametext zzz purge --purge all   # 只做清理这一步
```

| 档位 | 删什么 | 省多少 | 代价 |
| --- | --- | ---: | --- |
| `none`（默认） | 不删 | — | — |
| `git` | 只删 `.git` | 1.62 GB | 解析仍可**离线重跑**；但下次取数是全量重克隆，省不掉增量 |
| `all` | 整个快照目录 | 5.95 GB | 最省；但改了 parser 也得先重新下载才能重跑 |

只有整条流水线跑成功才会清理——失败时留着快照，才好接着查。

**清理不影响可追溯性**：commit 与版本号已经写进 `build/<游戏>/snapshot.json` 和每一条输出，
`--purge git` 之后的离线重跑会沿用那份记录，并在报告里注明"这次没做完整性检查"。

> 这里有个**很隐蔽的坑**，实测踩到过：`.git` 被删之后，`git rev-parse HEAD` 会顺着
> 目录树往上找仓库，一路找到**本项目自己的** git 仓库，把我们的 commit 和日期当成
> 上游的记进每一条输出——而流水线照样退出 0、报告照样是绿的。所以 `snapshot` 里的
> `has_git()` 判断必须做在任何 git 命令之前。

但它确实和"获取与解析分离"这条原则打架（`all` 档之后改 parser 就得重新下载），
所以默认是不删，要不要省磁盘由你定。

## 槽里的快照

槽（`.worktrees/<槽位>/`）里没有被忽略的 `upstream/`、`build/`、`corpus/`。各槽可能要不同的上游版本，快照按槽隔离：给主 checkout 的快照仓库开一个 git worktree，共享对象库、不重新下载。

```bash
git -C <主 checkout>/upstream/<游戏> worktree add --detach <槽的绝对路径>/upstream/<游戏> <commit>
(cd <槽> && uv run gametext <游戏> all --no-fetch)
```

主 checkout 的路径用 `git worktree list` 第一行找。`<槽>` 要写绝对路径：相对路径会按 `-C` 指的快照目录解析，worktree 就落进快照里面去了。`<commit>` 与主 checkout 相同就取 `git -C upstream/<游戏> rev-parse HEAD`，要别的上游版本就取那个版本的 commit（见[跨版本回归](#跨版本回归)里怎么找）。槽里第一次 `uv run` 会给槽建自己的 `.venv`：别拿主 checkout 的 venv 跑槽里的代码，路径会解析回主 checkout。

sparse-checkout 的设置会带过去（实测 git 2.44），工作区与主快照一样只含所选语种。槽里的所有目录都留在本槽，不解析回主 checkout：语料是产物、`upstream/` 会被改写，解析回去会让槽里的运行覆盖主 checkout。

四处要知道：

- 在槽里**带 fetch** 跑，`snapshot` 会在 worktree 快照上 `reset --hard origin/main`，并对共享对象库执行 `gc --prune=now`；只想解析就加 `--no-fetch`。
- `--purge git` 对 worktree 快照不起作用（它的 `.git` 是文件，不是目录）。
- `--purge all` 删掉 worktree 快照后，主快照仓库里留下悬空的 worktree 记录：`git -C upstream/<游戏> worktree prune`。删槽前同理。
- 移动了快照目录（worktree 快照或主快照）之后，git 记的路径就旧了：在主快照仓库里带上 worktree 快照的新路径修一次，`git -C upstream/<游戏> worktree repair <槽的绝对路径>/upstream/<游戏>`；只移了 worktree 快照、主快照没动时，在 worktree 快照里 `git worktree repair` 也行。

### 从按游戏分目录的旧布局搬过来

2026-10 合成一个包之前，每款游戏一个目录，运行时目录是 `<游戏>/upstream`、`<游戏>/build`、`<游戏>/data`。旧 checkout 切到合包后的提交之后，这些被忽略的目录还留在原处，在 checkout 根搬一次：

```bash
mkdir -p upstream build
mv genshin/upstream upstream/genshin && mv genshin/build build/genshin && rm -rf genshin/data   # starrail、zzz 同样
uv run gametext genshin all --no-fetch                                                       # 三款各一次，语料重新出到 corpus/<游戏>/
```

- 用普通移动就行：但切到合包后的提交时，旧的 `genshin/` 等已不被任何 `.gitignore` 挡着：搬完之前别做 `git add -A`、`git clean`、`git stash -u`，它们会收进、删掉或卷走这些目录。`build/` 一起搬、别删：快照被 `--purge git` 清过之后，`build/<游戏>/snapshot.json` 是上游身份的唯一记录。旧的 `data/` 删掉，重跑出来的语料指纹应与搬之前相同。
- 各槽里的 worktree 快照要跟着修，见上面"移动了快照目录"那条。
- Windows 上移不动时，多半是有进程（编辑器、终端、杀毒扫描）开着目录里的文件，先找出来关掉。

## 跨版本回归

什么时候做：改了解析代码（推断、判据、归属）之后，在上一版快照上验它没坏；以及隔一段时间拿明显更旧的版本验一次"认结构不认字段名"。只是升上游版本、代码没改时不用做（同一份代码在旧快照上必然出同一个指纹），看报告即可；与上次发布比分布在 `release` 时做。

做法（改了解析代码时）：

1. 旧上游 commit 取 `releases/<游戏>/fingerprints.tsv` 最后一行（上次发布的那份），或某个版本的数据提交（`git -C upstream/<游戏> log --oneline` 里标题带版本号的那条）。快照是深度 50 的浅克隆，太旧的 commit 不在里面时先 `git -C upstream/<游戏> fetch --depth 200 origin`（取数，只在主 checkout 做）。
2. 按[槽里的快照](#槽里的快照)给那个 commit 开一个 worktree 快照，放在槽里或任意临时目录。
3. 改动前的代码在旧快照上跑一次作基线：`uv run gametext <游戏> all --no-fetch --upstream <旧快照> --out <基线>/<游戏>`（旧代码可以用 `git worktree add` 另开一个 checkout，在那里 `uv run`）。
4. 改动后的代码：`uv run python dev_tools/regress.py <游戏…> --upstream-root <旧快照的上一级> --base-root <基线>`。它并行跑（默认 4 个），指纹不同就逐表列出 `content_sha256` 不同的文件，逐一说清是不是有意的。改的是 `core`，三款都做。`--seeds 1 2`（换两个 `PYTHONHASHSEED`）只在改了"遍历 set / dict 的顺序会影响输出"的代码时加，抓的是 zzz 槽位那类随遍历顺序变的不确定性；平常不用。

下面是 2026-09 做过的一次（代码不改、退回更旧的版本）：

"认结构不认字段名"是本仓库反复讲的设计取向，但一直只在原神上被动验证过一次
（6.6.0→7.0.0 恰好赶上）。所以做了一次主动的：三款各把上游 `git checkout` 到
一个明显更旧的版本，**代码一行不改**重跑。

| 游戏 | 旧版本 | 跨度 | 结果 |
| --- | --- | --- | --- |
| genshin | 6.7.0 | 2 个小版本 / 1.5 个月 | 4177 任务 / 33.4 万对话节点，非预期失败 **0** |
| starrail | 3.8.0 | 7 个小版本 / **8 个月** | 1927 任务 / 8.7 万对话事件，台词覆盖 70.3% |
| zzz | 2.7.0 | 5 个小版本 / **半年** | 2.7 万场景 / 20.1 万台词 / 902 短信组 |

三个都跑通，硬失败全为 0，上游存活检测也都正确报出了"这份快照很旧"。

**绝区零那一轮最有说服力**：它的整套解析建立在推断混淆字段名之上，而两个版本之间
**16 个推断项的字段名一个都没重合**（`PFOAJKNPCHL` → `HHPGHOAKJJO` 等），推断却全部
命中——Perform 主键对场景 id 的覆盖率两版分别是 81.0% 与 81.1%。详见
[zzz 的开发指南](zzz/dev-guide.md#跨版本回归)。

### 它抓到了一个真问题

绝区零有一张桥表在旧版本上**静默消失**了：判据里那条"命中率 ≥ 0.3"的门槛，在
3.2.0 上该字段是 0.32、2.7.0 上是 0.20（命中数一点没少，是分母里的悬空引用变多了）。
报告依然全绿，只是"场景↔任务边"悄悄变成 0。

这条教训比测试结果本身更值钱：**凡是靠阈值分类的地方，都要想一想"版本变化会不会把它
推过线"**；判据尽量并联两条不同量纲的（这里补了绝对命中数）。

### 顺带发现：快照工作区可能不等于它记录的 commit

绝区零的上游 HEAD 里有 21 组只差大小写的同名文件，20 组内容不同。Windows 文件系统
装不下两个，每组只落一个、落哪个不确定。于是"上游版本可追溯"这条原则被悄悄破坏了：
输出里写着 commit X，实际解析的是 X 和别的 commit 的混合。

结论是**只把 commit 写进输出不够**，还得校验工作区确实等于那个 commit。`core.snapshot.check_integrity`
对三款都做这项检测并上报（原神与崩铁的上游各有 0 组冲突），结果进报告的 warnings 与清单的 `integrity_checked`。同名冲突只看 sparse 实际检出的文件：没检出的目录不解析，那里的冲突与产出无关。

## 发布

语料发布与代码发布是两件事，别混；改内容契约时还要多做一步。都在主 checkout 的 `dev` 上做，工作区干净、要发布的分支已合回 `dev`：

- **语料发布**（`release`）：把当前 `corpus/<游戏>/` 的指纹记进 `releases/<游戏>/fingerprints.tsv`，再打包进根 `out/`；同时与同目录的 `profile.json` 比分布、发布后把它更新成这一份的摘要。规则见[指纹表与 rev](architecture.md#指纹表与-rev)与[内容契约](architecture.md#内容契约)。包不公开分发，交给下游的包只从 `release` 出。
  - `release` 拒绝不是当前 HEAD 产的语料（只改了文档也要先重跑 `all`），以及提取代码有未提交改动时产的语料。一次发几款：各款都重跑、都 `release` 完，再把 `releases/` 一起提交（先提交一款，HEAD 就变了，后面几款会被拒）；`release` 只查提取代码的改动，`releases/` 里未提交的改动不碍事。
  - 分布偏移被拦下时，逐条看是不是预期内（上游改版、修了提取缺陷），是就 `release --accept-drift "<为什么>"`；不是就是提取出了问题，先查。
  - 还没有 `profile.json` 时（冷启动），先用当前代码在 `fingerprints.tsv` 最后一行的上游 commit 上跑一次（快照做法见[槽里的快照](#槽里的快照)，`--upstream/--build/--out` 指到临时目录），再 `release --baseline-from <那次的语料目录>`，它只写基线、不发布。
- **改内容契约**：改游戏模块的契约声明，按[内容契约](architecture.md#内容契约)的版本规则决定要不要升主版本；升了就写进 `CHANGELOG.md`，并通知下游（FlowOCR）跟进。
- **代码发布**（`publish.py`）：公开的 `main` 只由 `python dev_tools/publish.py publish` 从 `dev` 生成，每次一个快照提交，剥离私有路径（`docs/plans/` 等，见 `.publish.toml`）。先 `python dev_tools/publish.py check` 预演。`--push` 先推到 `ci-gate` 分支，CI（`.github/workflows/ci.yml`，即 `uv run pytest`）全绿才把同一个提交推上 `main`。发布与 `--push` 都要 owner 明确要求。

## 文档检查

改了文档后、提交前跑（`uv run pytest` 里也有这一项）：

```bash
python dev_tools/check_docs.py --public
```

它查链接与锚点能否落地、公开文档有没有指进私有路径、`docs/plans/` 里的 plan 有没有状态块；只看 git 认得的文件，嵌套的 `upstream/` 快照不在其中。它只证明链接落了地，不证明目标说的就是链接所称的内容。
