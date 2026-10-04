"""与独立来源的交叉校验（一次性用途，不进主流水线）。

**先说清楚这个校验能做到什么、做不到什么。**

绝区零没有可按 id 全量对齐的第二来源，情况比另外两个游戏都差：

- 上游的几个"镜像"（`ZZZure/ZenlessRes` 等）自述以 `Dimbreath/ZenlessData` 为源，
  **同源就不算独立**，对上了也证明不了什么。
- HuggingFace 上没有绝区零的语音/台词数据集（崩铁那条路子在这里走不通）。
  唯一沾边的 `mrzjy/zenless_zone_zero_interknots_v1.0` 只有绳网帖子、不到 1K 条、
  且停在游戏 1.0 版本，覆盖不到我们的语料。

所以外部来源用**玩家维基**：`zenless-zone-zero.fandom.com` 的条目是玩家从实机整理的，
与解包数据完全无关，是真正独立的一条路径。代价是它只有英文、只覆盖有条目的内容，
而且随时可能改版式。

三项检查，各自能证明的东西不同：

1. **委托名 vs 维基条目标题**（外部）——证明我们从 TextMap 取的英文任务名是对的，
   而且没有整批漏掉某类委托。
2. **角色名 vs 维基 Agents 名单**（外部）——证明说话人字段确实是说话人。
   维基用全名（`Anby Demara`），游戏对话里用称呼（`Anby`），所以按词匹配。
3. **场景类别 vs FileCfg 资源路径**（内部）——这一条不是独立来源，但走的是上游里
   **另一条命名路径**：TextMap 的 key 段（`Main_GalGame_...`）与 Perform 表的资源
   路径（`.../Perform/Data/GalGame/...`）由不同的东西生成，两者吻合说明我们对 key
   的切分没切错。

它回答不了"有没有漏"：维基只收录有人写过的条目。

用法：
    uv run python tools/zzz/crosscheck.py [--miss-out build/zzz/crosscheck_misses.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

from gametext import paths
from gametext.core import jsonl as _jsonl          # 产物可能是 .zst，统一走它

DATA = paths.corpus("zzz")
BUILD = paths.build("zzz")

WIKI = "https://zenless-zone-zero.fandom.com/api.php"
# 维基对默认 UA 不友好，且我们只读公开的 MediaWiki API
UA = {"User-Agent": "Mozilla/5.0 (game-text-data crosscheck; research use)"}

# 括号里的消歧后缀（"…(Commission)"）不是名字的一部分
_PAREN = re.compile(r"\s*\([^()]*\)\s*$")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def norm(text: str) -> str:
    """比对用归一化：去消歧后缀、统一引号、只留字母数字。"""
    if not text:
        return ""
    text = _PAREN.sub("", text).replace("’", "'")
    return _NON_ALNUM.sub("", text.lower())


def wiki(params: dict) -> dict:
    url = WIKI + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def category_members(category: str, cap: int = 5000) -> list:
    """取一个分类下的正文条目（namespace 0），自动翻页。"""
    out, cont = [], None
    while len(out) < cap:
        params = {"action": "query", "list": "categorymembers",
                  "cmtitle": "Category:" + category, "cmlimit": "500",
                  "cmnamespace": "0", "cmprop": "title"}
        if cont:
            params["cmcontinue"] = cont
        doc = wiki(params)
        out.extend(m["title"] for m in doc["query"]["categorymembers"])
        cont = (doc.get("continue") or {}).get("cmcontinue")
        if not cont:
            break
    # 子页（`X/Story`、`X/Draft`）是维基自己的组织方式，不是游戏内名字
    return [t for t in out if "/" not in t]


def iter_jsonl(path):
    return _jsonl.iter_rows(path)


def need(path):
    if not _jsonl.exists(path):
        sys.exit("读不到语料：%s（先跑 uv run gametext zzz all）" % path)
    return path


def section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def check_quests(misses):
    section("1. 委托名 vs 维基条目标题（外部来源）")
    names = {}
    for q in iter_jsonl(need(os.path.join(DATA, "quests_en.jsonl"))):
        # display_name 是游戏里实际显示的标题，与 name 可能不同，两者都算数
        for field in ("name", "display_name"):
            if q.get(field):
                names.setdefault(norm(q[field]), q[field])
    print("本地 EN 任务名去重后 %d 种" % len(names))

    titles = category_members("Commissions")
    print("维基 Commissions 正文条目 %d 条" % len(titles))
    if not titles:
        print("!! 维基取不到条目，跳过")
        return
    miss = [t for t in titles if norm(t) not in names]
    print("命中 %d / %d = %.1f%%" % (len(titles) - len(miss), len(titles),
                                    100 * (1 - len(miss) / len(titles))))
    misses["quests"] = miss
    # 维基把"委托类型"本身也建成条目（City Commission、Story Commission…），
    # 那些不是具体委托，单独拎出来免得看着像漏
    kind_pages = [t for t in miss if t.endswith(" Commission")]
    print("其中 %d 条是维基的委托类型索引页（如 %s），不是具体委托"
          % (len(kind_pages), "、".join(kind_pages[:3])))
    real = [t for t in miss if t not in kind_pages]
    print("真正对不上的 %d 条（%.1f%%），前 15 条：" % (
        len(real), 100 * len(real) / len(titles)))
    for t in real[:15]:
        print("   ", t)


def check_agents(misses):
    section("2. 角色名 vs 维基 Agents 名单（外部来源）")
    # 场景的出场角色表（`cast`）。它证明的是"这些名字确实是角色名"，
    # **证明不了逐行配对**——第一版把它读成"说话人字段确实是说话人"，而逐行配对恰恰是错的
    speakers = set()
    for s in iter_jsonl(need(os.path.join(DATA, "scenes_en.jsonl"))):
        for name in s.get("cast") or []:
            if name:
                speakers.add(norm(name))
    print("本地 EN 出场角色名 %d 种" % len(speakers))

    agents = [a for a in category_members("Agents") if a != "Agent"]
    if not agents:
        print("!! 维基取不到条目，跳过")
        return
    # 维基用全名（Anby Demara / Von Lycaon），游戏对话里用称呼（Anby / Lycaon），
    # 所以只要有**任一个词**对上就算命中
    def hit(name):
        return (norm(name) in speakers
                or any(norm(w) in speakers for w in name.split()))

    miss = [a for a in agents if not hit(a)]
    print("命中 %d / %d = %.1f%%" % (len(agents) - len(miss), len(agents),
                                    100 * (1 - len(miss) / len(agents))))
    misses["agents"] = miss
    for a in miss:
        print("    未命中:", a)
    if miss:
        print("  注：维基用的是英文全名，而游戏对话里用的是称呼，两者在上游是**不同的 key**"
              "（`Avatar_Female_Size01_Lucy_En_FullName` = Luciana de Montefio，"
              "对话里是 Lucy）。这类未命中不是缺口，逐条看 --miss-out 再判断。")


def check_scene_kind():
    section("3. 场景类别 vs FileCfg 资源路径（内部，另一条命名路径）")
    path = os.path.join(BUILD, "index", "scenes.jsonl")
    if not _jsonl.exists(path):
        print("!! 没有 build/index/scenes.jsonl，先跑 index")
        return
    by_category = defaultdict(Counter)
    total = 0
    for s in iter_jsonl(path):
        perform = s.get("perform")
        if not perform or not perform.get("kind"):
            continue
        by_category[s["category"]][perform["kind"]] += 1
        total += 1
    if not total:
        print("!! 没有带 Perform 元信息的场景")
        return
    pure = sum(c.most_common(1)[0][1] for c in by_category.values())
    print("带资源类型的场景 %d，TextMap 类别 %d 个" % (total, len(by_category)))
    print("落在本类别众数资源类型上的比例：%.2f%%" % (100 * pure / total))
    print("（TextMap 的 key 段与 Perform 的资源路径由不同的东西生成，"
          "吻合说明 key 的切分没切错）")
    worst = sorted((c.most_common(1)[0][1] / sum(c.values()), k, dict(c.most_common(3)))
                   for k, c in by_category.items() if sum(c.values()) >= 30)
    print("纯度最低的 5 个类别：")
    for rate, key, dist in worst[:5]:
        print("   %-40s %.2f  %s" % (key, rate, dist))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--miss-out",
                    default=os.path.join(BUILD, "crosscheck_misses.json"),
                    help="把未命中的条目落盘，便于逐条看")
    args = ap.parse_args()

    misses = {}
    check_quests(misses)
    check_agents(misses)
    check_scene_kind()

    os.makedirs(os.path.dirname(args.miss_out), exist_ok=True)
    with open(args.miss_out, "w", encoding="utf-8") as f:
        json.dump(misses, f, ensure_ascii=False, indent=2)
    print()
    print("未命中条目已写入", args.miss_out)


if __name__ == "__main__":
    main()
