"""snapshot 阶段：把上游快照拉到本地并记录版本。

**本模块是整个流水线里唯一允许联网的地方**（根 AGENTS.md 取数原则 2）。其余阶段
只读快照目录，改 parser 永远不会触发重新下载。

各游戏在自己的模块里给一份 `Upstream`（仓库地址、取哪些目录、版本号的写法、存活阈值），
机制在这里只写一份。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


@dataclass(frozen=True)
class Upstream:
    repo: str
    branch: str
    always: tuple
    """总要取的 sparse 规则（non-cone 写法，如 `/ExcelBinOutput/`）。上游存活检测要读 `/README.md`，记得列上。"""
    textmap_patterns: Callable
    """语种元组 → 这些语种的 TextMap 文件规则。**TextMap 按语种逐文件挑，不整目录拉**：
    上游带十几个语种，默认三语只占两成。"""
    version_re: re.Pattern
    """从提交标题里认游戏版本号，第一组是版本号。"""
    stale_days: int
    """超过这么多天没有带版本号的数据提交，就告警（按这款游戏上游的常态更新间隔定）。"""
    own_repos: tuple = ()
    """origin 必须包含其中之一，否则重建；空 = 不查（镜像 origin 也接受）。"""
    legacy_repos: tuple = ()
    """origin 包含其中之一就是指向已废弃的旧仓库，重建。"""

    def sparse_paths(self, langs):
        return list(self.always) + self.textmap_patterns(langs)

    def stale_origin(self, origin) -> bool:
        """origin 读不到、指向已废弃的仓库、或（列了本仓库地址时）一个都不匹配 → 要重建。"""
        if origin is None or any(old in origin for old in self.legacy_repos):
            return True
        return bool(self.own_repos) and not any(r in origin for r in self.own_repos)


def _git(args, cwd=None):
    return subprocess.run(
        ["git"] + args, cwd=cwd, check=True, text=True, capture_output=True
    ).stdout.strip()


# 深度不能是 1：版本号只写在某几次数据提交的标题里，HEAD 常常是改 README 之类
# 的杂项提交，深度 1 会让 describe() 完全翻不到版本号。多几十条提交只多几 KB 元数据。
DEPTH = 50

# 上游 README 里出现这些词，多半意味着仓库已迁走或停止维护。
# 原神的上游真出过：旧仓库的 README 被换成一行 "Deprecated due to hitting repository
# size. Refer to ..."，而我们照旧 pull 了三个月都没察觉，只以为上游停更。
DEPRECATION_MARKERS = ("deprecated", "no longer", "moved to", "refer to")


def _force_rmtree(path: str) -> None:
    """删除 git 工作区。Windows 上 .git/objects/pack 里的文件是只读的，
    直接 rmtree 会 PermissionError，得先去掉只读位。"""

    def on_error(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onerror=on_error)


def _origin(upstream_dir: str):
    try:
        return _git(["remote", "get-url", "origin"], cwd=upstream_dir)
    except Exception:
        return None


def ensure_upstream(up: Upstream, upstream_dir: str, langs) -> None:
    """首次克隆，之后 pull；origin 不对（读不到、已废弃、不是本仓库）时自动重建。"""
    if has_git(upstream_dir):
        origin = _origin(upstream_dir)
        if up.stale_origin(origin):
            # origin 指向搬走前的旧仓库（继续 pull 只会永远停在旧版本而毫无提示），
            # 或者根本读不出来（.git 损坏）—— 都重建，别在坏状态上继续。
            print("本地快照不可用（origin=%s），重新克隆 ..." % (origin or "读不到"))
            _force_rmtree(upstream_dir)
        else:
            print("更新已有快照 ...")
            _git(["fetch", "--depth", str(DEPTH), "origin"], cwd=upstream_dir)
            # 每次都重设一遍：sparse 规则写在代码里，改了之后老快照的
            # sparse 配置不会自己跟上，会静默少拉目录。
            _set_sparse(up, upstream_dir, langs)
            _git(["reset", "--hard", "origin/" + up.branch], cwd=upstream_dir)
            # 惰性拉取（--filter=blob:none）每次 fetch 都新开一个 pack，旧版本的
            # blob 也会一直留着：实测 56 个 pack / 638 MB，gc 后 2 个 pack / 258 MB。
            # --auto 让 git 自己判断该不该动，真动的时候顺便把不可达对象清掉。
            _git(["gc", "--auto", "--prune=now", "--quiet"], cwd=upstream_dir)
            return
    print("首次克隆（sparse，只取 %s 的 TextMap）..." % "/".join(langs))
    if os.path.isdir(upstream_dir) and os.listdir(upstream_dir):
        # 目录还在但 .git 没了 —— 多半是 purge("git") 之后又要取数。
        # git clone 不肯往非空目录里克隆，只能整个清掉重来：**省不掉增量**，
        # 这正是 `--purge git` 的代价，purge 的文档里写明了。
        print("（快照的 .git 之前被清理过，这次只能全量重克隆）")
        _force_rmtree(upstream_dir)
    os.makedirs(os.path.dirname(os.path.abspath(upstream_dir)), exist_ok=True)
    _git(["clone", "--depth", str(DEPTH), "--filter=blob:none", "--sparse",
          "--branch", up.branch, up.repo, upstream_dir])
    _set_sparse(up, upstream_dir, langs)


def _set_sparse(up: Upstream, upstream_dir: str, langs) -> None:
    _git(["sparse-checkout", "set", "--no-cone"] + up.sparse_paths(langs), cwd=upstream_dir)


def purge(upstream_dir: str, mode: str = "none") -> int:
    """解析完之后按需清掉上游快照，返回释放的字节数。

    快照是**可再生**的（重新克隆就有），但重新取数是几个 GB 的下载，所以默认保留。
    产出的可追溯性不受影响：commit 与版本号已经写进 `build/<游戏>/snapshot.json` 和每条输出。

    | mode  | 删什么 | 代价 |
    | ----- | ------ | ---- |
    | none  | 不删（默认） | — |
    | git   | 只删 `.git` | 解析仍可离线重跑；下次取数要**全量重克隆**（省不掉增量） |
    | all   | 整个快照目录 | 最省；但改了 parser 也得先重新下载才能重跑 |

    `git` 这一档能省掉约一半体积：`.git` 里装的基本就是工作区那份数据的压缩副本
    （`--filter=blob:none` 惰性拉取，每次 fetch 生成一个新 pack）。
    """
    if mode not in ("none", "git", "all"):
        raise ValueError("purge mode 只能是 none / git / all，收到 %r" % mode)
    if mode == "none" or not os.path.isdir(upstream_dir):
        return 0
    target = upstream_dir if mode == "all" else os.path.join(upstream_dir, ".git")
    if not os.path.isdir(target):
        return 0
    freed = _dir_size(target)
    _force_rmtree(target)
    print("已清理 %s（释放 %.1f GB）" % (target, freed / 2 ** 30))
    return freed


def _dir_size(path: str) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def has_git(upstream_dir: str) -> bool:
    """快照目录里有没有它自己的 `.git`。

    **这个判断必须做在任何 git 命令之前。** git 会顺着目录树往上找仓库：快照的
    `.git` 被 `purge` 掉之后，`git rev-parse HEAD` 会一路找到**本项目自己的**仓库，
    把我们的 commit 和日期当成上游的记进每一条输出——实测踩到过，而且流水线照样
    退出 0、报告照样是绿的。这是"上游版本可追溯"最隐蔽的破法。

    `.git` 是文件也算：快照可以是上游仓库的 `git worktree`（如在本仓库的 worktree
    槽里解析另一个上游版本，与主 checkout 的快照共享对象库），那里的 `.git` 是一个
    指向 gitdir 的文件。只认目录会把它误判成"已 purge"。
    """
    return os.path.exists(os.path.join(upstream_dir, ".git"))


def _reuse_recorded(upstream_dir: str, recorded: str) -> dict:
    """`.git` 已被清理时，沿用上一次记下来的上游信息，而不是去问 git。"""
    if not os.path.isdir(upstream_dir):
        raise SystemExit(
            "快照目录 %s 不存在（`--purge all` 之后就是这样）。解析要读工作区里的原始"
            "数据，先联网跑一次 snapshot 把它拉回来。" % upstream_dir)
    if not os.path.exists(recorded):
        raise SystemExit(
            "快照目录 %s 里没有 .git，而 %s 也不存在——无从确定这份数据来自哪个上游 "
            "commit。先联网跑一次 snapshot 再继续。" % (upstream_dir, recorded))
    with open(recorded, encoding="utf-8") as f:
        info = json.load(f)
    info["snapshot_purged"] = True
    # 沿用旧记录里的完整性告警会骗人：这一次根本没检查。换成明说。
    info["integrity_warnings"] = [
        "快照的 .git 已被清理，这次跑没有做完整性检查（工作区是否等于所记 commit "
        "无从验证）。上游信息沿用 build/<游戏>/snapshot.json 里上一次的记录。"]
    with open(recorded, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print("快照的 .git 已清理，沿用上次记录的上游信息：%s @ %s"
          % (info.get("version") or "?", (info.get("commit") or "")[:10]))
    return info


def _find_version(up: Upstream, upstream_dir: str):
    """最近一次带版本号的提交：(版本号, 提交标题, 提交日期)，找不到是三个 None。"""
    for line in _git(["log", "--format=%cI%x1f%s"], cwd=upstream_dir).splitlines():
        date, _, subject = line.partition("\x1f")
        m = up.version_re.search(subject)
        if m:
            return m.group(1), subject, date
    return None, None, None


def describe(up: Upstream, upstream_dir: str, fetch: bool = True) -> dict:
    """读出 commit 与游戏版本，供每条输出记录出处。上游用提交标题记录游戏版本，
    HEAD 未必是这样的提交（可能是改 README），所以要往回找。"""
    commit = _git(["rev-parse", "HEAD"], cwd=upstream_dir)
    date = _git(["log", "-1", "--format=%cI"], cwd=upstream_dir)
    version, subject, _ = _find_version(up, upstream_dir)
    if version is None and fetch and int(_git(["rev-list", "--count", "HEAD"], cwd=upstream_dir)) < DEPTH:
        # 老快照可能是 --depth 1 拉的，历史里根本没有带版本号的提交，加深再试
        _git(["fetch", "--depth", str(DEPTH), "origin"], cwd=upstream_dir)
        version, subject, _ = _find_version(up, upstream_dir)
    return {"repo": up.repo, "commit": commit, "commit_date": date,
            "version": version, "version_subject": subject}


def check_integrity(upstream_dir: str) -> list:
    """快照工作区是不是真的等于它记录的那个 commit。

    取数原则 5 说"上游版本可追溯"，但只把 commit 写进输出是不够的——工作区可能根本
    不等于那个 commit，而解析读的是工作区。绝区零实测踩到两种情况：

    1. **同名不同大小写的文件**。HEAD 的树里有 21 对（`BPLevelVersionTemplateTb.json`
       与 `BpLevelVersionTemplateTb.json`），其中 20 对内容不同。**Windows 文件系统
       装不下两个**，每对只会落一个，落哪个取决于 git 最后写的是谁——于是我们解析的
       内容既不确定、也可能来自另一个 commit。
    2. 由此导致 `git status` 永远不干净，`git checkout` 到别的 commit 会直接失败。

    同名冲突只看 sparse 实际检出的文件：没检出的目录不解析，那里的冲突与产出无关，算进来只会让
    清单的 `integrity_checked` 误报 false（zzz 在 `1277ebca4b` 上唯一的一组就在不检出的 `Data/_unsorted/`）。

    这里只做检测与上报，不擅自改动快照：真要修得挑一边留，那是取舍不是修复。
    """
    warnings = []
    try:
        dirty = _git(["status", "--porcelain"], cwd=upstream_dir).splitlines()
    except Exception as exc:
        return ["读不到快照的 git 状态：%s" % exc]
    if dirty:
        # porcelain 是 "XY <path>"，但 _git 会 strip 掉整段输出的首尾空白，
        # 第一行的前导空格会被吃掉——所以按空白切，别按固定下标取
        paths_dirty = [d.split(None, 1)[-1] for d in dirty]
        warnings.append(
            "快照工作区与记录的 commit 不一致，有 %d 个文件有改动（解析读的是工作区，"
            "不是那个 commit）：%s"
            % (len(dirty), "、".join(paths_dirty[:4])))

    try:
        # -t 给每个索引项标状态：H 是检出的，S 是被 sparse 跳过的
        entries = _git(["ls-files", "-t", "-z"], cwd=upstream_dir).split("\0")
    except Exception:
        return warnings
    paths = [e[2:] for e in entries if e.startswith("H ")]
    lowered = {}
    clashes = set()
    for p in paths:
        key = p.lower()
        if key in lowered and lowered[key] != p:
            clashes.add(key)
        lowered[key] = p
    if clashes:
        sample = sorted(clashes)[:3]
        warnings.append(
            "上游有 %d 组只差大小写的同名文件（如 %s）。Windows 上每组只能落一个，"
            "落哪个不确定；这些文件的解析结果不可复现"
            % (len(clashes), "、".join(os.path.basename(c) for c in sample)))
    return warnings


def check_liveness(up: Upstream, upstream_dir: str, info: dict) -> list:
    """上游存活检测。返回警告文本列表，不抛异常。

    只用本地快照里已有的信息判断，不额外联网。
    """
    warnings = []

    readme = os.path.join(upstream_dir, "README.md")
    if os.path.exists(readme):
        with open(readme, encoding="utf-8", errors="replace") as f:
            head = f.read(4000)
        hit = [m for m in DEPRECATION_MARKERS if m in head.lower()]
        if hit:
            first = next((ln.strip() for ln in head.splitlines() if ln.strip()), "")
            warnings.append(
                "上游 README 含疑似废弃/迁移标记 %s：%r —— 确认仓库是否已搬家"
                % (hit, first[:160]))

    if not info.get("version"):
        # 版本号是语料可复现的凭据，找不到就进报告，别只打印
        warnings.append("最近 %d 条提交里找不到版本号，输出将缺少 upstream.version："
                        "上游可能改了提交标题的格式，核对这款游戏的 version_re" % DEPTH)

    # 看最近一次**带版本号**的数据提交，不看 HEAD：HEAD 可能只是改 README。
    # 找不到带版本号的提交（标题格式变了）时退回 HEAD 的日期，照样算
    last, what = info.get("commit_date"), "提交（HEAD，认不出带版本号的数据提交）"
    if info.get("version_subject"):
        try:
            found = _find_version(up, upstream_dir)[2]
        except Exception:
            found = None
        if found:
            last, what = found, "数据提交"
    if last:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).days
        if age > up.stale_days:
            warnings.append(
                "最近一次%s（%s）已是 %d 天前，超过 %d 天。"
                "上游可能停更、也可能已迁走 —— 去 README 和作者主页确认一次"
                % (what, last[:10], age, up.stale_days))
    return warnings


def run(up: Upstream, upstream_dir: str, build_dir: str, langs, fetch: bool = True) -> dict:
    if fetch:
        ensure_upstream(up, upstream_dir, langs)
    if not has_git(upstream_dir):
        return _reuse_recorded(upstream_dir, os.path.join(build_dir, "snapshot.json"))
    info = describe(up, upstream_dir, fetch)
    info["liveness_warnings"] = check_liveness(up, upstream_dir, info)
    for w in info["liveness_warnings"]:
        print("!! 上游存活检测：%s" % w)
    info["integrity_warnings"] = check_integrity(upstream_dir)
    for w in info["integrity_warnings"]:
        print("!! 快照完整性：%s" % w)
    os.makedirs(build_dir, exist_ok=True)
    with open(os.path.join(build_dir, "snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    return info
