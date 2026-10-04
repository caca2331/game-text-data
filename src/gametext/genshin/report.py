"""genshin 的完整性报告与硬性校验（公共部分在 `gametext.core.report`）。

以下任一项异常时 `hard_failures` 非空，CLI 以非零退出码结束。
"""

from __future__ import annotations

import json

from ..core import report as core_report
from . import emit as emit_mod
from . import textmap
from .contract import CONTRACTS

# 已知且已定性的缺口，写进报告备查，不算失败。定性见 docs/genshin/architecture.md。
KNOWN_GAPS = {
    "talk_group_containers": {
        "note": "BinOutput/Talk 下的 *Group 目录是 talk 容器而非对话列表，"
                "整批判为 no text field 并计入 failures_expected，不产出节点",
    },
    "inferred_attribution": {
        "note": "没有任务显式引用的 talk 按 talkId 前缀推测归属，节点上标 "
                "attribution=inferred，下游可自行过滤",
    },
    "reminder_not_linked_to_quest": {
        "note": "reminders_* 是 ReminderExcelConfigData 的语音字幕链（边玩边说的对白），"
                "由任务 / 关卡脚本触发，触发关系没解析，所以不挂到任务上；id 空间很小"
                "（1003 这种），按数值去 Quest 里撞会撞出假关联，宁可不挂",
    },
    "non_quest_talks_not_emitted": {
        "note": "约 1.67 万个不归属任何任务的 talk（NPC 闲聊 1.37 万、Gadget、Coop、Activity…）"
                "在 build/index/talks.jsonl 里有，但不进产物。7.0.0 上拿游戏直播量过："
                "五段视频合计只多圈到 11 条屏幕文本，不值一份产物",
    },
}


def build(snapshot, index_stats, assemble_stats, emit_result, out_path):
    per_lang = emit_result["per_lang"]
    hard = []
    for what, key in (("quests", "rows"), ("reminders", "reminders_rows"), ("terms", "terms_rows")):
        counts = {lang: per_lang[lang].get(key, 0) for lang in textmap.LANGS}
        if len(set(counts.values())) != 1:
            hard.append("%s 各语种行数不一致: %s" % (what, counts))
        if not emit_result["stats"].get(what + "_aligned"):
            hard.append("%s 各语种逐行 id 不一致" % what)
    # 语音字幕链：推断失败走 unparsed（非预期失败，下面那条会红）；无头的环在 index 里
    # 单独成链、计 reminder_cycles，不会静默丢（所以这里没有"没走到的 id"这条判据）

    written = index_stats.get("quests_written", 0)
    excel = index_stats.get("excel_main_quests", 0)
    if written < excel:
        hard.append("输出主任务 %d 少于上游 %d" % (written, excel))
    unexpected = index_stats.get(
        "failures_unexpected", index_stats.get("failures", 0))
    if unexpected:
        hard.append(
            "index 阶段有 %d 条**非预期**未解析记录，见 build/unparsed.jsonl"
            % unexpected
        )

    contract = emit_result.get("contract") or {}
    contract_hard, contract_warnings = core_report.contract_findings(CONTRACTS, contract, textmap.LANGS[0])
    hard.extend(contract_hard)

    # 上游存活检测的结果一并进报告：这类问题（上游搬家、停更）不会让任何
    # 数字变难看，只会让语料悄悄停在旧版本，必须显式摆出来。
    warnings = list(snapshot.get("liveness_warnings") or [])
    # 快照被 purge 掉 .git 时，这里会带上"这次没做完整性检查"的说明
    warnings.extend(snapshot.get("integrity_warnings") or [])
    warnings.extend(contract_warnings)
    for lang in textmap.LANGS:
        # 阈值按 6.6.0 实测基线略放宽，用途是抓**回归**而不是重复报告已知事实。
        # 基线（"上游四语种均无"口径）：对话 0.00%、标题 2.85%、描述 16.10%、
        # 步骤 <0.1%、章节 0%。描述那 16% 主要是 $HIDDEN / test 脚手架任务，
        # 上游本就没写描述。
        # reminder 的基线（7.0.0）：上游各语种均无 0.39%（72/18 396）
        for kind, limit in (("dialog", 0.01), ("title", 0.05),
                            ("desc", 0.20), ("step", 0.02), ("meta", 0.02),
                            ("reminder", 0.02)):
            lookups = per_lang[lang].get(kind + "_lookups", 0)
            if not lookups:
                continue
            # 只看"四语种都查不到"的部分：缺译是上游的既成事实，报警没有意义
            rate = per_lang[lang].get(kind + "_absent_upstream", 0) / lookups
            if rate > limit:
                warnings.append(
                    "%s 的 %s 文本在上游四语种均无，占比 %.2f%%，超过阈值 %.0f%%"
                    % (lang, kind, 100 * rate, 100 * limit)
                )

    report = {
        "upstream": snapshot,
        "extractor": core_report.extractor_version("genshin"),
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
    lines.append("上游 %s @ %s" % (up.get("version") or "?", (up.get("commit") or "")[:10]))
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
        lines.append(
            "  %-4s 行 %-6d 对话 %-7d 空对话任务 %d" %
            (lang, p.get("rows", 0), p.get("dialog_nodes", 0),
             p.get("quests_without_dialog", 0))
        )
        def part(suffix):
            return sum(p.get(k + suffix, 0)
                       for k in ("dialog", "title", "desc", "step", "meta"))
        lines.append(
            "       未解析: 对话 %.2f%%  标题 %.2f%%  描述 %.2f%%  步骤 %.2f%%"
            "   (其中上游缺译 %d，上游四语种均无 %d)"
            % (rate("dialog"), rate("title"), rate("desc"), rate("step"),
               part("_untranslated"), part("_absent_upstream"))
        )
    idx = report.get("index", {})
    lines.append(
        "  归属: 显式 %d 条对话 / 推测 %d 条；未归属 talk %d 个；任务引用的 talk 不存在 %d 个"
        % (report.get("assemble", {}).get("dialog_explicit", 0),
           report.get("assemble", {}).get("dialog_inferred", 0),
           idx.get("talk_orphans", 0) - idx.get("talk_attributed_by_prefix", 0),
           idx.get("quest_talk_dangling", 0))
    )
    p0 = report["per_lang"][textmap.LANGS[0]]
    lines.append(
        "  语音字幕（reminders）: %d 条链 / %d 行，悬空 next %d，环 %d，"
        "汇合点 %d（汇合的链各带一份尾巴，reminder_id 在产物里不唯一）"
        % (p0.get("reminders_rows", 0), p0.get("reminder_lines", 0),
           idx.get("reminder_dangling_next", 0), idx.get("reminder_cycles", 0),
           idx.get("reminder_merge_points", 0)))
    lines.append(
        "  配音标记（reminders，按表行）: voiced %d / unvoiced %d / unknown %d；任务对话一律 unknown"
        % tuple(idx.get("reminder_voice_" + k, 0) for k in ("voiced", "unvoiced", "unknown")))
    lines.append(
        "  短名词（terms，CHS ≤%d 字）: %d 条；各语种缺译 %s"
        % (emit_mod.TERM_MAX_CHARS, p0.get("terms_rows", 0),
           "、".join("%s %d" % (lang, report["per_lang"][lang].get("terms_missing", 0))
                    for lang in textmap.LANGS)))
    lines.append(core_report.contract_line(report))
    lines.append(
        "  未解析: 预期内 %d（*Group 容器目录）/ 非预期 %d"
        % (idx.get("failures_expected", 0), idx.get("failures_unexpected", 0))
    )
    for w in report["warnings"]:
        lines.append("  [警告] %s" % w)
    for h in report["hard_failures"]:
        lines.append("  [失败] %s" % h)
    if not report["hard_failures"]:
        lines.append("  完整性校验通过")
    return "\n".join(lines)
