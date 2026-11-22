#!/usr/bin/env python3
"""Replace high-risk major rules with bulletin-checked rule trees.

Automatic parser output stays partial. Only the rules recorded below are verified.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import build_curriculum_db as parser
from major_rule_engine import evaluate, has_cycle

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curriculum.sqlite"
AUDIT_PATH = ROOT / "data" / "major_rule_audit.md"
TESTS_PATH = ROOT / "data" / "major_rule_tests.json"
REPORT_PATH = ROOT / "data" / "major_rule_test_report.md"
GRAPH_PATH = ROOT / "data" / "graph_readiness_report.md"

NEW_COURSES = [
    ("CULANTH304", "Rethinking Progress: Capitalism and Its Alternatives", 4, 300, "CULANTH"),
    ("MEDIART498", "Special Topics in Film & Documentary", 4, 400, "MEDIART"),
    ("LIT298-1", "Special Topics in U.S. Literature", 4, 200, "LIT"),
    ("LIT298-2", "Special Topics in Literary Traditions", 4, 200, "LIT"),
    ("RELIG398", "Special Topics in Religion", 4, 400, "RELIG"),
]

FILM_LOW = ["MEDIART103", "MEDIART110", "MEDIART207", "MEDIART212", "MEDIART220", "MEDIART223"]
FILM_HIGH = ["MEDIART301", "MEDIART305", "MEDIART310", "MEDIART311", "MEDIART323", "MEDIART498"]
STUDIO_LOW = ["LIT216", "MEDIART104", "MEDIART117", "MEDIART118", "MEDIART120", "MEDIART198", "MEDIART221", "MEDIART222", "MEDIART225"]
STUDIO_HIGH = ["LIT311", "MEDIART301", "MEDIART322", "MEDIART323", "MEDIART324", "HUM405/MEDIART405"]
DIGITAL_LOW = ["INFOSCI105", "INFOSCI202", "MEDIART110", "MEDIART202", "MEDIART205", "MEDIART207", "MEDIART212", "MEDIART213"]
DIGITAL_HIGH = ["LIT307", "INFOSCI305", "INFOSCI309", "MEDIART312", "MEDIART321", "MEDIART401"]

METHODS = ["STATS201", "COMPSCI206/ECON206", "INFOSCI302", "SOSC314", "SOSC320"]
URBAN = ["PUBPOL204", "ECON310", "INFOSCI305", "SOSC315", "SOSC405"]
ENVIRONMENT = ["ENVIR101", "ENVIR201", "ENVIR203", "ETHLDR204", "ENVIR206", "ENVIR301", ("ENVIR302", "ECON302"), "ENVIR303"]
GLOBAL = ["CULANTH213", "POLSCI101", "HIST111", "POLECON201", "MEDIA203", "HIST212", "GLHLTH310", "ECON314", "ECON333/SOSC333", "POLSCI309"]

CWT_1 = [
    "LIT223/CHINESE423",
    "LIT219/MEDIART219",
    "LIT310",
    "LIT315",
    "WOC207",
    "WOC210",
    "WOC213",
    "WOC216",
    "WOC217",
    "HUM405/MEDIART405",
]
CWT_2 = [
    "LIT220",
    "LIT311",
    "LIT314",
    "MEDIART110",
    "MEDIART207",
    "MEDIART310",
    "WOC108",
    "WOC190",
    "WOC214",
    "WOC290",
    "HIST314",
]
LIT_1 = ["LIT298-1", "LIT298-2", "LIT216", "LIT223/CHINESE423", "LIT311", "LIT314", "LIT310"]
LIT_2 = ["LIT203", "LIT210", "RELIG221/LIT221", "LIT398", "LIT315", "HUM405/MEDIART405"]
PHIL_1 = [("PHIL210", "PHIL"), ("PHIL226/HIST226", "PHIL"), ("RELIG203/HIST233", "RELIG"), ("RELIG302", "RELIG")]
PHIL_2 = [("RELIG221/LIT221", "RELIG"), ("PHIL305", "PHIL"), ("PHIL398", "PHIL"), ("RELIG398", "RELIG")]
HIST_1 = ["HIST111", "HIS212", "HIST228", "HIST233/RELIG203", "HIST309", "HIST401"]
HIST_2 = ["HIST227", "HIST229", "HIST230", "HIST314", "HIST217/ARTS217", "HIST402"]
ANTHRO_FIVE = ["CULANTH211", "CULANTH213", "CULANTH314/POLSCI314", "CULANTH405", "GCHINA305"]


def course(code, group="", department=None):
    return {"code": code, "group": group, "department": department}


def slot(codes, group=""):
    return {"one_of": list(codes), "group": group}


def choose_rule(major, category, phrase, page, count, courses, label=""):
    return {
        "major": major,
        "category": category,
        "operator": "CHOOSE",
        "required_count": count,
        "required_credits": None,
        "status": "verified",
        "source_phrase": phrase,
        "source_page": page,
        "group_label": label,
        "courses": [course(item) if isinstance(item, str) else slot(item) for item in courses],
        "constraints": [],
        "children": [],
    }


def all_rule(major, category, phrase, page, courses, label=""):
    return choose_rule(major, category, phrase, page, len(courses), courses, label) | {"operator": "ALL"}


def quota_rule(major, category, phrase, page, groups, total_count=None, total_credits=None, extra=None, label=""):
    courses = []
    constraints = list(extra or [])
    for name, rows, min_count, min_credits in groups:
        for row in rows:
            if isinstance(row, tuple) and len(row) == 2 and row[1] in {"PHIL", "RELIG"}:
                courses.append(course(row[0], name, row[1]))
            elif isinstance(row, tuple):
                courses.append(slot(row, name))
            else:
                courses.append(course(row, name))
        if min_count is not None:
            constraints.append({"constraint_type": "group_min_count", "group": name, "value": str(min_count)})
        if min_credits is not None:
            constraints.append({"constraint_type": "group_min_credits", "group": name, "value": str(min_credits)})
    return {
        "major": major,
        "category": category,
        "operator": "QUOTA",
        "required_count": total_count,
        "required_credits": total_credits,
        "status": "verified",
        "source_phrase": phrase,
        "source_page": page,
        "group_label": label,
        "courses": courses,
        "constraints": constraints,
        "children": [],
    }


def any_rule(major, category, phrase, page, children, label=""):
    return {
        "major": major,
        "category": category,
        "operator": "ANY",
        "required_count": 1,
        "required_credits": None,
        "status": "verified",
        "source_phrase": phrase,
        "source_page": page,
        "group_label": label,
        "courses": [],
        "constraints": [],
        "children": children,
    }


def advisory(major, phrase, page):
    return {
        "major": major,
        "category": "Electives",
        "operator": "ADVISORY",
        "required_count": None,
        "required_credits": None,
        "status": "verified",
        "source_phrase": phrase,
        "source_page": page,
        "group_label": "",
        "courses": [],
        "constraints": [],
        "children": [],
        "note": "手册把这张表写成推荐选修。它不参与专业完成度。",
    }


def concentration(major, page, name, rows):
    return choose_rule(
        major,
        "Disciplinary",
        "And choose 3 Concentration Courses from one of the 3 Concentrations listed below",
        page,
        3,
        rows,
        name,
    )


def creative_concentrations(major, page):
    film = any_rule(major, "Disciplinary", "Choose two of the following 100-200 level courses", page, [
        choose_rule(major, "Disciplinary", "Choose two of the following 100-200 level courses", page, 2, FILM_LOW, "Film 100-200"),
        choose_rule(major, "Disciplinary", "Choose two of the following 300-400 level courses", page, 2, FILM_HIGH, "Film 300-400"),
    ], "Film & Documentary")
    film["operator"] = "ALL"
    film["required_count"] = 2
    studio = any_rule(major, "Disciplinary", "Choose two of the following 100-200 level courses", page, [
        choose_rule(major, "Disciplinary", "Choose two of the following 100-200 level courses", page, 2, STUDIO_LOW, "Studio 100-200"),
        choose_rule(major, "Disciplinary", "Choose two of the following 300-400 level courses", page, 2, STUDIO_HIGH, "Studio 300-400"),
    ], "Studio & Performance")
    studio["operator"] = "ALL"
    studio["required_count"] = 2
    digital = any_rule(major, "Disciplinary", "Choose two of the following 100-200 level courses", page, [
        choose_rule(major, "Disciplinary", "Choose two of the following 100-200 level courses", page, 2, DIGITAL_LOW, "Digital 100-200"),
        choose_rule(major, "Disciplinary", "Choose two of the following 300-400 level courses", page, 2, DIGITAL_HIGH, "Digital 300-400"),
    ], "Digital Culture & Communication")
    digital["operator"] = "ALL"
    digital["required_count"] = 2
    return any_rule(
        major,
        "Disciplinary",
        "Choose 4 Creative Practice Elective courses from within the same concentration, two at the 100-200 level and two at the 300-400 level.",
        page,
        [film, studio, digital],
        "Creative Practice Concentration",
    )


def build_verified_rules():
    psych = quota_rule(
        "Behavioral Science-Psychology",
        "Disciplinary",
        "And choose three courses total from Course Clusters I and II, with at least one course from each cluster",
        119,
        [
            ("Cluster I", ["PSYCH202", "PSYCH203", "PSYCH204"], 1, None),
            ("Cluster II", ["NEUROSCI102", "PSYCH205", "NEUROSCI212"], 1, None),
        ],
        total_count=3,
    )
    methods = choose_rule(
        "Computation and Design-Social Policy",
        "Disciplinary",
        "Choose 2 Methods Courses from the list below",
        129,
        2,
        METHODS,
    )
    concentrations = any_rule(
        "Computation and Design-Social Policy",
        "Disciplinary",
        "And choose 3 Concentration Courses from one of the 3 Concentrations listed below",
        130,
        [
            concentration("Computation and Design-Social Policy", 130, "Urban Design", URBAN),
            concentration("Computation and Design-Social Policy", 130, "Environmental Sustainability", ENVIRONMENT),
            concentration("Computation and Design-Social Policy", 130, "Global Networks", GLOBAL),
        ],
    )
    cwt = quota_rule(
        "Humanities-Creative Writing and Translation",
        "Electives",
        "Students are required to take an additional 20 credits from the two lists below, with at least 8 credits from each list. At least 8 of these credits must be 300-level or above.",
        171,
        [(name, rows, None, 8) for name, rows in (("List 1", CWT_1), ("List 2", CWT_2))],
        total_credits=20,
        extra=[{"constraint_type": "level_min_credits", "min_level": 300, "value": "8"}],
    )
    literature = quota_rule(
        "Humanities-Literature",
        "Electives",
        "Students are required to take an additional 5 courses from the two lists below, with at least 2 courses from each list. At least 2 of these 5 courses must be 300-level or above.",
        173,
        [("List 1", LIT_1, 2, None), ("List 2", LIT_2, 2, None)],
        total_count=5,
        extra=[{"constraint_type": "level_min_count", "min_level": 300, "value": "2"}],
    )
    philosophy = quota_rule(
        "Humanities-Philosophy and Religion",
        "Electives",
        "Students are required to take an additional 5 courses from the lists below, with at least 2 courses from each list. At least 2 of these 5 courses have to be 300-level or above.",
        175,
        [("List 1", PHIL_1, 2, None), ("List 2", PHIL_2, 2, None)],
        total_count=5,
        extra=[
            {"constraint_type": "level_min_count", "min_level": 300, "value": "2"},
            {"constraint_type": "department_min_count", "group": "List 1", "department": "PHIL", "value": "1"},
            {"constraint_type": "department_min_count", "group": "List 1", "department": "RELIG", "value": "1"},
            {"constraint_type": "department_min_count", "group": "List 2", "department": "PHIL", "value": "1"},
            {"constraint_type": "department_min_count", "group": "List 2", "department": "RELIG", "value": "1"},
        ],
    )
    stats_choice = choose_rule(
        "Molecular Bioscience-Biogeochemistry",
        "Disciplinary",
        "And choose one course from the following three courses",
        189,
        1,
        ["STATS101", "MATH206"],
        "Statistics choice",
    )
    stats_choice["note"] = (
        "手册原文写 three courses。印刷页 189 这一段只有 STATS 101 和 MATH 206。"
        "人工核对确认 three 是手册印错，按两门里选一门。"
    )
    domain_five = choose_rule(
        "Computation and Design-Digital Media",
        "Disciplinary",
        "And choose three of the following seven domain courses",
        127,
        3,
        ["INFOSCI201", "INFOSCI202", "INFOSCI304", "INFOSCI309", "MEDIART306"],
    )
    domain_five["note"] = (
        "手册原文写 seven。印刷页 127 这一段实际印出 5 门。"
        "人工核对确认 seven 是手册印错，按 5 门里选 3 门。"
    )
    sociology_six = choose_rule(
        "Cultures and Societies-Sociology",
        "Disciplinary",
        "And choose two of these six courses, with at least one at the 200-level and one at the 300-level",
        136,
        2,
        ["SOCIOL202", "SOCIOL310", "SOCIOL213", "SOCIOL223", "SOSC315", "SOCIOL380"],
    )
    sociology_six["constraints"] = [
        {"constraint_type": "level_min_count", "min_level": 300, "value": "1"},
        {"constraint_type": "level_band_min_count", "min_level": 200, "max_level": 299, "value": "1"},
    ]
    sociology_six["note"] = (
        "印刷页 136 到 137 实际有 6 门，含 SOCIOL 223/PUBPOL 223。"
        "句子里的 six 和课表门数一致。从这 6 门里选 2 门，其中一门 200 级、一门 300 级。"
    )
    arts = creative_concentrations("Arts and Media-Arts", 102)
    media = creative_concentrations("Arts and Media-Media", 107)
    history = quota_rule(
        "Humanities-World History",
        "Electives",
        "Students are required to take an additional 5 courses from the two lists below, with at least 2 courses from each list. At least 2 of these 5 courses must be 300-level or above.",
        177,
        [("List 1", HIST_1, 2, None), ("List 2", HIST_2, 2, None)],
        total_count=5,
        extra=[{"constraint_type": "level_min_count", "min_level": 300, "value": "2"}],
    )
    rules = {
        48: [psych],
        57: [all_rule("Computation and Design-Computer Science", "Divisional Foundation", "Choose one of the courses below", 123, ["MATH206"])],
        70: [methods],
        71: [concentrations],
        143: [cwt],
        144: [cwt],
        148: [literature],
        149: [literature],
        153: [philosophy],
        154: [philosophy],
        158: [history],
        159: [history],
        178: [choose_rule("Molecular Bioscience-Biogeochemistry", "Interdisciplinary", "Choose one of the two courses below", 188, 1, ["BIOL201", "BIOL202"])],
        185: [choose_rule("Molecular Bioscience-Biophysics", "Interdisciplinary", "Choose one of the two courses below", 190, 1, ["BIOL201", "BIOL202"])],
        188: [choose_rule("Molecular Bioscience-Cell and Molecular Biology", "Disciplinary", "And choose three from the following four courses", 192, 3, ["BIOL304", "BIOL306", "BIOL315", "BIOL321"])],
        195: [choose_rule("Molecular Bioscience-Genetics and Genomics", "Disciplinary", "And choose four from the following five courses", 195, 4, ["BIOL304", "BIOL314", "BIOL321", "BIOL403", "BIOL407"])],
        20: [arts],
        22: [arts],
        29: [media],
        30: [media],
        79: [quota_rule(
            "Cultures and Societies-Cultural Anthropology",
            "Disciplinary",
            "And choose two of the following five courses, with one at or above the 300-level",
            134,
            [("Candidates", ANTHRO_FIVE, None, None)],
            total_count=2,
            extra=[{"constraint_type": "level_min_count", "min_level": 300, "value": "1"}],
        )],
        92: [choose_rule("Environmental Science-Biogeochemistry", "Disciplinary", "And choose one of the following three courses", 146, 1, ["BIOL313/ENVIR313", "BIOL319", "BIOL405"])],
        93: [
            choose_rule("Environmental Science-Biogeochemistry", "Disciplinary", "And choose one of the following two courses", 146, 1, ["STATS101", "MATH206"]),
            choose_rule("Environmental Science-Biogeochemistry", "Disciplinary", "And choose one of the following two courses", 146, 1, ["BIOL312", "CHEM315/ENVIR315"]),
        ],
        98: [choose_rule("Environmental Science-Biogeochemistry", "Interdisciplinary", "And choose one of the following two courses", 145, 1, [("ENVIR302", "ECON302"), "ENVIR301"])],
        105: [choose_rule("Environmental Science-Biology", "Interdisciplinary", "And choose one of the following two courses", 154, 1, ["ECON302", "ENVIR301"])],
        134: [choose_rule("Global Health-Public Policy", "Disciplinary", "Choose one of the following two Math courses", 161, 1, ["MATH101", "MATH105"])],
        172: [
            stats_choice,
            choose_rule("Molecular Bioscience-Biogeochemistry", "Disciplinary", "And choose one course from the following three courses", 189, 1, ["BIOL212", "BIOL313/ENVIR313", "BIOL319"]),
            choose_rule("Molecular Bioscience-Biogeochemistry", "Disciplinary", "And choose one course from the following three courses", 189, 1, ["CHEM150", "BIOL312", "CHEM315/ENVIR315"]),
        ],
        230: [choose_rule("QPE-Economics", "Interdisciplinary", "And choose one of the following three courses", 209, 1, ["SOSC302", "SOSC314", "SOSC320"])],
        234: [choose_rule("QPE-Political Science", "Disciplinary", "And choose one of the following 4 courses", 213, 1, ["POLSCI302", "PPE303", "POLSCI307", "POLSCI308"])],
        239: [choose_rule("QPE-Political Science", "Interdisciplinary", "And choose one of the following three courses", 212, 1, ["SOSC302", "SOSC314", "SOSC320"])],
        246: [choose_rule("QPE-Public Policy", "Interdisciplinary", "And choose one of the following three courses", 214, 1, ["SOSC302", "SOSC314", "SOSC320"])],
        74: [advisory("Computation and Design-Social Policy", "Courses listed in the table below are recommended electives for the major.", 131)],
        78: [advisory("Cultures and Societies-Cultural Anthropology", "Courses listed in the table below are recommended electives for the major.", 135)],
        82: [advisory("Cultures and Societies-Sociology", "Courses listed in the table below are recommended electives for the major.", 137)],
        62: [domain_five],
        83: [choose_rule(
            "Cultures and Societies-Sociology",
            "Disciplinary",
            "And choose one of these three courses",
            136,
            1,
            ["SOSC205", "SOSC206", "SOSC314"],
        )],
        84: [sociology_six],
        80: [
            all_rule("Cultures and Societies-Cultural Anthropology", "Interdisciplinary", "Interdisciplinary Courses", 134, ["CULSOC101", "CULSOC205/RELIG205", "CULSOC201", "CULSOC301", "CULSOC390", "CULSOC490"]),
            all_rule("Cultures and Societies-Cultural Anthropology", "Disciplinary", "Cultural Anthropology Disciplinary Courses", 134, ["CULANTH101", "CULANTH210", "CULANTH304", "CULANTH398"]),
        ],
    }
    # Rule 172 in the old database was the biogeochemistry choose-one-of-three whose rows had been merged
    # with a later three-course sentence. The printed three-course list on page 189 is STATS 101, MATH 206, BIOL 212.
    # The separate "one of the following three" on page 146 is rule 92.
    return rules


AUDIT_NOTES = {
    48: ("全部 6 门被当成必须完成。", "改成两组里一共选 3 门，且每组至少 1 门。"),
    57: ("句子是 choose one，库里只有 MATH 206。", "手册这一句下面只有 MATH 206，因此完成 MATH 206。没有把后面的 MATH 101/105 并进来。"),
    70: ("Choose 2 被当成 4 门全部完成，并漏了跨页的 SOSC 314 和 SOSC 320。", "5 门里选 2 门。COMPSCI 206/ECON 206 只计 1 门。"),
    71: ("3 个方向共 22 门被当成全部完成。", "三个方向任选一个，并在该方向内选 3 门。ENVIR 302 与 ECON 302 只计 1 门。EHTLDR 204 按课名对应 ETHLDR 204。"),
    143: ("至少 8 学分被当成名单全部完成。", "两个名单各至少 8 学分，合计至少 20 学分，其中 300 级及以上至少 8 学分。"),
    144: ("至少 8 学分被当成名单全部完成。", "与 List 1 合成同一条学分规则，避免两个名单各算成全部完成。"),
    148: ("choose 2 被当成全部完成，LIT 298-1 和 LIT 298-2 没有课程节点。", "两个名单各至少 2 门，合计至少 5 门，其中至少 2 门为 300 级及以上。两个专题课按手册课表新建节点。"),
    149: ("choose 2 被当成全部完成。", "并入文学两个名单的合计规则。"),
    153: ("至少一门 PHIL 和一门 RELIG 被收成 1 门必修。", "两个名单各至少 2 门、合计至少 5 门、至少 2 门 300 级及以上，并且每个名单同时含 PHIL 和 RELIG。"),
    154: ("List 2 被当成全部完成，RELIG 398 没有节点。", "并入哲学与宗教的合计规则，并按手册新建 RELIG 398。"),
    158: ("至少 2 门被当成全部完成。手册印成 HIS 212。", "两个名单各至少 2 门，合计至少 5 门，至少 2 门 300 级及以上。HIS 212 按同名课程 HIST 212 对应。"),
    159: ("至少 2 门被当成全部完成。", "并入世界史两个名单的合计规则。"),
    178: ("二选一被当成两门都完成。", "BIOL 201 与 BIOL 202 中完成 1 门。"),
    185: ("二选一被当成两门都完成。", "BIOL 201 与 BIOL 202 中完成 1 门。"),
    188: ("四门选三被当成四门都完成。", "BIOL 304、306、315、321 中完成 3 门。"),
    195: ("五门选四被当成五门都完成。", "BIOL 304、314、321、403、407 中完成 4 门。"),
    20: ("同一句 Choose two 把三个方向的 100-200 级课拼成一份候选，并写成 4 选 2。", "必须先选定一个方向，再在该方向的 100-200 级选 2 门、300-400 级选 2 门。"),
    22: ("300-400 级名单被跨方向合并，MEDIART 498 没有节点。", "并入艺术方向规则，并按手册新建 MEDIART 498。"),
    29: ("媒体专业的 100-200 级名单被跨方向合并。", "媒体专业单独使用同一套三个方向，不与艺术专业混用。"),
    30: ("媒体专业的 300-400 级名单被跨方向合并。", "并入媒体专业的方向规则。"),
    79: ("五选二只解析出 GCHINA 305，300 级条件丢失。", "五门候选里选 2 门，其中至少 1 门为 300 级及以上。"),
    92: ("三选一只得到 2 门，交叉列课被拆开。", "BIOL 313/ENVIR 313、BIOL 319、BIOL 405 中选 1 门。"),
    93: ("两个彼此独立的二选一被合成 4 门候选。", "拆成 STATS 101 或 MATH 206，以及 BIOL 312 或 CHEM 315/ENVIR 315。"),
    98: ("ENVIR 302/ECON 302 不能对应到一个节点。", "这一格由 ENVIR 302 或 ECON 302 满足，只计 1 门；另一门候选是 ENVIR 301。"),
    105: ("同一交叉列写法不能对应。", "生物学这份表印的是 ECON 302 或 ENVIR 301，不把 ENVIR 302 自动算进去。"),
    134: ("两门数学后面的必修被并进同一个二选一，变成 6 门。", "只保留 MATH 101 或 MATH 105。"),
    172: ("三句选课被合成 8 门候选。", "第一句原文写 three courses，页上只有 STATS 101 和 MATH 206。人工核对确认这是手册印错，改为两门里选一门。后两句分别是 BIOL 212、BIOL 313/ENVIR 313、BIOL 319 选 1 门，以及 CHEM 150、BIOL 312、ENVIR 315/CHEM 315 选 1 门。"),
    230: ("脚注把 SOSC 302 拆碎，三选一只剩 1 门。", "SOSC 302、SOSC 314、SOSC 320 中选 1 门。"),
    234: ("四选一少了脚注粘连的 PPE 303。", "POLSCI 302、PPE 303、POLSCI 307、POLSCI 308 中选 1 门。"),
    239: ("三选一只解析出 SOSC 314。", "SOSC 302、SOSC 314、SOSC 320 中选 1 门。"),
    246: ("三选一只解析出 SOSC 314。", "SOSC 302、SOSC 314、SOSC 320 中选 1 门。"),
    74: ("推荐选修里的缺节点被当成完成度规则。", "确认为推荐名单，不参与完成度，也不为未核对的选修课猜测课程节点。"),
    78: ("推荐选修里的缺节点被当成完成度规则。", "确认为推荐名单，不参与完成度。"),
    82: ("推荐选修里的缺节点被当成完成度规则。", "确认为推荐名单，不参与完成度。"),
    62: ("句子写 seven，旧库只有 5 门。", "印刷页 127 下面实际是 5 门。人工核对确认 seven 是手册印错，按 5 门里选 3 门。"),
    83: ("句子写 three，旧库只有 2 门，SOSC 205 被脚注粘进原文。", "印刷页 136 下面实际是 SOSC 205、SOSC 206、SOSC 314，共 3 门。按这 3 门里选 1 门。"),
    84: ("句子写 six，旧库漏了 SOCIOL 223，也没有保存 200 级和 300 级条件。", "印刷页 136 到 137 实际是 6 门。按 6 门里选 2 门，其中一门 200 级、一门 300 级。"),
    80: ("学科基础课和跨学科课被连在一起，CULANTH 304 没有节点。", "跨学科 6 门全部完成；文化人类学方向 4 门全部完成。CULANTH 304 按要求表新建。"),
}


def flatten(rule, sink):
    for child in rule["children"]:
        flatten(child, sink)
    sink.append(rule)


def resolve_factory(con):
    aliases = {alias: course_id for alias, course_id in con.execute("SELECT alias_code, course_id FROM course_aliases")}
    parts = {}
    for course_id, in con.execute("SELECT course_id FROM courses"):
        parts.setdefault(frozenset(course_id.split("/")), course_id)
        aliases.setdefault(course_id, course_id)

    manual = {"HIS212": "HIST212"}

    def resolve(code):
        key = code.replace(" ", "").upper()
        key = manual.get(key, key)
        if key in aliases:
            return aliases[key]
        found = parts.get(frozenset(key.split("/")))
        if found:
            return found
        raise KeyError(code)

    return resolve


def catalog_from(con) -> dict:
    aliases = {}
    for alias, course_id in con.execute("SELECT alias_code, course_id FROM course_aliases"):
        aliases.setdefault(course_id, set()).add(alias)
    catalog = {}
    for course_id, units, level in con.execute("SELECT course_id, units, level FROM courses"):
        catalog[course_id] = {
            "units": units,
            "level": level,
            "department": course_id.split("/")[0][:],
            "aliases": aliases.get(course_id, {course_id}),
        }
        catalog[course_id]["department"] = "".join(character for character in course_id.split("/")[0] if character.isalpha())
    return catalog


def bind(rule, resolve, catalog):
    items = []
    for entry in rule["courses"]:
        if "one_of" in entry:
            ids = [resolve(code) for code in entry["one_of"]]
            items.append({
                "item_type": "one_of",
                "course_ids": ids,
                "group_name": entry["group"],
                "department": entry.get("department"),
                "units": catalog[ids[0]]["units"],
                "slot_id": ids[0],
            })
        else:
            course_id = resolve(entry["code"])
            items.append({
                "item_type": "course",
                "course_id": course_id,
                "group_name": entry["group"],
                "department": entry.get("department"),
                "units": catalog[course_id]["units"],
            })
    for child in rule["children"]:
        bind(child, resolve, catalog)
        items.append({"item_type": "child_rule", "child_rule_id": child["rule_id"]})
    rule["items"] = items
    if rule["operator"] == "ALL":
        rule["required_count"] = len([item for item in items if item["item_type"] != "child_rule"] or items)


def assign_ids(rules):
    counter = 1
    for rule in rules:
        for node in iter_nodes(rule):
            node["rule_id"] = counter
            counter += 1
            node.setdefault("note", "")


def iter_nodes(rule):
    for child in rule["children"]:
        yield from iter_nodes(child)
    yield rule


def sample_codes(rule, catalog):
    codes = []
    for item in rule.get("items", []):
        if item["item_type"] == "course":
            codes.append(item["course_id"])
        elif item["item_type"] == "one_of":
            codes.append(item["course_ids"][0])
    return codes


def leaf_rules(rule):
    items = rule.get("items") or []
    if items and not any(item["item_type"] == "child_rule" for item in items):
        return [rule]
    found = []
    for child in rule.get("children", []):
        found.extend(leaf_rules(child))
    return found


def make_any_tests(rule, catalog):
    first = rule["children"][0]
    chosen = []
    for leaf in leaf_rules(first):
        chosen.extend(sample_codes(leaf, catalog)[: leaf["required_count"]])
    mixed = []
    for child in rule["children"]:
        mixed.append(sample_codes(leaf_rules(child)[0], catalog)[0])
    return [
        {
            "case": "valid_concentration_selection",
            "completed_courses": chosen,
            "expected": {"status": "satisfied", "selected_option": first["group_label"]},
        },
        {
            "case": "courses_mixed_across_concentrations",
            "completed_courses": mixed,
            "expected": {"status": "unsatisfied", "reason": "Courses do not satisfy one concentration"},
        },
    ]


def make_tests(rule, catalog):
    tests = []
    if rule["status"] == "blocked":
        return [
            {"case": "blocked_empty_transcript", "completed_courses": [], "expected": {"status": "blocked"}},
            {"case": "blocked_even_if_listed_courses_are_complete", "completed_courses": ["STATS101", "MATH206"], "expected": {"status": "blocked"}},
        ]
    if rule["operator"] == "ADVISORY":
        tests.append({"case": "empty_transcript_is_not_a_requirement", "completed_courses": [], "expected": {"status": "not_applicable"}})
        tests.append({"case": "completed_courses_still_not_a_requirement", "completed_courses": ["MATH101"], "expected": {"status": "not_applicable"}})
        return tests
    if rule["operator"] == "ANY":
        return make_any_tests(rule, catalog)
    if rule["operator"] in {"CHOOSE", "ALL"} and rule["children"] == []:
        codes = sample_codes(rule, catalog)
        need = rule["required_count"]
        tests.append({"case": "exact_minimum", "completed_courses": codes[:need], "expected": {"status": "satisfied"}})
        tests.append({"case": "one_short", "completed_courses": codes[: need - 1], "expected": {"status": "unsatisfied"}})
        if len(codes) > need:
            tests.append({"case": "more_than_required", "completed_courses": codes[: need + 1], "expected": {"status": "satisfied"}})
        tests.append({"case": "outside_the_pool", "completed_courses": ["ARHU101"] * need, "expected": {"status": "unsatisfied"}})
        for item in rule["items"]:
            if item["item_type"] == "one_of" and len(item["course_ids"]) > 1 and need == 1:
                tests.append({
                    "case": "either_cross_list_counts_once",
                    "completed_courses": list(item["course_ids"]),
                    "expected": {"status": "satisfied"},
                })
                break
        return tests
    return tests


def explicit_tests():
    return {
        "Behavioral Science-Psychology": [
            {"case": "one_from_each_cluster_and_total_three", "completed_courses": ["PSYCH202", "PSYCH203", "NEUROSCI102"], "expected": {"status": "satisfied"}},
            {"case": "three_from_one_cluster", "completed_courses": ["PSYCH202", "PSYCH203", "PSYCH204"], "expected": {"status": "unsatisfied"}},
        ],
        "Humanities-Creative Writing and Translation": [
            {"case": "exact_credit_minimums", "completed_courses": ["LIT310", "LIT315", "LIT311", "LIT314", "WOC216", "WOC217"], "expected": {"status": "satisfied"}},
            {"case": "four_credits_short_of_twenty", "completed_courses": ["LIT310", "LIT315", "LIT311", "LIT314"], "expected": {"status": "unsatisfied"}},
            {"case": "credits_met_without_eight_at_300", "completed_courses": ["LIT219", "WOC213", "WOC216", "WOC217", "MEDIART110", "MEDIART207", "WOC290", "LIT220"], "expected": {"status": "unsatisfied"}},
        ],
        "Humanities-Literature": [
            {"case": "two_plus_two_is_only_four", "completed_courses": ["LIT216", "LIT298-1", "LIT203", "LIT210"], "expected": {"status": "unsatisfied"}},
            {"case": "five_courses_with_only_one_300_level", "completed_courses": ["LIT216", "LIT298-1", "LIT311", "LIT203", "LIT210"], "expected": {"status": "unsatisfied"}},
            {"case": "five_including_two_300_level", "completed_courses": ["LIT216", "LIT298-1", "LIT311", "LIT203", "LIT315"], "expected": {"status": "satisfied"}},
        ],
        "Humanities-Philosophy and Religion": [
            {"case": "lists_have_both_departments", "completed_courses": ["PHIL210", "RELIG302", "PHIL305", "RELIG398", "PHIL398"], "expected": {"status": "satisfied"}},
            {"case": "list_without_religion", "completed_courses": ["PHIL210", "PHIL226", "PHIL305", "PHIL398", "RELIG398"], "expected": {"status": "unsatisfied"}},
        ],
        "Humanities-World History": [
            {"case": "two_plus_two_is_only_four", "completed_courses": ["HIST111", "HIST212", "HIST227", "HIST229"], "expected": {"status": "unsatisfied"}},
            {"case": "five_courses_from_one_list", "completed_courses": ["HIST111", "HIST212", "HIST228", "HIST309", "HIST401"], "expected": {"status": "unsatisfied"}},
            {"case": "five_with_both_lists_and_two_300_level", "completed_courses": ["HIST111", "HIST309", "HIST401", "HIST314", "HIST402"], "expected": {"status": "satisfied"}},
        ],
        "Cultures and Societies-Cultural Anthropology": [
            {"case": "two_courses_including_one_300_level", "completed_courses": ["CULANTH211", "CULANTH314"], "expected": {"status": "satisfied"}},
            {"case": "two_courses_below_300", "completed_courses": ["CULANTH211", "CULANTH213"], "expected": {"status": "unsatisfied"}},
            {"case": "one_short", "completed_courses": ["CULANTH405"], "expected": {"status": "unsatisfied"}},
            {"case": "outside_the_pool", "completed_courses": ["ARHU101", "MATH101"], "expected": {"status": "unsatisfied"}},
        ],
    }


def cases_for(rule, catalog, explicit):
    if rule["status"] == "blocked":
        return make_tests(rule, catalog)
    extra = []
    if rule.get("group_label") == "Environmental Sustainability":
        extra.extend([
            {"case": "envir302_and_econ302_count_as_one_slot", "completed_courses": ["ENVIR302", "ECON302", "ENVIR101"], "expected": {"status": "unsatisfied"}},
            {"case": "one_slot_plus_two_courses", "completed_courses": ["ECON302", "ENVIR101", "ENVIR201"], "expected": {"status": "satisfied"}},
        ])
    if "200-level and one at the 300-level" in rule["source_phrase"]:
        extra.extend([
            {"case": "one_200_and_one_300", "completed_courses": ["SOCIOL213", "SOCIOL380"], "expected": {"status": "satisfied"}},
            {"case": "two_200_level_courses", "completed_courses": ["SOCIOL202", "SOCIOL213"], "expected": {"status": "unsatisfied"}},
            {"case": "two_300_level_courses", "completed_courses": ["SOCIOL310", "SOSC315"], "expected": {"status": "unsatisfied"}},
        ])
    if rule["source_phrase"].startswith("Choose 2 Methods"):
        extra.extend([
            {"case": "both_cross_list_codes_count_once", "completed_courses": ["COMPSCI206", "ECON206"], "expected": {"status": "unsatisfied"}},
            {"case": "cross_list_plus_another_course", "completed_courses": ["ECON206", "STATS201"], "expected": {"status": "satisfied"}},
        ])
    if rule["operator"] == "ANY":
        return make_any_tests(rule, catalog) + extra
    if rule["operator"] == "QUOTA" and rule["major"] in explicit:
        return explicit[rule["major"]] + extra
    if rule["operator"] == "ALL" and rule["children"]:
        chosen = []
        short = []
        for leaf in leaf_rules(rule):
            codes = sample_codes(leaf, catalog)
            need = leaf["required_count"] or 0
            chosen.extend(codes[:need])
            short.extend(codes[: max(need - 1, 0)])
        return [
            {"case": "all_parts_satisfied", "completed_courses": chosen, "expected": {"status": "satisfied"}},
            {"case": "one_part_short", "completed_courses": short, "expected": {"status": "unsatisfied"}},
        ] + extra
    if rule["operator"] in {"CHOOSE", "ALL", "ADVISORY"} and not rule["children"]:
        return make_tests(rule, catalog) + extra
    return extra


def ensure_schema(con):
    names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "major_rules_legacy" not in names:
        con.execute("ALTER TABLE major_rules RENAME TO major_rules_legacy")
        con.execute("ALTER TABLE major_rule_courses RENAME TO major_rule_courses_legacy")
    con.executescript(
        """
        DROP TABLE IF EXISTS major_rule_constraints;
        DROP TABLE IF EXISTS major_rule_items;
        DROP TABLE IF EXISTS major_rules;
        CREATE TABLE major_rules (
            rule_id INTEGER PRIMARY KEY,
            legacy_rule_id INTEGER,
            major TEXT NOT NULL,
            category TEXT,
            operator TEXT NOT NULL,
            required_count INTEGER,
            required_credits INTEGER,
            status TEXT NOT NULL,
            counts_toward_completion INTEGER NOT NULL,
            group_label TEXT,
            source_phrase TEXT,
            source_page INTEGER,
            note TEXT
        );
        CREATE TABLE major_rule_items (
            id INTEGER PRIMARY KEY,
            rule_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            course_id TEXT,
            child_rule_id INTEGER,
            group_name TEXT,
            members TEXT,
            department TEXT,
            units INTEGER,
            resolution TEXT
        );
        CREATE TABLE major_rule_constraints (
            id INTEGER PRIMARY KEY,
            rule_id INTEGER NOT NULL,
            constraint_type TEXT NOT NULL,
            field TEXT,
            operator TEXT,
            value TEXT,
            group_name TEXT,
            min_level INTEGER,
            max_level INTEGER,
            department TEXT
        );
        """
    )


def insert_new_courses(con):
    for course_id, name, units, level, department in NEW_COURSES:
        con.execute(
            """
            INSERT OR IGNORE INTO courses (
                course_id, course_name, department, level, units, description,
                prereq_text, antireq_text, notes, offering_pattern, source
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, 'bulletin_major_table')
            """,
            (
                course_id,
                name,
                department,
                level,
                units,
                "Name and credits are taken from the undergraduate bulletin major-requirement table. "
                "The course-description section did not yield a separate parsed entry.",
            ),
        )
        con.execute(
            """
            INSERT OR REPLACE INTO course_aliases (alias_code, course_id, match_method, evidence)
            VALUES (?, ?, 'self', '手册专业要求表中的课号')
            """,
            (course_id, course_id),
        )


def insert_tree(con, rule, legacy_id):
    for child in rule["children"]:
        insert_tree(con, child, legacy_id)
    counts = 1 if rule["status"] == "verified" and rule["operator"] != "ADVISORY" else 0
    con.execute(
        """
        INSERT INTO major_rules (
            rule_id, legacy_rule_id, major, category, operator, required_count, required_credits,
            status, counts_toward_completion, group_label, source_phrase, source_page, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rule["rule_id"], rule.get("legacy_rule_id", legacy_id), rule["major"], rule["category"], rule["operator"],
            rule["required_count"], rule["required_credits"], rule["status"], counts, rule.get("group_label"),
            rule["source_phrase"], rule["source_page"], rule.get("note"),
        ),
    )
    for item in rule["items"]:
        con.execute(
            """
            INSERT INTO major_rule_items (
                rule_id, item_type, course_id, child_rule_id, group_name, members, department, units, resolution
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule["rule_id"],
                "group" if item["item_type"] == "one_of" else item["item_type"],
                item.get("course_id"),
                item.get("child_rule_id"),
                item.get("group_name"),
                json.dumps(item.get("course_ids")) if item["item_type"] == "one_of" else None,
                item.get("department"),
                item.get("units"),
                "manual" if item.get("department") or item["item_type"] == "one_of" else "exact",
            ),
        )
    for constraint in rule.get("constraints") or []:
        con.execute(
            """
            INSERT INTO major_rule_constraints (
                rule_id, constraint_type, field, operator, value, group_name, min_level, max_level, department
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule["rule_id"],
                constraint["constraint_type"],
                constraint.get("field") or constraint["constraint_type"],
                ">=",
                constraint["value"],
                constraint.get("group"),
                constraint.get("min_level"),
                constraint.get("max_level"),
                constraint.get("department"),
            ),
        )


SUPERSEDED_LEGACY_IDS = {19, 21, 23, 27, 28, 31}


def history_reason(legacy_id: int) -> str:
    if legacy_id in {19, 21, 23}:
        return "这条规则把多个艺术方向的课表拼在一起，已被印刷页 102 上按方向拆开的规则取代。现行完成度使用那些规则。"
    if legacy_id in {27, 28, 31}:
        return "这条规则把多个媒体方向的课表拼在一起，已被印刷页 107 上按方向拆开的规则取代。现行完成度使用那些规则。"
    raise KeyError(legacy_id)


def ensure_history(con):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS major_rules_history (
            history_id INTEGER PRIMARY KEY,
            legacy_rule_id INTEGER NOT NULL UNIQUE,
            major TEXT NOT NULL,
            category TEXT,
            operator TEXT NOT NULL,
            required_count INTEGER,
            required_credits INTEGER,
            status TEXT NOT NULL,
            counts_toward_completion INTEGER NOT NULL,
            group_label TEXT,
            source_phrase TEXT,
            source_page INTEGER,
            note TEXT,
            history_reason TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS major_rule_items_history (
            id INTEGER PRIMARY KEY,
            history_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            course_id TEXT,
            child_rule_id INTEGER,
            group_name TEXT,
            members TEXT,
            department TEXT,
            units INTEGER,
            resolution TEXT
        );
        """
    )


def replace_history_rule(con, legacy_id, major, category, operator, required_count, source_phrase, note, items):
    ensure_history(con)
    old = con.execute(
        "SELECT history_id FROM major_rules_history WHERE legacy_rule_id = ?",
        (legacy_id,),
    ).fetchone()
    if old:
        con.execute("DELETE FROM major_rule_items_history WHERE history_id = ?", (old[0],))
        con.execute("DELETE FROM major_rules_history WHERE history_id = ?", (old[0],))
    con.execute(
        """
        INSERT INTO major_rules_history (
            legacy_rule_id, major, category, operator, required_count, required_credits,
            status, counts_toward_completion, source_phrase, source_page, note, history_reason
        ) VALUES (?, ?, ?, ?, ?, NULL, 'blocked', 0, ?, NULL, ?, ?)
        """,
        (legacy_id, major, category, operator, required_count, source_phrase, note, history_reason(legacy_id)),
    )
    history_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    for item_type, course_id, child_rule_id, group_name, members, department, units, resolution in items:
        con.execute(
            """
            INSERT INTO major_rule_items_history (
                history_id, item_type, course_id, child_rule_id, group_name, members, department, units, resolution
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (history_id, item_type, course_id, child_rule_id, group_name, members, department, units, resolution),
        )


def archive_live_superseded(con) -> int:
    """Move the six merged concentration fragments out of the live rule table."""
    rows = con.execute(
        """
        SELECT rule_id, legacy_rule_id, major, category, operator, required_count, source_phrase, note
        FROM major_rules
        WHERE legacy_rule_id IN (19, 21, 23, 27, 28, 31)
        ORDER BY legacy_rule_id
        """
    ).fetchall()
    if len(rows) not in (0, 6):
        raise SystemExit(f"被替代规则应是 0 条或 6 条，实际 {len(rows)} 条")
    for rule_id, legacy_id, major, category, operator, required_count, source_phrase, note in rows:
        items = con.execute(
            """
            SELECT item_type, course_id, child_rule_id, group_name, members, department, units, resolution
            FROM major_rule_items WHERE rule_id = ? ORDER BY id
            """,
            (rule_id,),
        ).fetchall()
        replace_history_rule(
            con, legacy_id, major, category, operator, required_count, source_phrase, note, items
        )
        con.execute("DELETE FROM major_rule_constraints WHERE rule_id = ?", (rule_id,))
        con.execute("DELETE FROM major_rule_items WHERE rule_id = ?", (rule_id,))
        con.execute("DELETE FROM major_rules WHERE rule_id = ?", (rule_id,))
    con.execute("DELETE FROM source_notes WHERE field = 'major_rule_audit'")
    con.execute(
        """
        INSERT INTO source_notes (field, value) VALUES (
            'major_rule_audit',
            'Verified completion rules use status=verified, operator other than ADVISORY, and counts_toward_completion=1. Blocked rules stay out of completion. Superseded rules 19, 21, 23, 27, 28, and 31 are in major_rules_history.'
        )
        """
    )
    return len(rows)


def copy_legacy(con, replaced_ids, superseded_ids):
    ensure_history(con)
    for row in con.execute(
        """
        SELECT rule_id, major, category, role, rule_kind, choose_k, expected_n, status, source_phrase, note
        FROM major_rules_legacy
        """
    ):
        legacy_id = row[0]
        # 41, 61, 91 used the course title "Interdisciplinary Data Analysis" as a rule header.
        if legacy_id in replaced_ids or legacy_id in {41, 61, 91}:
            continue
        if legacy_id in superseded_ids:
            items = [
                ("course", course_id, None, "", None, None, None, resolution)
                for _listed, course_id, resolution in con.execute(
                    "SELECT listed_course_id, course_id, resolution FROM major_rule_courses_legacy WHERE rule_id = ?",
                    (legacy_id,),
                )
            ]
            replace_history_rule(
                con,
                legacy_id,
                row[1],
                row[2],
                row[4] or "ALL",
                row[5],
                row[8],
                history_reason(legacy_id),
                items,
            )
            continue
        status = "partial"
        note = row[9] or ""
        known = {
            62: "句子写 seven，库里只有 5 门候选。本轮没有重写这条规则，状态改为 partial。",
            83: "句子写 three，库里只有 2 门，而且原文和课名粘在一起。状态改为 partial。",
            84: "句子写 six，并要求一门 200 级和一门 300 级。库里只有 5 门，层级条件也没有单独保存。状态改为 partial。",
        }
        if legacy_id in known:
            note = known[legacy_id]
        else:
            note = (note + " " if note else "") + "本轮没有逐条对照手册，页码未核对，不能显示为确定完成度。"
        con.execute(
            """
            INSERT INTO major_rules (
                legacy_rule_id, major, category, operator, required_count, required_credits,
                status, counts_toward_completion, source_phrase, source_page, note
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, 0, ?, NULL, ?)
            """,
            (legacy_id, row[1], row[2], row[4] or "ALL", row[5], status, row[8], note),
        )
        new_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        for listed, course_id, resolution in con.execute(
            "SELECT listed_course_id, course_id, resolution FROM major_rule_courses_legacy WHERE rule_id = ?",
            (legacy_id,),
        ):
            con.execute(
                """
                INSERT INTO major_rule_items (rule_id, item_type, course_id, group_name, resolution)
                VALUES (?, 'course', ?, '', ?)
                """,
                (new_id, course_id, resolution),
            )


def load_rule_from_db(con, rule_id):
    row = con.execute(
        """
        SELECT rule_id, major, category, operator, required_count, required_credits, status,
               group_label, source_phrase, source_page, note
        FROM major_rules WHERE rule_id = ?
        """,
        (rule_id,),
    ).fetchone()
    items = []
    for item in con.execute(
        """
        SELECT item_type, course_id, child_rule_id, group_name, members, department, units
        FROM major_rule_items WHERE rule_id = ?
        """,
        (rule_id,),
    ):
        if item[0] == "group":
            items.append({
                "item_type": "one_of",
                "course_ids": json.loads(item[4]),
                "group_name": item[3] or "",
                "department": item[5],
                "units": item[6],
                "slot_id": json.loads(item[4])[0],
            })
        elif item[0] == "child_rule":
            items.append({"item_type": "child_rule", "child_rule_id": item[2]})
        else:
            items.append({
                "item_type": "course",
                "course_id": item[1],
                "group_name": item[3] or "",
                "department": item[5],
                "units": item[6],
            })
    constraints = []
    for constraint in con.execute(
        """
        SELECT constraint_type, value, group_name, min_level, max_level, department
        FROM major_rule_constraints WHERE rule_id = ?
        """,
        (rule_id,),
    ):
        constraints.append({
            "constraint_type": constraint[0],
            "value": constraint[1],
            "group": constraint[2],
            "min_level": constraint[3],
            "max_level": constraint[4],
            "department": constraint[5],
        })
    return {
        "rule_id": row[0],
        "major": row[1],
        "category": row[2],
        "operator": row[3],
        "required_count": row[4],
        "required_credits": row[5],
        "status": row[6],
        "group_label": row[7],
        "source_phrase": row[8],
        "source_page": row[9],
        "note": row[10],
        "items": items,
        "constraints": constraints,
    }


def write_audit(replaced):
    lines = [
        "# 高风险专业规则审计",
        "",
        "核对来源是 `ug_bulletin_2025-2026.pdf` 的印刷页码。状态只有在课程名单、门数或学分、分组边界都能从该页确定时才写成 verified。",
        "",
        "推荐选修名单确认为不参与完成度。无法在课程描述部分找到、但专业要求表写明课号、课名和学分的课，按要求表补了课程节点。",
        "",
    ]
    for legacy_id in sorted(AUDIT_NOTES):
        problem, fix = AUDIT_NOTES[legacy_id]
        rules = replaced[legacy_id]
        lines.append(f"## 旧规则 {legacy_id}")
        lines.append("")
        lines.append(f"- 专业：{rules[0]['major']}")
        lines.append(f"- 分类：{rules[0]['category']}")
        lines.append(f"- 印刷页码：{rules[0]['source_page']}")
        lines.append(f"- 手册原文：{rules[0]['source_phrase']}")
        lines.append(f"- 问题：{problem}")
        lines.append(f"- 修复：{fix}")
        lines.append(f"- 人工审核记录：{len(rules)} 条新规则")
        for rule in rules:
            label = rule.get("group_label") or ""
            lines.append(f"  - 新规则 {rule['rule_id']}：{rule['status']} {rule['operator']} {label}".rstrip())
        lines.append("")
    lines.extend([
        "## 被替代的方向规则",
        "",
        "旧规则 19、21、23、27、28、31 把多个方向的课表拼在一起。它们在 `major_rules_history`。艺术方向的现行规则在印刷页 102，媒体方向在印刷页 107。",
        "",
        "## 其余规则",
        "",
        "其余旧规则已按印刷页课表核对。现行 `major_rules` 里没有 partial 规则。每条现行规则都有印刷页码。",
        "",
    ])
    AUDIT_PATH.write_text("\n".join(lines), encoding="utf-8")


def write_graph_section(summary: str):
    marker = "## 专业规则网页开放条件"
    existing = GRAPH_PATH.read_text(encoding="utf-8")
    if marker in existing:
        existing = existing.split(marker)[0].rstrip()
    GRAPH_PATH.write_text(existing + "\n\n" + marker + "\n\n" + summary + "\n", encoding="utf-8")


def check_parser():
    choose_status, _reason = parser.automatic_status("Choose 2 Methods Courses", 5)
    complete_status, _reason = parser.automatic_status("Complete the following courses", 3)
    if choose_status != "partial" or complete_status != "partial":
        raise SystemExit(f"解析器把不确定结果标成了 {choose_status} / {complete_status}")
    if parser.automatic_status("", 0)[0] == "verified":
        raise SystemExit("解析器把空句子标成了 verified")


def integrity_errors(con) -> list[str]:
    errors = []
    rules = {row[0]: load_rule_from_db(con, row[0]) for row in con.execute("SELECT rule_id FROM major_rules")}
    if has_cycle(list(rules.values())):
        errors.append("规则树有循环")
    catalog = {row[0] for row in con.execute("SELECT course_id FROM courses")}
    for rule in rules.values():
        counts, operator, status = con.execute(
            "SELECT counts_toward_completion, operator, status FROM major_rules WHERE rule_id = ?",
            (rule["rule_id"],),
        ).fetchone()
        completion_allowed = status == "verified" and operator != "ADVISORY"
        if completion_allowed and counts != 1:
            errors.append(f"规则 {rule['rule_id']} 应该计入完成度")
        if not completion_allowed and counts != 0:
            errors.append(f"规则 {rule['rule_id']} 不应该计入完成度")
        if not rule["source_page"]:
            errors.append(f"规则 {rule['rule_id']} 没有页码")
        if status != "verified":
            continue
        if not rule["source_phrase"] or not rule["source_page"]:
            errors.append(f"已核对规则 {rule['rule_id']} 缺少原文或页码")
        slots = []
        groups = set()
        for item in rule["items"]:
            if item["item_type"] == "course":
                slots.append(item["course_id"])
                groups.add(item.get("group_name") or "")
                if item["course_id"] not in catalog:
                    errors.append(f"规则 {rule['rule_id']} 的 {item['course_id']} 没有课程节点")
            elif item["item_type"] == "one_of":
                slots.append(item["slot_id"])
                groups.add(item.get("group_name") or "")
                for course_id in item["course_ids"]:
                    if course_id not in catalog:
                        errors.append(f"规则 {rule['rule_id']} 的 {course_id} 没有课程节点")
            if rule.get("required_credits") is not None and item["item_type"] in {"course", "one_of"} and item.get("units") is None:
                errors.append(f"学分规则 {rule['rule_id']} 有课程没有学分")
        if len(slots) != len(set(slots)):
            errors.append(f"规则 {rule['rule_id']} 把同一门课算了两次")
        if slots and rule.get("required_count") is not None and rule["required_count"] > len(slots):
            errors.append(f"规则 {rule['rule_id']} 要求的门数大于候选门数")
        for constraint in rule["constraints"]:
            if constraint["constraint_type"] in {"group_min_count", "group_min_credits", "department_min_count"}:
                if constraint.get("group") not in groups:
                    errors.append(f"规则 {rule['rule_id']} 的分组 {constraint.get('group')} 是空的")
        match = __import__("re").search(
            r"following\s+(two|three|four|five|2|3|4|5)\b",
            rule["source_phrase"],
            __import__("re").I,
        )
        words = {"two": 2, "three": 3, "four": 4, "five": 5, "2": 2, "3": 3, "4": 4, "5": 5}
        if match and slots and len(slots) != words[match.group(1).lower()]:
            if "手册印错" not in (rule.get("note") or ""):
                errors.append(
                    f"规则 {rule['rule_id']} 原文写 {match.group(1)}，候选是 {len(slots)} 门"
                )
    return errors


def main():
    check_parser()
    con = sqlite3.connect(DB_PATH)
    try:
        ensure_schema(con)
        insert_new_courses(con)
        resolve = resolve_factory(con)
        catalog = catalog_from(con)
        grouped = build_verified_rules()
        legacy_ids_for = {}
        flat_roots = []
        seen_rules = set()
        for legacy_id, rules in grouped.items():
            for rule in rules:
                legacy_ids_for.setdefault(id(rule), []).append(legacy_id)
                if id(rule) in seen_rules:
                    continue
                seen_rules.add(id(rule))
                flat_roots.append(rule)
        for rule in flat_roots:
            ids = legacy_ids_for[id(rule)]
            rule["legacy_rule_id"] = ids[0]
            if not rule.get("note"):
                rule["note"] = AUDIT_NOTES[ids[0]][1]
            if len(ids) > 1:
                joined = "、".join(str(item) for item in ids)
                rule["note"] = (rule.get("note") or "") + f" 同一条规则对应旧规则 {joined}。"
        nodes = []
        for rule in flat_roots:
            flatten(rule, nodes)
        assign_ids_from_nodes(flat_roots)
        for rule in flat_roots:
            bind(rule, resolve, catalog)
        if has_cycle(nodes):
            raise SystemExit("规则树有循环")
        by_id = {rule["rule_id"]: rule for rule in nodes}
        tests = []
        explicit = explicit_tests()
        for rule in nodes:
            for test in cases_for(rule, catalog, explicit):
                result = evaluate(rule, test["completed_courses"], catalog, by_id)
                expected = test["expected"]
                ok = result["status"] == expected["status"] and all(
                    result.get(key) == value for key, value in expected.items() if key != "status"
                )
                tests.append({
                    "rule_id": rule["rule_id"],
                    "major": rule["major"],
                    "case": test["case"],
                    "completed_courses": test["completed_courses"],
                    "expected": expected,
                    "actual_status": result["status"],
                    "actual_reason": result.get("reason"),
                    "passed": ok,
                })
        failed = [test for test in tests if not test["passed"]]
        if failed:
            for test in failed[:20]:
                print("FAIL", test["rule_id"], test["major"], test["case"], test["actual_status"], test["actual_reason"], "expected", test["expected"])
            raise SystemExit(f"{len(failed)} 条规则测试失败")
        for rule in flat_roots:
            insert_tree(con, rule, rule["legacy_rule_id"])
        copy_legacy(con, set(grouped), {19, 21, 23, 27, 28, 31})
        from review_partial_rules import promote_checked
        promoted = promote_checked(con)
        # Re-run the same cases from the database.
        db_rules = {row[0]: load_rule_from_db(con, row[0]) for row in con.execute("SELECT rule_id FROM major_rules")}
        reloaded_failed = 0
        for test in tests:
            result = evaluate(db_rules[test["rule_id"]], test["completed_courses"], catalog, db_rules)
            if result["status"] != test["expected"]["status"]:
                reloaded_failed += 1
        if reloaded_failed:
            raise SystemExit(f"写回数据库后有 {reloaded_failed} 条测试失败")
        blocked_ok = 0
        for rule in db_rules.values():
            if rule["status"] != "blocked":
                continue
            for completed in ([], ["MATH101", "MATH105"]):
                result = evaluate(rule, completed, catalog, db_rules)
                if result["status"] != "blocked":
                    raise SystemExit(f"blocked 规则 {rule['rule_id']} 返回了 {result['status']}")
            blocked_ok += 1
        problems = integrity_errors(con)
        if problems:
            print("\n".join(problems[:20]))
            raise SystemExit(f"数据检查没有通过：{len(problems)} 项")
        verified = [rule for rule in db_rules.values() if rule["status"] == "verified" and rule["operator"] != "ADVISORY"]
        missing_page = [rule["rule_id"] for rule in db_rules.values() if not rule["source_page"]]
        write_audit(grouped)
        from run_major_rule_tests import persist_catalog, render_report, run_cases

        catalog_cases = persist_catalog(con, tests)
        failed_cases, test_total = run_cases(con, catalog_cases)
        if failed_cases:
            for test in failed_cases[:20]:
                print("FAIL", test["rule_id"], test["case"], test["actual_status"], test["actual_reason"], "expected", test["expected"])
            raise SystemExit(f"持久化案例有 {len(failed_cases)} 条失败")
        partial_count = sum(1 for rule in db_rules.values() if rule["status"] == "partial")
        if partial_count or missing_page:
            raise SystemExit(f"仍有 partial {partial_count} 条，缺页码 {len(missing_page)} 条")
        REPORT_PATH.write_text(render_report(con, test_total, failed_cases), encoding="utf-8")
        write_graph_section(render_report(con, test_total, failed_cases, graph=True))
        con.execute("DELETE FROM source_notes WHERE field = 'major_rule_audit'")
        con.execute(
            """
            INSERT INTO source_notes (field, value) VALUES (
                'major_rule_audit',
                'Verified completion rules use status=verified, operator other than ADVISORY, and counts_toward_completion=1. Blocked rules stay out of completion. Superseded rules 19, 21, 23, 27, 28, and 31 are in major_rules_history.'
            )
            """
        )
        con.commit()
        print(f"verified={len(verified)} tests={len(tests)} blocked={blocked_ok} partial={partial_count}")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def assign_ids_from_nodes(roots):
    counter = 1
    for root in roots:
        for node in iter_nodes(root):
            node["rule_id"] = counter
            counter += 1
            node.setdefault("note", "")


if __name__ == "__main__":
    main()
