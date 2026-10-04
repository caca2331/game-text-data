"""所有目录的唯一解析入口：一律相对本 checkout 的根。

worktree 槽各有一套，互不解析到别的 checkout（`upstream/` 会被 snapshot 改写，语料是产物）。
"""

from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if not os.path.exists(os.path.join(ROOT, "pyproject.toml")):
    # 目录都按源码位置推：只有 editable 安装（uv 的默认）才落在本 checkout 里
    raise ImportError("gametext 要从源码 checkout 以 editable 方式安装（uv sync），推出的根 %s 不是 checkout" % ROOT)
OUT = os.path.join(ROOT, "out")
"""产物包 zip（所有游戏共用；下游 FlowOCR 从这里找包）。"""


def upstream(game: str) -> str:
    """上游快照：一个嵌套的 git 仓库（或它的 worktree），snapshot 会改写它。"""
    return os.path.join(ROOT, "upstream", game)


def build(game: str) -> str:
    """中间产物，可整目录删；例外：快照被 `--purge git` 清过之后，`snapshot.json` 是上游身份的唯一记录。"""
    return os.path.join(ROOT, "build", game)


def corpus(game: str) -> str:
    """语料 + `manifest.json` + `report.json`。"""
    return os.path.join(ROOT, "corpus", game)


def releases(game: str) -> str:
    """发布记录（追踪、公开）：`fingerprints.tsv` 与分布基线 `profile.json`。"""
    return os.path.join(ROOT, "releases", game)
