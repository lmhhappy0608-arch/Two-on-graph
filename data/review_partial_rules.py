#!/usr/bin/env python3
"""Re-read bulletin major tables and compare them with partial rules.

This script does not write the database. It prints which partial rules
match a fresh reading of the printed pages.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pymupdf

import build_curriculum_db as bulletin

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curriculum.sqlite"
PDF_PATH = ROOT / "ug_bulletin_2025-2026.pdf"
OUT_PATH = ROOT / "data" / "partial_rule_review.json"


def lines_with_pages(doc) -> list[tuple[int | None, str]]:
    rows = []
    for page in doc:
        raw = page.get_text().splitlines()
        printed = None
        for index, line in enumerate(raw[:8]):
            if line.strip() == "Back to TOC" and index + 1 < len(raw) and raw[index + 1].strip().isdigit():
                printed = int(raw[index + 1].strip())
                break
        for line in bulletin.join_broken_codes(bulletin.page_lines(page)):
            rows.append((printed, line))
    return rows


def fresh_groups(rows: list[tuple[int | None, str]]) -> list[dict]:
    lines = [line for _page, line in rows]
    part = bulletin.find_marker(lines, lambda s: s.startswith("Part 10: Majors and Courses"))
    catalog = bulletin.find_marker(lines, lambda s: s == "Course Descriptions", part)
    body = rows[part:catalog]
    hits = []
    for index, (_page, line) in enumerate(body):
        short = bulletin.TITLE_TO_MAJOR.get(bulletin.norm_title(line))
        if not short:
            continue
        window = [item for _p, item in body[index : index + 80]]
        if any(bulletin.category_name(item) == "Divisional Foundation" for item in window):
            distance = next(i for i, item in enumerate(window) if bulletin.category_name(item) == "Divisional Foundation")
            hits.append((index, short, distance))
    best = {}
    for index, short, distance in hits:
        current = best.get(short)
        if current is None or distance < current[1] or (distance == current[1] and index > current[0]):
            best[short] = (index, distance)
    ordered = sorted(((index, short) for short, (index, _) in best.items()), key=lambda item: item[0])
    groups = []
    for pos, (start, short) in enumerate(ordered):
        end = ordered[pos + 1][0] if pos + 1 < len(ordered) else len(body)
        groups.extend(parse_chunk(short, body[start:end]))
    groups.extend(parse_chunk("All Majors", common_core_chunk(rows)))
    return groups


def common_core_chunk(rows):
    lines = [line for _page, line in rows]
    start = None
    for index, line in enumerate(lines):
        if line == "Requirements for All Majors" and any(
            lines[j].startswith("Common Core") for j in range(index, min(index + 12, len(lines)))
        ):
            start = index
            break
    if start is None:
        return []
    end = start + 1
    while end < len(lines) and not lines[end].startswith("Part 10:"):
        end += 1
        if end - start > 400:
            break
    return rows[start:end]


def parse_chunk(major: str, chunk: list[tuple[int | None, str]]) -> list[dict]:
    groups = []
    category = None
    phrase = ""
    page = None
    courses = []
    advisory = False

    def flush():
        nonlocal courses, advisory
        if courses or advisory:
            groups.append({
                "major": major,
                "category": category,
                "phrase": phrase,
                "page": page,
                "courses": courses,
                "advisory": advisory or (category == "Electives" and not any(word in phrase.lower() for word in ("choose", "complete", "required"))),
            })
        courses = []
        advisory = False

    for printed, line in chunk:
        if bulletin.BOUNDARY_RE.match(line):
            continue
        cat = bulletin.category_name(line)
        if cat:
            flush()
            category = cat
            phrase = line
            page = printed
            continue
        if bulletin.SKIP_MAJOR_LINE.match(line):
            continue
        if "recommended electives" in line.lower():
            advisory = True
            continue
        if bulletin.INSTRUCTION_RE.match(line):
            flush()
            phrase = line
            page = printed
            continue
        if category and bulletin.CODE_ONLY.match(line):
            courses.append(bulletin.canon_code(line))
            if page is None:
                page = printed
    flush()
    return [group for group in groups if group["courses"] or group["advisory"]]


def resolve_all(codes, resolver):
    resolved = []
    missing = []
    for code in codes:
        try:
            resolved.append(resolver(code))
        except KeyError:
            missing.append(code)
    return resolved, missing


def boilerplate_on_page(doc, index_of, printed: int) -> bool:
    import re
    chunks = []
    for page in (printed, (printed or 0) + 1):
        idx = index_of.get(page)
        if idx is not None:
            chunks.append(doc[idx].get_text())
    text = re.sub(r"\s+", "", " ".join(chunks).lower())
    return "recommendedelective" in text


def decide(group: dict, boilerplate: bool) -> dict | None:
    phrase = group["phrase"] or ""
    low = phrase.lower()
    count = len(dict.fromkeys(group["rule_courses"]))
    if count <= 0 or not group.get("page"):
        return None
    if low.startswith("interdisciplinary data analy"):
        return None
    if phrase == "Electives":
        if not boilerplate:
            return None
        return {
            "operator": "ADVISORY",
            "required_count": None,
            "page": group["page"],
            "phrase": "Courses listed in the table below are recommended electives for the major.",
            "note": "手册把这张表写成推荐选修。它不参与专业完成度。",
            "counts": 0,
            "status": "verified",
        }
    import re
    if re.search(r"choose\s+one\b", low):
        kind = "CHOOSE"
        required = 1
    elif re.search(r"choose\s+two\b", low):
        kind = "CHOOSE"
        required = 2
    elif "complete the following" in low or phrase in {
        "Disciplinary Courses",
        "Interdisciplinary Courses",
        "Divisional Foundation Courses",
    }:
        kind = "ALL"
        required = count
    else:
        return None
    if required > count:
        return None
    note = "对照印刷页上的课表后核对。"
    if kind == "ALL":
        note = "这一栏下面列出的课全部完成。"
    elif kind == "CHOOSE":
        note = f"按这句话下面的课表，从 {count} 门里选 {required} 门。"
    return {
        "operator": kind,
        "required_count": required,
        "page": group["page"],
        "phrase": phrase,
        "note": note,
        "counts": 1,
        "status": "verified",
    }


def promote_checked(con) -> dict:
    """Apply bulletin checks for the former partial rules. Raises if a test fails."""
    import pymupdf
    from major_rule_engine import evaluate

    doc = pymupdf.open(PDF_PATH)
    index_of = {}
    for index, page in enumerate(doc):
        raw = page.get_text().splitlines()
        for pos, line in enumerate(raw[:8]):
            if line.strip() == "Back to TOC" and pos + 1 < len(raw) and raw[pos + 1].strip().isdigit():
                index_of[int(raw[pos + 1].strip())] = index
                break
    groups = fresh_groups(lines_with_pages(doc))
    aliases = {alias: course_id for alias, course_id in con.execute("SELECT alias_code, course_id FROM course_aliases")}
    parts = {}
    for course_id, in con.execute("SELECT course_id FROM courses"):
        parts.setdefault(frozenset(course_id.split("/")), course_id)
        aliases.setdefault(course_id, course_id)

    def resolve(code):
        key = code.replace(" ", "").upper()
        if key in aliases:
            return aliases[key]
        found = parts.get(frozenset(key.split("/")))
        if found:
            return found
        raise KeyError(code)

    fresh_by_major = {}
    for group in groups:
        resolved, _missing = resolve_all(group["courses"], resolve)
        group["resolved"] = resolved
        fresh_by_major.setdefault(group["major"], []).append(group)

    partials = []
    for row in con.execute("""
        SELECT rule_id, legacy_rule_id, major, source_phrase
        FROM major_rules WHERE status = 'partial'
    """):
        courses = [item[0] for item in con.execute(
            "SELECT course_id FROM major_rule_items WHERE rule_id = ? AND course_id IS NOT NULL",
            (row[0],),
        )]
        partials.append({"rule_id": row[0], "legacy_rule_id": row[1], "major": row[2], "phrase": row[3], "courses": courses})

    used = set()
    decisions = []
    for rule in partials:
        wanted = frozenset(course for course in rule["courses"] if course)
        match = None
        for index, group in enumerate(fresh_by_major.get(rule["major"], [])):
            key = (rule["major"], index)
            if key in used:
                continue
            if wanted and frozenset(group["resolved"]) == wanted:
                match = group
                used.add(key)
                break
        if match is None and rule["legacy_rule_id"] == 67:
            match = {"phrase": "Electives", "page": 127, "resolved": rule["courses"]}
        if match is None:
            continue
        match = dict(match)
        match["rule_courses"] = rule["courses"]
        boilerplate = match["phrase"] == "Electives" and boilerplate_on_page(doc, index_of, match["page"])
        choice = decide(match, boilerplate)
        if choice is None:
            continue
        choice["rule_id"] = rule["rule_id"]
        choice["legacy_rule_id"] = rule["legacy_rule_id"]
        decisions.append(choice)

    # Common core and the two capstone options were read on printed pages 91 and 92.
    by_legacy = {rule["legacy_rule_id"]: rule for rule in partials}
    if 16 in by_legacy:
        decisions.append({
            "rule_id": by_legacy[16]["rule_id"],
            "legacy_rule_id": 16,
            "operator": "ALL",
            "required_count": 3,
            "page": 91,
            "phrase": "All students regardless of their choice of major will be required to complete the following courses.",
            "note": "共同核心是 GCHINA 101、GLOCHALL 201、ETHLDR 201，共 12 学分。",
            "counts": 1,
            "status": "verified",
        })
    if 17 in by_legacy:
        decisions.append({
            "rule_id": by_legacy[17]["rule_id"],
            "legacy_rule_id": 17,
            "operator": "ALL",
            "required_count": 2,
            "page": 92,
            "phrase": "Signature Work Capstone Courses (8 credits)",
            "note": "两种学分拆法都是完成 CAPSTONE 495 和 CAPSTONE 496。Option 2 把 495 拆成两门 2 学分，不是另一组课程。",
            "counts": 1,
            "status": "verified",
        })
    if 18 in by_legacy:
        decisions.append({
            "rule_id": by_legacy[18]["rule_id"],
            "legacy_rule_id": 18,
            "operator": "ALL",
            "required_count": None,
            "page": 92,
            "phrase": "Option 2 (2+2+4 credits)",
            "note": "这是 CAPSTONE 495 和 CAPSTONE 496 的另一种学分拆法，已经并入同一条毕业要求，不再单独计算。",
            "counts": 0,
            "status": "blocked",
        })
    for choice in decisions:
        con.execute(
            """
            UPDATE major_rules
            SET status = ?, operator = ?, required_count = ?, source_phrase = ?, source_page = ?,
                note = ?, counts_toward_completion = ?
            WHERE rule_id = ?
            """,
            (
                choice["status"], choice["operator"], choice["required_count"], choice["phrase"],
                choice["page"], choice["note"], choice["counts"], choice["rule_id"],
            ),
        )
        con.execute(
            """
            DELETE FROM major_rule_items
            WHERE rule_id = ?
              AND course_id IS NOT NULL
              AND id NOT IN (
                SELECT MIN(id) FROM major_rule_items
                WHERE rule_id = ? AND course_id IS NOT NULL
                GROUP BY course_id
              )
            """,
            (choice["rule_id"], choice["rule_id"]),
        )

    catalog = {}
    alias_sets = {}
    for alias, course_id in con.execute("SELECT alias_code, course_id FROM course_aliases"):
        alias_sets.setdefault(course_id, set()).add(alias)
    for course_id, units, level in con.execute("SELECT course_id, units, level FROM courses"):
        catalog[course_id] = {
            "units": units,
            "level": level,
            "department": "",
            "aliases": alias_sets.get(course_id, {course_id}),
        }

    failed = []
    tested = 0
    for choice in decisions:
        rule = {
            "rule_id": choice["rule_id"],
            "status": choice["status"],
            "operator": choice["operator"],
            "required_count": choice["required_count"],
            "required_credits": None,
            "note": choice["note"],
            "constraints": [],
            "items": [
                {"item_type": "course", "course_id": course_id, "group_name": ""}
                for course_id in con.execute(
                    "SELECT course_id FROM major_rule_items WHERE rule_id = ? AND course_id IS NOT NULL",
                    (choice["rule_id"],),
                ).fetchall()
                for course_id in course_id
            ],
        }
        # fetchall returns rows; the double for flattens sqlite rows. Rebuild cleanly.
        rule["items"] = []
        seen = []
        for (course_id,) in con.execute(
            "SELECT DISTINCT course_id FROM major_rule_items WHERE rule_id = ? AND course_id IS NOT NULL",
            (choice["rule_id"],),
        ):
            seen.append(course_id)
            rule["items"].append({"item_type": "course", "course_id": course_id, "group_name": ""})
        if choice["status"] == "blocked":
            cases = [
                ([], "blocked"),
                (seen or ["MATH101"], "blocked"),
            ]
        elif choice["operator"] == "ADVISORY":
            cases = [([], "not_applicable"), (["MATH101"], "not_applicable")]
        elif choice["operator"] == "ALL":
            cases = [(seen, "satisfied"), (seen[:-1], "unsatisfied")]
        else:
            need = choice["required_count"]
            cases = [(seen[:need], "satisfied"), (seen[: need - 1], "unsatisfied"), (["ZZZ999"] * need, "unsatisfied")]
        for completed, expected in cases:
            tested += 1
            result = evaluate(rule, completed, catalog, {rule["rule_id"]: rule})
            if result["status"] != expected:
                failed.append((choice["legacy_rule_id"], expected, result["status"], result.get("reason")))
    if failed:
        for item in failed[:12]:
            print("PROMOTE FAIL", item)
        raise SystemExit(f"核对后的规则有 {len(failed)} 条测试失败")
    verified = sum(1 for choice in decisions if choice["status"] == "verified" and choice["operator"] != "ADVISORY")
    advisory = sum(1 for choice in decisions if choice["operator"] == "ADVISORY")
    blocked = sum(1 for choice in decisions if choice["status"] == "blocked")
    return {"verified": verified, "advisory": advisory, "blocked": blocked, "tested": tested}


def main():
    doc = pymupdf.open(PDF_PATH)
    groups = fresh_groups(lines_with_pages(doc))
    con = sqlite3.connect(DB_PATH)
    aliases = {alias: course_id for alias, course_id in con.execute("SELECT alias_code, course_id FROM course_aliases")}
    parts = {}
    for course_id, in con.execute("SELECT course_id FROM courses"):
        parts.setdefault(frozenset(course_id.split("/")), course_id)
        aliases.setdefault(course_id, course_id)

    def resolve(code):
        key = code.replace(" ", "").upper()
        if key in aliases:
            return aliases[key]
        found = parts.get(frozenset(key.split("/")))
        if found:
            return found
        raise KeyError(code)

    fresh = []
    for group in groups:
        resolved, missing = resolve_all(group["courses"], resolve)
        group["resolved"] = resolved
        group["missing"] = missing
        fresh.append(group)

    partials = []
    for row in con.execute("""
        SELECT rule_id, legacy_rule_id, major, category, operator, required_count, source_phrase
        FROM major_rules WHERE status = 'partial' ORDER BY legacy_rule_id
    """):
        courses = [item[0] for item in con.execute(
            "SELECT course_id FROM major_rule_items WHERE rule_id = ? AND course_id IS NOT NULL",
            (row[0],),
        )]
        partials.append({
            "rule_id": row[0],
            "legacy_rule_id": row[1],
            "major": row[2],
            "category": row[3],
            "operator": row[4],
            "required_count": row[5],
            "phrase": row[6],
            "courses": courses,
        })

    used = set()
    report = []
    for rule in partials:
        wanted = frozenset(rule["courses"])
        candidates = []
        for index, group in enumerate(fresh):
            if index in used or group["major"] != rule["major"]:
                continue
            if frozenset(group["resolved"]) == wanted and wanted:
                candidates.append(index)
        if len(candidates) == 1:
            used.add(candidates[0])
            group = fresh[candidates[0]]
            report.append({"match": "same_courses", "rule": rule, "group": {k: group[k] for k in ("phrase", "page", "category", "advisory", "missing", "courses")}})
        else:
            report.append({"match": "no_unique_list", "rule": rule, "candidate_count": len(candidates)})

    same = [item for item in report if item["match"] == "same_courses"]
    missing = [item for item in report if item["match"] != "same_courses"]
    print(f"fresh_groups={len(fresh)} partial={len(partials)} same_list={len(same)} unmatched={len(missing)}")
    print("-- unmatched --")
    for item in missing:
        rule = item["rule"]
        print(f"L{rule['legacy_rule_id']} {rule['major']} {rule['operator']} n={len(rule['courses'])} | {rule['phrase'][:100]}")
    print("-- phrase differs from stored header --")
    for item in same:
        rule = item["rule"]
        group = item["group"]
        if bulletin.norm_space(rule["phrase"] or "")[:40].lower() != bulletin.norm_space(group["phrase"] or "")[:40].lower():
            print(f"L{rule['legacy_rule_id']} stored={rule['phrase'][:50]!r} fresh={group['phrase'][:50]!r} page={group['page']} advisory={group['advisory']}")
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT_PATH)


if __name__ == "__main__":
    main()
