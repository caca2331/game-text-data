"""命令入口：`gametext <游戏> <阶段> [选项]`。只做参数解析与阶段调度，不含解析逻辑。

    gametext genshin all [--no-fetch]                # snapshot → 各解析阶段 → emit（含清单）
    gametext genshin index                           # 单独重跑某一阶段
    gametext genshin manifest | bundle               # 产物包（gtd-bundle/1，见 core/bundle.py）
    gametext genshin release [--bump --note 原因]    # 发布：记进 releases/<游戏>/fingerprints.tsv 再打包

各阶段读写的目录默认是 `upstream/<游戏>/`、`build/<游戏>/`、`corpus/<游戏>/`（见 `gametext.paths`）。
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time

from .. import paths
from . import bundle as bundle_mod
from . import snapshot as snapshot_mod

GAMES = ("genshin", "starrail", "zzz")


def load(name: str):
    """游戏模块按名字加载：core 不 import 任何游戏模块。"""
    return importlib.import_module("gametext." + name).GAME


def resolve_langs(textmap, spec):
    """把 `--langs chs,en,jp` 解析成规范化的语种元组。基准语种永远排第一位并强制在列——
    少了它，"缺译"和"上游没有"就分不开，报告会把两者混成一个虚高的未解析率。"""
    if not spec:
        return textmap.LANGS
    want = [x.strip().upper() for x in spec.split(",") if x.strip()]
    bad = [x for x in want if x not in textmap.ALL_LANGS]
    if bad:
        raise SystemExit("不认识的语种 %s；上游提供的是：%s"
                         % ("、".join(bad), "、".join(textmap.ALL_LANGS)))
    return tuple([textmap.BASE_LANG] + [x for x in want if x != textmap.BASE_LANG])


def _read_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _print_stats(stats):
    for k in sorted(stats):
        v = stats[k]
        if isinstance(v, dict):
            print("  %s:" % k)
            for kk, vv in list(v.items())[:8]:
                print("      %-30s %s" % (kk, vv))
        else:
            print("  %-32s %s" % (k, v))


def cmd_snapshot(game, args):
    info = snapshot_mod.run(game.upstream, args.upstream, args.build, game.textmap.LANGS,
                            fetch=not args.no_fetch)
    print("上游 %s @ %s (%s)" % (info["version"], info["commit"][:10], info["commit_date"]))
    return 0


def _stage(name, fn):
    def run(game, args):
        stats = fn(args)
        os.makedirs(args.build, exist_ok=True)
        with open(os.path.join(args.build, "%s_stats.json" % name), "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        _print_stats(stats)
        return 0
    return run


def cmd_emit(game, args):
    snap = _read_json(os.path.join(args.build, "snapshot.json"))
    bundle_mod.remove_manifest(args.out)
    stats = {name: _read_json(os.path.join(args.build, "%s_stats.json" % name))
             for name, _ in game.stages}
    rep = game.emit(args, snap, stats)
    print(game.summarize(rep))
    if rep["hard_failures"]:
        return 1
    return cmd_manifest(game, args)


def cmd_manifest(game, args):
    """只从现有语料目录算清单，不重跑 emit。"""
    try:
        m = bundle_mod.write_manifest(game, args.out)
    except bundle_mod.BundleError as e:
        print("出不了清单：%s" % e)
        return 1
    print("清单 %s（%s）" % (os.path.join(args.out, bundle_mod.MANIFEST), m["fingerprint"]))
    return 0


def cmd_bundle(game, args):
    """重算清单并打包进仓库根的 out/（默认；--bundle-dir 可改）。"""
    try:
        path = bundle_mod.bundle(game, args.out, args.bundle_dir)
    except bundle_mod.BundleError as e:
        print("打不了包：%s" % e)
        return 1
    print("包 %s\n  sha256 %s" % (os.path.normpath(path), bundle_mod.sha256_of(path)))
    return 0


def cmd_release(game, args):
    """发布：把语料记进指纹表，再打包。`rev` 只在这里按需递增（--bump）。"""
    try:
        if args.baseline_from:
            path = bundle_mod.profile_path(game)
            prof = bundle_mod.write_profile(args.baseline_from, path)
            print("分布基线 %s（上游 %s）" % (path, prof["upstream"]["version"]))
            return 0
        path, msg = bundle_mod.release(game, args.out, args.bundle_dir, bump=args.bump,
                                       note=args.note, accept_drift=args.accept_drift)
    except bundle_mod.BundleError as e:
        print("发布不了：%s" % e)
        return 1
    print(msg)
    print("包 %s\n  sha256 %s" % (os.path.normpath(path), bundle_mod.sha256_of(path)))
    return 0


def cmd_purge(game, args):
    """按需清掉上游快照。`all --purge <mode>` 会在 emit 成功后自动做这一步。

    这里**不给默认值**：删几个 GB 的下载是不可逆的，必须显式说删什么。
    """
    if args.purge == "none":
        print("要删什么得说清楚：--purge git（只删 .git）或 --purge all（整个快照目录）")
        return 2
    if not snapshot_mod.purge(args.upstream, args.purge):
        print("没有可清理的内容（mode=%s）" % args.purge)
    return 0


def cmd_all(game, args):
    steps = [("snapshot", cmd_snapshot)] + [(n, _stage(n, fn)) for n, fn in game.stages] \
        + [("emit", cmd_emit)]
    for name, fn in steps:
        print("\n=== %s ===" % name)
        t = time.time()
        code = fn(game, args)
        print("(%.1fs)" % (time.time() - t))
        if code:
            return code
    # 只有整条流水线都成功才清理：失败时留着快照，才好接着查
    snapshot_mod.purge(args.upstream, args.purge)
    return 0


def _common(game):
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--upstream", help="上游快照目录（默认 upstream/%s）" % game.name)
    p.add_argument("--build", help="中间产物目录（默认 build/%s）" % game.name)
    p.add_argument("--out", help="语料目录（默认 corpus/%s）" % game.name)
    p.add_argument("--no-fetch", action="store_true",
                   help="snapshot 阶段跳过联网，只读现有快照的版本信息")
    p.add_argument("--langs", default=None,
                   help="要出哪些语种，逗号分隔（默认 %s）。基准语种 %s 永远在列。"
                        "它同时决定 snapshot 下载哪些 TextMap 文件 —— 上游带十几个"
                        "语种，只取需要的能省约八成"
                        % (",".join(game.textmap.LANGS), game.textmap.BASE_LANG))
    p.add_argument("--compress", choices=("zstd", "none"), default="zstd",
                   help="产物是否 zstd 压缩（默认压）。压缩后是 *.jsonl.zst，"
                        "实测约为原始的 14%%；读端一律透明")
    p.add_argument("--purge", choices=("none", "git", "all"), default="none",
                   help="解析完之后清掉上游快照：git=只删 .git（约省一半，"
                        "解析仍可离线重跑，但下次取数要全量重克隆）；"
                        "all=整个快照目录都删（最省，改 parser 也得重新下载）")
    p.add_argument("--bundle-dir", help="bundle 把包写到哪（默认仓库根的 out/）")
    return p


def parser():
    ap = argparse.ArgumentParser(prog="gametext", description="游戏文本提取：gametext <游戏> <阶段> [选项]")
    games = ap.add_subparsers(dest="game", required=True, metavar="<游戏>")
    for name in GAMES:
        game = load(name)
        common = _common(game)
        sub = games.add_parser(name, help=game.title["zh-Hans"]).add_subparsers(
            dest="cmd", required=True, metavar="<阶段>")
        cmds = [("snapshot", cmd_snapshot)] + [(n, _stage(n, fn)) for n, fn in game.stages] + [
            ("emit", cmd_emit), ("all", cmd_all), ("purge", cmd_purge),
            ("manifest", cmd_manifest), ("bundle", cmd_bundle), ("release", cmd_release)]
        for cmd, fn in cmds:
            sub.add_parser(cmd, parents=[common]).set_defaults(func=fn, game_obj=game)
        rel = sub.choices["release"]
        rel.add_argument("--bump", action="store_true",
                         help="这次发布的产出和同一份上游上次发布的不同：rev 加一（要写 --note）")
        rel.add_argument("--note", default="", help="rev 为什么变（写进指纹表）")
        rel.add_argument("--accept-drift", default="", metavar="为什么",
                         help="与上次发布相比分布偏移超过门槛时，确认是预期内的并写明原因（记进指纹表）")
        rel.add_argument("--baseline-from", default="", metavar="语料目录",
                         help="只把那份语料的分布摘要写成基线 releases/<游戏>/profile.json，不发布（冷启动用）")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    game = args.game_obj
    # 语种是全局设定：snapshot 用它决定下载什么，emit / report 用它决定产出什么。
    # 在这里一次性定下来，下面各阶段都读 textmap.LANGS。
    game.textmap.LANGS = resolve_langs(game.textmap, args.langs)
    args.upstream = os.path.abspath(args.upstream or paths.upstream(game.name))
    args.build = os.path.abspath(args.build or paths.build(game.name))
    args.out = os.path.abspath(args.out or paths.corpus(game.name))
    args.bundle_dir = os.path.abspath(args.bundle_dir or paths.OUT)
    return args.func(game, args)


if __name__ == "__main__":
    sys.exit(main())
