#!/usr/bin/env python3
"""Read-only runner for the persisted major-rule cases.

    python3 data/run_major_rule_tests.py

Opens curriculum.sqlite with mode=ro and query_only. It does not insert, update,
or delete. It rewrites the two markdown reports from the live counts and the
test result.

    python3 data/run_major_rule_tests.py --write-catalog

Rebuilds data/major_rule_tests.json from the hand-written cases plus one
standard case set for every other live rule. That command also leaves the
database unchanged.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curriculum.sqlite"
TESTS_PATH = ROOT / "data" / "major_rule_tests.json"
REPORT_PATH = ROOT / "data" / "major_rule_test_report.md"
SUPERSEDED_LEGACY_IDS = (19, 21, 23, 27, 28, 31)


def open_readonly():
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def rule_signature(rule: dict) -> str:
    tokens = []
    for item in rule["items"]:
        if item["item_type"] == "course":
            tokens.append("course:" + item["course_id"])
        elif item["item_type"] == "one_of":
            tokens.append("one_of:" + ",".join(item["course_ids"]))
        elif item["item_type"] == "child_rule":
            tokens.append("child:" + str(item["child_rule_id"]))
        else:
            tokens.append(item["item_type"])
    constraints = []
    for constraint in rule.get("constraints") or []:
        constraints.append(
            "|".join(
                str(constraint.get(key))
                for key in ("constraint_type", "value", "group", "min_level", "max_level", "department")
            )
        )
    return "||".join(
        [
            str(rule["major"]),
            str(rule["operator"]),
            str(rule["required_count"]),
            str(rule["required_credits"]),
            str(rule["status"]),
            ";".join(tokens),
            ";".join(constraints),
        ]
    )


def listed_courses(rule: dict) -> list[str]:
    seen = []
    for item in rule["items"]:
        course_id = item.get("course_id")
        if item["item_type"] == "course" and course_id and course_id not in seen:
            seen.append(course_id)
    return seen


def standard_case_specs(rule: dict) -> list[tuple[str, list[str], dict]]:
    if any(item["item_type"] == "child_rule" for item in rule["items"]):
        raise SystemExit(f"规则 {rule['rule_id']} 含有子规则，没有手工案例")
    if rule.get("constraints"):
        raise SystemExit(f"规则 {rule['rule_id']} 含有附加条件，没有手工案例")
    courses = listed_courses(rule)
    if rule["status"] == "blocked":
        return [
            ("empty", [], {"status": "blocked"}),
            ("listed_or_unrelated", courses or ["MATH101"], {"status": "blocked"}),
        ]
    if rule["operator"] == "ADVISORY":
        return [
            ("empty", [], {"status": "not_applicable"}),
            ("unrelated_course", ["MATH101"], {"status": "not_applicable"}),
        ]
    if rule["operator"] == "ALL":
        if not courses:
            raise SystemExit(f"规则 {rule['rule_id']} 没有课程")
        return [
            ("all_courses", courses, {"status": "satisfied"}),
            ("one_short", courses[:-1], {"status": "unsatisfied"}),
        ]
    if rule["operator"] == "CHOOSE":
        need = rule["required_count"]
        if not isinstance(need, int) or need < 1 or len(courses) < need:
            raise SystemExit(f"规则 {rule['rule_id']} 的选择门数无法生成案例")
        return [
            ("exact_minimum", courses[:need], {"status": "satisfied"}),
            ("one_short", courses[: need - 1], {"status": "unsatisfied"}),
            ("outside_pool", ["ZZZ999"] * need, {"status": "unsatisfied"}),
        ]
    raise SystemExit(f"规则 {rule['rule_id']} 的 {rule['operator']} 没有手工案例")


def legacy_of(con, rule_id: int):
    row = con.execute("SELECT legacy_rule_id FROM major_rules WHERE rule_id = ?", (rule_id,)).fetchone()
    if row is None:
        raise SystemExit(f"规则 {rule_id} 不在现行表")
    return row[0]


def persist_catalog(con, hand_cases: list[dict]) -> list[dict]:
    from repair_high_risk_rules import load_rule_from_db

    stored = []
    covered = set()
    for case in hand_cases:
        rule = load_rule_from_db(con, case["rule_id"])
        if rule is None:
            raise SystemExit(f"手工案例指向不存在的规则 {case['rule_id']}")
        covered.add(case["rule_id"])
        stored.append(
            {
                "rule_id": case["rule_id"],
                "legacy_rule_id": legacy_of(con, case["rule_id"]),
                "major": case["major"],
                "case": case["case"],
                "completed_courses": case["completed_courses"],
                "expected": case["expected"],
                "origin": "hand",
                "signature": rule_signature(rule),
            }
        )
    for (rule_id,) in con.execute("SELECT rule_id FROM major_rules ORDER BY rule_id"):
        if rule_id in covered:
            continue
        rule = load_rule_from_db(con, rule_id)
        legacy_id = legacy_of(con, rule_id)
        if legacy_id in SUPERSEDED_LEGACY_IDS:
            raise SystemExit(f"被替代旧规则 {legacy_id} 仍在现行表")
        for name, completed, expected in standard_case_specs(rule):
            stored.append(
                {
                    "rule_id": rule_id,
                    "legacy_rule_id": legacy_id,
                    "major": rule["major"],
                    "case": name,
                    "completed_courses": completed,
                    "expected": expected,
                    "origin": "standard",
                    "signature": rule_signature(rule),
                }
            )
    TESTS_PATH.write_text(json.dumps(stored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stored


def run_cases(con, cases: list[dict]) -> tuple[list[dict], int]:
    from major_rule_engine import evaluate
    from repair_high_risk_rules import catalog_from, load_rule_from_db

    rules = {
        rule_id: load_rule_from_db(con, rule_id)
        for (rule_id,) in con.execute("SELECT rule_id FROM major_rules")
    }
    catalog = catalog_from(con)
    failed = []
    seen = set()
    for case in cases:
        seen.add(case["rule_id"])
        rule = rules.get(case["rule_id"])
        if rule is None:
            failed.append({**case, "actual_status": "missing", "actual_reason": "规则不在现行表"})
            continue
        if rule_signature(rule) != case["signature"]:
            failed.append({**case, "actual_status": "changed", "actual_reason": "规则内容与案例签名不一致"})
            continue
        result = evaluate(rule, case["completed_courses"], catalog, rules)
        expected = case["expected"]
        matched = result["status"] == expected["status"] and all(
            result.get(key) == value for key, value in expected.items() if key != "status"
        )
        if not matched:
            failed.append(
                {
                    **case,
                    "actual_status": result["status"],
                    "actual_reason": result.get("reason"),
                }
            )
    for rule_id in sorted(set(rules) - seen):
        failed.append(
            {
                "rule_id": rule_id,
                "case": "coverage",
                "expected": {},
                "actual_status": "untested",
                "actual_reason": "没有持久化案例",
            }
        )
    live_superseded = [
        row[0]
        for row in con.execute(
            "SELECT legacy_rule_id FROM major_rules WHERE legacy_rule_id IN (19, 21, 23, 27, 28, 31)"
        )
    ]
    if live_superseded:
        failed.append(
            {
                "rule_id": None,
                "case": "history",
                "expected": {},
                "actual_status": "still_live",
                "actual_reason": f"被替代规则仍在现行表：{live_superseded}",
            }
        )
    return failed, len(cases)


def live_facts(con) -> dict:
    completion = con.execute(
        """
        SELECT COUNT(*) FROM major_rules
        WHERE status = 'verified' AND operator != 'ADVISORY' AND counts_toward_completion = 1
        """
    ).fetchone()[0]
    advisory = con.execute(
        "SELECT COUNT(*) FROM major_rules WHERE operator = 'ADVISORY'"
    ).fetchone()[0]
    blocked = con.execute(
        "SELECT COUNT(*) FROM major_rules WHERE status = 'blocked'"
    ).fetchone()[0]
    partial = con.execute(
        "SELECT COUNT(*) FROM major_rules WHERE status = 'partial'"
    ).fetchone()[0]
    missing_page = con.execute(
        "SELECT COUNT(*) FROM major_rules WHERE source_page IS NULL"
    ).fetchone()[0]
    majors = con.execute(
        """
        SELECT COUNT(DISTINCT major) FROM major_rules
        WHERE status = 'verified' AND operator != 'ADVISORY' AND counts_toward_completion = 1
        """
    ).fetchone()[0]
    total_rules = con.execute("SELECT COUNT(*) FROM major_rules").fetchone()[0]
    history_ids = [
        row[0]
        for row in con.execute("SELECT legacy_rule_id FROM major_rules_history ORDER BY legacy_rule_id")
    ]
    return {
        "completion": completion,
        "advisory": advisory,
        "blocked": blocked,
        "partial": partial,
        "missing_page": missing_page,
        "majors": majors,
        "total_rules": total_rules,
        "history_ids": history_ids,
    }


def render_report(con, test_total: int, failed: list[dict], graph: bool = False) -> str:
    facts = live_facts(con)
    history = ", ".join(str(legacy_id) for legacy_id in facts["history_ids"])
    bullets = [
        f"- 计入完成度的 verified 规则：{facts['completion']} 条，覆盖 {facts['majors']} 个专业。查询条件是 `status = 'verified' AND operator != 'ADVISORY' AND counts_toward_completion = 1`。",
        f"- 推荐选修 ADVISORY：{facts['advisory']} 条，不计入完成度。",
        f"- blocked：{facts['blocked']} 条。现行表保留旧规则 18，签名作品的另一种学分拆法，印刷页 92。",
        f"- partial：{facts['partial']} 条。现行 {facts['total_rules']} 条规则都有印刷页码。"
        if facts["missing_page"] == 0
        else f"- partial：{facts['partial']} 条。现行规则里有 {facts['missing_page']} 条没有印刷页码。",
        f"- 被替代的旧规则 {history} 在 `major_rules_history`，共 {len(facts['history_ids'])} 条。艺术方向的替代规则在印刷页 102，媒体方向在印刷页 107。",
        f"- 只读测试 {test_total} 条，失败 {len(failed)} 条。",
    ]
    if graph:
        return "\n".join(bullets)
    lines = [
        "# 专业规则测试报告",
        "",
        "运行 `python3 data/run_major_rule_tests.py`。数据库以只读方式打开。",
        "",
        *bullets,
        "",
        "## 案例文件",
        "",
        "`data/major_rule_tests.json` 保存全部案例。`origin` 为 `hand` 的是高风险规则的手工案例，`standard` 的是其余现行规则的标准案例。案例带有规则签名。规则内容变化后，只读运行会失败，需要重新执行 `python3 data/run_major_rule_tests.py --write-catalog`。",
        "",
    ]
    if failed:
        lines.extend(["## 失败案例", ""])
        for case in failed[:30]:
            lines.append(
                f"- 规则 {case.get('rule_id')} / {case.get('case')}：得到 {case.get('actual_status')}，期望 {case.get('expected')}。{case.get('actual_reason') or ''}"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    from repair_high_risk_rules import write_graph_section

    connection = open_readonly()
    try:
        if "--write-catalog" in argv:
            raw = json.loads(TESTS_PATH.read_text(encoding="utf-8"))
            hand = [case for case in raw if case.get("origin", "hand") != "standard"]
            cases = persist_catalog(connection, hand)
            print(f"cases={len(cases)}")
            return 0
        cases = json.loads(TESTS_PATH.read_text(encoding="utf-8"))
        failed, total = run_cases(connection, cases)
        REPORT_PATH.write_text(render_report(connection, total, failed), encoding="utf-8")
        write_graph_section(render_report(connection, total, failed, graph=True))
        print(f"tests={total} failed={len(failed)}")
        return 1 if failed else 0
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
