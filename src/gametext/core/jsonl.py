"""产物的读写：JSONL，可选 zstd 压缩。

**格式选择的依据（实测，不是拍脑袋）：**

- 压缩比：`zstd -3` 把 851 MB 的产出压到 118 MB（14%）。`-1` 是 16%、`-9` 是 12%
  但慢 4 倍，`gzip -1` 比 `zstd -3` 又大又慢。所以固定用 **level 3**。
- **语料目录里分文件压。** 实测整包 `tar.zst` 反而比逐文件压**大 0.22%**（tar 头和
  对齐的开销超过了跨文件共享上下文的收益），而逐文件保留了"只读某个语种/某类产物"
  的随机访问能力。搬运用的包是另一层投影：`bundle` 把语料目录原样装进一个 zip
  （成员不再压缩），带清单与哈希，见 `bundle.py`。
- 读端一律走 `open_read`，它**优先找 `.zst`、其次找原始文件**，所以开不开压缩对
  下游是透明的。
"""

from __future__ import annotations

import io
import json
import os

import zstandard

LEVEL = 3


def open_write(path: str, compress: str = "zstd"):
    """打开产物用于写。`compress="zstd"` 时实际写的是 `path + ".zst"`。"""
    if compress == "none":
        return open(path, "w", encoding="utf-8")
    if compress != "zstd":
        raise ValueError("compress 只能是 none / zstd，收到 %r" % compress)
    raw = open(path + ".zst", "wb")
    writer = zstandard.ZstdCompressor(level=LEVEL).stream_writer(raw)
    return io.TextIOWrapper(writer, encoding="utf-8", write_through=True)


def out_path(path: str, compress: str = "zstd") -> str:
    return path if compress == "none" else path + ".zst"


def open_read(path: str):
    """打开产物用于读：**先找 `.zst`，再找原始文件**，对下游透明。"""
    if os.path.exists(path + ".zst"):
        raw = open(path + ".zst", "rb")
        reader = zstandard.ZstdDecompressor().stream_reader(raw)
        return io.TextIOWrapper(reader, encoding="utf-8")
    return open(path, encoding="utf-8")


def exists(path: str) -> bool:
    return os.path.exists(path) or os.path.exists(path + ".zst")


def iter_rows(path: str):
    """逐行读回 JSONL；文件不在就产出空序列（调用方自己判断要不要报错）。"""
    if not exists(path):
        return
    with open_read(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def cleanup_stale(path: str, compress: str = "zstd") -> None:
    """删掉另一种形态的旧产物。

    不删的话，从压缩切回不压缩（或反过来）会在语料目录里留下上一次的文件，
    而 `open_read` 优先读 `.zst`——于是下游拿到的是**上一次跑的结果**，还看不出来。
    """
    stale = path if compress != "none" else path + ".zst"
    if os.path.exists(stale):
        os.remove(stale)
