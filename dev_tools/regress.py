"""回归：用当前代码离线重跑几款游戏，内容指纹与现有语料比。

    uv run python dev_tools/regress.py                          # 三款，与 corpus/<游戏>/ 比
    uv run python dev_tools/regress.py zzz --seeds 1 2          # 换两个 PYTHONHASHSEED 各跑一次
    uv run python dev_tools/regress.py --upstream-root <目录>   # 用别的快照（<目录>/<游戏>），比如旧版本

各次运行并行（`-j`，默认 4），输出在 `build/regress/<游戏>-<种子>/`（被忽略，可删），不碰 `corpus/`。
指纹不同就逐表列出 `content_sha256` 不同的文件。退出码：0 全部相同，1 有不同或有运行失败。
基线语料（默认 `corpus/<游戏>/`）要先用改动前的代码跑出来。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMES = ("genshin", "starrail", "zzz")


def run(game, seed, upstream_root):
    out = os.path.join(ROOT, "build", "regress", "%s-%s" % (game, seed or "default"))
    os.makedirs(out, exist_ok=True)
    cmd = [sys.executable, "-m", "gametext.core.cli", game, "all", "--no-fetch",
           "--build", os.path.join(out, "build"), "--out", os.path.join(out, "corpus")]
    if upstream_root:
        cmd += ["--upstream", os.path.join(upstream_root, game)]
    env = dict(os.environ)
    if seed:
        env["PYTHONHASHSEED"] = str(seed)
    with open(os.path.join(out, "run.log"), "w", encoding="utf-8") as log:
        code = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    return game, seed, code, os.path.join(out, "corpus")


def manifest(corpus):
    path = os.path.join(corpus, "manifest.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def compare(base, new):
    """不同的地方，一条一句；相同返回空列表。"""
    if base["fingerprint"] == new["fingerprint"]:
        return []
    files = lambda m: {(f["table"], f["lang"]): f for f in m["files"] if "table" in f}  # noqa: E731
    b, n = files(base), files(new)
    out = []
    for key in sorted(set(b) | set(n)):
        x, y = b.get(key), n.get(key)
        if x is None or y is None:
            out.append("%s × %s 只在%s里有" % (key[0], key[1], "新的" if x is None else "基线"))
        elif x["content_sha256"] != y["content_sha256"]:
            out.append("%s × %s 内容不同（行数 %d → %d）" % (key[0], key[1], x["rows"], y["rows"]))
    return out or ["指纹不同，但逐文件的 content_sha256 都相同（表或语种集合不同？）"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="用当前代码离线重跑，内容指纹与现有语料比")
    ap.add_argument("games", nargs="*", default=list(GAMES), help="默认三款都跑")
    ap.add_argument("--seeds", nargs="*", default=[None], help="PYTHONHASHSEED，给几个就每款各跑几次")
    ap.add_argument("--upstream-root", help="快照根目录（其下 <游戏>/），默认 upstream/")
    ap.add_argument("--base-root", default=os.path.join(ROOT, "corpus"), help="基线语料根目录（其下 <游戏>/），默认 corpus/")
    ap.add_argument("-j", type=int, default=4, help="同时跑几个（默认 4）")
    args = ap.parse_args(argv)
    bad = [g for g in args.games if g not in GAMES]
    if bad:
        ap.error("不认识的游戏 %s" % bad)

    jobs = [(g, s) for g in args.games for s in args.seeds]
    with ThreadPoolExecutor(max_workers=max(1, args.j)) as pool:
        results = list(pool.map(lambda job: run(job[0], job[1], args.upstream_root), jobs))

    ok = True
    for game, seed, code, corpus in results:
        label = "%s（种子 %s）" % (game, seed or "默认")
        if code:
            ok = False
            print("%s 运行失败（退出码 %d），见 %s" % (label, code, os.path.join(os.path.dirname(corpus), "run.log")))
            continue
        base = manifest(os.path.join(args.base_root, game))
        new = manifest(corpus)
        if base is None:
            ok = False
            print("%s 没有基线：%s 下没有 manifest.json" % (label, os.path.join(args.base_root, game)))
            continue
        diffs = compare(base, new)
        print("%s %s %s" % (label, "相同" if not diffs else "不同", new["fingerprint"][:19]))
        for d in diffs:
            print("    " + d)
        ok &= not diffs
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
