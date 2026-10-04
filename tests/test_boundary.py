"""import 边界：游戏模块之间不 import，core 不 import 任何游戏模块（根 AGENTS.md 护栏第一条）。"""

import ast
import pathlib

import pytest

from gametext.core import cli

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "gametext"


def imported(path):
    """这个文件 import 的 gametext 下的顶层模块名（相对 import 按所在包解析）。"""
    here = path.relative_to(PKG).parts[:-1]
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(here[:len(here) - node.level + 1])
                mod = base + (node.module.split(".") if node.module else [])
                names = [".".join(["gametext"] + mod + [a.name]) if not mod else ".".join(["gametext"] + mod)
                         for a in node.names]
            else:
                names = [node.module]
        else:
            continue
        for n in names:
            parts = n.split(".")
            if parts[0] == "gametext" and len(parts) > 1:
                out.add(parts[1])
    return out


@pytest.mark.parametrize("game", cli.GAMES)
def test_game_imports_only_core(game):
    others = set(cli.GAMES) - {game}
    for path in (PKG / game).rglob("*.py"):
        assert not imported(path) & others, path


def test_core_imports_no_game():
    for path in (PKG / "core").rglob("*.py"):
        assert not imported(path) & set(cli.GAMES), path


@pytest.mark.parametrize("game", cli.GAMES)
def test_every_game_loads(game):
    g = cli.load(game)
    assert g.name == game
    assert set(g.outputs) == set(g.contracts)
