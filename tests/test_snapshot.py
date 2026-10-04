"""快照的两个判断（gametext.core.snapshot）：认不认得出 `.git`、origin 要不要重建。"""

import re

from gametext.core.snapshot import Upstream, has_git


def test_has_git_accepts_worktree_file(tmp_path):
    assert not has_git(str(tmp_path))
    (tmp_path / ".git").write_text("gitdir: /somewhere/.git/worktrees/upstream\n")
    assert has_git(str(tmp_path))


def test_has_git_accepts_directory(tmp_path):
    (tmp_path / ".git").mkdir()
    assert has_git(str(tmp_path))


def up(own=(), legacy=()):
    return Upstream(repo="r", branch="b", always=(), textmap_patterns=lambda langs: [],
                    version_re=re.compile(r"(x)"), stale_days=1, own_repos=own, legacy_repos=legacy)


def test_stale_origin_rules():
    mirror_ok = up(legacy=("old/Repo",))
    assert mirror_ok.stale_origin(None)
    assert mirror_ok.stale_origin("https://host/old/Repo.git")
    assert not mirror_ok.stale_origin("https://mirror/anything.git")
    strict = up(own=("host/new",))
    assert not strict.stale_origin("https://host/new.git")
    assert strict.stale_origin("https://elsewhere/new.git")


def test_liveness_uses_last_versioned_commit_not_head(tmp_path):
    """HEAD 只是改 README 时，停更告警看的是最近一次带版本号的数据提交。"""
    import os
    import subprocess

    from gametext.core.snapshot import check_liveness, describe

    def commit(msg, date):
        env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date,
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", msg], cwd=tmp_path, env=env, check=True)

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    commit("CNRELWin1.2.3_R1_S2_D3", "2020-01-01T00:00:00+00:00")
    commit("update README", "2099-01-01T00:00:00+00:00")
    u = Upstream(repo="r", branch="b", always=(), textmap_patterns=lambda langs: [],
                 version_re=re.compile(r"[A-Z]+Win(\d+\.\d+\.\d+)"), stale_days=30)
    info = describe(u, str(tmp_path), fetch=False)
    assert info["version"] == "1.2.3"
    warnings = check_liveness(u, str(tmp_path), info)
    assert any("2020-01-01" in w for w in warnings), warnings


def test_liveness_without_version_falls_back_to_head(tmp_path):
    """提交标题认不出版本号时，停更告警按 HEAD 的日期照样算。"""
    import os
    import subprocess

    from gametext.core.snapshot import check_liveness, describe

    env = dict(os.environ, GIT_AUTHOR_DATE="2020-01-01T00:00:00+00:00", GIT_COMMITTER_DATE="2020-01-01T00:00:00+00:00",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "renamed title format"], cwd=tmp_path, env=env, check=True)
    u = Upstream(repo="r", branch="b", always=(), textmap_patterns=lambda langs: [],
                 version_re=re.compile(r"[A-Z]+Win(\d+\.\d+\.\d+)"), stale_days=30)
    info = describe(u, str(tmp_path), fetch=False)
    assert info["version"] is None
    warnings = check_liveness(u, str(tmp_path), info)
    assert any("2020-01-01" in w for w in warnings)
    assert any("找不到版本号" in w for w in warnings)


def test_case_clash_counts_only_checked_out_files(tmp_path):
    """只差大小写的同名文件在 sparse 没检出的目录里，不算完整性问题；在检出的目录里才算。"""
    import subprocess

    from gametext.core.snapshot import check_integrity

    def git(*args, **kw):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True, **kw).stdout

    git("init", "-q")
    blob = git("hash-object", "-w", "--stdin", input="x").strip()
    for path in ("Skip/a.json", "Skip/A.json", "Keep/b.json"):
        git("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, path))
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c")
    git("sparse-checkout", "set", "--no-cone", "/Keep/")
    assert not any("大小写" in w for w in check_integrity(str(tmp_path)))
    git("sparse-checkout", "set", "--no-cone", "/Keep/", "/Skip/")
    assert any("大小写" in w for w in check_integrity(str(tmp_path)))
