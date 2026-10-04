"""完整性报告与硬性校验。"""

from __future__ import annotations

import json

from ..core import report as core_report
from . import textmap
from .contract import CONTRACTS
from .emit import OUTPUTS, TERM_MAX_CHARS

# 已定性、不视为异常的缺口，写进报告备查。
KNOWN_GAPS = {
    "dialogue_branch_absent_upstream": {
        "note": "GalGame / Chat 的选项与跳转在 Perform 脚本资源里，而上游仓库**没有** "
                "Data/ScriptConfig/ 这个目录——PerformTemplateTb 只给资源路径，脚本本体不在。"
                "这是上游边界，不是解析没做。短信系统是唯一有完整分支图的对话，已产出。",
    },
    "scene_quest_link_partial": {
        "note": "场景→任务只能由 FileCfg 里同时引用两者的『桥表』给出（ArchiveFileQuest "
                "等），覆盖不到全部场景。没有桥表的场景 quests 为空数组，不臆造关联。"
                "已查证过三条可能的补路，全部不通：MainCityQuest 没有指向 Perform 的"
                "字段；它经 MainCityObject / InteractData 再跳一层也到不了 Perform；"
                "447 条已验证边里场景 id 与任务 id 的编号毫无关系（无法推断）。"
                "触发关系应在 Perform 脚本资源里，而那部分不在上游仓库。",
    },
    "auto_event_keys_have_no_config": {
        "note": "AutoEvent100000_26 这类 key 在整个 FileCfg 里搜不到任何引用，"
                "上游没有对应配置表，成不了场景；随 loose_* 输出，group/seq 取自 key "
                "（事件号 + 序号）",
    },
    "comic_keys_unordered": {
        "note": "漫画过场 Comic_<32 位 hash>（约 2400 条）在整个 FileCfg 里没有引用，"
                "key 里也没有顺序；随 loose_* 输出，是无序散句",
    },
    "scene_speaker_is_cast_not_per_line": {
        "note": "_Name_NNN 是场景的出场角色表（9419/9438 个场景的序号严格 1..k 连续、名字"
                "互不重复），不是逐行说话人。逐行说话人在 Perform 脚本里，脚本不在上游仓库；"
                "场景只给 cast，行上没有 speaker",
    },
    "quest_config_rows_without_text": {
        "note": "QuestConfigTemplateTb 的行数（约 1.9 万）多于有文本的任务，多出来的行"
                "引用的 TextMap key 在上游根本不存在（废弃/未上线内容），不进产出",
    },
}


def build(snapshot, index_stats, emit_result, out_path):
    per_lang = emit_result["per_lang"]
    hard = []
    for what in OUTPUTS:
        counts = {lang: per_lang[lang].get(what + "_rows", 0) for lang in textmap.LANGS}
        if len(set(counts.values())) != 1:
            hard.append("%s 多语种行数不一致: %s" % (what, counts))
        if not emit_result["stats"].get(what + "_aligned"):
            hard.append("%s 多语种逐行 id 不一致" % what)

    warnings = list(snapshot.get("liveness_warnings") or [])
    warnings.extend(snapshot.get("integrity_warnings") or [])
    # 阈值按 3.2.0 实测基线设定，用途是抓回归而非重复报告已知事实
    limits = {"text": 0.02, "speaker": 0.05, "quest": 0.05, "option": 0.02,
              "title": 0.20, "intro": 0.20}
    for lang in textmap.LANGS:
        p = per_lang[lang]
        for kind, limit in limits.items():
            n = p.get(kind + "_lookups", 0)
            if not n:
                continue
            rate = p.get(kind + "_absent_upstream", 0) / n
            if rate > limit:
                warnings.append(
                    "%s 的 %s 文本在上游各语种均无，占比 %.2f%%，超过阈值 %.0f%%"
                    % (lang, kind, 100 * rate, 100 * limit))

    # FileCfg 的推断结果本身也要校验：任何一张表推断失败都是硬失败，
    # 因为"推断失败"和"推断出垃圾"外观相同，必须让它显式变红
    cfg = index_stats.get("filecfg") or {}
    for label, info in cfg.items():
        if isinstance(info, dict) and info.get("failed"):
            hard.append("FileCfg %s 表推断失败: %s" % (label, info["failed"]))

    contract = emit_result.get("contract") or {}
    contract_hard, contract_warnings = core_report.contract_findings(CONTRACTS, contract, textmap.LANGS[0])
    hard.extend(contract_hard)
    warnings.extend(contract_warnings)

    report = {
        "upstream": snapshot,
        "extractor": core_report.extractor_version("zzz"),
        "index": index_stats,
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


def summarize(report):
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

        lines.append("  %-4s 场景 %-6d 台词 %-7d 任务 %-6d 短信组 %-5d 短信 %-6d"
                     % (lang, p.get("scenes_rows", 0), p.get("lines", 0),
                        p.get("quests_rows", 0), p.get("messages_rows", 0),
                        p.get("message_lines", 0)))
        lines.append("       未解析: 台词 %.2f%%  说话人 %.2f%%  任务 %.2f%%  选项 %.2f%%"
                     "   (上游缺译 %d，各语种均无 %d)"
                     % (rate("text"), rate("speaker"), rate("quest"), rate("option"),
                        sum(p.get(k + "_untranslated", 0)
                            for k in ("text", "speaker", "quest", "option")),
                        sum(p.get(k + "_absent_upstream", 0)
                            for k in ("text", "speaker", "quest", "option"))))

    idx = report.get("index", {})
    lines.append("  索引: %d 个场景 / %d 条台词，带出场角色表的场景 %d；任务 %d 个"
                 % (idx.get("scenes", 0), idx.get("scene_lines", 0),
                    idx.get("scenes_with_cast", 0), idx.get("quests", 0)))
    lines.append("  散条目（loose）: %d 条，其中能按 key 分组的 %d；按原因 %s"
                 % (idx.get("loose", 0), idx.get("loose_grouped", 0),
                    idx.get("loose_by_reason", {})))

    cfg = idx.get("filecfg") or {}
    perform = cfg.get("perform") or {}
    if perform.get("rows"):
        lines.append("  FileCfg: Perform %d 行，覆盖 %.1f%% 的长场景 id；"
                     "场景带元信息 %d，其中能连到任务 %d"
                     % (perform["rows"], 100 * perform.get("scene_id_coverage", 0),
                        idx.get("scenes_with_perform", 0),
                        idx.get("scenes_with_quest", 0)))
        kinds = perform.get("kinds") or {}
        lines.append("       场景类型: %s"
                     % "  ".join("%s %d" % kv for kv in list(kinds.items())[:6]))
    edges = cfg.get("scene_quest_edges") or {}
    if edges.get("sources"):
        top = "、".join("%s(%d)" % (s["table"].replace("TemplateTb.json", ""),
                                   s["edges"]) for s in edges["sources"][:4])
        lines.append("       场景↔任务边 %d 条，来自 %d 张桥表：%s"
                     % (edges.get("edges", 0), len(edges["sources"]), top))
    msg = cfg.get("messages") or {}
    if msg.get("groups"):
        lines.append("       短信 %d 组 / %d 个分支节点 / %d 条选项，关联到任务的组 %d；"
                     "跳转落空 %d"
                     % (msg["groups"], idx.get("message_nodes", 0),
                        idx.get("message_options", 0),
                        idx.get("message_groups_with_quest", 0),
                        msg.get("dangling_goto_steps", 0)))
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
