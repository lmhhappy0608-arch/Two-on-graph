"""Course, alias, and recorded-section queries."""

from __future__ import annotations

from app.database import Database
from app.models import CourseDetail, CourseNotFound, CourseSummary, Number, SectionRecord

_SEARCH_CAP = 50


def normalize_code(value: str) -> str:
    return value.replace(" ", "").upper().strip()


def _number(value) -> Number | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class CourseRepository:
    def __init__(self, database: Database | None = None):
        self.database = database or Database()

    def list_canonical_ids(self) -> list[str]:
        rows = self.database.query(
            """
            SELECT course_id
            FROM course_aliases
            WHERE alias_code = course_id
            ORDER BY course_id
            """
        )
        return [row["course_id"] for row in rows]

    def resolve_course_code(self, code: str) -> str | None:
        key = normalize_code(code or "")
        if not key:
            return None
        rows = self.database.query(
            """
            SELECT course_id
            FROM course_aliases
            WHERE REPLACE(UPPER(alias_code), ' ', '') = ?
            """,
            (key,),
        )
        if not rows:
            return None
        return rows[0]["course_id"]

    def search_courses(self, query: str, limit: int = 20) -> list[CourseSummary]:
        text = (query or "").strip()
        if not text:
            return []
        limit = max(0, min(int(limit), _SEARCH_CAP))
        if limit == 0:
            return []
        key = normalize_code(text)
        rows = self.database.query(
            """
            SELECT c.course_id, c.course_name, c.department, c.level, c.units, a.alias_code
            FROM course_aliases AS a
            JOIN courses AS c ON c.course_id = a.course_id
            WHERE REPLACE(UPPER(a.alias_code), ' ', '') = ?
               OR REPLACE(UPPER(c.course_id), ' ', '') = ?
               OR REPLACE(UPPER(a.alias_code), ' ', '') LIKE ? || '%'
               OR INSTR(LOWER(COALESCE(c.course_name, '')), LOWER(?)) > 0
            """,
            (key, key, key, text),
        )
        best: dict[str, CourseSummary] = {}
        for row in rows:
            rank, alias = _match_rank(row["course_id"], row["alias_code"], row["course_name"], text, key)
            if rank is None:
                continue
            current = best.get(row["course_id"])
            summary = CourseSummary(
                course_id=row["course_id"],
                course_name=_text(row["course_name"]),
                department=_text(row["department"]),
                level=row["level"],
                units=_number(row["units"]),
                matched_alias=alias,
                match_rank=rank,
            )
            if current is None or (rank, alias or "") < (current.match_rank, current.matched_alias or ""):
                best[row["course_id"]] = summary
        ordered = sorted(best.values(), key=lambda item: (item.match_rank, item.course_id))
        return ordered[:limit]

    def get_course(self, course_id_or_alias: str) -> CourseDetail | None:
        course_id = self.resolve_course_code(course_id_or_alias)
        if course_id is None:
            return None
        rows = self.database.query(
            """
            SELECT course_id, course_name, department, level, units, description,
                   prereq_text, antireq_text, source
            FROM courses
            WHERE course_id = ?
            """,
            (course_id,),
        )
        if not rows:
            return None
        row = rows[0]
        aliases = tuple(
            item["alias_code"]
            for item in self.database.query(
                """
                SELECT alias_code
                FROM course_aliases
                WHERE course_id = ?
                ORDER BY alias_code
                """,
                (course_id,),
            )
        )
        fields = {
            "course_name": _text(row["course_name"]),
            "department": _text(row["department"]),
            "level": row["level"],
            "units": _number(row["units"]),
            "description": _text(row["description"]),
            "prereq_text": _text(row["prereq_text"]),
            "antireq_text": _text(row["antireq_text"]),
            "source": _text(row["source"]),
        }
        optional_requirement_fields = {"prereq_text", "antireq_text"}
        missing = tuple(
            name
            for name, value in fields.items()
            if value is None
            and name != "source"
            and name not in optional_requirement_fields
        )
        return CourseDetail(
            course_id=course_id,
            aliases=aliases,
            missing_fields=missing,
            **fields,
        )

    def get_recorded_sections(self, course_id_or_alias: str) -> list[SectionRecord]:
        course_id = self.resolve_course_code(course_id_or_alias)
        if course_id is None:
            raise CourseNotFound(course_id_or_alias)
        rows = self.database.query(
            """
            SELECT term_code, year_term, class_nbr, section, component, session_code,
                   status, start_dt, end_dt, units
            FROM class_sections
            WHERE canonical_course_id = ?
            ORDER BY term_code, class_nbr
            """,
            (course_id,),
        )
        records = []
        for row in rows:
            raw_units = None if row["units"] is None else str(row["units"]).strip()
            records.append(
                SectionRecord(
                    term_code=row["term_code"],
                    term_name=row["year_term"],
                    class_nbr=row["class_nbr"],
                    section=_text(row["section"]),
                    component=_text(row["component"]),
                    session_code=_text(row["session_code"]),
                    status=_text(row["status"]),
                    start_dt=_text(row["start_dt"]),
                    end_dt=_text(row["end_dt"]),
                    units=_number(raw_units) if raw_units else None,
                    units_text=raw_units or None,
                )
            )
        return records

    def recorded_terms(self) -> list[tuple[str, str]]:
        rows = self.database.query(
            """
            SELECT term_code, year_term
            FROM class_sections
            GROUP BY term_code, year_term
            ORDER BY term_code
            """
        )
        return [(row["term_code"], row["year_term"]) for row in rows]


def _match_rank(course_id: str, alias: str, name: str | None, query: str, key: str):
    normalized_id = normalize_code(course_id)
    normalized_alias = normalize_code(alias)
    if normalized_id == key:
        return 0, None
    if normalized_alias == key:
        return 1, alias
    if key and (normalized_id.startswith(key) or normalized_alias.startswith(key)):
        return 2, alias if normalized_alias.startswith(key) and normalized_alias != normalized_id else None
    if name and query.lower() in name.lower():
        return 3, None
    return None, None
