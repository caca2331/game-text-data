"""原神：从 Dimbreath/animegamedata2 提取任务、语音字幕与短名词。不变量见同目录 AGENTS.md。

    snapshot → upstream/genshin ─index→ build/genshin/index ─assemble→ build/genshin/assembled.jsonl
    （文本仍是 hash） ─emit→ corpus/genshin
"""

from __future__ import annotations

import os
import re

from ..core.game import Game
from ..core.snapshot import Upstream
from . import report, textmap
from .assemble import Assembler
from .contract import CONTRACTS
from .emit import OUTPUTS, Emitter
from .index import Indexer

# 上游在 2026-06-29 搬过一次家：原 Dimbreath/AnimeGameData 因仓库体积超限被弃用，
# 其 README 只剩一行指向 animegamedata2。旧仓库停在 6.6.0，新仓库已到 7.0.0。
# GitHub 的 DimbreathBot/AnimeGameData 是同一份数据的镜像（commit sha 一致），
# 其 master 分支是旧仓库的残留、main 分支才是新的 —— 别追错分支。
# 不列"本仓库"地址，只列旧地址：镜像的 master 是旧仓库的残留，所以镜像 origin 按旧仓库处理、重建；
# 指向 animegamedata2 才增量更新。
UPSTREAM = Upstream(
    repo="https://gitlab.com/Dimbreath/animegamedata2.git",
    branch="main",
    # 只取用得上的目录。全量克隆包含 Ability/Scene 等大量无关数据，没必要。
    always=("/ExcelBinOutput/", "/BinOutput/Talk/", "/BinOutput/Quest/", "/BinOutput/CodexQuest/",
            "/README.md"),
    textmap_patterns=textmap.sparse_patterns,
    # 提交标题形如 CNRELWin6.6.0_R44873995_S44916582_D44916582
    version_re=re.compile(r"[A-Z]+Win(\d+\.\d+\.\d+)"),
    # 数据提交的间隔常态是 1–2 个月
    stale_days=75,
    legacy_repos=("gitlab.com/Dimbreath/AnimeGameData", "github.com/DimbreathBot/AnimeGameData"),
)


def _index(args):
    ix = Indexer(args.upstream, args.build)
    talk_ids = ix.index_talks()
    ix.index_quests(talk_ids)
    ix.index_reminders()
    return ix.finish()


def _assemble(args):
    asm = Assembler(args.upstream, args.build)
    print("写出", asm.run())
    return dict(asm.stats)


def _emit(args, snapshot, stats):
    result = Emitter(args.upstream, args.build, args.out, snapshot, compress=args.compress).run()
    return report.build(snapshot, stats["index"], stats["assemble"], result,
                        os.path.join(args.out, "report.json"))


GAME = Game(
    name="genshin",
    title={"zh-Hans": "原神", "en": "Genshin Impact", "ja": "原神"},
    upstream=UPSTREAM,
    textmap=textmap,
    contracts=CONTRACTS,
    outputs=OUTPUTS,
    stages=(("index", _index), ("assemble", _assemble)),
    emit=_emit,
    summarize=report.summarize,
    rows_key={"quests": "rows"},
)
