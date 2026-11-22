#!/usr/bin/env python3
"""Build data/curriculum.sqlite from the DKU undergraduate bulletin PDF.

The website should read this database. Recorded class meetings live in
class_sections, which this script does not build. Do not infer that a course
offered in one Fall or Spring will be offered every later Fall or Spring.
Nothing in this script writes courselist.xlsx.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = ROOT / "ug_bulletin_2025-2026.pdf"
GOLD_PATH = ROOT / "curriculum_subset_math_cs_ds.xlsx"
DB_PATH = ROOT / "data" / "curriculum.sqlite"
REPORT_PATH = ROOT / "data" / "coverage_report.txt"

HUB_NOTE = (
    "The bulletin does not print a standing Fall/Spring/Both pattern. "
    "Recorded meetings are stored only in class_sections. "
    "Do not infer that a course offered in one recorded Fall or Spring "
    "will be offered in every later Fall or Spring."
)

MAJORS = [
    ("Applied Mathematics and Computational Sciences/Computer Science", "AMCS-Computer Science"),
    ("Applied Mathematics and Computational Sciences/Mathematics", "AMCS-Mathematics"),
    ("Arts and Media/Arts", "Arts and Media-Arts"),
    ("Arts and Media/Media", "Arts and Media-Media"),
    ("Behavioral Science/Economics", "Behavioral Science-Economics"),
    ("Behavioral Science/Neuroscience", "Behavioral Science-Neuroscience"),
    ("Behavioral Science/Psychology", "Behavioral Science-Psychology"),
    ("Computation and Design/Computer Science", "Computation and Design-Computer Science"),
    ("Computation and Design/Digital Media", "Computation and Design-Digital Media"),
    ("Computation and Design/Social Policy", "Computation and Design-Social Policy"),
    ("Cultures and Societies/Cultural Anthropology", "Cultures and Societies-Cultural Anthropology"),
    ("Cultures and Societies/Sociology", "Cultures and Societies-Sociology"),
    ("Data Science", "Data Science"),
    ("Environmental Science/Biogeochemistry", "Environmental Science-Biogeochemistry"),
    ("Environmental Science/Biology", "Environmental Science-Biology"),
    ("Environmental Science/Chemistry", "Environmental Science-Chemistry"),
    ("Environmental Science/Public Policy", "Environmental Science-Public Policy"),
    ("Global China Studies", "Global China Studies"),
    ("Global Health/Biology", "Global Health-Biology"),
    ("Global Health/Public Policy", "Global Health-Public Policy"),
    ("Humanities/Creative Writing and Translation", "Humanities-Creative Writing and Translation"),
    ("Humanities/Literature", "Humanities-Literature"),
    ("Humanities/Philosophy and Religion", "Humanities-Philosophy and Religion"),
    ("Humanities/World History", "Humanities-World History"),
    ("Materials Science/Chemistry", "Materials Science-Chemistry"),
    ("Materials Science/Physics", "Materials Science-Physics"),
    ("Molecular Bioscience/Biogeochemistry", "Molecular Bioscience-Biogeochemistry"),
    ("Molecular Bioscience/Biophysics", "Molecular Bioscience-Biophysics"),
    ("Molecular Bioscience/Cell and Molecular Biology", "Molecular Bioscience-Cell and Molecular Biology"),
    ("Molecular Bioscience/Genetics and Genomics", "Molecular Bioscience-Genetics and Genomics"),
    ("Molecular Bioscience/Neuroscience", "Molecular Bioscience-Neuroscience"),
    ("Philosophy, Politics, and Economics/Economic History", "PPE-Economic History"),
    ("Philosophy, Politics, and Economics/Philosophy", "PPE-Philosophy"),
    ("Philosophy, Politics, and Economics/Political Science", "PPE-Political Science"),
    ("Philosophy, Politics, and Economics/Public Policy", "PPE-Public Policy"),
    ("Quantitative Political Economy/Economics", "QPE-Economics"),
    ("Quantitative Political Economy/Political Science", "QPE-Political Science"),
    ("Quantitative Political Economy/Public Policy", "QPE-Public Policy"),
]

CODE_TOKEN = r"[A-Z]{2,}\s*\d{2,3}(?:-\d+)?[A-Z]?"
CODE_HEAD = re.compile(
    rf"^(?P<codes>{CODE_TOKEN}(?:\s*/\s*{CODE_TOKEN})*)\s+(?P<rest>.+)$"
)
CODE_ONLY = re.compile(
    rf"^(?P<codes>{CODE_TOKEN}(?:\s*/\s*{CODE_TOKEN})*)$"
)
CREDITS_END = re.compile(r"\((\d+)\s*credits?\)\s*$", re.I)
PRE_RE = re.compile(
    r"^(?:Pre(?:\s*/\s*|\s+or\s+)Co-?requisite(?:\(s\)|s)?|Pre-?requisite(?:\(s\)|s)?)\s*:\s*(.*)$",
    re.I,
)
ANTI_RE = re.compile(r"^Anti-?requisite(?:\(s\)|s)?\s*:\s*(.*)$", re.I)
SUBJECT_RE = re.compile(r"^Courses with Course Subject:\s+.+?\(([A-Z]{2,})\)\s*$")
CREDIT_ONLY = re.compile(r"^\d{1,2}$")
SKIP_LINE = re.compile(r"^Back to TOC$")

CATEGORY_RE = re.compile(
    r"^(Divisional Foundation(?: Courses)?|Interdisciplinary(?: Courses)?|"
    r"Disciplinary(?: Courses)?|Capstone(?: Courses)?|Electives)\b",
    re.I,
)
INSTRUCTION_RE = re.compile(
    r"^(Choose\b|And choose\b|And complete\b|Complete the following\b|"
    r"List\s*\d|Students are required|Students must|Electives\b)",
    re.I,
)
BOUNDARY_RE = re.compile(
    r"^(Course Cluster\b|List\s*\d|.*\bConcentration\b|"
    r"Film\s*&\s*Documentary|Studio\s*&\s*Performance|Digital Culture)",
    re.I,
)
SKIP_MAJOR_LINE = re.compile(
    r"^(Course Code|Course Name|Course Credit|Course|Credit|Academic Year|"
    r"First Year|Second Year|Third Year|Fourth Year|Requirements|"
    r"Major Requirements)$",
    re.I,
)


def norm_space(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    text = text.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def norm_title(text: str) -> str:
    text = norm_space(text)
    text = re.sub(r"\s*/\s*", "/", text)
    return text.lower()


TITLE_TO_MAJOR = {norm_title(title): short for title, short in MAJORS}


def page_lines(page) -> list[str]:
    """One visual line per row. Drop SimSun spaces inserted inside justified words."""
    data = page.get_text("dict")
    lines = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            parts = []
            for span in line.get("spans", []):
                if span.get("text", "").strip() == "" and "SimSun" in span.get("font", ""):
                    continue
                parts.append(span.get("text", ""))
            raw = norm_space("".join(parts))
            if not raw or SKIP_LINE.match(raw):
                if raw == "Back to TOC":
                    lines.append("__PAGEBREAK__")
                continue
            if lines and lines[-1] == "__PAGEBREAK__" and re.fullmatch(r"\d{1,3}", raw):
                lines.pop()
                continue
            if lines and lines[-1] == "__PAGEBREAK__":
                lines.pop()
            lines.append(raw)
    if lines and lines[-1] == "__PAGEBREAK__":
        lines.pop()
    return lines


def join_broken_codes(lines: list[str]) -> list[str]:
    """Rejoin table cells that PyMuPDF splits, such as 'STATS' + '302/COMPSCI' + '309'."""
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.fullmatch(r"[A-Z]{2,}", line) and i + 1 < len(lines):
            nxt = lines[i + 1]
            if re.match(r"^(?:/|\d)", nxt):
                merged = f"{line} {nxt}"
                i += 2
                if (
                    i < len(lines)
                    and re.fullmatch(r"\d{2,3}[A-Z]?", lines[i])
                    and not re.search(r"\d{2,3}[A-Z]?$", merged.strip())
                ):
                    merged = f"{merged} {lines[i]}"
                    i += 1
                out.append(norm_space(merged))
                continue
        if CODE_ONLY.match(line) and i + 1 < len(lines) and lines[i + 1].startswith("/"):
            out.append(norm_space(line + lines[i + 1]))
            i += 2
            continue
        out.append(line)
        i += 1
    return out


def explode_requirement_labels(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        parts = re.split(r"(?<=\.)\s+(?=(?:Anti|Pre)-?requisite)", line, flags=re.I)
        for part in parts:
            part = part.strip()
            if part:
                out.append(part)
    return out


def document_lines(doc) -> list[str]:
    lines = []
    for page in doc:
        lines.extend(page_lines(page))
    return explode_requirement_labels(join_broken_codes(lines))


def canon_code(code: str) -> str:
    parts = []
    for piece in re.split(r"\s*/\s*", code.strip()):
        parts.append(re.sub(r"\s+", "", piece).upper())
    return "/".join(parts)


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


def find_marker(lines: list[str], predicate, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if predicate(lines[i]):
            return i
    raise RuntimeError("marker not found")


def match_catalog_header(lines: list[str], index: int):
    line = lines[index]
    match = CODE_HEAD.match(line)
    if not match:
        return None
    credits = CREDITS_END.search(match.group("rest"))
    if credits:
        title = CREDITS_END.sub("", match.group("rest")).strip(" -")
        return canon_code(match.group("codes")), norm_space(title), int(credits.group(1)), 1
    if index + 1 >= len(lines):
        return None
    nxt = lines[index + 1]
    if CODE_HEAD.match(nxt) or CODE_ONLY.match(nxt):
        return None
    credits = CREDITS_END.search(nxt)
    if not credits:
        return None
    title = norm_space(match.group("rest") + " " + CREDITS_END.sub("", nxt))
    title = title.strip(" -")
    return canon_code(match.group("codes")), title, int(credits.group(1)), 2


def parse_catalog(lines: list[str]) -> dict[str, dict]:
    start = find_marker(lines, lambda s: s == "Course Descriptions")
    courses: dict[str, dict] = {}
    alias: dict[str, str] = {}
    current = None
    mode = None
    section_dept = None

    def ensure(cid: str) -> dict:
        if cid not in courses:
            courses[cid] = {
                "course_id": cid,
                "course_name": None,
                "department": department_of(cid),
                "level": level_of(cid),
                "units": None,
                "description": [],
                "prereq_text": [],
                "antireq_text": [],
                "notes": [],
            }
            for part in cid.split("/"):
                alias[part] = cid
            alias[cid] = cid
        return courses[cid]

    i = start + 1
    while i < len(lines):
        line = lines[i]
        subject = SUBJECT_RE.match(line)
        if subject:
            section_dept = subject.group(1)
            mode = None
            i += 1
            continue
        header = match_catalog_header(lines, i)
        if header:
            cid, title, units, consumed = header
            # Same cross-list printed under the other subject keeps the first id.
            existing = None
            parts = frozenset(cid.split("/"))
            for known in courses:
                if frozenset(known.split("/")) == parts:
                    existing = known
                    break
            cid = existing or cid
            row = ensure(cid)
            if title and not row["course_name"]:
                row["course_name"] = title
            elif not title and not row["course_name"]:
                row["notes"].append("Bulletin header has no course title.")
            if row["units"] is None:
                row["units"] = units
            if section_dept and "/" not in cid:
                row["department"] = section_dept
            current = cid
            mode = "skip" if row["description"] else "description"
            i += consumed
            continue
        pre = PRE_RE.match(line)
        anti = ANTI_RE.match(line)
        if current and pre:
            if courses[current]["prereq_text"]:
                mode = "skip"
            else:
                mode = "prereq"
                payload = pre.group(1)
                if re.match(r"^Pre(?:\s*/\s*|\s+or\s+)Co", line, re.I):
                    payload = "pre or co-requisite: " + payload
                if payload:
                    courses[current]["prereq_text"].append(payload)
            i += 1
            continue
        if current and anti:
            if courses[current]["antireq_text"]:
                mode = "skip"
            else:
                mode = "antireq"
                if anti.group(1):
                    courses[current]["antireq_text"].append(anti.group(1))
            i += 1
            continue
        if current and mode == "skip":
            i += 1
            continue
        if current and mode in {"prereq", "antireq"}:
            courses[current][f"{mode}_text"].append(line)
            i += 1
            continue
        if current and mode == "description":
            if line.lower().startswith("recommended"):
                courses[current]["notes"].append(line)
            else:
                courses[current]["description"].append(line)
        i += 1

    for row in courses.values():
        row["description"] = repair_split_words(glue_fragments(row["description"])) or None
        row["prereq_text"] = repair_split_words(norm_space(" ".join(row["prereq_text"]))) or None
        row["antireq_text"] = repair_split_words(norm_space(" ".join(row["antireq_text"]))) or None
        row["course_name"] = repair_split_words(row["course_name"]) if row["course_name"] else None
        row["notes"] = norm_space(" ".join(row["notes"])) or None
    return courses


def glue_fragments(parts: list[str]) -> str:
    """Join words the PDF breaks at the end of a line, such as 'concepts f' + 'rom'."""
    out = ""
    for part in parts:
        if not part:
            continue
        if out and re.search(r"(?:^|\s)[A-Za-z]$", out) and re.match(r"[a-z]", part):
            out += part
        elif out:
            out += " " + part
        else:
            out = part
    return norm_space(out)


def repair_split_words(text: str | None) -> str | None:
    """Join letters split by PDF justification, such as 't echniques' or 'f rom'."""
    if not text:
        return text
    return re.sub(r"\b([b-hj-z])\s+(?=[a-z])", r"\1", text)


def expand_bare_numbers(text: str) -> str:
    """Turn 'MATH 101 or 105' and 'MATH101 or 105' into full course codes."""
    pattern = re.compile(
        r"([A-Z]{2,})\s*(\d{2,3}(?:-\d+)?[A-Z]?)|((?:or|and|,)\s+)(\d{2,3}(?:-\d+)?[A-Z]?)\b",
    )
    subject = None

    def repl(match):
        nonlocal subject
        if match.group(1):
            subject = match.group(1).upper()
            return f"{subject} {match.group(2)}"
        if subject and match.group(4):
            return f"{match.group(3)}{subject} {match.group(4)}"
        return match.group(0)

    return pattern.sub(repl, text)


def strip_consent(text: str) -> str:
    text = re.sub(
        r"(?:,?\s*(?:or|and))?\s*(?:consent of (?:the )?instructor|permission(?: only)?"
        r"(?: of (?:the )?instructor)?|instructor permission)\b",
        "",
        text,
        flags=re.I,
    )
    return norm_space(text).strip(" ;,.")


def split_top(text: str, sep_re: str) -> list[str]:
    parts = []
    buf = []
    depth = 0
    i = 0
    pattern = re.compile(sep_re, re.I)
    while i < len(text):
        char = text[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if depth == 0:
            match = pattern.match(text, i)
            if match:
                piece = "".join(buf).strip(" ;,")
                if piece:
                    parts.append(piece)
                buf = []
                i = match.end()
                continue
        buf.append(char)
        i += 1
    tail = "".join(buf).strip(" ;,")
    if tail:
        parts.append(tail)
    return parts


def clause_type(clause: str) -> str:
    if re.search(r"pre-?(?:\s*/\s*|\s+or\s+)co-?\s*requisite", clause, re.I):
        return "prerequisite_or_corequisite"
    has_pre = re.search(r"pre-?\s*requisite", clause, re.I)
    has_co = re.search(r"co-?\s*requisite", clause, re.I)
    if has_pre and has_co:
        return "prerequisite_or_corequisite"
    if has_co and not has_pre:
        return "corequisite"
    return "prerequisite"


def codes_in(text: str) -> list[str]:
    found = []
    for match in re.finditer(
        rf"{CODE_TOKEN}(?:\s*/\s*{CODE_TOKEN})*",
        text,
    ):
        found.append(canon_code(match.group(0)))
    # unique, keep order
    out = []
    seen = set()
    for cid in found:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def parse_relation_text(raw: str, kind: str) -> list[dict]:
    """Parse AND/OR prerequisite text. Recommended and consent-only text yield no edges."""
    if not raw:
        return []
    text = norm_space(raw)
    pieces = re.split(r"(?<=\.)\s+|;\s*", text)
    kept = [piece for piece in pieces if piece and not re.search(r"\bis recommended\b", piece, re.I)]
    text = norm_space("; ".join(kept))
    if not text or re.match(r"^(recommended|permission only)\b", text, re.I):
        return []
    text = expand_bare_numbers(text)
    clauses = split_top(text, r";\s*")
    rows = []
    group_index = 0
    for clause in clauses:
        link = "and"
        lead = re.match(r"^(and|or)\b\s*", clause, re.I)
        if lead:
            link = lead.group(1).lower()
            clause = clause[lead.end() :]
        if re.search(r"\bis recommended\b", clause, re.I):
            continue
        clause = strip_consent(clause)
        if not clause:
            continue
        relation = kind if kind == "antirequisite" else clause_type(clause)
        clause = re.sub(
            r"\b(?:pre-?\s*or\s*co-?\s*requisite|co-?\s*requisite|pre-?\s*requisite)"
            r"(?:\s+or\s+co-?\s*requisite)?\s*:?\s*",
            " ",
            clause,
            flags=re.I,
        )
        clause = clause.replace("(", " ").replace(")", " ")
        clause = norm_space(clause)
        or_parts = split_top(clause, r"\s+or\s+")
        if len(or_parts) > 1:
            part_ids = [codes_in(part) for part in or_parts]
            if all(len(ids) <= 1 for ids in part_ids):
                ids = [cid for ids in part_ids for cid in ids]
                if ids:
                    group_index += 1
                    logic = "or" if len(ids) > 1 else "single"
                    for cid in ids:
                        rows.append(
                            {
                                "source_course": cid,
                                "group_id": f"G{group_index}",
                                "relation_type": relation,
                                "logic_within_group": logic,
                                "group_relation": link,
                                "raw_clause": clause,
                            }
                        )
                continue
            for part_i, ids in enumerate(part_ids):
                if not ids:
                    continue
                group_index += 1
                logic = "and" if len(ids) > 1 else "single"
                for cid in ids:
                    rows.append(
                        {
                            "source_course": cid,
                            "group_id": f"G{group_index}",
                            "relation_type": relation,
                            "logic_within_group": logic,
                            "group_relation": "or" if part_i else link,
                            "raw_clause": or_parts[part_i],
                        }
                    )
            continue
        ids = codes_in(clause)
        if not ids:
            continue
        # An OR-alternative such as "or MATH 405 and COMPSCI 201" stays one group.
        if link == "or" and len(ids) > 1:
            group_index += 1
            logic = "and" if re.search(r"\band\b|,", clause, re.I) else "or"
            for cid in ids:
                rows.append(
                    {
                        "source_course": cid,
                        "group_id": f"G{group_index}",
                        "relation_type": relation,
                        "logic_within_group": logic,
                        "group_relation": link,
                        "raw_clause": clause,
                    }
                )
            continue
        # Top-level AND lists become one single-course group each, matching the gold tables.
        if len(ids) > 1 and re.search(r"\band\b|,", clause, re.I):
            for cid in ids:
                group_index += 1
                rows.append(
                    {
                        "source_course": cid,
                        "group_id": f"G{group_index}",
                        "relation_type": relation,
                        "logic_within_group": "single",
                        "group_relation": link,
                        "raw_clause": clause,
                    }
                )
            continue
        group_index += 1
        logic = "or" if len(ids) > 1 else "single"
        for cid in ids:
            rows.append(
                {
                    "source_course": cid,
                    "group_id": f"G{group_index}",
                    "relation_type": relation,
                    "logic_within_group": logic,
                    "group_relation": link,
                    "raw_clause": clause,
                }
            )
    return rows


def role_from_phrase(phrase: str) -> str:
    compact = re.sub(r"\s+", "", phrase).lower()
    rules = [
        (r"choose(?:one|1)ofthefollowing(?:two|2)", "choose_one_of_two"),
        (r"choose(?:one|1)ofthefollowing(?:three|3)", "choose_one_of_three"),
        (r"choose(?:one|1)ofthefollowing(?:four|4)", "choose_one_of_four"),
        (r"choose(?:two|2)ofthefollowing(?:four|4)", "choose_two_of_four"),
        (r"choose(?:two|2)ofthefollowing(?:five|5)", "choose_two_of_five"),
        (r"choose(?:two|2)ofthefollowing(?:three|3)", "choose_two_of_three"),
        (r"choose(?:one|1)ofthefollowing", "choose_one"),
        (r"choose(?:two|2)ofthefollowing", "choose_two"),
        (r"choose(?:three|3)ofthefollowing", "choose_three"),
        (r"chooseoneofthefollowingtwomath", "choose_one_of_two"),
        (r"andcomplete", "required"),
        (r"completetthefollowing", "required"),
        (r"completthefollowing", "required"),
        (r"electives", "elective"),
    ]
    # The compact form of "complete the following" is "completetthefollowing"
    # only if spaces are removed as "complete"+"the"... "complete the following"
    # -> "completetthefollowing". Check both.
    compact = compact.replace("completetthefollowing", "completethefollowing")
    rules = [
        (r"choose(?:one|1)ofthefollowing(?:two|2)", "choose_one_of_two"),
        (r"choose(?:one|1)coursefromthefollowing(?:two|2)", "choose_one_of_two"),
        (r"choose(?:one|1)ofthefollowing(?:three|3)", "choose_one_of_three"),
        (r"choose(?:one|1)coursefromthefollowing(?:three|3)", "choose_one_of_three"),
        (r"choose(?:one|1)ofthefollowing(?:four|4)", "choose_one_of_four"),
        (r"choose(?:two|2)ofthefollowing(?:four|4)", "choose_two_of_four"),
        (r"choose(?:two|2)ofthefollowing(?:five|5)", "choose_two_of_five"),
        (r"choose(?:two|2)ofthefollowing(?:three|3)", "choose_two_of_three"),
        (r"choose(?:three|3)ofthefollowing", "choose_three"),
        (r"choose(?:two|2)ofthefollowing", "choose_two"),
        (r"choose(?:one|1)ofthefollowing", "choose_one"),
        (r"choose(?:one|1)course", "choose_one"),
        (r"andchoosetwo", "choose_two"),
        (r"andchooseone", "choose_one"),
        (r"completethefollowing", "required"),
        (r"andcompletethefollowing", "required"),
        (r"^electives", "elective"),
    ]
    for pattern, role in rules:
        if re.search(pattern, compact):
            return role
    return "required"


def automatic_status(phrase: str, course_count: int) -> tuple[str, str]:
    """Return partial or blocked. This parser never marks a rule verified."""
    text = norm_space(phrase or "")
    lowered = text.lower()
    if not text:
        return "blocked", "没有手册原句，不能自动判断。"
    if re.search(r"\b(cluster|concentration)\b", lowered) or re.search(r"list\s*\d", lowered):
        return "partial", "分组、方向或 List 需要人工确认边界。"
    if "credit" in lowered or "at least" in lowered:
        return "partial", "学分或至少条件不能自动当成全部完成。"
    if "choose" in lowered:
        return "partial", "选课句不能自动升级为已验证规则。"
    if course_count <= 0:
        return "blocked", "要求句下面没有解析到课程。"
    return "partial", "自动解析结果尚未人工对照手册。"


def refine_role(role: str, count: int) -> str:
    """Use the length of the bulletin list. 'Choose two' over four rows is choose_two_of_four."""
    table = {
        ("choose_one", 2): "choose_one_of_two",
        ("choose_one", 3): "choose_one_of_three",
        ("choose_one", 4): "choose_one_of_four",
        ("choose_two", 3): "choose_two_of_three",
        ("choose_two", 4): "choose_two_of_four",
        ("choose_two", 5): "choose_two_of_five",
        ("choose_three", 4): "choose_three_of_four",
    }
    return table.get((role, count), role)


def apply_role_counts(rows: list[dict]) -> list[dict]:
    grouped: list[list[dict]] = []
    for row in rows:
        key = (row["major"], row["category"], row["source_phrase"], row["role"])
        if grouped and (
            grouped[-1][0]["major"],
            grouped[-1][0]["category"],
            grouped[-1][0]["source_phrase"],
            grouped[-1][0]["role"],
        ) == key:
            grouped[-1].append(row)
        else:
            grouped.append([row])
    out = []
    for group in grouped:
        role = refine_role(group[0]["role"], len(group))
        for row in group:
            row["role"] = role
            out.append(row)
    return out


def category_name(line: str) -> str | None:
    match = CATEGORY_RE.match(line)
    if not match:
        return None
    low = match.group(1).lower()
    if low.startswith("divisional"):
        return "Divisional Foundation"
    if low.startswith("interdisciplinary"):
        return "Interdisciplinary"
    if low.startswith("disciplinary"):
        return "Disciplinary"
    if low.startswith("capstone"):
        return "Capstone"
    if low.startswith("elective"):
        return "Electives"
    return None


def parse_common_core(lines: list[str]) -> list[dict]:
    """Common core and signature-work options that apply before any major."""
    start = None
    for index, line in enumerate(lines):
        if line == "Requirements for All Majors" and any(
            lines[j].startswith("Common Core") for j in range(index, min(index + 12, len(lines)))
        ):
            start = index
            break
    if start is None:
        return []
    end = find_marker(
        lines,
        lambda s: norm_title(s)
        == norm_title("Applied Mathematics and Computational Sciences/Computer Science"),
        start,
    )
    chunk = lines[start:end]
    category = None
    role = "required"
    phrase = ""
    rows = []
    i = 0
    while i < len(chunk):
        line = chunk[i]
        if line.startswith("Common Core"):
            category, role, phrase = "Common Core", "required", line
            i += 1
            continue
        if line.startswith("Signature Work Capstone Courses"):
            category, role, phrase = "Signature Work", "required", line
            i += 1
            continue
        if line.startswith("Option 1"):
            category, role, phrase = "Signature Work", "option_1", line
            i += 1
            continue
        if line.startswith("Option 2"):
            category, role, phrase = "Signature Work", "option_2", line
            i += 1
            continue
        if line.startswith("Mini-Term") or line.startswith("DKU 101"):
            category, role, phrase = "Mini-Term", "required", line
            i += 1
            continue
        if category not in {"Common Core", "Signature Work", "Mini-Term"} or not CODE_ONLY.match(line):
            i += 1
            continue
        cid = canon_code(line)
        name_parts = []
        units = None
        j = i + 1
        while j < len(chunk) and j < i + 6:
            if CODE_ONLY.match(chunk[j]) or chunk[j].startswith(
                ("Option ", "Common Core", "Signature Work Capstone Courses", "Distributional", "Language Courses", "Writing Course", "Mini-Term")
            ):
                break
            if CREDIT_ONLY.match(chunk[j]) and int(chunk[j]) <= 12:
                units = int(chunk[j])
                j += 1
                break
            if SKIP_MAJOR_LINE.match(chunk[j]) or chunk[j] in {"First Year", "Second Year", "Third Year"}:
                j += 1
                continue
            name_parts.append(chunk[j])
            j += 1
        rows.append(
            {
                "major": "All Majors",
                "category": category,
                "role": role,
                "course_id": cid,
                "course_name": norm_space(" ".join(name_parts)) or None,
                "units": units,
                "source_phrase": phrase,
            }
        )
        i = j
    return rows


def parse_majors(lines: list[str]) -> tuple[list[dict], int]:
    part = find_marker(lines, lambda s: s.startswith("Part 10: Majors and Courses"))
    catalog = find_marker(lines, lambda s: s == "Course Descriptions", part)
    body = lines[part:catalog]
    hits = []
    for index, line in enumerate(body):
        short = TITLE_TO_MAJOR.get(norm_title(line))
        if not short:
            continue
        window = body[index : index + 80]
        if any(category_name(item) == "Divisional Foundation" for item in window):
            distance = next(
                i for i, item in enumerate(window) if category_name(item) == "Divisional Foundation"
            )
            hits.append((index, short, distance))
    best: dict[str, tuple[int, int]] = {}
    for index, short, distance in hits:
        current = best.get(short)
        if current is None or distance < current[1] or (distance == current[1] and index > current[0]):
            best[short] = (index, distance)
    ordered = sorted(((index, short) for short, (index, _) in best.items()), key=lambda item: item[0])
    rows = []
    for pos, (start, short) in enumerate(ordered):
        end = ordered[pos + 1][0] if pos + 1 < len(ordered) else len(body)
        rows.extend(parse_one_major(short, body[start:end]))
    rows.extend(parse_common_core(lines))
    return apply_role_counts(rows), len(ordered)


def parse_one_major(short: str, chunk: list[str]) -> list[dict]:
    rows = []
    category = None
    role = "required"
    phrase = ""
    boundary = ""
    i = 0
    while i < len(chunk):
        line = chunk[i]
        if BOUNDARY_RE.match(line):
            boundary = line
            i += 1
            continue
        cat = category_name(line)
        if cat:
            category = cat
            role = "elective" if cat == "Electives" else "required"
            phrase = line
            boundary = ""
            i += 1
            continue
        if SKIP_MAJOR_LINE.match(line):
            i += 1
            continue
        if INSTRUCTION_RE.match(line):
            parts = [line]
            j = i + 1
            while j < len(chunk) and j < i + 4:
                if (
                    CODE_ONLY.match(chunk[j])
                    or category_name(chunk[j])
                    or INSTRUCTION_RE.match(chunk[j])
                ):
                    break
                parts.append(chunk[j])
                j += 1
            phrase = norm_space(" ".join(parts))
            if boundary:
                phrase = norm_space(f"{boundary}. {phrase}")
                boundary = ""
            role = role_from_phrase(phrase)
            i = j
            continue
        if category and CODE_ONLY.match(line):
            cid = canon_code(line)
            name_parts = []
            units = None
            j = i + 1
            while j < len(chunk) and j < i + 6:
                if CODE_ONLY.match(chunk[j]) or category_name(chunk[j]) or INSTRUCTION_RE.match(chunk[j]):
                    break
                if CREDIT_ONLY.match(chunk[j]) and int(chunk[j]) <= 12:
                    units = int(chunk[j])
                    j += 1
                    break
                if SKIP_MAJOR_LINE.match(chunk[j]):
                    j += 1
                    continue
                name_parts.append(chunk[j])
                j += 1
            rows.append(
                {
                    "major": short,
                    "category": category,
                    "role": role,
                    "course_id": cid,
                    "course_name": norm_space(" ".join(name_parts)) or None,
                    "units": units,
                    "source_phrase": phrase,
                }
            )
            i = j
            continue
        i += 1
    return rows


def resolve_course_id(cid: str, courses: dict[str, dict]) -> str:
    if cid in courses:
        return cid
    parts = cid.split("/")
    if len(parts) > 1:
        wanted = frozenset(parts)
        for known in courses:
            if frozenset(known.split("/")) == wanted:
                return known
    for known in courses:
        if cid in known.split("/"):
            # Prefer the cross-listed id only when this code is not its own course.
            if known == cid:
                return known
    if any(cid == known or cid in known.split("/") for known in courses):
        matches = [known for known in courses if cid == known or cid in known.split("/")]
        # A standalone course wins over a cross-list that merely mentions it.
        for known in matches:
            if known == cid:
                return known
        return matches[0]
    return cid


def build_relations(courses: dict[str, dict]) -> list[dict]:
    rows = []
    for cid, course in courses.items():
        for kind, raw in (
            ("prerequisite", course.get("prereq_text")),
            ("antirequisite", course.get("antireq_text")),
        ):
            for row in parse_relation_text(raw, kind):
                row["source_course"] = resolve_course_id(row["source_course"], courses)
                row["target_course"] = cid
                rows.append(row)
    return rows


def init_db(path: Path) -> sqlite3.Connection:
    if path.exists():
        existing = sqlite3.connect(path)
        has_sections = existing.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'class_sections'"
        ).fetchone()
        existing.close()
        if has_sections:
            raise SystemExit(
                "Refusing to delete curriculum.sqlite because class_sections is already loaded. "
                "This builder replaces bulletin tables only and would wipe recorded class meetings."
            )
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE courses (
            course_id TEXT PRIMARY KEY,
            course_name TEXT,
            department TEXT,
            level INTEGER,
            units INTEGER,
            description TEXT,
            prereq_text TEXT,
            antireq_text TEXT,
            notes TEXT,
            offering_pattern TEXT,
            source TEXT NOT NULL
        );
        CREATE TABLE relations (
            id INTEGER PRIMARY KEY,
            source_course TEXT NOT NULL,
            target_course TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            group_id TEXT,
            logic_within_group TEXT,
            group_relation TEXT,
            raw_clause TEXT
        );
        CREATE TABLE major_requirements (
            id INTEGER PRIMARY KEY,
            major TEXT NOT NULL,
            category TEXT,
            role TEXT,
            course_id TEXT NOT NULL,
            course_name TEXT,
            units INTEGER,
            source_phrase TEXT
        );
        CREATE TABLE source_notes (
            field TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE coverage_diff (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            item TEXT NOT NULL,
            detail TEXT
        );
        """
    )
    return conn


def norm_cmp(text) -> str:
    if text is None:
        return ""
    text = norm_space(str(text)).lower()
    text = text.replace(" ", "")
    text = text.replace(".", "")
    return text


def ident(cid: str) -> str:
    parts = sorted(canon_code(str(cid)).split("/"))
    return "/".join(parts)


def compare_gold(conn: sqlite3.Connection, courses: dict, relations: list[dict], majors: list[dict]) -> str:
    import pandas as pd

    gold_courses = pd.read_excel(GOLD_PATH, "courses")
    gold_rel = pd.read_excel(GOLD_PATH, "relations")
    gold_maj = pd.read_excel(GOLD_PATH, "major_requirements")
    diffs = []

    gold_ids = [canon_code(str(x)) for x in gold_courses.course_id]
    found_ids = {ident(cid) for cid in courses}
    missing_courses = [cid for cid in gold_ids if ident(cid) not in found_ids]
    for cid in missing_courses:
        diffs.append(("missing_course", cid, "gold course id not extracted from bulletin"))

    gold_by_id = {canon_code(str(r.course_id)): r for r in gold_courses.itertuples(index=False)}
    by_ident = {ident(cid): course for cid, course in courses.items()}
    name_mismatch = units_mismatch = prereq_mismatch = 0
    compared = 0
    for cid, grow in gold_by_id.items():
        row = courses.get(cid) or by_ident.get(ident(cid))
        if not row:
            continue
        compared += 1
        if norm_cmp(row["course_name"]) != norm_cmp(grow.course_name):
            name_mismatch += 1
            diffs.append(("name", cid, f"bulletin={row['course_name']!r} gold={grow.course_name!r}"))
        gold_units = None if pd.isna(grow.units) else int(grow.units)
        if row["units"] != gold_units:
            units_mismatch += 1
            diffs.append(("units", cid, f"bulletin={row['units']} gold={gold_units}"))
        if norm_cmp(row["prereq_text"]) != norm_cmp(grow.prereq_text if not pd.isna(grow.prereq_text) else ""):
            prereq_mismatch += 1
            diffs.append(("prereq_text", cid, f"bulletin={row['prereq_text']!r} gold={grow.prereq_text!r}"))

    def edge_key(src, tgt, rtype):
        return (ident(src), ident(tgt), str(rtype).lower())

    gold_ids_ident = {ident(cid) for cid in gold_by_id}
    gold_edges = {
        edge_key(r.source_course, r.target_course, r.relation_type)
        for r in gold_rel.itertuples(index=False)
    }
    our_edges = {
        edge_key(r["source_course"], r["target_course"], r["relation_type"])
        for r in relations
        if ident(r["target_course"]) in gold_ids_ident
    }
    # Gold co-requisite wording is stored as prerequisite. Count a match if we
    # recorded prerequisite_or_corequisite for the same pair.
    relaxed_our = set()
    for src, tgt, rtype in our_edges:
        relaxed_our.add((src, tgt, rtype))
        if rtype == "prerequisite_or_corequisite":
            relaxed_our.add((src, tgt, "prerequisite"))
    missing_edges = sorted(gold_edges - relaxed_our)
    extra_edges = sorted(
        e for e in our_edges if e not in gold_edges and (e[0], e[1], "prerequisite") not in gold_edges
        and not (e[2] == "prerequisite_or_corequisite" and (e[0], e[1], "prerequisite") in gold_edges)
    )
    for src, tgt, rtype in missing_edges:
        diffs.append(("missing_edge", f"{src}->{tgt}", rtype))
    for src, tgt, rtype in extra_edges:
        if tgt in gold_by_id:
            diffs.append(("extra_edge", f"{src}->{tgt}", rtype))

    gold_req = {
        (str(r.major), ident(r.course_id), str(r.category), str(r.role))
        for r in gold_maj.itertuples(index=False)
    }
    our_req = {
        (r["major"], ident(r["course_id"]), r["category"], r["role"])
        for r in majors
        if r["major"] in {m for m, _, _, _ in gold_req}
    }
    missing_req = sorted(gold_req - our_req)
    extra_req = sorted(our_req - gold_req)
    for item in missing_req:
        diffs.append(("missing_requirement", "|".join(item), ""))
    for item in extra_req:
        diffs.append(("extra_requirement", "|".join(item), "in bulletin major section, not in gold subset"))

    for kind, item, detail in diffs:
        conn.execute(
            "INSERT INTO coverage_diff (kind, item, detail) VALUES (?, ?, ?)",
            (kind, item, detail),
        )

    course_recall = (len(gold_ids) - len(missing_courses)) / len(gold_ids)
    edge_recall = (len(gold_edges) - len(missing_edges)) / len(gold_edges) if gold_edges else 1
    req_recall = (len(gold_req) - len(missing_req)) / len(gold_req) if gold_req else 1
    lines = [
        "Gold subset: curriculum_subset_math_cs_ds.xlsx",
        f"courses compared: {compared}/{len(gold_ids)} recall={course_recall:.1%}",
        f"missing courses: {len(missing_courses)}",
        f"name mismatches among found courses: {name_mismatch}",
        f"unit mismatches among found courses: {units_mismatch}",
        f"prereq text mismatches among found courses: {prereq_mismatch}",
        f"relation edges: gold={len(gold_edges)} missing={len(missing_edges)} extra_on_gold_targets={len(extra_edges)} recall={edge_recall:.1%}",
        f"major requirement rows: gold={len(gold_req)} missing={len(missing_req)} extra={len(extra_req)} recall={req_recall:.1%}",
        "",
        "Differences",
    ]
    for kind, item, detail in diffs:
        lines.append(f"{kind}\t{item}\t{detail}")
    return "\n".join(lines) + "\n"


def self_check_parser() -> None:
    def edges(text):
        return [
            (r["source_course"], r["logic_within_group"], r["group_relation"], r["relation_type"])
            for r in parse_relation_text(text, "prerequisite")
        ]

    assert edges("Permission only") == []
    assert edges("Recommended for students who have had calculus") == []
    assert ("MATH101", "or", "and", "prerequisite") in edges("MATH 101 or 105")
    assert ("MATH105", "or", "and", "prerequisite") in edges("MATH 101 or 105")
    math304 = edges(
        "MATH 201; MATH 202; STATS 211; and COMPSCI 201 or COMPSCI 101 or STATS 102"
    )
    assert ("MATH201", "single", "and", "prerequisite") in math304
    assert ("COMPSCI201", "or", "and", "prerequisite") in math304
    assert ("STATS102", "or", "and", "prerequisite") in math304
    recommended = edges("MATH 201 and MATH 202; COMPSCI 201 or COMPSCI 101 or STATS 102 is recommended")
    assert all(src.startswith("MATH") for src, *_ in recommended)
    stats402 = edges("STATS 302/COMPSCI 309; or MATH 405 and COMPSCI 201")
    assert ("STATS302/COMPSCI309", "single", "and", "prerequisite") in stats402
    assert ("MATH405", "and", "or", "prerequisite") in stats402
    assert ("COMPSCI201", "and", "or", "prerequisite") in stats402


def main() -> None:
    self_check_parser()
    doc = pymupdf.open(PDF_PATH)
    lines = document_lines(doc)
    courses = parse_catalog(lines)
    major_rows, major_count = parse_majors(lines)
    relations = build_relations(courses)

    conn = init_db(DB_PATH)
    for course in courses.values():
        conn.execute(
            """
            INSERT INTO courses (
                course_id, course_name, department, level, units, description,
                prereq_text, antireq_text, notes, offering_pattern, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                course["course_id"],
                course["course_name"],
                course["department"],
                course["level"],
                course["units"],
                course["description"],
                course["prereq_text"],
                course["antireq_text"],
                course["notes"],
                "UG Bulletin 2025-2026 course descriptions",
            ),
        )
    for row in relations:
        conn.execute(
            """
            INSERT INTO relations (
                source_course, target_course, relation_type, group_id,
                logic_within_group, group_relation, raw_clause
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["source_course"],
                row["target_course"],
                row["relation_type"],
                row["group_id"],
                row["logic_within_group"],
                row["group_relation"],
                row["raw_clause"],
            ),
        )
    for row in major_rows:
        conn.execute(
            """
            INSERT INTO major_requirements (
                major, category, role, course_id, course_name, units, source_phrase
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["major"],
                row["category"],
                row["role"],
                row["course_id"],
                row["course_name"],
                row["units"],
                row["source_phrase"],
            ),
        )

    report = compare_gold(conn, courses, relations, major_rows)
    notes = {
        "bulletin": str(PDF_PATH.name),
        "built_by": "data/build_curriculum_db.py",
        "course_rows": str(len(courses)),
        "relation_rows": str(len(relations)),
        "major_requirement_rows": str(len(major_rows)),
        "majors_found": str(major_count),
        "offering_pattern": "Not printed on bulletin course entries. Column left null. Do not invent Fall/Spring/Both.",
        "dkuhub": HUB_NOTE,
        "divisions": "Per-course division labels are not a field on bulletin course entries, so no course_divisions table is filled from a guess.",
        "gold_check": "See coverage_diff and data/coverage_report.txt. Blanks were not filled from courselist.xlsx.",
        "website_read": (
            "SELECT * FROM courses; "
            "SELECT * FROM relations WHERE target_course = ?; "
            "SELECT * FROM major_requirements WHERE major = ?; "
            "SELECT year_term, section, status, start_dt, end_dt FROM class_sections "
            "WHERE course_code = ? ORDER BY term_code, section. "
            "These rows are recorded terms only, not a standing offering pattern."
        ),
    }
    for field, value in notes.items():
        conn.execute("INSERT INTO source_notes (field, value) VALUES (?, ?)", (field, value))
    conn.commit()
    conn.close()
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"courses {len(courses)}")
    print(f"relations {len(relations)}")
    print(f"major rows {len(major_rows)} majors {major_count}")
    print(f"database {DB_PATH}")
    print(report.split("Differences")[0])


if __name__ == "__main__":
    main()
