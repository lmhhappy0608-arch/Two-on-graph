#!/usr/bin/env python3
"""Rebuild courselist.xlsx to match curriculum_subset_math_cs_ds.xlsx schema.

Sources:
  - legacy courselist.xlsx (backed up)
  - curriculum_subset_math_cs_ds.xlsx (gold for AMCS/DS + schema)
  - ug_bulletin_2025-2026.pdf text extracts in /tmp/dii_pdf
"""

from __future__ import annotations

import re
import shutil
from collections import defaultdict
from pathlib import Path

import openpyxl
from openpyxl import Workbook

ROOT = Path("/Users/mohan/Desktop/Dii")
PDF_TXT = Path("/tmp/dii_pdf")
BACKUP = ROOT / "courselist_backup_before_rebuild.xlsx"
# Always rebuild from backup if present, else current file
SRC = BACKUP if BACKUP.exists() else ROOT / "courselist.xlsx"
SUBSET = ROOT / "curriculum_subset_math_cs_ds.xlsx"
OUT = ROOT / "courselist.xlsx"

# Course codes in major tables (after preprocess collapses spaces)
CODE_TOKEN = r"[A-Z]{2,}\d{2,3}(?:-\d+)?[AB]?(?:/[A-Z]{2,}\d{2,3}(?:-\d+)?[AB]?)?"
CODE_TOKEN_RE = re.compile(rf"\b({CODE_TOKEN})\*?\b")

MAJOR_ALIASES = {
    "Applied Mathematics and Computational Sciences/Computer Science": "AMCS-Computer Science",
    "Applied Mathematics and Computational Sciences/Mathematics": "AMCS-Mathematics",
    "Arts and Media/Arts": "Arts and Media-Arts",
    "Arts and Media/Media": "Arts and Media-Media",
    "Behavioral Science / Economics": "Behavioral Science-Economics",
    "Behavioral Science/Economics": "Behavioral Science-Economics",
    "Behavioral Science / Neuroscience": "Behavioral Science-Neuroscience",
    "Behavioral Science/Neuroscience": "Behavioral Science-Neuroscience",
    "Behavioral Science / Psychology": "Behavioral Science-Psychology",
    "Behavioral Science/Psychology": "Behavioral Science-Psychology",
    "Computation and Design/Computer Science": "Computation and Design-Computer Science",
    "ComputationandDesign/ComputerScience": "Computation and Design-Computer Science",
    "ComputationandDesign/Computer Science": "Computation and Design-Computer Science",
    "Computation and Design / Digital Media": "Computation and Design-Digital Media",
    "Computation and Design/Digital Media": "Computation and Design-Digital Media",
    "ComputationandDesign/Digital Media": "Computation and Design-Digital Media",
    "Computation and Design / Social Policy": "Computation and Design-Social Policy",
    "Computation and Design/Social Policy": "Computation and Design-Social Policy",
    "ComputationandDesign/Social Policy": "Computation and Design-Social Policy",
    "Cultures and Societies / Cultural Anthropology": "Cultures and Societies-Cultural Anthropology",
    "Cultures and Societies/Cultural Anthropology": "Cultures and Societies-Cultural Anthropology",
    "Cultures and Societies / Sociology": "Cultures and Societies-Sociology",
    "Cultures and Societies/Sociology": "Cultures and Societies-Sociology",
    "Data Science": "Data Science",
    "Environmental Science / Biogeochemistry": "Environmental Science-Biogeochemistry",
    "Environmental Science/Biogeochemistry": "Environmental Science-Biogeochemistry",
    "Environmental Science / Biology": "Environmental Science-Biology",
    "Environmental Science/Biology": "Environmental Science-Biology",
    "Environmental Science / Chemistry": "Environmental Science-Chemistry",
    "Environmental Science/Chemistry": "Environmental Science-Chemistry",
    "Environmental Science / Public Policy": "Environmental Science-Public Policy",
    "Environmental Science/Public Policy": "Environmental Science-Public Policy",
    "Global China Studies": "Global China Studies",
    "Global Health / Biology": "Global Health-Biology",
    "Global Health/Biology": "Global Health-Biology",
    "Global Health / Public Policy": "Global Health-Public Policy",
    "Global Health/Public Policy": "Global Health-Public Policy",
    "Humanities / Creative Writing and Translation": "Humanities-Creative Writing and Translation",
    "Humanities/Creative Writing and Translation": "Humanities-Creative Writing and Translation",
    "Humanities / Literature": "Humanities-Literature",
    "Humanities/Literature": "Humanities-Literature",
    "Humanities / Philosophy and Religion": "Humanities-Philosophy and Religion",
    "Humanities/Philosophy and Religion": "Humanities-Philosophy and Religion",
    "Humanities/ Philosophy and Religion": "Humanities-Philosophy and Religion",
    "Humanities / World History": "Humanities-World History",
    "Humanities/World History": "Humanities-World History",
    "Humanities/ World History": "Humanities-World History",
    "Materials Science / Chemistry": "Materials Science-Chemistry",
    "Materials Science/Chemistry": "Materials Science-Chemistry",
    "Materials Science / Physics": "Materials Science-Physics",
    "Materials Science/Physics": "Materials Science-Physics",
    "Molecular Bioscience / Biogeochemistry": "Molecular Bioscience-Biogeochemistry",
    "Molecular Bioscience/Biogeochemistry": "Molecular Bioscience-Biogeochemistry",
    "Molecular Bioscience / Biophysics": "Molecular Bioscience-Biophysics",
    "Molecular Bioscience/Biophysics": "Molecular Bioscience-Biophysics",
    "Molecular Bioscience / Cell and Molecular Biology": "Molecular Bioscience-Cell and Molecular Biology",
    "Molecular Bioscience/Cell and Molecular Biology": "Molecular Bioscience-Cell and Molecular Biology",
    "Molecular Bioscience / Genetics and Genomics": "Molecular Bioscience-Genetics and Genomics",
    "Molecular Bioscience/Genetics and Genomics": "Molecular Bioscience-Genetics and Genomics",
    "Molecular Bioscience / Neuroscience": "Molecular Bioscience-Neuroscience",
    "Molecular Bioscience/Neuroscience": "Molecular Bioscience-Neuroscience",
    "Philosophy, Politics, and Economics / Economic History": "PPE-Economic History",
    "Philosophy, Politics, and Economics/Economic History": "PPE-Economic History",
    "Philosophy, Politics, and Economics / Philosophy": "PPE-Philosophy",
    "Philosophy, Politics, and Economics/Philosophy": "PPE-Philosophy",
    "Philosophy, Politics, and Economics / Political Science": "PPE-Political Science",
    "Philosophy, Politics, and Economics/Political Science": "PPE-Political Science",
    "Philosophy, Politics, and Economics / Public Policy": "PPE-Public Policy",
    "Philosophy, Politics, and Economics/Public Policy": "PPE-Public Policy",
    "Quantitative Political Economy / Economics": "QPE-Economics",
    "Quantitative Political Economy/Economics": "QPE-Economics",
    "Quantitative Political Economy / Political Science": "QPE-Political Science",
    "Quantitative Political Economy/Political Science": "QPE-Political Science",
    "Quantitative Political Economy / Public Policy": "QPE-Public Policy",
    "Quantitative Political Economy/Public Policy": "QPE-Public Policy",
}

DIVISION_CANON = {
    "social science": "Social Sciences",
    "social sciences": "Social Sciences",
    "social sciences foundations": "Social Sciences Foundations",
    "natural science": "Natural Sciences",
    "natural sciences": "Natural Sciences",
    "natural science foundations": "Natural Science Foundations",
    "quantitative reasoning": "Quantitative Reasoning",
    "arts and humanities": "Arts and Humanities",
    "2-credit writing": "2-credit Writing",
    "common core": "Common Core",
    "none": None,
}

STOP_PHRASES = [
    r"(?m)^\s*Electives\s*$",
    r"Creative Practice Thematic Concentrations",
    r"Courses listed in the table below are recommended electives",
    r"(?m)^\s*recommended electives for the major",
    r"(?m)^\s*MajorRequirements\s*$",
]

JUNK_IDS = {
    "CONSENT",
    "PERMISSION",
    "NONE",
    "COURSE",
    "COURSECODE",
    "BACKTOTOC",
    "COURSECREDIT",
}


def norm_space(s: str | None) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def canon_division(d: str | None) -> str | None:
    if d is None:
        return None
    t = norm_space(d)
    if not t or t.lower() == "none":
        return None
    key = t.lower().rstrip()
    return DIVISION_CANON.get(key, t)


def dept_of(cid: str) -> str:
    m = re.match(r"[A-Z]+", cid)
    return m.group(0) if m else cid


def pretty_code(cid: str) -> str:
    if "/" in cid:
        return "/".join(pretty_code(p) for p in cid.split("/"))
    m = re.match(r"^([A-Z]+)(\d+[A-Z]?)$", cid)
    return f"{m.group(1)} {m.group(2)}" if m else cid


def level_from_id(cid: str) -> int | None:
    m = re.search(r"(\d{3})", cid.split("/")[0])
    if not m:
        m = re.search(r"(\d{2})", cid.split("/")[0])
        return int(m.group(1)) * 10 if m else None
    return (int(m.group(1)) // 100) * 100


def first(seq, default=None):
    for x in seq:
        if x is not None and x != "":
            return x
    return default


def unique_join(items, sep="; "):
    out, seen = [], set()
    for x in items:
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return sep.join(out) if out else None


def load_pdf_pages(start: int, end: int) -> str:
    parts = []
    for i in range(start, end + 1):
        p = PDF_TXT / f"all-{i:04d}.txt"
        if p.exists():
            parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def preprocess_major_text(text: str) -> str:
    t = text.replace("\u202f", " ").replace("\xa0", " ")
    # Join common split cross-lists
    t = re.sub(
        r"\b([A-Z]{2,})\s*\n\s*(\d{2,3}[AB]?)\s*/\s*([A-Z]{2,})\s*\n\s*(\d{2,3}[AB]?)\b",
        r"\1\2/\3\4",
        t,
    )
    t = re.sub(
        r"\b([A-Z]{2,})\s+(\d{2,3}[AB]?)\s*/\s*\n\s*([A-Z]{2,})(\d{2,3}[AB]?)\b",
        r"\1\2/\3\4",
        t,
    )
    t = re.sub(
        r"\b([A-Z]{2,})\s+(\d{2,3}[AB]?)\s*/\s*([A-Z]{2,})(\d{2,3}[AB]?)\b",
        r"\1\2/\3\4",
        t,
    )
    t = re.sub(
        r"\b([A-Z]{2,})\s+(\d{2,3}[AB]?)\s*\n\s*/\s*([A-Z]{2,})(\d{2,3}[AB]?)\b",
        r"\1\2/\3\4",
        t,
    )
    t = re.sub(
        r"\b([A-Z]{2,})\s*\n\s*(\d{2,3}[AB]?)/([A-Z]{2,})(\d{2,3}[AB]?)\b",
        r"\1\2/\3\4",
        t,
    )
    t = re.sub(
        r"\b([A-Z]{2,})\s+(\d{2,3}[AB]?)\s*/\s*([A-Z]{2,})\s*\n\s*(\d{2,3}[AB]?)\b",
        r"\1\2/\3\4",
        t,
    )
    t = re.sub(
        r"\b([A-Z]{2,})\s+(\d{2,3}[AB]?)\s*/\s*([A-Z]{2,})\s+(\d{2,3}[AB]?)\b",
        r"\1\2/\3\4",
        t,
    )
    # Collapse SUBJECT 123 -> SUBJECT123 (incl. 298-1 style)
    t = re.sub(r"\b([A-Z]{2,})\s+(\d{2,3}(?:-\d+)?[AB]?)\b", r"\1\2", t)

    # Line-based footnote cleanup only (do NOT delete major titles)
    cleaned_lines = []
    skip_cont = False
    for line in t.splitlines():
        s = line.strip()
        if re.fullmatch(r"\d{1,3}", s):
            # bare footnote marker; skip
            continue
        if re.match(r"^\d{0,3}\s*(This course was nam|The\s*course was nam)", s, re.I):
            skip_cont = True
            continue
        if skip_cont:
            # continuation of footnote until a blank or a real table/header line
            if not s:
                skip_cont = False
                cleaned_lines.append(line)
                continue
            if re.match(
                r"^(BacktoTOC|Divisional|Interdisciplinary|Disciplinary|Electives|Choose|And|"
                r"[A-Z]{2,}\d{2,3}|CourseCode|MajorRequirements|[A-Z][a-z]+.*/)",
                s,
            ):
                skip_cont = False
            else:
                continue
        cleaned_lines.append(line)
    t2 = "\n".join(cleaned_lines)
    # Drop asterisk substitute notes (including wrapped continuations)
    t2 = re.sub(
        r"(?im)^\s*\*.*(?:\n(?!\s*(?:Divisional|Interdisciplinary|Disciplinary|Electives|Choose|And|[A-Z]{2,}\d|[A-Z][a-z]+.*/)).*)*",
        "",
        t2,
    )
    t2 = re.sub(r"(?im)^\s*substitute for [A-Z0-9/]+\.?\s*$", "", t2)
    return t2


CODE_FIXES = {
    "EHTLDR204": "ETHLDR204",
    "CLUANTH101": "CULANTH101",
    "PYSCH203": "PSYCH203",
    "POLISCI223": "POLSCI223",
    "HIS212": "HIST212",
}


def extract_codes(block: str) -> list[str]:
    codes, seen = [], set()
    for m in CODE_TOKEN_RE.finditer(block):
        cid = m.group(1).upper()
        cid = CODE_FIXES.get(cid, cid)
        if cid in JUNK_IDS:
            continue
        if cid not in seen:
            seen.add(cid)
            codes.append(cid)
    return codes


def role_from_phrase(phrase: str) -> str:
    p = re.sub(r"\s+", "", phrase).lower()
    rules = [
        (r"choose(?:one|1)ofthefollowing(?:two|2)", "choose_one_of_two"),
        (r"choose(?:one|1)ofthefollowing(?:three|3)", "choose_one_of_three"),
        (r"choose(?:one|1)ofthefollowing(?:four|4)", "choose_one_of_four"),
        (r"choose(?:two|2)ofthefollowing(?:four|4)", "choose_two_of_four"),
        (r"choose(?:two|2)ofthefollowing(?:three|3)", "choose_two_of_three"),
        (r"choose(?:two|2)ofthefollowing(?:five|5)", "choose_two_of_five"),
        (r"choose(?:two|2)ofthefollowing100", "choose_two_of_100_200"),
        (r"choose(?:two|2)ofthefollowing300", "choose_two_of_300_400"),
        (r"choose2methodscourses", "choose_two_methods"),
        (r"choose(?:two|2)methodscourses", "choose_two_methods"),
        (r"choose3concentrationcourses", "choose_three_from_one_concentration"),
        (r"choose(?:three|3)concentrationcourses", "choose_three_from_one_concentration"),
        (r"list1:choose", "choose_from_list_1"),
        (r"list2:choose", "choose_from_list_2"),
        (r"studentsarerequiredtotakeanadditional", "additional_from_lists"),
        (r"choose(?:two|2)4-?creditcourses", "choose_two"),
        (r"choose(?:two|2)ofthefollowing", "choose_two"),
        (r"choose(?:three|3)ofthefollowing", "choose_three"),
        (r"choose(?:one|1)ofthefollowing", "choose_one"),
        (r"choose(?:one|1)ofthecoursesbelow", "choose_one"),
        (r"choose4creativepractice", "choose_four_creative_practice"),
        (r"andcomplete(?:the)?following", "required"),
        (r"complete(?:the)?following", "required"),
    ]
    for rx, role in rules:
        if re.search(rx, p):
            return role
    return "required"


def find_major_spans(text: str) -> list[tuple[str, str, int, int]]:
    titles = sorted(MAJOR_ALIASES.keys(), key=len, reverse=True)
    hits: list[tuple[int, int, str, str, int]] = []
    for title in titles:
        short = MAJOR_ALIASES[title]
        parts = [re.escape(p) for p in re.split(r"\s+", title) if p]
        if not parts:
            continue
        rx = re.compile(r"\s*".join(parts), re.I)
        for m in rx.finditer(text):
            after = text[m.end() : m.end() + 500]
            before = text[max(0, m.start() - 250) : m.start()]
            # Must be a real major requirements header block
            if not re.search(r"Divisional\s*Foundation", after, re.I):
                continue
            # Avoid elective / prose mentions
            if re.search(r"IntroductiontoDataScience|Introduction to Data Science", m.group(0) + after[:80], re.I):
                if short == "Data Science" and not re.search(r"MajorRequirements", before, re.I):
                    continue
            score = 1
            if re.search(r"MajorRequirements", before, re.I):
                score += 3
            if re.search(r"Divisional\s*Foundation", after[:120], re.I):
                score += 2
            hits.append((m.start(), m.end(), title, short, score))

    best: dict[str, tuple] = {}
    for start, end, title, short, score in hits:
        cur = best.get(short)
        if cur is None or score > cur[4] or (score == cur[4] and start < cur[0]):
            best[short] = (start, end, title, short, score)

    picked = sorted(best.values(), key=lambda x: x[0])
    spans = []
    for i, (start, end, title, short, _score) in enumerate(picked):
        next_start = picked[i + 1][0] if i + 1 < len(picked) else len(text)
        spans.append((title, short, start, next_start))
    return spans


def cut_requirements_body(body: str) -> str:
    cut = body
    stops = []
    for rx in STOP_PHRASES:
        for m in re.finditer(rx, cut, re.I):
            if "MajorRequirements" in rx and m.start() < 80:
                continue
            stops.append(m.start())
    if stops:
        cut = cut[: min(stops)]
    return cut


def parse_major_requirements(majors_text: str) -> list[tuple[str, str, str, str]]:
    text = preprocess_major_text(majors_text)
    spans = find_major_spans(text)
    rows: list[tuple[str, str, str, str]] = []

    section_rx = re.compile(
        r"(Divisional\s*Foundation(?:\s*Courses)?|"
        r"Interdisciplinary(?:\s*Courses)?|"
        r"Disciplinary(?:\s*Courses)?)",
        re.I,
    )
    phrase_rx = re.compile(
        r"(Choose[^\n]{0,200}|And\s*choose[^\n]{0,200}|And\s*complete[^\n]{0,120}|"
        r"Andchoos[^\n]{0,200}|Andcomplet[^\n]{0,120}|"
        r"Choosetwo[^\n]{0,200}|Chooseone[^\n]{0,200}|Choose4[^\n]{0,200}|"
        r"Choose2[^\n]{0,200}|Choose3[^\n]{0,200}|"
        r"List\s*1\s*:[^\n]{0,200}|List\s*2\s*:[^\n]{0,200}|"
        r"Students are required to take an additional[^\n]{0,200})",
        re.I,
    )

    for _title, short, start, end in spans:
        body = cut_requirements_body(text[start:end])
        # Find sections
        section_hits = [(m.start(), m.group(1)) for m in section_rx.finditer(body)]
        cleaned = []
        for pos, raw in section_hits:
            low = re.sub(r"\s+", "", raw).lower()
            if low.startswith("divisional"):
                cat = "Divisional Foundation"
            elif low.startswith("interdisciplinary"):
                cat = "Interdisciplinary"
            else:
                cat = "Disciplinary"
            if cleaned and cleaned[-1][1] == cat and pos - cleaned[-1][0] < 50:
                continue
            cleaned.append((pos, cat))
        if not cleaned:
            continue

        for i, (pos, cat) in enumerate(cleaned):
            sec_end = cleaned[i + 1][0] if i + 1 < len(cleaned) else len(body)
            sec = body[pos:sec_end]
            markers = [(0, "required")]
            for m in phrase_rx.finditer(sec):
                markers.append((m.start(), m.group(1)))
            # dedup close
            mm = []
            for p2, ph in markers:
                if mm and p2 - mm[-1][0] < 8:
                    continue
                mm.append((p2, ph))

            for j, (mpos, phrase) in enumerate(mm):
                mend = mm[j + 1][0] if j + 1 < len(mm) else len(sec)
                chunk = sec[mpos:mend]
                role = role_from_phrase(chunk[:200] if j == 0 else phrase)
                for cid in extract_codes(chunk):
                    rows.append((short, cat, role, cid))

    # Dedup preserve order
    seen, out = set(), []
    for r in rows:
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    return out


def parse_course_catalog(catalog_text: str) -> dict[str, dict]:
    """Parse jammed bulletin headers like COMPSCI101Introduction...(4credits)."""
    text = catalog_text.replace("\u202f", " ").replace("\xa0", " ")
    # SUBJECT123Title(4credits) or SUBJECT123ATitle or cross SUBJECT123/SUBJECT456Title
    header_rx = re.compile(
        r"(?m)(?P<code>[A-Z]{2,}\d{2,3}[AB]?(?:/[A-Z]{2,}\d{2,3}[AB]?)?)"
        r"(?P<title>[A-Z][^()]{2,160}?)"
        r"\(\s*(?P<units>\d+)\s*credits?\s*\)",
    )
    courses: dict[str, dict] = {}
    matches = list(header_rx.finditer(text))
    for i, m in enumerate(matches):
        cid = m.group("code").upper()
        title = norm_space(m.group("title"))
        # Fix title if camel jammed: insert spaces before capitals lightly for readability? keep as-is but spaced if already spaced
        title = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", title)
        title = norm_space(title)
        units = int(m.group("units"))
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(text), m.end() + 3000)
        body = norm_space(text[m.end() : end])

        prereq = antireq = None
        pm = re.search(r"Prerequisite(?:\(s\))?:\s*(.+?)(?=Anti-requisite|\Z)", body, re.I)
        if pm:
            prereq = norm_space(pm.group(1)).rstrip(".")
        am = re.search(r"Anti-requisite(?:\(s\))?:\s*(.+?)(?=Prerequisite|\Z)", body, re.I)
        if am:
            antireq = norm_space(am.group(1)).rstrip(".")

        desc = body
        desc = re.split(r"Prerequisite(?:\(s\))?:", desc, maxsplit=1, flags=re.I)[0]
        desc = re.split(r"Anti-requisite(?:\(s\))?:", desc, maxsplit=1, flags=re.I)[0]
        desc = norm_space(desc) or None

        entry = {
            "course_id": cid,
            "course_name": title,
            "units": units,
            "prereq_text": prereq,
            "antireq_text": antireq,
            "description": desc,
            "department": dept_of(cid.split("/")[0]),
        }
        courses[cid] = entry
        if "/" in cid:
            for side in cid.split("/"):
                courses.setdefault(side, {**entry, "course_id": side})
    return courses


def load_subset():
    wb = openpyxl.load_workbook(SUBSET, data_only=True)
    courses = {}
    ws = wb["courses"]
    headers = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2, values_only=True):
        d = dict(zip(headers, row))
        courses[d["course_id"]] = d
    rels = []
    ws = wb["relations"]
    headers = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0]:
            rels.append(dict(zip(headers, row)))
    majors = []
    ws = wb["major_requirements"]
    headers = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0]:
            majors.append(dict(zip(headers, row)))
    return courses, rels, majors


def load_old_courselist():
    wb = openpyxl.load_workbook(SRC, data_only=True)
    # Support both old and already-rebuilt schemas
    sheet = "course information" if "course information" in wb.sheetnames else "courses"
    info = defaultdict(lambda: {
        "names": [],
        "divisions": [],
        "levels": [],
        "terms": [],
        "descs": [],
        "units": [],
        "notes": [],
        "prereqs": [],
        "antireqs": [],
        "departments": [],
    })
    ws = wb[sheet]
    headers = [norm_space(c.value).lower() if c.value else "" for c in ws[1]]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if sheet == "course information":
            cid, name, div, level, terms, desc, units, notes = row[:8]
            prereq = antireq = dept = None
        else:
            d = dict(zip(headers, row))
            cid = d.get("course_id")
            name = d.get("course_name")
            div = d.get("divisions")
            level = d.get("level")
            terms = d.get("offering_pattern")
            desc = d.get("description")
            units = d.get("units")
            notes = d.get("notes")
            prereq = d.get("prereq_text")
            antireq = d.get("antireq_text")
            dept = d.get("department")
        if not cid:
            continue
        cid = str(cid).strip().upper()
        b = info[cid]
        if name:
            b["names"].append(norm_space(name))
        if dept:
            b["departments"].append(norm_space(dept))
        if div:
            if sheet == "courses":
                for part in str(div).split(";"):
                    cd = canon_division(part.strip())
                    if cd:
                        b["divisions"].append(cd)
            else:
                cd = canon_division(div)
                if cd:
                    b["divisions"].append(cd)
        if level is not None:
            b["levels"].append(level)
        if terms:
            b["terms"].append(norm_space(terms))
        if desc:
            b["descs"].append(norm_space(desc))
        if units is not None:
            b["units"].append(units)
        if notes:
            b["notes"].append(norm_space(notes))
        if prereq:
            b["prereqs"].append(norm_space(prereq))
        if antireq:
            b["antireqs"].append(norm_space(antireq))

    rel_sheet = "relation" if "relation" in wb.sheetnames else "relations"
    rels = []
    ws = wb[rel_sheet]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        src, gid, tgt, rtype, logic, grel = row[:6]
        rels.append(
            {
                "source_course": str(src).strip().upper() if src else None,
                "group_id": str(gid).strip() if gid else None,
                "target_course": str(tgt).strip().upper() if tgt else None,
                "relation_type": norm_space(rtype).lower() if rtype else None,
                "logic_within_group": norm_space(logic).lower() if logic else None,
                "group_relation": norm_space(grel).lower() if grel else None,
            }
        )
    return info, rels


def normalize_relations(rels: list[dict]) -> list[dict]:
    counts = defaultdict(int)
    for r in rels:
        counts[(r["target_course"], r["relation_type"], r["group_id"])] += 1
    out = []
    for r in rels:
        if not r.get("source_course") or not r.get("target_course"):
            continue
        if r["source_course"] in JUNK_IDS:
            continue
        rtype = r.get("relation_type") or "prerequisite"
        if rtype == "recommended":
            continue
        logic = r.get("logic_within_group") or "and"
        key = (r["target_course"], rtype, r["group_id"])
        if counts[key] == 1:
            logic = "single"
        elif logic not in {"or", "and", "single"}:
            logic = "or"
        grel = r.get("group_relation") or "and"
        if grel not in {"or", "and"}:
            grel = "and"
        out.append(
            {
                "source_course": r["source_course"],
                "group_id": r["group_id"],
                "target_course": r["target_course"],
                "relation_type": rtype,
                "logic_within_group": logic,
                "group_relation": grel,
            }
        )
    return out


def build_prereq_antireq_text(rels: list[dict]) -> dict[str, dict[str, str | None]]:
    by_target = defaultdict(lambda: defaultdict(list))
    for r in rels:
        by_target[r["target_course"]][r["relation_type"]].append(r)
    out = {}
    for tgt, typed in by_target.items():
        fields = {"prereq_text": None, "antireq_text": None}
        for rtype, key in [("prerequisite", "prereq_text"), ("antirequisite", "antireq_text")]:
            items = typed.get(rtype, [])
            if not items:
                continue
            groups = defaultdict(list)
            grel = "and"
            for it in items:
                groups[it["group_id"] or "G?"].append(it)
                if it.get("group_relation"):
                    grel = it["group_relation"]
            group_texts = []
            for gid in sorted(groups, key=lambda x: (len(str(x)), str(x))):
                gitems = groups[gid]
                logic = gitems[0].get("logic_within_group") or "single"
                codes = [pretty_code(x["source_course"]) for x in gitems]
                if len(codes) == 1 or logic == "single":
                    group_texts.append(codes[0] if len(codes) == 1 else " or ".join(codes))
                elif logic == "and":
                    group_texts.append(" and ".join(codes))
                else:
                    group_texts.append(" or ".join(codes))
            joiner = "; and " if grel == "and" else "; or "
            fields[key] = group_texts[0] if len(group_texts) == 1 else joiner.join(group_texts)
        out[tgt] = fields
    return out


def main():
    if not BACKUP.exists() and (ROOT / "courselist.xlsx").exists():
        # First run may have already overwritten; try to detect old schema
        wb_probe = openpyxl.load_workbook(ROOT / "courselist.xlsx", read_only=True)
        if "course information" in wb_probe.sheetnames:
            shutil.copy2(ROOT / "courselist.xlsx", BACKUP)
        wb_probe.close()

    if not BACKUP.exists():
        raise SystemExit("Missing backup of original courselist.xlsx")

    subset_courses, subset_rels, subset_majors = load_subset()
    old_info, old_rels = load_old_courselist()

    majors_text = load_pdf_pages(95, 216)
    catalog_text = load_pdf_pages(217, 435)
    bulletin_courses = parse_course_catalog(catalog_text)
    parsed_majors = parse_major_requirements(majors_text)

    # Overlay verified subset majors
    subset_major_names = {m["major"] for m in subset_majors}
    parsed_majors = [r for r in parsed_majors if r[0] not in subset_major_names]
    for m in subset_majors:
        parsed_majors.append((m["major"], m["category"], m["role"], m["course_id"]))

    # Course universe: old + subset + majors + relations (NOT full catalog dump)
    all_ids = set(old_info.keys()) | set(subset_courses.keys())
    for r in old_rels + subset_rels:
        if r.get("source_course"):
            all_ids.add(r["source_course"])
        if r.get("target_course"):
            all_ids.add(r["target_course"])
    for _a, _b, _c, cid in parsed_majors:
        all_ids.add(cid)
        if "/" in cid:
            all_ids.update(cid.split("/"))
    all_ids = {c for c in all_ids if c and c not in JUNK_IDS and re.search(r"\d", c)}

    # Merge relations with subset overlay for subset targets
    rel_map = {}
    for r in normalize_relations(old_rels):
        key = (r["source_course"], r["group_id"], r["target_course"], r["relation_type"])
        rel_map[key] = r
    subset_targets = {r["target_course"] for r in subset_rels}
    merged_rels = [r for r in rel_map.values() if r["target_course"] not in subset_targets]
    for r in subset_rels:
        merged_rels.append(
            {
                "source_course": r["source_course"],
                "group_id": r["group_id"],
                "target_course": r["target_course"],
                "relation_type": str(r["relation_type"]).lower(),
                "logic_within_group": str(r["logic_within_group"]).lower(),
                "group_relation": str(r["group_relation"]).lower(),
            }
        )
    text_from_rels = build_prereq_antireq_text(merged_rels)

    courses_rows, division_rows, offerings_rows = [], [], []
    for cid in sorted(all_ids, key=lambda x: (dept_of(x.split("/")[0]), x)):
        old = old_info.get(cid)
        sub = subset_courses.get(cid)
        bul = bulletin_courses.get(cid)

        name = divisions = level = offering = units = prereq = antireq = desc = notes = None
        if old:
            name = first(old["names"])
            divisions = unique_join(old["divisions"])
            level = first(old["levels"])
            offering = first(old["terms"])
            units = first(old["units"])
            desc = first(old["descs"])
            notes = unique_join(old["notes"]) if old["notes"] else None
            prereq = first(old["prereqs"])
            antireq = first(old["antireqs"])
        if bul:
            name = name or bul.get("course_name")
            units = units if units is not None else bul.get("units")
            desc = desc or bul.get("description")
            prereq = bul.get("prereq_text") or prereq
            antireq = bul.get("antireq_text") or antireq
        if sub:
            name = sub.get("course_name") or name
            divisions = sub.get("divisions") or divisions
            level = sub.get("level") if sub.get("level") is not None else level
            offering = sub.get("offering_pattern") or offering
            units = sub.get("units") if sub.get("units") is not None else units
            prereq = sub.get("prereq_text") or prereq
            antireq = sub.get("antireq_text") or antireq
            desc = sub.get("description") or desc
            notes = sub.get("notes") or notes

        rt = text_from_rels.get(cid, {})
        prereq = prereq or rt.get("prereq_text")
        antireq = antireq or rt.get("antireq_text")
        if level is None:
            level = level_from_id(cid)
        if isinstance(level, int) and level not in (100, 200, 300, 400) and not sub:
            # keep AP-style 20/21 etc as-is if from id < 100
            if level >= 100:
                level = level_from_id(cid)

        if not name:
            name = cid
            notes = ((notes + "; ") if notes else "") + "Name filled from course_id; not found in sources."

        courses_rows.append(
            {
                "course_id": cid,
                "course_name": name,
                "department": dept_of(cid.split("/")[0]),
                "divisions": divisions,
                "level": level,
                "offering_pattern": offering,
                "units": units,
                "prereq_text": prereq,
                "antireq_text": antireq,
                "description": desc,
                "notes": notes,
            }
        )
        if divisions:
            for d in [x.strip() for x in divisions.split(";") if x.strip()]:
                division_rows.append((cid, d, "listed_or_attribute"))
        offerings_rows.append(
            {"course_id": cid, "year": None, "term": None, "frequency": offering, "status": None}
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "courses"
    course_headers = [
        "course_id",
        "course_name",
        "department",
        "divisions",
        "level",
        "offering_pattern",
        "units",
        "prereq_text",
        "antireq_text",
        "description",
        "notes",
    ]
    ws.append(course_headers)
    for r in courses_rows:
        ws.append([r[h] for h in course_headers])

    ws = wb.create_sheet("relations")
    rel_headers = [
        "source_course",
        "group_id",
        "target_course",
        "relation_type",
        "logic_within_group",
        "group_relation",
    ]
    ws.append(rel_headers)
    for r in sorted(
        merged_rels,
        key=lambda x: (
            x["target_course"] or "",
            x["relation_type"] or "",
            str(x["group_id"] or ""),
            x["source_course"] or "",
        ),
    ):
        ws.append([r[h] for h in rel_headers])

    ws = wb.create_sheet("offerings")
    off_headers = ["course_id", "year", "term", "frequency", "status"]
    ws.append(off_headers)
    for r in offerings_rows:
        ws.append([r[h] for h in off_headers])

    ws = wb.create_sheet("major_requirements")
    ws.append(["major", "category", "role", "course_id"])
    for row in parsed_majors:
        ws.append(list(row))

    ws = wb.create_sheet("course_divisions")
    ws.append(["course_id", "division", "role"])
    for row in division_rows:
        ws.append(list(row))

    ws = wb.create_sheet("source_notes")
    ws.append(["field", "value"])
    for a, b in [
        ("Primary bulletin source", "DKU UG Bulletin 2025-2026"),
        ("Schema source", "Aligned to curriculum_subset_math_cs_ds.xlsx"),
        (
            "Major requirement coverage",
            "All undergraduate majors/tracks in Part 10; AMCS-CS, AMCS-Math, Data Science verified from subset",
        ),
        (
            "Course universe",
            "Original courselist courses + subset courses + courses referenced by majors/relations; enriched from bulletin catalog",
        ),
        (
            "Normalization",
            "One row per course_id; divisions semicolon-joined and exploded into course_divisions",
        ),
        (
            "Relations",
            "Lowercased relation_type; logic_within_group in {single,or,and}; recommended edges omitted",
        ),
        ("Backup of original workbook", BACKUP.name),
        ("Missing data policy", "Unknown fields left blank on purpose"),
    ]:
        ws.append([a, b])

    wb.save(OUT)

    majors = sorted({r[0] for r in parsed_majors})
    print(f"Wrote {OUT}")
    print(f"courses: {len(courses_rows)}")
    print(f"relations: {len(merged_rels)}")
    print(f"major_requirements: {len(parsed_majors)}")
    print(f"majors ({len(majors)}):")
    for m in majors:
        n = sum(1 for r in parsed_majors if r[0] == m)
        print(f" - {m}: {n} rows")
    print(f"course_divisions: {len(division_rows)}")
    print(
        "missing description:",
        sum(1 for r in courses_rows if not r["description"]),
        "missing units:",
        sum(1 for r in courses_rows if r["units"] is None),
    )
    print("bulletin catalog parsed:", len(bulletin_courses))


if __name__ == "__main__":
    main()
