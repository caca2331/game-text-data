"""崩坏：星穹铁道：从 Dimbreath/turnbasedgamedata 提取任务、任务外对话、短信、全量台词表与短名词。
不变量见同目录 AGENTS.md。

    snapshot → upstream/starrail ─index→ build/starrail/index ─assemble→ build/starrail/assembled*.jsonl
    （文本仍是 hash） ─emit→ corpus/starrail
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

UPSTREAM = Upstream(
    repo="https://gitlab.com/Dimbreath/turnbasedgamedata.git",
    branch="main",
    # **Config/Level 是对话引用的主体**，不能省：P0 摸底时只取 ExcelOutput/Story/TextMap，
    # 结果 24 万条台词里只有 6.6% 找得到引用；把 Config/Level 加进来之后升到 65%
    # （Config/Level/Mission 一处就贡献 14 万条）。
    # 只取 Config/Level 而非整个 Config：整个 Config 会让快照从 1.5 GB 涨到 2.9 GB，
    # 而其余子目录实测几乎不含台词引用。
    always=("/ExcelOutput/", "/Story/", "/Config/Level/", "/README.md"),
    textmap_patterns=textmap.sparse_patterns,
    # 提交标题形如 OSPRODWin4.5.0_D16445860_A16307208_L16320302
    version_re=re.compile(r"[A-Z]+Win(\d+\.\d+\.\d+)"),
    # 崩铁上游是几天一更，比原神勤得多，所以阈值也收紧
    stale_days=40,
    own_repos=("gitlab.com/Dimbreath/turnbasedgamedata",),
)


def _index(args):
    ix = Indexer(args.upstream, args.build)
    ids = ix.index_sentences()
    ix.index_missions(ids)
    ix.index_textjoin()
    ix.index_dialogues(ids)
    ix.index_messages()
    ix.dump_dangling(ids)
    ix.coverage(ids)
    return ix.finish()


def _assemble(args):
    asm = Assembler(args.upstream, args.build)
    for name, path in asm.run().items():
        print("写出 %-10s %s" % (name, path))
    return dict(asm.stats)


def _emit(args, snapshot, stats):
    result = Emitter(args.upstream, args.build, args.out, snapshot, compress=args.compress).run()
    return report.build(snapshot, stats["index"], stats["assemble"], result,
                        os.path.join(args.out, "report.json"))


GAME = Game(
    name="starrail",
    title={"zh-Hans": "崩坏：星穹铁道", "en": "Honkai: Star Rail", "ja": "崩壊：スターレイル"},
    upstream=UPSTREAM,
    textmap=textmap,
    contracts=CONTRACTS,
    outputs=OUTPUTS,
    stages=(("index", _index), ("assemble", _assemble)),
    emit=_emit,
    summarize=report.summarize,
)
