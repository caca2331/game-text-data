"""产物包清单（gametext.core.bundle）：指纹只看内容，与压缩形态无关。"""

import json
import os
import re
from types import SimpleNamespace

import pytest

from gametext.core import bundle, jsonl
from gametext.core.contract import Contracts, F, Table
from gametext.core.game import Game
from gametext.core.snapshot import Upstream

LANGS = ("CHS", "EN")
GAME = Game(
    name="t", title={"zh-Hans": "测", "en": "T"},
    upstream=Upstream(repo="r", branch="b", always=(), textmap_patterns=lambda langs: [],
                      version_re=re.compile(r"(x)"), stale_days=1),
    textmap=SimpleNamespace(LANGS=LANGS, ALL_LANGS=LANGS, BASE_LANG="CHS"),
    contracts=Contracts("t", {"rows": Table(1, [F("id", "int", None, None, "id")], [])}),
    outputs=("rows",), stages=(), emit=None, summarize=None,
)


def corpus(path, compress, rows=3):
    os.makedirs(path)
    for lang in LANGS:
        with jsonl.open_write(os.path.join(path, "rows_%s.jsonl" % lang.lower()), compress) as f:
            for i in range(rows):
                f.write(json.dumps({"id": i}) + "\n")
    report = {
        "upstream": {"repo": "r", "commit": "c" * 40, "version": "1.0.0"},
        "extractor": {"git_head": "h", "dirty": False},
        "emit": {"langs": list(LANGS)},
        "per_lang": {lang: {"rows_rows": rows} for lang in LANGS},
        "contract": {"rows": {"label": "t.rows/1", "langs": {}}},
        "hard_failures": [],
    }
    with open(os.path.join(path, bundle.REPORT), "w", encoding="utf-8") as f:
        json.dump(report, f)
    return path


def test_fingerprint_ignores_compression(tmp_path):
    table = str(tmp_path / "fingerprints.tsv")
    z = bundle.build_manifest(GAME, corpus(str(tmp_path / "z"), "zstd"), table)
    n = bundle.build_manifest(GAME, corpus(str(tmp_path / "n"), "none"), table)
    assert z["fingerprint"] == n["fingerprint"]
    sha = {f["lang"]: f["sha256"] for f in z["files"] if "table" in f}
    assert all(sha[f["lang"]] != f["sha256"] for f in n["files"] if "table" in f)
    assert z["tables"] == {"rows": {"rows": 3, "contract": "t.rows/1"}}
    assert z["rev"].startswith("0+")


def test_fingerprint_changes_with_content(tmp_path):
    table = str(tmp_path / "fingerprints.tsv")
    a = bundle.build_manifest(GAME, corpus(str(tmp_path / "a"), "zstd", rows=3), table)
    b = bundle.build_manifest(GAME, corpus(str(tmp_path / "b"), "zstd", rows=4), table)
    assert a["fingerprint"] != b["fingerprint"]


def test_stale_contract_is_refused(tmp_path):
    d = corpus(str(tmp_path / "d"), "zstd")
    path = os.path.join(d, bundle.REPORT)
    with open(path, encoding="utf-8") as f:
        report = json.load(f)
    report["contract"]["rows"]["label"] = "t.rows/0"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f)
    with pytest.raises(bundle.BundleError, match="重跑 emit"):
        bundle.build_manifest(GAME, d, str(tmp_path / "fingerprints.tsv"))


def test_release_refuses_corpus_from_other_commit(tmp_path):
    """语料清单里的 git_head 不是当前 HEAD（旧代码产的）就不发布。"""
    d = corpus(str(tmp_path / "d"), "zstd")
    with pytest.raises(bundle.BundleError, match="重跑 all"):
        bundle.release(GAME, d, str(tmp_path / "out"), table=str(tmp_path / "fingerprints.tsv"),
                       profile=str(tmp_path / "profile.json"))
