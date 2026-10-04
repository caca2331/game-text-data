"""一款游戏交给 core 的全部参数。每个游戏模块在自己的 `__init__.py` 里定义 `GAME = Game(...)`，
CLI 按名字加载它；core 不 import 任何游戏模块。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import ModuleType
from typing import Callable

from .contract import Contracts
from .snapshot import Upstream


@dataclass(frozen=True)
class Game:
    name: str
    """目录名、命令里的游戏名、清单的 `game`、契约版本的前缀。"""
    title: dict
    """清单的 `title`：{BCP-47: 游戏名}，至少有 zh-Hans 与 en。"""
    upstream: Upstream
    textmap: ModuleType
    """这款游戏的 TextMap 模块：`LANGS`（默认语种，CLI 按 `--langs` 改写，各阶段都读它）、
    `ALL_LANGS`（上游提供的语种）、`BASE_LANG`（基准语种，永远在列、排第一）。"""
    contracts: Contracts
    outputs: tuple
    """产物表，按这个顺序写清单。"""
    stages: tuple
    """snapshot 与 emit 之间的阶段：((名, fn(args) -> 统计 dict), ...)。统计写成 `build/<游戏>/<名>_stats.json`。"""
    emit: Callable
    """fn(args, snapshot, stats) -> report：写出语料与 report.json。`stats` 是 {阶段名: 统计}。"""
    summarize: Callable
    """report -> 打印给人看的摘要。"""
    rows_key: dict = field(default_factory=dict)
    """表 -> report.json 的 `per_lang` 里记这张表行数的键；默认 `<表>_rows`。"""
