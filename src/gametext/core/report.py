"""完整性报告的公共部分：提取代码版本、契约检查结果怎么进报告。

各游戏的 `report.py` 组装自己的报告（判据、阈值、摘要各不相同），用这里的几块拼。
产出必须自带完整性报告（根 AGENTS.md 取数原则 4）；`hard_failures` 非空时 CLI 以
非零退出码结束 —— 静默的数据缺口是本仓库最主要的失败模式，宁可让流水线红掉。
"""

from __future__ import annotations

import subprocess

from .. import paths


def extractor_version(game: str) -> dict:
    """产出这份数据的**提取代码**是哪一版：本仓库 HEAD + 有没有未提交改动。

    `upstream` 只说明取的是哪份上游数据，说明不了是哪版代码取的——同一份上游，
    zzz 改一处槽位逻辑台词就差了 219 条，而产物和报告里都没有痕迹。
    `dirty` 只看会影响这款游戏产出的文件：`core/`、这款游戏的模块、`paths.py`、包的
    `__init__.py`、`pyproject.toml` 与 `uv.lock`（依赖版本也会改变产出）；别的游戏的模块有改动不算。
    已跟踪文件的改动之外**也算没跟踪的新文件**——新加一个源文件还没 `git add` 就跑，产物同样
    不是 HEAD 那版代码产的（下游项目的一次审计查出来的）；`__pycache__` 已被 .gitignore 挡掉。"""
    scope = ["src/gametext/core", "src/gametext/" + game, "src/gametext/paths.py",
             "src/gametext/__init__.py", "pyproject.toml", "uv.lock"]
    try:
        def git(*args):
            return subprocess.run(["git", *args], cwd=paths.ROOT, check=True, text=True,
                                  capture_output=True).stdout.strip()
        return {"git_head": git("rev-parse", "HEAD"),
                "dirty": bool(git("status", "--porcelain", "--untracked-files=normal", "--", *scope))}
    except Exception as exc:  # 不在 git 仓库里（被拷走了）也照样出报告，只是记不上
        return {"git_head": None, "error": str(exc)}


def contract_findings(contracts, checked: dict, base_lang: str):
    """emit 的契约检查摘要（{表: {语种: Checker.summary()}}）→ (硬失败, 告警)。

    违反是硬失败（下游据契约读，越界的值会被悄悄归错类）；开放枚举的新值只告警。
    新值各语种一样（枚举不随语种变），只报基准语种那份。"""
    hard, warnings = [], []
    for table, per in checked.items():
        label = contracts.label(table)
        for lang, s in per.items():
            for what, n in s["violations"].items():
                hard.append("契约 %s（%s）：%s，%d 处，例 %s"
                            % (label, lang, what, n, s["violation_samples"][what]))
        for path, vals in (per.get(base_lang) or {}).get("new_values", {}).items():
            warnings.append("契约 %s 的开放枚举 %s 出现新值：%s（确认含义后加进 contract.py）"
                            % (label, path, vals))
    return hard, warnings


def contract_section(contracts, checked: dict) -> dict:
    """report.json 的 `contract` 一节：每张表的契约版本与各语种的检查摘要。"""
    return {t: {"label": contracts.label(t), "langs": per} for t, per in checked.items()}


def contract_line(report: dict) -> str:
    con = report.get("contract") or {}
    return ("  内容契约: %s；违反 %d 处"
            % ("、".join(c["label"] for c in con.values()) or "未检查",
               sum(n for c in con.values() for s in c["langs"].values() for n in s["violations"].values())))
