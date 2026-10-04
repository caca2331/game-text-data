"""文档检查（dev_tools/check_docs.py --public）：链接与锚点落地、公开文档不指进私有路径、plan 有状态块。"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_check_docs_public():
    r = subprocess.run([sys.executable, str(ROOT / "dev_tools" / "check_docs.py"), "-C", str(ROOT), "--public"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
