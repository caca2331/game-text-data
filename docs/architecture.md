# 架构说明

全仓库的设计取向、代码结构与共同协议。各款游戏怎么解析，见 `docs/<游戏>/architecture.md`。

## 设计取向

本仓库的共同倾向是**离线数据源优先于网页爬虫**：

- 解包数据是完整快照，不存在"漏爬"这个概念；网页抓取只能靠图遍历逼近全集。
- 多语言在上游同一条记录里用同一个 key 索引，天然对齐；分语言抓网页会出现某一语种少几条这种静默缺口。
- 增量更新退化成 `git pull` + diff，而不是重新遍历全站。
- 数据获取与解析分离：先落原始快照，解析随时可重跑，改 parser 不需要重新获取数据。

只有当某款游戏确实没有可用的离线数据源时，才考虑抓站，且必须落原始响应以便重解析。

还有几条是 genshin 做下来才浮现的：

- **解包数据的字段名往往是逐版本变化的混淆串**（原神实测五个版本无一重合），所以解析要
  认结构不认字段名；而推断能力一强，就要防"成功地解析出垃圾"——那比解析失败危险，因为
  报告是绿的。
- **上游会搬家，而且不会通知你。** 原神的上游因仓库体积超限被弃用，README 只剩一行指向
  继任者，我们照旧 pull 了三个月才发现，还误以为是上游停更。每款游戏都要有上游存活
  检测（README 迁移标记 + 数据提交年龄）。
- **同一个游戏的 TextMap 往往不止一张表**（原神 plain/Medium、崩铁 TextMap/TextMapMain、
  绝区零 Template/Overwrite）。合并规则要先核实是并集还是覆盖，搞错会静默丢文本或拿到旧文本。
- **靠阈值分类的判据会被版本变化打穿。** 绝区零实测：同一个字段的命中率从 0.32 掉到
  0.20，判据门槛 0.3，于是整张桥表在旧版本上静默消失而报告全绿。判据要并联两条不同
  量纲的（比率 + 绝对数），并且**定期拿旧版本回归一次**——见开发指南的[跨版本回归](dev-guide.md#跨版本回归)。

### 三款数据的形态差异

同一个作者维护的三份数据，形态完全不同——这也是解析层各写各的实证依据：

| | 原神 | 崩铁 | 绝区零 |
| --- | --- | --- | --- |
| 顶层目录 | `BinOutput` / `ExcelBinOutput` / `TextMap` | `Config` / `ExcelOutput` / `Story` / `TextMap` | `Data` / `FileCfg` / `TextMap` |
| 字段名 | 混淆，逐版本全变 | **明文**，带 `$type` | 混淆 |
| 文件名 | 明文目录 | 明文 | 大多明文（1499/1721），222 个 hash |
| TextMap key | 32 位数字 hash | 64 位数字 hash | **明文路径字符串** |
| 解析难度 | 中 | 低 | 中 |

原神的核心是 510 行结构推断，**崩铁完全用不上**；绝区零的剧情文本直接从 TextMap
就能取，配置表的混淆字段则靠"取值命中 TextMap 明文 key"反推身份——判据比原神的数字
hash 多一层语义。三款共用的是协议与通用机制，见[代码结构](#代码结构core-与游戏模块)。

## 代码结构：core 与游戏模块

一个包 `gametext`（`src/gametext/`）。`core` 提供机制，游戏模块给参数；游戏模块之间不 import，`core` 也不 import
游戏模块（CLI 按名字加载 `gametext.<游戏>.GAME`）。

| `core` 里的 | 游戏模块给的 |
| --- | --- |
| `snapshot`：稀疏浅克隆、增量取数、purge、origin 判定与重建、找不到版本号时加深历史、快照完整性检查、上游存活检测 | `__init__.py` 里的 `Upstream`：仓库地址与分支、sparse 目录、TextMap 文件规则、版本号正则、存活阈值、"本仓库"与"已废弃"两个地址列表 |
| `contract`：字段声明的写法、逐行检查、分布摘要与偏移比较 | `contract.py`：各表的字段声明 |
| `bundle`：清单、产物包、`release` 与指纹表 | 游戏名、标题、产物表 |
| `report`：提取代码版本、契约检查结果怎么进报告 | `report.py`：判据、阈值、摘要 |
| `cli`：参数与 `all` / `purge` / `manifest` / `bundle` / `release` 的调度；`jsonl`：产物读写 | 自己的阶段（genshin、starrail 有 `assemble`，zzz 没有）与 `emit` |

origin 判定：读不到、或在"已废弃"列表里 → 重建；"本仓库"列表非空而一个都不匹配 → 重建；其余接受。genshin 的"本仓库"列表是空的，
只列旧地址（含 GitHub 镜像：它的 master 是旧仓库的残留）。

`report.json` 的 `extractor.dirty` 只看会影响这款游戏产出的文件：`core/`、这款游戏的模块、`paths.py`、包的 `__init__.py`、
`pyproject.toml`、`uv.lock`；别的游戏的模块有改动不算。所有目录只从 `gametext.paths` 解析，一律相对本 checkout 的根。

## 产物格式：JSONL + zstd

```bash
uv run gametext zzz all --compress zstd   # 默认
uv run gametext zzz all --compress none   # 出原始 .jsonl
```

产物是 **JSONL**（UTF-8，一行一个 JSON 对象，中文不转义）。压缩后是 `*.jsonl.zst`：

| | 四语未压 | 三语 + zstd |
| --- | ---: | ---: |
| genshin | 391 MB | **41 MB** |
| starrail | 234 MB | **21 MB** |
| zzz | 227 MB | **28 MB** |
| **合计** | **852 MB** | **90 MB** |

三个选择的依据都是实测，不是拍脑袋：

- **level 3**：851 MB 压到 118 MB（14%）。`-1` 是 16%、`-9` 是 12% 但慢四倍，
  `gzip -1` 比 `zstd -3` 又大又慢。
- **语料目录里分文件压**：整包 `tar.zst` 反而比逐文件压**大 0.22%**（tar 头和对齐的
  开销超过了跨文件共享上下文的收益），而逐文件保留了"只读某个语种"的随机访问。
  搬运用的包是另一层投影，见[产物包协议](#产物包协议gtd-bundle1)。
- **读端透明**：一律走 `gametext.core.jsonl.open_read`，它先找 `.zst`、再找原始文件。
  切换形态时会删掉另一种形态的旧产物，否则下游会读到**上一次跑的结果**还看不出来。

## 产物包协议（gtd-bundle/1）

产物本身不公开分发，但要方便私下传：每款游戏把语料目录 `corpus/<游戏>/` 打成**一个自描述的包**，放进仓库根的 `out/`：

```bash
uv run gametext genshin bundle      # -> out/genshin-7.1.0-<指纹前 12 位>.zip
uv run gametext genshin release     # 发布：先记进 releases/genshin/fingerprints.tsv，再打包（见下面的「指纹表与 rev」）
```

协议叫 `gtd-bundle/1`，实现在 `gametext.core.bundle`，约定如下：

- **清单** `corpus/<游戏>/manifest.json`：`emit` 结束时写，`manifest` 子命令只从现有语料重算（不碰上游、不重跑取数）。
  字段：`schema`、`game`（= 游戏名）、`title`、`fingerprint`、`rev`（见[指纹表与 rev](#指纹表与-rev)）、`upstream`（repo / commit / commit_date / version /
  version_subject / `integrity_checked`）、`extractor`（`subproject` = 游戏名、git_head、dirty；键名 `subproject` 有意保留，FlowOCR 把整个 `extractor` 抄进出处记录）、`langs`（BCP-47 → 文件后缀，
  文件名照上游叫法不改，`ja` 在原神 / 星铁是 `jp`）、`base_lang`、`tables`（每张表的行数与[内容契约](#内容契约)版本，如 `{"rows": 12703, "contract": "genshin.reminders/1"}`）、`files`（语料目录下除清单外的全部文件）。
- **两种哈希**：每个文件的 `sha256` 按存储字节算，管传输完整性；数据文件另有 `content_sha256`，按解压后的 JSONL 算，管内容身份。
- **指纹** = `sha256` over 按 `(table, lang)` 排序的 `"<table>\t<lang>\t<content_sha256>\n"` 串接：只看内容，
  换压缩档位、改文件名、`report.json` 多一条警告都不改变它。它回答"是不是同一份语料"。
- **生成时核**：各语种行数一致、和 `report.json` 的计数一致；语料目录里有不认识的文件或残留的旧语种就拒绝出清单。
- **包**：`<game>/` 下放清单、`report.json`、数据文件与 `NOTICE.txt`（版权归属与"不得公开再分发"）。
  成员不压缩（本来就是 zstd），成员排序、时间戳与属性固定——同一份语料两次打包逐字节相同。
  打新包时删掉同一游戏的旧包（`out/` 是语料目录的投影，旧包留着会被下游当成候选）。
- 包自带的哈希只证明"包和它自己的清单一致"，防的是拷坏和版本对不上；改了内容再重算一份清单，它查不出。
  要确认"这是维护者发出的那份"，拿指纹去对[指纹表](#指纹表与-rev)。

### 指纹表与 `rev`

`releases/<游戏>/fingerprints.tsv`（追踪、随公开仓库发布）一行一份**发布过的**语料：
`rev`、上游版本、上游 commit、语种（BCP-47，逗号分隔）、完整指纹、发布日期、说明。拿到包的人看清单里的 `fingerprint`，
在表里找得到，就是维护者发出的那份；表里那一行同时说明它出自哪份上游、哪一版提取行为。

- **`rev` 是提取行为的版本，不是代码的版本**：同一份上游、同一组语种、同一个 `rev` → 同一个指纹。
  改文档、改注释、重构、改报告字段都不改变产出，`rev` 就不动；提取代码的 commit 照旧记在清单与 `report.json` 里，给维护者追溯。
  实测：三款同一份上游、换一版提取代码（只差注释、清单与报告字段）重跑，指纹都与原来相同。
- **只在发布时按需递增**：`release` 默认沿用上次发布的 `rev`；产出确实变了才 `release --bump --note "<为什么>"`。
  核对只靠表：同一份上游、同一组语种、同一个 `rev` 已发布过别的指纹就拒绝（该加 `rev` 没加，或提取不确定）；
  上游也换了的那次判不出产出变没变，由维护者判断，必要时拿旧上游重跑一次。提取代码有未提交改动、或语料不是当前 HEAD 的代码产的（清单的 `extractor.git_head`），都不许发布。
- **本地迭代的包**不进表，清单里的 `rev` 标成 `<上次发布的 rev>+<指纹前 8 位>`（如 `1+0a1b2c3d`）：
  不用手动计数，指纹前缀天然唯一；发布过的语料 `rev` 是整数。
- 表里不记包本身的 `sha256`：包里的 `report.json` 与清单记着提取代码的 commit，换个 commit 重新打包，包的哈希会变、指纹不变。

### 内容契约

包封只说包里有哪些文件、哈希怎么算；**内容契约**说每张表的每个字段是什么：类型、能不能为 null（能的话 null 是什么意思）、取值范围（封闭枚举 / 开放枚举 / 自由）、含义，以及表级不变量（各语种行数与逐行 id 相同、`id` 是否唯一）。下游据它写代码，产出方据它自查。

- **唯一来源是各游戏模块 `contract.py` 里的声明**（如 `src/gametext/genshin/contract.py`），检查机制在 `gametext.core.contract`。人和下游直接读声明，各游戏的使用说明链接过去，不另抄字段表。
- **逐行检查**：`emit` 写每一行前按声明检查。类型不符、"从不为 null"的字段出现 null、封闭枚举外的值、没声明的键、缺键，都是硬失败，`bundle` 拒绝出包；开放枚举出现新值只告警（确认含义后加进声明）。清单里的契约版本取自 `report.json` 里那次实际做过的检查，与当前代码的版本不一致（语料是旧代码产的、或之后改了契约）就不出清单。
- **版本**：清单里每张表带 `<游戏>.<表>/<主版本>`。删字段、改名、改类型、改含义、"从不"为 null 的字段变得可为 null、封闭枚举加值、表级不变量变化 → 主版本 +1，写进 `CHANGELOG.md` 并通知下游；加可选字段、加表、开放枚举出现新值不改版本。没有次版本。下游见到不认识的主版本就拒绝。
- **与 `rev` 各管各的**：`rev` 管"同一上游出同一份内容"，契约版本管"字段是什么意思"。只改契约、内容不变的两份包指纹相同，区别只在清单的 `contract`。
- **与上次发布比分布**：取值合法的漂移（如某个枚举字段整列从一个值变成另一个合法值、可为 null 的字段整列变 null、一张表少了一大截行）逐行检查抓不到。所以 `emit` 按"表 × 语种"记一份分布摘要（行数、嵌套列表的元素数、各字段 null 率、枚举取值占比）写进 `report.json`；`release` 拿它和 `releases/<游戏>/profile.json`（上次发布的摘要，追踪）比：任一 null 率或枚举占比变化超过 5 个百分点、或行数 / 元素数相对变化超过 10%，或某张表、某个语种只在一边出现，就要 `--accept-drift "<为什么>"`，理由记进指纹表的说明列。本地 `all` / `bundle` 不比，所以交给下游的包只从 `release` 出。

## 备选路线：自己解包（记录在案，暂不实施）

三个游戏目前都依赖 Dimbreath 一个人维护的解包数据。若上游全部失效，自解包的链路是：

```
游戏安装目录 → StreamingAssets/AssetBundles/blocks/*.blk（加密）
  → 解密（mhy0 格式，密钥可能逐版本变）
  → Unity AssetBundle → AssetStudio / Escartem/AnimeStudio / UnityPy
  → TextAsset（TextMap、JSON 配置）、MonoBehaviour（需 il2cpp typetree）
```

最活跃的工具是 [Escartem/AnimeStudio](https://github.com/Escartem/AnimeStudio)（AssetStudio
的 fork，明确支持米哈游系加密）。

**暂不实施**，理由：三个上游当前都活跃（崩铁、绝区零甚至每天更新）；成本高一个数量级
（要装并持续更新几十 GB 游戏本体、跟进每版本加密变化、提 il2cpp typetree），本质是重做
Dimbreath 在做的整件事。真要做，第一步是拿一个已有安装验证 blk 解密能跑通——那是可行性
的分水岭。以上链路**未经实测**。
