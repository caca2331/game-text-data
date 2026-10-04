"""绝区零：从 dimbreath/ZenlessData（Gitea）提取剧情场景、任务、短信、散落文本与短名词。
不变量见同目录 AGENTS.md。

    snapshot → upstream/zzz ─index→ build/zzz/index ─emit→ corpus/zzz

没有独立的 assemble 阶段：中间层已经是"场景 + 文本 key"，emit 直接展开即可。
"""

from __future__ import annotations

import os
import re

from ..core.game import Game
from ..core.snapshot import Upstream
from . import report, textmap
from .contract import CONTRACTS
from .emit import OUTPUTS, Emitter
from .index import Indexer

# 托管在作者自建的 **Gitea**（`git.mero.moe`），不是 GitHub/GitLab：GitHub 上的
# `Dimbreath/ZenlessData` 返回 `Repository access blocked`。HTTP API / raw 对**默认 UA
# 返回 403**，必须带浏览器 UA；`git clone` 不受影响。
UPSTREAM = Upstream(
    repo="https://git.mero.moe/dimbreath/ZenlessData.git",
    branch="master",
    # TextMap 给剧情文本本身；FileCfg 给"对话属于哪个任务""选项跳到哪"这类结构。
    # FileCfg 是混淆的配置表（文件名 hash、字段名混淆），解析方式见 tables.py。
    always=("/FileCfg/", "/README.md"),
    textmap_patterns=textmap.sparse_patterns,
    # 提交标题形如 CNPRODWin3.2.0_R18779629_S18779629_D18761130
    version_re=re.compile(r"[A-Z]+Win(\d+\.\d+\.\d+)"),
    # 绝区零上游是天级更新，阈值比崩铁再紧一点；它托管在个人 Gitea、GitHub 那份已被封，停更风险要认真对待
    stale_days=30,
    own_repos=("ZenlessData",),
)


def _index(args):
    ix = Indexer(args.upstream, args.build)
    ix.run()
    return ix.finish()


def _emit(args, snapshot, stats):
    result = Emitter(args.upstream, args.build, args.out, snapshot, compress=args.compress).run()
    return report.build(snapshot, stats["index"], result, os.path.join(args.out, "report.json"))


GAME = Game(
    name="zzz",
    title={"zh-Hans": "绝区零", "en": "Zenless Zone Zero", "ja": "ゼンレスゾーンゼロ"},
    upstream=UPSTREAM,
    textmap=textmap,
    contracts=CONTRACTS,
    outputs=OUTPUTS,
    stages=(("index", _index),),
    emit=_emit,
    summarize=report.summarize,
)
