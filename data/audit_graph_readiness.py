#!/usr/bin/env python3
"""Make curriculum.sqlite ready to build a graph.

The bulletin course ids and the class-search course codes are aligned here.
False prerequisite edges found during that alignment are kept out of graph_edges.
Major requirement rows are grouped into major_rules. Offering patterns are not inferred.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curriculum.sqlite"
BACKUP_PATH = ROOT / "data" / "curriculum.pre_audit.sqlite"
REPORT_PATH = ROOT / "data" / "graph_readiness_report.md"

# Relation ids whose source code is not a course. The bulletin text was checked
# for each one. Eight are parser mistakes. Three name a real course code that
# has no course entry, and those sources are added below.
EXCLUDED_RELATIONS = {
    283: (
        "bleed",
        "GCHINA 306 是下一门课的标题，不是 GCHINA 305 的先修。手册先修只有 GCHINA 108。",
    ),
    320: (
        "false_code",
        "“200-level”被读成课号 ARHU200。手册原文是 ARHU 101，或任意 4 学分的 100/200 级 LIT 课。",
    ),
    322: (
        "false_code",
        "“200-level”被读成课号 ARHU200。手册原文是 ARHU 101，或任意 4 学分的 100/200 级 LIT 课。",
    ),
    410: (
        "bleed",
        "MUSIC 210 Orchestra 是下一门课，不是 MUSIC 20 的先修。MUSIC 20 的先修是任课教师同意。",
    ),
    462: (
        "bleed",
        "POLSCI 398-2 是下一门课，不是 POLSCI 398-1 的先修。398-1 的先修是 POLSCI 223 或任课教师同意。",
    ),
    467: (
        "bleed",
        "PSYCH 304 是下一门课，不是 PSYCH 205 的先修。PSYCH 205 的先修是 PSYCH 101。",
    ),
    538: (
        "false_code",
        "“EAP 14-week”是校历里的 14 周课，不是课号 EAP14。",
    ),
    539: (
        "false_code",
        "“EAP 14-week”是校历里的 14 周课，不是课号 EAP14。同一句被写入了两次。",
    ),
    297: (
        "nonbinding",
        "GLHLTH 312 的原文是 “GLHLTH 101 recommended”，后面接的是下一门课 GLHLTH 408 的简介。",
    ),
    298: (
        "bleed",
        "BIOL 408/CHEM 408/GLHLTH 408 是串进来的下一门课，不是 GLHLTH 312 的先修。",
    ),
    441: (
        "nonbinding",
        "PHYS 306 对 PHYS 301 的原文是 “is encouraged”，不是先修。PHYS 201 和 MATH 202 仍保留。",
    ),
    492: (
        "nonbinding",
        "SOSC 320 对 MATH 206 的原文是 “highly encouraged”。STATS 101 和 SOSC 205 仍保留。",
    ),
}

PREREQ_REPAIRS = {
    "GCHINA305": "GCHINA 108",
    "PSYCH205": "PSYCH 101",
    "POLSCI398-1": "POLSCI 223 or Consent of the Instructor",
    "MUSIC20": "Consent of the Instructor",
    "WOC290": "EAP 102B or equivalent or Consent of the Instructor",
    "GLHLTH312": "GLHLTH 101 recommended",
    "WOC206": "EAP 101B or equivalent or Consent of the Instructor",
}

TYPO_COURSES = {
    "POLISCI223": "POLSCI223",
    "HIS212": "HIST212",
    "EHTLDR204": "ETHLDR204",
}

RECOVERED_COURSES = [
    {
        "course_id": "CHEM101",
        "course_name": None,
        "units": None,
        "description": None,
        "prereq_text": None,
        "notes": (
            "Named as a prerequisite of BIOL 411/GLHLTH 411. "
            "The 2025-26 bulletin has no CHEM 101 course entry."
        ),
        "source": "cited_prerequisite",
    },
    {
        "course_id": "MATH205",
        "course_name": None,
        "units": None,
        "description": None,
        "prereq_text": None,
        "notes": (
            "Named as the anti-requisite of MATH 206 and as an alternative prerequisite of MATH 306. "
            "The 2025-26 bulletin has no MATH 205 course entry."
        ),
        "source": "cited_prerequisite",
    },
    {
        "course_id": "GCHINA306",
        "course_name": "Traditions of Power: Historical Origins of Modern China",
        "units": None,
        "description": (
            "What are the historical roots of Chinese social and political institutions? "
            "This course considers how institutional legacies persist either directly within today's "
            "governance structures or indirectly in the values and behaviors shaping contemporary society. "
            "Topics include the imperial examination system and its enduring influence on meritocracy, "
            "education, and social hierarchy; historical patterns such as rice farming in southern China "
            "versus wheat farming in the north, which shaped regional differences in labor organization, "
            "collective practices, and governance; and conflicts such as Japan's mid-twentieth century "
            "invasion of China, which changed the course of Chinese political, social, and cultural history."
        ),
        "prereq_text": None,
        "notes": (
            "Bulletin entry was concatenated into GCHINA 305's prerequisite text. "
            "The header does not print credits or a prerequisite."
        ),
        "source": "bulletin_recovered",
    },
    {
        "course_id": "PSYCH304",
        "course_name": "Quantitative Research Methods and Statistics for Psychological Science",
        "units": 4,
        "description": (
            "Design of research studies and use of statistical methods to become better consumers, creators, "
            "and communicators of psychological research. This course will (1) focus on research methods in "
            "psychology, including research design and measurement, ethical issues, and statistical tests for "
            "quantitative studies; (2) provide students with hands-on practice with experimental design and "
            "programming and data analysis and interpretation. Students will develop the methodological and "
            "statistical knowledge and skills to design, program, conduct, and analyze quantitative "
            "psychological research that can be applied in their signature work and further studies at DKU "
            "and beyond. Includes workshop and lab section."
        ),
        "prereq_text": "PSYCH 101; and STATS 101 or MATH 206",
        "notes": "Bulletin entry was concatenated into PSYCH 205's prerequisite text.",
        "source": "bulletin_recovered",
    },
    {
        "course_id": "POLSCI398-2",
        "course_name": "Special Topics in Chinese International Relations",
        "units": None,
        "description": (
            "This course offers an in-depth exploration of specific topics in Chinese International Relations. "
            "The topic or theme will vary based on the instructor and curricular needs."
        ),
        "prereq_text": "GCHINA 108 or POLSCI 101 or Consent of the Instructor",
        "notes": (
            "Bulletin entry was concatenated into POLSCI 398-1's prerequisite text. "
            "The header does not print credits."
        ),
        "source": "bulletin_recovered",
    },
    {
        "course_id": "MUSIC210",
        "course_name": "Orchestra",
        "units": 2,
        "description": (
            "Music is said to be the universal language. This course is designed for students to utilize their "
            "knowledge of this language to further their understanding of this performing art and gain a deeper "
            "insight into group performance. Students will explore new or old repertoire with fellow musicians "
            "during the course of the term under the guidance of the instructor and will perform in various venues "
            "around Kunshan and Shanghai area. Students are required to join weekly rehearsals with assigned groups "
            "and all groups will perform in a concert at the end of the term. This course will also invite guest "
            "musicians as coaches to help each individual group. Previous experience in learning and performing a "
            "musical instrument is recommended. This course may be repeated for credit."
        ),
        "prereq_text": "Consent of the Instructor",
        "notes": "CR/NC grading. Recovered from the bulletin; the header had been appended to MUSIC 20.",
        "source": "bulletin_recovered",
    },
    {
        "course_id": "MUSIC211",
        "course_name": "Chamber Music",
        "units": 2,
        "description": (
            "Playing in small formations, students will be able to explore chamber repertoire of all epochs, "
            "with a special focus on modern repertoire. The ensembles will be established by the instructor at "
            "the beginning of the course. Their repertoire will be chosen by the instructor in consultation with "
            "the students involved. The groups will participate to one concert per semester. They may occasionally "
            "be invited to perform in the wider Jiangsu area. The ensembles will be coached regularly by the "
            "instructor. Guest musicians will offer workshops to the ensembles and may occasionally perform with "
            "the students. At least some degree of proficiency in instrumental playing and consent of the "
            "instructor are required."
        ),
        "prereq_text": "Consent of the Instructor",
        "notes": "CR/NC grading. Recovered from the bulletin entry that follows MUSIC 210.",
        "source": "bulletin_recovered",
    },
]

NEW_RELATIONS = [
    ("PSYCH101", "PSYCH304", "prerequisite", "G1", "single", "and", "PSYCH 101"),
    ("STATS101", "PSYCH304", "prerequisite", "G2", "or", "and", "STATS 101 or MATH 206"),
    ("MATH206", "PSYCH304", "prerequisite", "G2", "or", "and", "STATS 101 or MATH 206"),
    (
        "GCHINA108",
        "POLSCI398-2",
        "prerequisite",
        "G1",
        "or",
        "and",
        "GCHINA 108 or POLSCI 101 or Consent of the Instructor",
    ),
    (
        "POLSCI101",
        "POLSCI398-2",
        "prerequisite",
        "G1",
        "or",
        "and",
        "GCHINA 108 or POLSCI 101 or Consent of the Instructor",
    ),
]

COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
CHOOSE_ROLE = re.compile(
    r"choose_(one|two|three|four|five)(?:_of_(two|three|four|five))?$"
)


def level_of(course_id: str) -> int | None:
    match = re.search(r"(\d{3})", course_id.split("/")[0])
    if not match:
        return None
    level = (int(match.group(1)) // 100) * 100
    if level in {100, 200, 300, 400}:
        return level
    return None


def department_of(course_id: str) -> str:
    match = re.match(r"[A-Z]+", course_id.split("/")[0])
    return match.group(0) if match else ""


def course_ids(con: sqlite3.Connection) -> set[str]:
    return {row[0] for row in con.execute("SELECT course_id FROM courses")}


def ensure_schema(con: sqlite3.Connection) -> None:
    columns = [row[1] for row in con.execute("PRAGMA table_info(class_sections)")]
    if "canonical_course_id" not in columns:
        con.execute("ALTER TABLE class_sections ADD COLUMN canonical_course_id TEXT")
    con.executescript(
        """
        DROP TABLE IF EXISTS course_aliases;
        DROP TABLE IF EXISTS relation_audit;
        DROP TABLE IF EXISTS graph_edges;
        DROP TABLE IF EXISTS major_rules;
        DROP TABLE IF EXISTS major_rule_courses;
        DROP TABLE IF EXISTS audit_checks;
        CREATE TABLE course_aliases (
            alias_code TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            match_method TEXT NOT NULL,
            evidence TEXT
        );
        CREATE TABLE relation_audit (
            relation_id INTEGER PRIMARY KEY,
            graph_use TEXT NOT NULL,
            issue TEXT NOT NULL,
            strict INTEGER NOT NULL,
            note TEXT
        );
        CREATE TABLE graph_edges (
            id INTEGER PRIMARY KEY,
            source_course TEXT NOT NULL,
            target_course TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            group_id TEXT,
            logic_within_group TEXT,
            group_relation TEXT,
            strict INTEGER NOT NULL,
            issue TEXT NOT NULL,
            relation_id INTEGER,
            raw_clause TEXT
        );
        CREATE TABLE major_rules (
            rule_id INTEGER PRIMARY KEY,
            major TEXT NOT NULL,
            category TEXT,
            role TEXT,
            rule_kind TEXT NOT NULL,
            choose_k INTEGER,
            expected_n INTEGER,
            option_group TEXT,
            status TEXT NOT NULL,
            course_count INTEGER NOT NULL,
            resolved_count INTEGER NOT NULL,
            source_phrase TEXT,
            note TEXT
        );
        CREATE TABLE major_rule_courses (
            id INTEGER PRIMARY KEY,
            rule_id INTEGER NOT NULL,
            requirement_id INTEGER NOT NULL,
            listed_course_id TEXT NOT NULL,
            course_id TEXT,
            resolution TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS course_text_repairs (
            course_id TEXT NOT NULL,
            field TEXT NOT NULL,
            old_text TEXT,
            new_text TEXT,
            reason TEXT NOT NULL
        );
        CREATE TABLE audit_checks (
            name TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            detail TEXT NOT NULL
        );
        """
    )


def insert_course(con: sqlite3.Connection, row: dict) -> None:
    if con.execute(
        "SELECT 1 FROM courses WHERE course_id = ?", (row["course_id"],)
    ).fetchone():
        return
    con.execute(
        """
        INSERT INTO courses (
            course_id, course_name, department, level, units, description,
            prereq_text, antireq_text, notes, offering_pattern, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)
        """,
        (
            row["course_id"],
            row.get("course_name"),
            row.get("department") or department_of(row["course_id"]),
            row.get("level", level_of(row["course_id"])),
            row.get("units"),
            row.get("description"),
            row.get("prereq_text"),
            row.get("notes"),
            row["source"],
        ),
    )


def choose_units(pairs: list[tuple[str, str]]) -> tuple[float | int | None, str | None]:
    parsed = []
    for raw, _component in pairs:
        text = "" if raw is None else str(raw).strip()
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            parsed.append(float(text))
    positive = {value for value in parsed if value > 0}
    if len(positive) == 1:
        value = positive.pop()
        return (int(value) if value.is_integer() else value), None
    if not positive:
        return None, None
    shown = sorted({"" if raw is None else str(raw).strip() for raw, _ in pairs})
    return None, "同一开课代码在已记录课节里出现了多种学分：" + "、".join(shown)


def insert_section_shells(con: sqlite3.Connection, unresolved: list[str]) -> None:
    special_notes = {
        "MATH101A": (
            "Class Search title is Introductory Calculus: Differentiation, 2 credits. "
            "Bulletin MATH101 is Introductory Calculus, 4 credits. "
            "This registration code is not an alias of MATH101."
        ),
        "MATH101B": (
            "Class Search title is Introductory Calculus: Integration, 2 credits. "
            "Bulletin MATH101 is Introductory Calculus, 4 credits. "
            "This registration code is not an alias of MATH101."
        ),
    }
    for code in unresolved:
        titles = [
            row[0].strip()
            for row in con.execute(
                "SELECT DISTINCT title FROM class_sections WHERE course_code = ? AND title IS NOT NULL",
                (code,),
            )
            if row[0] and row[0].strip()
        ]
        titles = list(dict.fromkeys(titles))
        subjects = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT subject FROM class_sections WHERE course_code = ?",
                (code,),
            )
        ]
        unit_pairs = con.execute(
            "SELECT units, component FROM class_sections WHERE course_code = ?",
            (code,),
        ).fetchall()
        units, unit_note = choose_units(unit_pairs)
        notes = [
            "Scheduled in the recorded Fall and Spring class search. "
            "No course entry in the 2025-26 bulletin course list. "
            "Title and units come from those sections."
        ]
        if code in special_notes:
            notes.append(special_notes[code])
        if len(titles) > 1:
            notes.append("Recorded sections use more than one title.")
        if unit_note:
            notes.append(unit_note)
        insert_course(
            con,
            {
                "course_id": code,
                "course_name": " | ".join(titles) if titles else None,
                "department": subjects[0] if subjects else department_of(code),
                "units": units,
                "notes": " ".join(notes),
                "source": "class_search",
            },
        )


def build_aliases(con: sqlite3.Connection) -> dict[str, tuple[str, str, str]]:
    """alias -> (canonical course id, method, evidence)."""
    courses = course_ids(con)
    hum = con.execute(
        "SELECT course_name, description, prereq_text FROM courses WHERE course_id = 'HUM405/MEDIART405'"
    ).fetchone()
    media = con.execute(
        "SELECT course_name, description, prereq_text FROM courses WHERE course_id = 'MEDIART405/GCULS405'"
    ).fetchone()
    if hum is None or media is None or hum != media:
        raise SystemExit("HUM405/MEDIART405 与 MEDIART405/GCULS405 的手册正文不一致，不能并成一个节点。")
    duplicates = {"MEDIART405/GCULS405": "HUM405/MEDIART405"}

    canonical_of = {cid: duplicates.get(cid, cid) for cid in courses}
    part_to: dict[str, set[str]] = defaultdict(set)
    for cid, canonical in canonical_of.items():
        part_to[cid].add(canonical)
        for part in cid.split("/"):
            part_to[part].add(canonical)

    aliases: dict[str, tuple[str, str, str]] = {}
    for cid, canonical in canonical_of.items():
        if cid == canonical:
            aliases[cid] = (canonical, "self", "课程表主键")
        else:
            aliases[cid] = (
                canonical,
                "duplicate_entry",
                "手册把同一门 The Curatorial 印了两次，课名、简介和先修相同。图上保留先出现的 HUM405/MEDIART405。",
            )
    for part, canons in part_to.items():
        if part in aliases:
            continue
        if len(canons) == 1:
            canonical = next(iter(canons))
            if part != canonical:
                aliases[part] = (
                    canonical,
                    "slash_part",
                    f"开课代码是交叉列课 {canonical} 的一个课号。",
                )
    return aliases


def classify_relation(row: tuple) -> tuple[str, str, int, str]:
    relation_id, _source, _target, _rtype, _logic, _combine, raw = row
    if relation_id in EXCLUDED_RELATIONS:
        issue, note = EXCLUDED_RELATIONS[relation_id]
        return "exclude", issue, 0, note
    text = raw or ""
    lowered = text.lower()
    if re.search(r"\b(encouraged|recommended)\b", lowered):
        return "exclude", "nonbinding", 0, "原句是鼓励或推荐，不作为先修边。"
    if "level" in lowered:
        return (
            "use",
            "level_constraint",
            0,
            "这一组还包含年级范围，编码里的课号只是其中一条路，不能当成唯一先修。",
        )
    if re.search(r"equivalent|consent|permission", lowered):
        return (
            "use",
            "listed_option",
            0,
            "原句还有 equivalent、consent 或 permission。列出的课号是充分条件，不是唯一条件。",
        )
    return "use", "ok", 1, "分组、组内逻辑和组间逻辑与原句一致，可以作为硬性边。"


def repair_texts(con: sqlite3.Connection) -> int:
    changed = 0
    for course_id, new_text in PREREQ_REPAIRS.items():
        current = con.execute(
            "SELECT prereq_text FROM courses WHERE course_id = ?", (course_id,)
        ).fetchone()
        if current is None or current[0] == new_text:
            continue
        con.execute(
            """
            INSERT INTO course_text_repairs (course_id, field, old_text, new_text, reason)
            VALUES (?, 'prereq_text', ?, ?, ?)
            """,
            (
                course_id,
                current[0],
                new_text,
                "去掉串进先修字段的下一门课、校历或误读课号，改回手册该门课自己的先修句。",
            ),
        )
        con.execute(
            "UPDATE courses SET prereq_text = ? WHERE course_id = ?",
            (new_text, course_id),
        )
        changed += 1
    con.execute(
        "UPDATE relations SET logic_within_group = 'single' WHERE id = 282 AND logic_within_group = 'and'"
    )
    return changed


def insert_recovered_relations(con: sqlite3.Connection) -> None:
    for source, target, relation_type, group_id, logic, combine, raw in NEW_RELATIONS:
        exists = con.execute(
            """
            SELECT 1 FROM relations
            WHERE source_course = ? AND target_course = ? AND relation_type = ? AND group_id = ?
            """,
            (source, target, relation_type, group_id),
        ).fetchone()
        if exists:
            continue
        con.execute(
            """
            INSERT INTO relations (
                source_course, target_course, relation_type, group_id,
                logic_within_group, group_relation, raw_clause
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (source, target, relation_type, group_id, logic, combine, raw),
        )


def parse_choose(role: str) -> tuple[str, int | None, int | None, str | None]:
    if role == "required":
        return "all", None, None, None
    if role == "elective":
        return "optional", None, None, None
    if role in {"option_1", "option_2"}:
        return "alternative", None, None, "signature_work"
    match = CHOOSE_ROLE.fullmatch(role or "")
    if not match:
        return "unknown", None, None, None
    choose_k = COUNT_WORDS[match.group(1)]
    expected = COUNT_WORDS[match.group(2)] if match.group(2) else None
    return "choose", choose_k, expected, None


def resolve_listed(
    listed: str, aliases: dict[str, tuple[str, str, str]], courses: set[str]
) -> tuple[str | None, str]:
    if listed in aliases:
        canonical, method, _evidence = aliases[listed]
        if method == "self":
            return canonical, "exact"
        if method == "duplicate_entry":
            return canonical, "duplicate_entry"
        return canonical, method
    if listed in TYPO_COURSES and TYPO_COURSES[listed] in courses:
        return TYPO_COURSES[listed], "typo"
    wanted = frozenset(listed.split("/"))
    if len(wanted) > 1:
        matches = []
        for cid in courses:
            canonical = aliases[cid][0] if cid in aliases else cid
            if frozenset(canonical.split("/")) == wanted and canonical not in matches:
                matches.append(canonical)
        if len(matches) == 1:
            return matches[0], "slash_order"
    parts = set(listed.split("/"))
    if len(parts) > 1:
        supersets = [
            cid
            for cid in courses
            if parts < set(cid.split("/"))
        ]
        canonical_supersets = []
        for cid in supersets:
            canonical = aliases.get(cid, (cid, "self", ""))[0]
            if canonical not in canonical_supersets:
                canonical_supersets.append(canonical)
        if len(canonical_supersets) == 1:
            return canonical_supersets[0], "crosslist_superset"
    return None, "unresolved"


def build_major_rules(
    con: sqlite3.Connection, aliases: dict[str, tuple[str, str, str]]
) -> None:
    courses = course_ids(con)
    rows = con.execute(
        """
        SELECT id, major, category, role, course_id, source_phrase
        FROM major_requirements
        ORDER BY major, category, role, id
        """
    ).fetchall()
    grouped: dict[tuple, list[tuple]] = defaultdict(list)
    for row in rows:
        grouped[(row[1], row[2], row[3], row[5])].append(row)

    for (major, category, role, phrase), items in grouped.items():
        kind, choose_k, expected_n, option_group = parse_choose(role)
        resolved_rows = []
        notes = []
        for item in items:
            canonical, how = resolve_listed(item[4], aliases, courses)
            resolved_rows.append((item, canonical, how))
            if how == "typo":
                notes.append(f"{item[4]} 按课号笔误对应到 {canonical}")
            elif how == "crosslist_superset":
                notes.append(f"{item[4]} 写少了交叉列课号，对应到 {canonical}")
            elif how == "duplicate_entry":
                notes.append(f"{item[4]} 与 {canonical} 是手册里重复印出的同一门课")
        distinct = []
        for _item, canonical, how in resolved_rows:
            key = canonical or f"missing:{_item[4]}"
            if key not in distinct:
                distinct.append(key)
        resolved_count = sum(1 for _item, canonical, _how in resolved_rows if canonical)
        unresolved = [item[4] for item, canonical, _how in resolved_rows if canonical is None]
        listed_ids = [item[4] for item, _canonical, _how in resolved_rows]
        if unresolved:
            status = "partial_unresolved"
        elif expected_n is not None and len(distinct) != expected_n:
            status = "partial_count"
            notes.append(f"角色要求 {expected_n} 门，这一组实际有 {len(distinct)} 个不同课号")
        elif kind == "choose" and choose_k is not None and len(distinct) < choose_k:
            status = "partial_count"
            notes.append(f"需要选择 {choose_k} 门，这一组只有 {len(distinct)} 门")
        elif any(how in {"typo", "crosslist_superset", "duplicate_entry"} for _i, _c, how in resolved_rows):
            status = "executable_flagged"
        else:
            status = "executable"
        if len(listed_ids) != len(set(listed_ids)):
            notes.append("同一门课在这一组里被写入了多次")
        if kind == "alternative":
            notes.append("这是签名作业的一个选项。学生完成 option 1 或 option 2 其中一组。")
        if kind == "optional":
            notes.append("这一组是选修池，手册没有在角色里写出最少门数。")
        if kind == "unknown":
            status = "partial_unresolved"
            notes.append(f"无法解释角色 {role}")
        note_text = "。".join(dict.fromkeys(notes)) or None
        rule_choose_k = choose_k
        if kind == "all":
            rule_choose_k = len(distinct)
        if kind == "alternative":
            rule_choose_k = len([key for key in distinct if not str(key).startswith("missing:")])
        con.execute(
            """
            INSERT INTO major_rules (
                major, category, role, rule_kind, choose_k, expected_n, option_group,
                status, course_count, resolved_count, source_phrase, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                major,
                category,
                role,
                kind,
                rule_choose_k,
                expected_n,
                option_group,
                status,
                len(items),
                resolved_count,
                phrase,
                note_text,
            ),
        )
        rule_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        for item, canonical, how in resolved_rows:
            con.execute(
                """
                INSERT INTO major_rule_courses (
                    rule_id, requirement_id, listed_course_id, course_id, resolution
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (rule_id, item[0], item[4], canonical, how),
            )


def build_graph_edges(
    con: sqlite3.Connection, aliases: dict[str, tuple[str, str, str]]
) -> tuple[int, int]:
    skipped = 0
    rows = con.execute(
        """
        SELECT r.id, r.source_course, r.target_course, r.relation_type,
               r.group_id, r.logic_within_group, r.group_relation, r.raw_clause,
               a.graph_use, a.issue, a.strict
        FROM relations r
        JOIN relation_audit a ON a.relation_id = r.id
        WHERE a.graph_use = 'use'
        ORDER BY r.id
        """
    )
    for row in rows:
        source = aliases.get(row[1], (None,))[0]
        target = aliases.get(row[2], (None,))[0]
        if not source or not target or source == target:
            skipped += 1
            continue
        con.execute(
            """
            INSERT INTO graph_edges (
                source_course, target_course, relation_type, group_id,
                logic_within_group, group_relation, strict, issue, relation_id, raw_clause
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source, target, row[3], row[4], row[5], row[6], row[10], row[9], row[0], row[7]),
        )
    used = con.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    return used, skipped


def write_checks(con: sqlite3.Connection, aliases: dict[str, tuple[str, str, str]]) -> None:
    unresolved_codes = con.execute(
        """
        SELECT DISTINCT course_code FROM class_sections
        WHERE course_code NOT IN (SELECT alias_code FROM course_aliases)
        ORDER BY 1
        """
    ).fetchall()
    dangling = con.execute(
        """
        SELECT COUNT(*) FROM graph_edges g
        WHERE g.source_course NOT IN (SELECT course_id FROM course_aliases WHERE alias_code = course_id)
           OR g.target_course NOT IN (SELECT course_id FROM course_aliases WHERE alias_code = course_id)
        """
    ).fetchone()[0]
    attached = con.execute("SELECT COUNT(*) FROM major_rule_courses").fetchone()[0]
    requirements = con.execute("SELECT COUNT(*) FROM major_requirements").fetchone()[0]
    invented = con.execute(
        "SELECT COUNT(*) FROM courses WHERE offering_pattern IS NOT NULL AND TRIM(offering_pattern) != ''"
    ).fetchone()[0]
    missing_sources = ["CHEM101", "MATH205", "ARHU200", "GCHINA306", "MUSIC210", "POLSCI398-2", "PSYCH304", "EAP14"]
    still_missing = [
        code
        for code in missing_sources
        if code not in aliases and code not in {"ARHU200", "EAP14"}
    ]
    group_problems = []
    groups: dict[tuple, list[tuple]] = defaultdict(list)
    for row in con.execute(
        """
        SELECT target_course, relation_type, group_id, logic_within_group, group_relation, source_course
        FROM graph_edges
        """
    ):
        groups[(row[0], row[1], row[2])].append(row)
    for key, items in groups.items():
        logics = {item[3] for item in items}
        combines = {item[4] for item in items}
        if len(logics) > 1 or len(combines) > 1:
            group_problems.append(str(key))
    checks = [
        (
            "offering_codes_resolve",
            "pass" if not unresolved_codes else "fail",
            "未解析开课代码 " + (", ".join(row[0] for row in unresolved_codes) if unresolved_codes else "0"),
        ),
        (
            "graph_edge_endpoints",
            "pass" if dangling == 0 else "fail",
            f"端点不在图节点里的边：{dangling}",
        ),
        (
            "cited_sources_present",
            "pass" if not still_missing else "fail",
            "仍缺课程节点：" + (", ".join(still_missing) if still_missing else "无。ARHU200 和 EAP14 不是课程，没有建节点。"),
        ),
        (
            "logic_groups",
            "pass" if not group_problems else "fail",
            "组内逻辑不一致的组：" + (", ".join(group_problems) if group_problems else "0"),
        ),
        (
            "major_rows_attached",
            "pass" if attached == requirements else "fail",
            f"专业要求 {requirements} 行，规则课程 {attached} 行",
        ),
        (
            "offering_pattern_not_inferred",
            "pass" if invented == 0 else "fail",
            f"填写了 offering_pattern 的课程：{invented}",
        ),
    ]
    con.executemany("INSERT INTO audit_checks (name, status, detail) VALUES (?, ?, ?)", checks)


def write_report(con: sqlite3.Connection, category_counts: dict[str, int], text_repairs: int) -> None:
    nodes = con.execute(
        "SELECT COUNT(*) FROM course_aliases WHERE alias_code = course_id"
    ).fetchone()[0]
    edges = con.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    strict_edges = con.execute("SELECT COUNT(*) FROM graph_edges WHERE strict = 1").fetchone()[0]
    by_type = dict(
        con.execute("SELECT relation_type, COUNT(*) FROM graph_edges GROUP BY 1")
    )
    by_issue = dict(con.execute("SELECT issue, COUNT(*) FROM graph_edges GROUP BY 1"))
    excluded = con.execute(
        "SELECT relation_id, issue, note FROM relation_audit WHERE graph_use = 'exclude' ORDER BY relation_id"
    ).fetchall()
    rules = dict(con.execute("SELECT status, COUNT(*) FROM major_rules GROUP BY 1"))
    resolutions = dict(
        con.execute("SELECT resolution, COUNT(*) FROM major_rule_courses GROUP BY 1")
    )
    rule_rows = con.execute("SELECT COUNT(*) FROM major_rules").fetchone()[0]
    unresolved_major = con.execute(
        """
        SELECT c.listed_course_id, COUNT(*), GROUP_CONCAT(DISTINCT r.major)
        FROM major_rule_courses c
        JOIN major_rules r ON r.rule_id = c.rule_id
        WHERE c.resolution = 'unresolved'
        GROUP BY c.listed_course_id
        ORDER BY c.listed_course_id
        """
    ).fetchall()
    partial_rules = con.execute(
        """
        SELECT major, role, expected_n, course_count, status, substr(source_phrase, 1, 90), note
        FROM major_rules
        WHERE status LIKE 'partial%'
        ORDER BY major, role
        """
    ).fetchall()
    flagged = con.execute(
        """
        SELECT major, role, note
        FROM major_rules
        WHERE status = 'executable_flagged'
        ORDER BY major, role
        """
    ).fetchall()
    checks = con.execute("SELECT name, status, detail FROM audit_checks ORDER BY name").fetchall()
    alias_methods = dict(
        con.execute(
            """
            SELECT match_method, COUNT(*) FROM course_aliases
            WHERE match_method != 'self' GROUP BY 1
            """
        )
    )
    same_title = con.execute(
        """
        SELECT c1.course_id, c2.course_id, c1.course_name
        FROM courses c1
        JOIN courses c2 ON c1.course_id < c2.course_id
         AND c1.course_name IS NOT NULL
         AND lower(c1.course_name) = lower(c2.course_name)
         AND IFNULL(c1.units, -1) = IFNULL(c2.units, -1)
        WHERE c1.course_id IN (SELECT course_id FROM course_aliases WHERE alias_code = course_id)
          AND c2.course_id IN (SELECT course_id FROM course_aliases WHERE alias_code = course_id)
          AND c1.description IS NOT NULL
          AND c1.description = c2.description
        ORDER BY 1
        """
    ).fetchall()

    def line_for_exclude(row: tuple) -> str:
        return f"- 关系 {row[0]}：{row[1]}。{row[2]}"

    partial_lines = []
    for row in partial_rules:
        partial_lines.append(
            f"- {row[0]} / {row[1]} / 期望 {row[2] if row[2] is not None else '未写门数'} / 行数 {row[3]} / {row[4]}。原句：{row[5] or ''}"
        )
    unresolved_lines = [
        f"- {row[0]}（{row[1]} 行）：{row[2]}" for row in unresolved_major
    ] or ["- 无"]
    flagged_lines = [f"- {row[0]} / {row[1]}：{row[2]}" for row in flagged] or ["- 无"]
    same_title_lines = [
        f"- {row[0]} 与 {row[1]}：{row[2]}" for row in same_title
    ] or ["- 无"]
    check_lines = [f"- {row[0]}：{row[1]}。{row[2]}" for row in checks]
    category_line = "、".join(f"{key} {value}" for key, value in category_counts.items())

    report = f"""# 建图前数据质量报告

审计对象是 `data/curriculum.sqlite`。开课记录仍只表示 2025 Fall、2026 Spring、2026 Fall、2027 Spring 里实际出现过的课节。没有填写 Fall/Spring/Both，也没有把某一次开课写成以后每次都会开。

## 164 个开课代码

精确比对时，课表里有 164 个 `course_code` 不等于课程表的 `course_id`。处理结果：{category_line}。

- 交叉列课号对到手册里唯一的 `A/B` 课号。例如课表里的 `COMPSCI309` 和 `STATS302` 都指向 `COMPSCI309/STATS302`。
- `MEDIART405` 同时出现在两行完全相同的手册记录里。图上只保留 `HUM405/MEDIART405`，`GCULS405` 和 `MEDIART405/GCULS405` 也指向它。
- `MATH101A` 和 `MATH101B` 不并进 `MATH101`。课表里它们分别是 2 学分的微分和积分，手册里的 `MATH101` 是 4 学分的 Introductory Calculus。
- `MUSIC210` 和 `MUSIC211` 从被串进上一门课的手册正文里恢复。
- 其余代码在 2025-26 手册课程表里没有条目。它们按课表标题和学分建成课程节点，先修留空。

现在每个开课代码都能通过 `course_aliases` 找到课程节点，并写进 `class_sections.canonical_course_id`。非自身别名 {alias_methods}。

## 11 条源课程不存在的关系

这 11 条原来的来源是 `CHEM101`、`MATH205`、`ARHU200`、`GCHINA306`、`MUSIC210`、`POLSCI398-2`、`PSYCH304`、`EAP14`。

- `CHEM101` 保留为 `BIOL411/GLHLTH411` 的先修。手册没有 CHEM 101 的课程条目，所以节点没有课名。
- `MATH205` 保留两条：`MATH206` 的反向限制，以及 `MATH306` 先修里 “MATH 203 or MATH 205” 的一个选项。手册没有 MATH 205 的课程条目。
- `ARHU200` 的两条边删除。它不是课。
- `GCHINA306`、`MUSIC210`、`POLSCI398-2`、`PSYCH304` 都是被串进上一门课的真实课程。指向上一门课的边删除，课程本身按手册补回。
- `PSYCH304` 的手册先修是 PSYCH 101，以及 STATS 101 或 MATH 206。这三条边已经写入。
- `POLSCI398-2` 的手册先修是 GCHINA 108 或 POLSCI 101 或任课教师同意。同意不是节点，所以这条边不是硬性先修。
- `MUSIC210` 的先修是任课教师同意，没有边。
- `EAP14` 的两条边删除，不建课。

另外在逻辑核对里排除了 4 条原句不是先修的边：`GLHLTH312` 的推荐和串入课程，`PHYS306` 的 encouraged，`SOSC320` 的 highly encouraged。先修字段已改回手册原句的课程是 GCHINA305、PSYCH205、POLSCI398-1、MUSIC20、WOC290、GLHLTH312、WOC206。改前文字在 `course_text_repairs`。

排除的关系：

{chr(10).join(line_for_exclude(row) for row in excluded)}

## 逻辑编码

图使用的边共 {edges} 条，其中硬性边 {strict_edges} 条。按类型：{by_type}。按完整性：{by_issue}。

核对结果：

- AND：多个课号各自成组，组间 `group_relation = and`，组内 `single`。`COMPSCI309/STATS302` 的 MATH 201、MATH 202、MATH 206、COMPSCI 201 是这种编码。
- OR：同一组里 `logic_within_group = or`。`MATH206` 的 “MATH 101 or MATH 105” 是这种编码。
- 组间 OR 加组内 AND：`STATS303` 是（`COMPSCI309/STATS302`）或（MATH 405 且 COMPSCI 201），再加先修或共修 STATS 211，再加 MATH 304 和 MATH 305。
- 先修或共修共 {by_type.get('prerequisite_or_corequisite', 0)} 条：`COMPSCI203` 的 COMPSCI 201 或 MATH 202，`COMPSCI306` 的 COMPSCI 205，`STATS303` 的 STATS 211。没有单独的 corequisite 类型。
- 反向限制共 {by_type.get('antirequisite', 0)} 条，按手册原文的方向保存。互为反向的有 MATH101 与 MATH105、MATH302 与 MATH304、STATS210 与 STATS211、ECON201 与 PUBPOL205、COMPSCI309/STATS302 与 MATH405。CHEM105 只写出不能与 CHEM110 同时算，CHEM110 自己没有反向限制句，所以没有补反向边。COMPSCI101 的 “COMPSCI 201 and STATS 102” 编成两条都要排除的反向限制。

`issue = ok` 且 `strict = 1` 的边可以进入硬性先修判断。`listed_option` 和 `level_constraint` 只说明手册列出了这条路，不能判断学生没选这门课就一定不能上目标课。

## 1,224 条专业要求

全部 1,224 行都进入了 `major_rule_courses`。规则共 {rule_rows} 条，状态计数：{rules}。课号对应方式：{resolutions}。交叉列课只是左右顺序不同时，对应到手册里的同一门课，不另建节点。

规则读法：

- `all`：这一组里的课都要完成。
- `choose`：`choose_k` 是要选的门数，`expected_n` 是原句写出的候选门数。候选门数对不上时状态是 `partial_count`。
- `optional`：选修池。手册这一角色没有最少门数。
- `alternative`：签名作业的 option 1 与 option 2，完成其中一组。

可执行但做了对应说明的规则：

{chr(10).join(flagged_lines)}

还不能执行的规则：

{chr(10).join(partial_lines) if partial_lines else '- 无'}

专业要求里仍没有课程节点的课号：

{chr(10).join(unresolved_lines)}

`ENVIR302` 和 `ECON302` 课名、简介、学分都相同，但先修不同，所以没有并成一门。专业要求里的 `ENVIR302/ECON302` 因此仍不能落到一个节点。

图节点里仍有同名且简介相同的课，这次没有合并：

{chr(10).join(same_title_lines)}

## 建图就绪清单

图节点是 `course_aliases` 里 `alias_code = course_id` 的课，共 {nodes} 个。边表是 `graph_edges`。专业规则表是 `major_rules`。某门课在已记录学期里的开课，用 `class_sections.canonical_course_id` 查询。

检查：

{chr(10).join(check_lines)}

可以开始做的事：

- 用硬性先修边建立有向图。边的方向是先修课指向需要它的课，并带上 `group_id`、`logic_within_group`、`group_relation`。
- 先修判断按组计算：组内 AND 要全部完成，组内 OR 完成一门即可；组间再按 `group_relation` 合并。
- 查询一门课在四次已记录学期中出现过的课节。交叉列课用规范课号，不把出现过一次写成固定开课季节。
- 对状态以 `executable` 开头的专业规则做“这一组是否完成”的判断。

还不能当作正确结果的事：

- `partial_count` 和 `partial_unresolved` 的专业规则不能用来判断毕业要求是否完成。
- `strict = 0` 的边不能单独决定一门课有没有解锁。
- 全校节点一次性画在一张图上不可读。图的查看范围应是一门课的先修邻域，或一个专业的规则范围。
- 最短路径不能当作一份可以上课的计划。
- 不要运行 `data/build_curriculum_db.py`。它现在会拒绝覆盖这份已经载入开课记录的数据库。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def categorize_unmatched(con: sqlite3.Connection) -> dict[str, int]:
    courses = {
        row[0]
        for row in con.execute(
            "SELECT course_id FROM courses WHERE source = 'UG Bulletin 2025-2026 course descriptions'"
        )
    }
    part_to: dict[str, set[str]] = defaultdict(set)
    for cid in courses:
        for part in cid.split("/"):
            part_to[part].add(cid)
    codes = [
        row[0]
        for row in con.execute("SELECT DISTINCT course_code FROM class_sections ORDER BY 1")
    ]
    counts = {
        "交叉列课号": 0,
        "重复印刷的交叉列课": 0,
        "独立于 MATH101 的半门课": 0,
        "从手册正文恢复": 0,
        "仅课表有记录": 0,
    }
    for code in codes:
        if code in courses:
            continue
        hits = part_to.get(code, set())
        if code == "MEDIART405" and len(hits) > 1:
            counts["重复印刷的交叉列课"] += 1
        elif len(hits) == 1:
            counts["交叉列课号"] += 1
        elif code in {"MATH101A", "MATH101B"}:
            counts["独立于 MATH101 的半门课"] += 1
        elif code in {"MUSIC210", "MUSIC211"}:
            counts["从手册正文恢复"] += 1
        else:
            counts["仅课表有记录"] += 1
    if sum(counts.values()) != 164:
        raise SystemExit(f"未匹配开课代码不是 164，而是 {sum(counts.values())}：{counts}")
    return counts


def main() -> None:
    if not BACKUP_PATH.exists():
        shutil.copy(DB_PATH, BACKUP_PATH)
    con = sqlite3.connect(DB_PATH)
    try:
        category_counts = categorize_unmatched(con)
        ensure_schema(con)
        for row in RECOVERED_COURSES:
            insert_course(con, row)
        unresolved = []
        aliases = build_aliases(con)
        for code, in con.execute("SELECT DISTINCT course_code FROM class_sections"):
            if code not in aliases:
                unresolved.append(code)
        insert_section_shells(con, unresolved)
        aliases = build_aliases(con)
        con.executemany(
            "INSERT INTO course_aliases (alias_code, course_id, match_method, evidence) VALUES (?, ?, ?, ?)",
            [(alias, course_id, method, evidence) for alias, (course_id, method, evidence) in sorted(aliases.items())],
        )
        con.execute(
            """
            UPDATE class_sections
            SET canonical_course_id = (
                SELECT course_id FROM course_aliases WHERE alias_code = class_sections.course_code
            )
            """
        )
        text_repairs = repair_texts(con)
        insert_recovered_relations(con)
        for row in con.execute(
            """
            SELECT id, source_course, target_course, relation_type,
                   logic_within_group, group_relation, raw_clause
            FROM relations
            ORDER BY id
            """
        ):
            graph_use, issue, strict, note = classify_relation(row)
            con.execute(
                """
                INSERT INTO relation_audit (relation_id, graph_use, issue, strict, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (row[0], graph_use, issue, strict, note),
            )
        build_major_rules(con, aliases)
        build_graph_edges(con, aliases)
        write_checks(con, aliases)
        failed = con.execute(
            "SELECT name, detail FROM audit_checks WHERE status != 'pass'"
        ).fetchall()
        if failed:
            raise SystemExit("审计检查没有通过：" + "; ".join(f"{name}: {detail}" for name, detail in failed))
        con.execute("DELETE FROM source_notes WHERE field = 'graph_audit'")
        con.execute(
            """
            INSERT INTO source_notes (field, value) VALUES (
                'graph_audit',
                'course_aliases, graph_edges, major_rules, and class_sections.canonical_course_id are the graph inputs. See data/graph_readiness_report.md. Do not infer a standing offering pattern.'
            )
            """
        )
        write_report(con, category_counts, text_repairs)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
