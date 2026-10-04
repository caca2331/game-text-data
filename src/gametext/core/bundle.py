"""产物包：`corpus/<游戏>/manifest.json`（协议 `gtd-bundle/1`）与 `out/<游戏>-<version>-<fp12>.zip`。

协议写在 docs/architecture.md 的"产物包协议"一节。下文的"语料目录"指 `corpus/<游戏>/`。

- **清单只从现有语料目录算**：不碰上游、不重跑 emit，纯读。
- **两种哈希**：`sha256` 按存储的字节算，管传输完整性；`content_sha256` 按解压后的 JSONL
  算，管内容身份——换压缩档位 / `--compress none` 不改变它。
- **指纹**只由 `(table, lang, content_sha256)` 算，不含文件名、不含 `report.json`：
  它回答"是不是同一份语料"，报告只是对语料的描述。
- **包是确定性的**：成员排序、时间戳和属性固定，同一份语料两次打包逐字节相同。
- 哈希防的是拷坏和版本对不上，**不是安全机制**。
- **指纹表** `releases/<游戏>/fingerprints.tsv`（追踪、随公开仓库发布）：一行一份发布过的语料，
  拿到包的人用它核"这是不是维护者发出的那份"。`rev` 是提取**行为**的版本：同一份上游、同一组语种、
  同一个 `rev` → 同一个指纹；commit 变了而产出不变，`rev` 不动。`rev` 只在发布（`release`）时按需递增，
  本地出的包在清单里标 `<上次发布的 rev>+<指纹前 8 位>`。
"""

from __future__ import annotations

import datetime
import glob
import hashlib
import json
import os
import re
import zipfile

import zstandard

from .. import paths
from . import contract
from . import report as core_report

SCHEMA = "gtd-bundle/1"
MANIFEST = "manifest.json"
REPORT = "report.json"
NOTICE = "NOTICE.txt"
TABLE_COLUMNS = ("rev", "upstream_version", "upstream_commit", "langs", "fingerprint", "released", "note")

# 上游语种代码 -> BCP-47。文件名照上游叫法（原神、崩铁 JP / KR，绝区零 JA / KO），清单负责把它说成标准码。
BCP47 = {"CHS": "zh-Hans", "CHT": "zh-Hant", "DE": "de", "EN": "en", "ES": "es",
         "FR": "fr", "ID": "id", "IT": "it", "JA": "ja", "JP": "ja", "KO": "ko", "KR": "ko",
         "PT": "pt", "RU": "ru", "TH": "th", "TR": "tr", "VI": "vi"}

ZIP_TIME = (1980, 1, 1, 0, 0, 0)
DATA_RE = re.compile(r"^(?P<table>[a-z_]+)_(?P<lang>[a-z]+)\.jsonl(?P<zst>\.zst)?$")
CHUNK = 1 << 20

NOTICE_TEXT = """\
本包含游戏《{zh}》的文本，版权归原权利人所有。
提取代码：game-text-data（GPL-3.0-or-later）的 {game} 部分；上游：社区解包数据 {repo}。
仅供个人研究使用，不得公开再分发。

This bundle contains text from {en}; the text is copyright its respective owners.
Extracted by game-text-data ({game}, code under GPL-3.0-or-later) from community-unpacked data at {repo}.
For personal research only. Do not redistribute publicly.
"""


class BundleError(RuntimeError):
    pass


def table_path(game) -> str:
    """指纹表：一行一份发布过的语料。"""
    return os.path.join(paths.releases(game.name), "fingerprints.tsv")


def profile_path(game) -> str:
    """上次发布那份语料的分布摘要（追踪、只有计数）。release 拿新语料和它比，偏移过大要 --accept-drift。"""
    return os.path.join(paths.releases(game.name), "profile.json")


def _report_rows(game, report: dict, table: str, lang: str):
    """report.json 里这张表、这个语种的行数（emit 阶段逐语种计的）。"""
    per = (report.get("per_lang") or {}).get(lang) or {}
    return per.get(game.rows_key.get(table, table + "_rows"))


def _hash_file(path: str, compressed: bool) -> dict:
    """存储字节的 sha256、解压后的 sha256 与行数。两遍读：一遍原样、一遍解压。"""
    raw = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            raw.update(chunk)
            size += len(chunk)
    if not compressed:
        content, rows = raw, _count_lines(path, None)
    else:
        content = hashlib.sha256()
        rows = _count_lines(path, content)
    return {"bytes": size, "sha256": raw.hexdigest(), "content_sha256": content.hexdigest(),
            "rows": rows}


def _count_lines(path: str, content) -> int:
    """数非空行（emit 每行一个对象、不写空行，这里仍按非空行数，和读端 iter_rows 同一口径）。
    `content` 给了就顺手喂解压后的字节。"""
    rows = 0
    with open(path, "rb") as f:
        stream = zstandard.ZstdDecompressor().stream_reader(f) if content is not None else f
        pending = b""
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            if content is not None:
                content.update(chunk)
            lines = (pending + chunk).split(b"\n")
            pending = lines.pop()
            rows += sum(1 for ln in lines if ln.strip())
        if pending.strip():
            rows += 1
    return rows


def fingerprint(files: list) -> str:
    items = sorted((f["table"], f["lang"], f["content_sha256"]) for f in files if "table" in f)
    body = "".join("%s\t%s\t%s\n" % it for it in items)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def read_table(path: str) -> list:
    """指纹表的行（`rev` 转成 int）。表还没有就是空表。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    if not lines or tuple(lines[0].split("\t")) != TABLE_COLUMNS:
        raise BundleError("%s 的表头应当是 %s" % (path, "\t".join(TABLE_COLUMNS)))
    rows = []
    for n, ln in enumerate(lines[1:], 2):
        cells = ln.split("\t")
        if len(cells) != len(TABLE_COLUMNS):
            raise BundleError("%s 第 %d 行应当有 %d 列，有 %d 列" % (path, n, len(TABLE_COLUMNS), len(cells)))
        row = dict(zip(TABLE_COLUMNS, cells))
        if not row["rev"].isdigit():
            raise BundleError("%s 第 %d 行的 rev 应当是整数，是 %r" % (path, n, row["rev"]))
        row["rev"] = int(row["rev"])
        rows.append(row)
    return rows


def _write_table(path: str, rows: list) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(TABLE_COLUMNS) + "\n")
        for r in rows:
            f.write("\t".join(str(r[c]) for c in TABLE_COLUMNS) + "\n")
    os.replace(tmp, path)


def _langs_key(m: dict) -> str:
    return ",".join(sorted(m["langs"]))


def rev_label(fp: str, rows: list):
    """发布过的语料是表里的 `rev`（int）；没发布过的是 `<上次发布的 rev>+<指纹前 8 位>`。
    不用手动计数：两条分支各自数出的号会对应不同的语料，指纹前缀天然唯一。"""
    for r in rows:
        if r["fingerprint"] == fp:
            return r["rev"]
    return "%d+%s" % (max((r["rev"] for r in rows), default=0), fp.split(":", 1)[1][:8])


def build_manifest(game, data_dir: str, table: str | None = None) -> dict:
    """从语料目录算清单；任何对不上都抛 BundleError，不出半份清单。"""
    rep_path = os.path.join(data_dir, REPORT)
    if not os.path.exists(rep_path):
        raise BundleError("%s 不存在：先跑 emit" % rep_path)
    with open(rep_path, encoding="utf-8") as f:
        report = json.load(f)
    if report.get("hard_failures"):
        raise BundleError("report.json 带硬失败，不出清单：%s" % report["hard_failures"])
    langs = list((report.get("emit") or {}).get("langs") or [])
    if not langs:
        raise BundleError("report.json 没有 emit.langs")
    unknown = [x for x in langs if x not in BCP47]
    if unknown:
        raise BundleError("语种 %s 没有 BCP-47 映射" % unknown)

    # 契约版本取自 emit 那次实际做过的检查：语料是旧代码产的、或 emit 之后改了契约，都不能冒称合规
    checked = {t: c.get("label") for t, c in (report.get("contract") or {}).items()}
    for t in game.outputs:
        if checked.get(t) != game.contracts.label(t):
            raise BundleError("%s 的契约检查是 %s、当前契约是 %s：用当前代码重跑 emit"
                              % (t, checked.get(t) or "没做过", game.contracts.label(t)))

    names = sorted(os.listdir(data_dir))
    stray = [n for n in names if n not in (MANIFEST, REPORT) and not DATA_RE.match(n)]
    if stray:
        raise BundleError("%s 里有不认识的文件：%s" % (data_dir, stray))

    files, tables = [], {}
    seen = set()
    for t in game.outputs:
        for lang in langs:
            cands = [n for n in ("%s_%s.jsonl.zst" % (t, lang.lower()),
                                 "%s_%s.jsonl" % (t, lang.lower())) if n in names]
            if len(cands) != 1:
                raise BundleError("%s × %s 应当恰好一个文件，找到 %s" % (t, lang, cands or "没有"))
            name = cands[0]
            seen.add(name)
            info = _hash_file(os.path.join(data_dir, name), name.endswith(".zst"))
            want = _report_rows(game, report, t, lang)
            if want != info["rows"]:
                raise BundleError("%s 有 %s 行，report.json 记的是 %s" % (name, info["rows"], want))
            prev = tables.setdefault(t, {"rows": info["rows"],
                                         "contract": checked[t]})["rows"]
            if prev != info["rows"]:
                raise BundleError("%s 的各语种行数不一致（%s vs %s）" % (t, prev, info["rows"]))
            files.append({"path": name, "table": t, "lang": BCP47[lang], **info})
    extra = [n for n in names if DATA_RE.match(n) and n not in seen]
    if extra:
        raise BundleError("%s 里有不在 emit.langs / 产物表里的旧文件：%s" % (data_dir, extra))
    with open(rep_path, "rb") as f:
        rep_bytes = f.read()
    files.append({"path": REPORT, "bytes": len(rep_bytes),
                  "sha256": hashlib.sha256(rep_bytes).hexdigest()})
    files.sort(key=lambda x: x["path"])

    up = report.get("upstream") or {}
    ex = report.get("extractor") or {}
    return {
        "schema": SCHEMA,
        "game": game.name,
        "title": game.title,
        "fingerprint": fingerprint(files),
        "rev": rev_label(fingerprint(files), read_table(table or table_path(game))),
        "upstream": {k: up.get(k) for k in ("repo", "commit", "commit_date", "version",
                                            "version_subject")}
                    | {"integrity_checked": not up.get("integrity_warnings")},
        "extractor": {"subproject": game.name, "git_head": ex.get("git_head"), "dirty": ex.get("dirty")},
        "langs": {BCP47[x]: x.lower() for x in langs},
        "base_lang": BCP47[langs[0]],
        "tables": tables,
        "files": files,
    }


def write_manifest(game, data_dir: str, table: str | None = None) -> dict:
    m = build_manifest(game, data_dir, table)
    path = os.path.join(data_dir, MANIFEST)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return m


def remove_manifest(data_dir: str) -> None:
    """emit 开始前调用：产物要重写了，旧清单留着就会和新文件对不上（或者 emit 中途失败，
    留下一份描述旧产物的清单）。"""
    path = os.path.join(data_dir, MANIFEST)
    if os.path.exists(path):
        os.remove(path)


def _member(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    zi = zipfile.ZipInfo(name, date_time=ZIP_TIME)
    zi.compress_type = zipfile.ZIP_STORED     # 成员本来就是 zstd，再压只费时间
    zi.create_system = 3
    zi.external_attr = 0o100644 << 16
    zf.writestr(zi, data)


def bundle(game, data_dir: str, out_dir: str, table: str | None = None) -> str:
    """重算清单、打一个确定性的 zip 进 `out_dir`，并删掉同一游戏的旧包
    （out/ 是语料目录的投影，旧包留着会被下游当成候选，和 jsonl.cleanup_stale 同一个道理）。"""
    m = write_manifest(game, data_dir, table)
    version = m["upstream"]["version"] or "unknown"
    name = "%s-%s-%s.zip" % (game.name, version, m["fingerprint"].split(":", 1)[1][:12])
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    tmp = path + ".tmp"
    notice = NOTICE_TEXT.format(zh=game.title["zh-Hans"], en=game.title["en"], game=game.name,
                                repo=m["upstream"]["repo"])
    members = {MANIFEST: None, NOTICE: notice.encode("utf-8")}
    members.update({f["path"]: None for f in m["files"]})
    try:
        with zipfile.ZipFile(tmp, "w") as zf:
            for rel in sorted(members):
                data = members[rel]
                if data is None:
                    with open(os.path.join(data_dir, rel), "rb") as f:
                        data = f.read()
                _member(zf, "%s/%s" % (game.name, rel), data)
        with zipfile.ZipFile(tmp) as zf:
            bad = zf.testzip()
        if bad:
            raise BundleError("刚写的包校验失败：%s" % bad)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    for old in glob.glob(os.path.join(out_dir, "%s-*.zip" % game.name)):
        if os.path.abspath(old) != os.path.abspath(path):
            os.remove(old)
    return path


def release(game, data_dir: str, out_dir: str, bump: bool = False, note: str = "", accept_drift: str = "",
            table: str | None = None, profile: str | None = None, today: str | None = None):
    """发布：把语料目录这份语料记进指纹表，再打包（清单里的 `rev` 随之是 int）。返回 (包路径, 说明)。

    `rev` 沿用上次发布的号，`bump` 才加一（维护者判断产出变了，`note` 写为什么）。核对只靠表：
    同一份上游、同一组语种、同一个 `rev` 已经发布过别的指纹 → 拒绝（该加 `rev` 没加，或提取不确定）。
    上游也换了的那次判不出产出变没变，由维护者判断，必要时拿旧上游重跑一次。

    分布比较：与 `profile.json`（上次发布的摘要）比，超过 `contract.DRIFT_*` 的门槛就要
    `accept_drift` 写明为什么，理由记进指纹表的说明列；发布后把这份的摘要写成新基线。
    `table` / `profile` 默认是 `releases/<游戏>/` 下那两份，测试时可指到别处。"""
    table = table or table_path(game)
    profile = profile or profile_path(game)
    m = build_manifest(game, data_dir, table)
    rows = read_table(table)
    known = [r for r in rows if r["fingerprint"] == m["fingerprint"]]
    if known:
        msg = "这份语料已在表里（rev %d），不新增行" % known[0]["rev"]
        if bump:
            msg += "；产出没变，--bump 忽略"
        return bundle(game, data_dir, out_dir, table), msg
    if m["extractor"].get("dirty"):
        raise BundleError("出这份语料的提取代码有未提交的改动（report.json 的 extractor.dirty）：先提交再重跑")
    head = core_report.extractor_version(game.name).get("git_head")
    if m["extractor"].get("git_head") != head:
        raise BundleError("这份语料是提取代码 %s 产的，当前 HEAD 是 %s：用当前代码重跑 all 再发布"
                          % ((m["extractor"].get("git_head") or "?")[:10], (head or "?")[:10]))
    commit = m["upstream"].get("commit")
    if not commit:
        raise BundleError("清单里没有上游 commit，记不进表")
    note = note.strip()
    if "\t" in note or "\n" in note:
        raise BundleError("--note 不能带制表符或换行")
    last = max((r["rev"] for r in rows), default=0)
    rev = last + 1 if bump or not rows else last
    if bump and not note:
        raise BundleError("加 rev 要写 --note：同一份上游的产出为什么变了")
    base = read_profile(profile)
    if base is None:
        raise BundleError("还没有分布基线 %s：先 release --baseline-from <上次发布那份上游跑出的语料目录>"
                          % profile)
    if rows and base["upstream"].get("commit") != rows[-1]["upstream_commit"]:
        raise BundleError("分布基线出自上游 %s，指纹表最后一次发布是 %s：基线该是上次发布那份，重新 --baseline-from"
                          % ((base["upstream"].get("commit") or "?")[:10], rows[-1]["upstream_commit"][:10]))
    drifts = contract.drift(base["tables"], contract.profiles(_read_report(data_dir)))
    accept_drift = accept_drift.strip()
    if "\t" in accept_drift or "\n" in accept_drift:
        raise BundleError("--accept-drift 不能带制表符或换行")
    if drifts and not accept_drift:
        raise BundleError("与上次发布（%s）相比分布偏移：\n  %s\n确认是预期内的，就 --accept-drift \"<为什么>\""
                          % (base["upstream"].get("version"), "\n  ".join(drifts[:40])))
    if drifts:
        note = "; ".join(x for x in (note, "drift: " + accept_drift) if x)
    clash = [r for r in rows if r["upstream_commit"] == commit and r["langs"] == _langs_key(m) and r["rev"] == rev]
    if clash:
        raise BundleError("同一份上游（%s）、同一组语种、rev %d 已发布过指纹 %s，这次是 %s。"
                          "产出确实变了就 --bump --note 写原因；没改提取代码却变了，是提取不确定，先查"
                          % (commit[:10], rev, clash[0]["fingerprint"], m["fingerprint"]))
    rows.append({"rev": rev, "upstream_version": m["upstream"].get("version") or "",
                 "upstream_commit": commit, "langs": _langs_key(m), "fingerprint": m["fingerprint"],
                 "released": today or datetime.date.today().isoformat(),
                 "note": note or ("首次发布" if last == 0 else "")})
    _write_table(table, rows)
    write_profile(data_dir, profile)
    return bundle(game, data_dir, out_dir, table), "记进表：rev %d（%s）" % (rev, table)


def _read_report(data_dir: str) -> dict:
    with open(os.path.join(data_dir, REPORT), encoding="utf-8") as f:
        return json.load(f)


def read_profile(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_profile(data_dir: str, path: str) -> dict:
    """把 `data_dir` 那份语料的分布摘要写成基线。release 每次发布后调用；
    冷启动时由 `release --baseline-from <语料目录>` 单独调用（只写基线、不发布）。"""
    report = _read_report(data_dir)
    if report.get("hard_failures"):
        raise BundleError("%s 的 report.json 带硬失败，不能当基线" % data_dir)
    tables = contract.profiles(report)
    if not tables:
        raise BundleError("%s 的 report.json 没有契约摘要：用当前代码重跑一次 emit" % data_dir)
    up = report.get("upstream") or {}
    prof = {"upstream": {"version": up.get("version"), "commit": up.get("commit")},
            "contracts": {t: c["label"] for t, c in report["contract"].items()},
            "tables": tables}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)  # 新加的游戏还没有 releases/<游戏>/
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(prof, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
    return prof


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()
