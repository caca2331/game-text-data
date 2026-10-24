"""完整性报告与硬性校验。

产出必须自带完整性报告（根 AGENTS.md 取数原则 4）。以下任一项异常时
`hard_failures` 非空，CLI 以非零退出码结束。
"""

from __future__ import annotations

import json

from ..core import report as core_report
from . import textmap
from .contract import CONTRACTS
from .emit import OUTPUTS, TERM_MAX_CHARS

# 已定性、不视为异常的缺口，写进报告备查。
KNOWN_GAPS = {
    "unreferenced_sentences": {
        "note": "约 32.6% 的台词在**整个上游仓库里**都找不到任何引用。已定性："
                "其中 44.8% 的语音类型是 StoryNew（过场演出配音），驱动它们的 "
                ".playable 时间轴文件不在上游仓库里；92.5% 的 id 与某条已引用台词"
                "同前缀，即属于我们已经拿到的那些场景。它们随全量台词表 sentences_* "
                "输出（sources 为空），不做连号归组。见 docs/starrail/data-source.md。",
    },
    "config_gameplays_not_in_sparse": {
        "note": "sparse 只取 Config/Level 省 900 MB，代价是丢掉 Config/Gameplays "
                "等处约 1100 条引用，是有意的取舍",
    },
    "stages_has_no_dialogue": {
        "note": "上游顶层还有 Stages/（3469 个文件），实测引用台词 0 条，"
                "故意不纳入 sparse",
    },
    "dangling_sentence_refs": {
        "note": "约 6700 个 id 被脚本引用、台词表里却没有（第一版数到 3852 个，已定性；"
                "补回活动/教程脚本后多出的约 2800 个没做跨版本对照）。定性结论：它们在 3.8.0 的"
                "台词表里**也不存在**，而该表 8 个月里 0 条被删——所以不是被删的内容，"
                "是上游脚本引用了从未发布过的台词。43% 与真实台词同场景前缀。"
                "明细见 build/index/dangling.json",
    },
    "non_mission_dialogue_has_no_quest": {
        "note": "任务外对话（约 1.4 万个脚本，含任务根目录下归不了属的活动/教程目录）"
                "本来就不属于任何任务。能给的归属是"
                "location（由路径里的 FloorID 查 MazePlane 得到，覆盖约三成）与"
                "interact_title（由 DialogueNPC/DialogueProp 的 ActPath 查得）",
    },
    "message_text_override_not_applied": {
        "note": "MessageItemTextOverride 有 26 条按任务进度替换短信正文的规则，"
                "条件表达式未解析，短信输出取的是默认正文",
    },
}


def build(snapshot, index_stats, assemble_stats, emit_result, out_path):
    per_lang = emit_result["per_lang"]
    counts = {lang: per_lang[lang]["rows"] for lang in textmap.LANGS}

    hard = []
    if len(set(counts.values())) != 1:
        hard.append("多语种行数不一致: %s" % counts)
    for name in OUTPUTS:
        if not emit_result["stats"].get(name + "_aligned"):
            hard.append("%s 多语种逐行 id 不一致" % name)
        c = {lang: per_lang[lang].get(name + "_rows", 0) for lang in textmap.LANGS}
        if len(set(c.values())) != 1:
            hard.append("%s 多语种行数不一致: %s" % (name, c))
    written = index_stats.get("missions_written", 0)
    excel = index_stats.get("excel_main_missions", 0)
    if written < excel:
        hard.append("输出任务 %d 少于上游 %d" % (written, excel))
    if index_stats.get("failures", 0):
        hard.append("index 阶段有 %d 条未解析记录，见 build/unparsed.jsonl"
                    % index_stats["failures"])

    warnings = list(snapshot.get("liveness_warnings") or [])
    # 快照被 purge 掉 .git 时，这里会带上"这次没做完整性检查"的说明
    warnings.extend(snapshot.get("integrity_warnings") or [])
    # 阈值按 4.5.0 实测基线略放宽，用途是抓回归而非重复报告已知事实。
    # 基线（"各语种均无"口径）：台词 0.00%、任务名 2.94%、步骤 6.16%。
    # 步骤那 6% 是 SubMission 的 TargetText/DescrptionText 本身有缺失。
    for lang in textmap.LANGS:
        p = per_lang[lang]
        for kind, limit in (("text", 0.01), ("name", 0.05), ("step", 0.08),
                            # 短信正文的基线是 1.35%（上游有 182 条 MainText
                            # 指向不存在的 hash）加上部分联系人没有签名
                            ("message", 0.04), ("option", 0.02),
                            ("location", 0.15)):
            n = p.get(kind + "_lookups", 0)
            if not n:
                continue
            rate = p.get(kind + "_absent_upstream", 0) / n
            if rate > limit:
                warnings.append(
                    "%s 的 %s 文本在上游各语种均无，占比 %.2f%%，超过阈值 %.0f%%"
                    % (lang, kind, 100 * rate, 100 * limit))

    contract = emit_result.get("contract") or {}
    contract_hard, contract_warnings = core_report.contract_findings(CONTRACTS, contract, textmap.LANGS[0])
    hard.extend(contract_hard)
    warnings.extend(contract_warnings)

    report = {
        "upstream": snapshot,
        "extractor": core_report.extractor_version("starrail"),
        "index": index_stats,
        "assemble": assemble_stats,
        "emit": emit_result["stats"],
        "per_lang": per_lang,
        "known_gaps": KNOWN_GAPS,
        "contract": core_report.contract_section(CONTRACTS, contract),
        "hard_failures": hard,
        "warnings": warnings,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


def summarize(report) -> str:
    lines = []
    up = report["upstream"]
    lines.append("上游 %s @ %s" % (up.get("version") or "?",
                                 (up.get("commit") or "")[:10]))
    ex = report.get("extractor") or {}
    lines.append("提取代码 %s%s" % ((ex.get("git_head") or "?")[:10],
                                  " +dirty（未提交的改动产的）" if ex.get("dirty") else ""))
    for w in up.get("liveness_warnings") or []:
        lines.append("  [上游存活] %s" % w)
    for lang in textmap.LANGS:
        p = report["per_lang"][lang]

        def rate(kind):
            n = p.get(kind + "_lookups", 0)
            return 100 * p.get(kind + "_unresolved", 0) / n if n else 0.0

        lines.append("  %-4s 行 %-6d 对话 %-7d 无对话任务 %d"
                     % (lang, p.get("rows", 0), p.get("dialog_nodes", 0),
                        p.get("missions_without_dialogue", 0)))
        lines.append("       未解析: 台词 %.2f%%  任务名 %.2f%%  步骤 %.2f%%"
                     "   (上游缺译 %d，各语种均无 %d)"
                     % (rate("text"), rate("name"), rate("step"),
                        sum(p.get(k + "_untranslated", 0)
                            for k in ("text", "name", "step", "speaker")),
                        sum(p.get(k + "_absent_upstream", 0)
                            for k in ("text", "name", "step", "speaker"))))
    idx = report.get("index", {})
    asm = report.get("assemble", {})
    lines.append("  归属: %d 条台词引用归到 %d 个任务；未归属 %d，悬空 %d"
                 % (idx.get("talk_refs_attributed", 0),
                    idx.get("missions_with_dialogue", 0),
                    idx.get("talk_refs_unattributed", 0),
                    idx.get("talk_refs_dangling", 0)))
    lines.append("  台词覆盖: %d/%d = %.1f%%（任务 %d + 任务外 %d），"
                 "全上游都无人引用 %d"
                 % (idx.get("sentences_referenced", 0), idx.get("sentences", 0),
                    100 * idx.get("sentence_coverage", 0.0),
                    idx.get("mission_refs", 0), idx.get("dialogue_refs", 0),
                    idx.get("sentences_unreferenced", 0)))
    lines.append("  任务外对话: %d 个脚本 / %d 个事件；带区域名 %d，带交互标题 %d"
                 % (idx.get("dialogue_scripts", 0), asm.get("dialogue_nodes", 0),
                    idx.get("dialogue_with_plane", 0),
                    idx.get("dialogue_with_interact_title", 0)))
    lines.append("       来源 top: %s"
                 % "、".join("%s(%d)" % (k.rsplit("/", 1)[-1], v) for k, v in
                             list((idx.get("dialogue_scripts_by_bucket") or {}).items())[:5]))
    lines.append("  悬空引用: %d 个 id / 被引用 %d 次（上游脚本引用了从未发布的台词，"
                 "见 build/index/dangling.json）"
                 % (idx.get("dangling_sentence_ids", 0), idx.get("dangling_refs", 0)))
    lines.append("  短信: %d 组 / %d 条 / %d 处分支；联系人 %d"
                 % (idx.get("message_groups", 0), idx.get("message_lines", 0),
                    idx.get("message_branches", 0), idx.get("message_contacts", 0)))
    lines.append("  选项带回答: %d（第一版这批全丢了）"
                 % asm.get("option_with_reply", 0))
    lines.append("  全量台词表: %d 句，其中 %d 句没有脚本引用（sources 为空，多为过场时间轴）"
                 % (asm.get("sentence_rows", 0), asm.get("sentence_rows_unreferenced", 0)))
    lines.append("  配音标记（台词表）: voiced %d / generic %d / unvoiced %d / unknown %d"
                 "（generic = 挂的全是被不同台词共用的泛用语音，%d 段；短信一律 unknown）"
                 % (*(idx.get("sentence_voice_" + k, 0) for k in ("voiced", "generic", "unvoiced", "unknown")),
                    idx.get("generic_voice_clips", 0)))
    p0 = report["per_lang"][textmap.LANGS[0]]
    lines.append("  玩家起名的占位（textjoins，{TEXTJOIN#n}）: %d 个；候选查不到 %s"
                 % (p0.get("textjoins_rows", 0),
                    "、".join("%s %d" % (lang, report["per_lang"][lang].get("textjoin_item_unresolved", 0))
                             for lang in textmap.LANGS)))
    lines.append("  短名词（terms，CHS ≤%d 字）: %d 条；各语种缺译 %s"
                 % (TERM_MAX_CHARS, report["per_lang"][textmap.LANGS[0]].get("terms_rows", 0),
                    "、".join("%s %d" % (lang, report["per_lang"][lang].get("terms_missing", 0))
                             for lang in textmap.LANGS)))
    for w in report["warnings"]:
        lines.append("  [警告] %s" % w)
    lines.append(core_report.contract_line(report))
    for h in report["hard_failures"]:
        lines.append("  [失败] %s" % h)
    if not report["hard_failures"]:
        lines.append("  完整性校验通过")
    return "\n".join(lines)
