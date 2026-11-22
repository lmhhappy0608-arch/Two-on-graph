"""Structured results for the read-only curriculum services."""

from __future__ import annotations

from dataclasses import dataclass, field


class CourseNotFound(LookupError):
    """A course code is neither a canonical id nor a known alias."""


class GraphIntegrityError(RuntimeError):
    """The curriculum graph does not match the database."""


Number = int | float


@dataclass(frozen=True)
class CourseSummary:
    course_id: str
    course_name: str | None
    department: str | None
    level: int | None
    units: Number | None
    matched_alias: str | None
    match_rank: int


@dataclass(frozen=True)
class CourseDetail:
    course_id: str
    aliases: tuple[str, ...]
    course_name: str | None
    department: str | None
    level: int | None
    units: Number | None
    description: str | None
    prereq_text: str | None
    antireq_text: str | None
    source: str | None
    missing_fields: tuple[str, ...]


@dataclass(frozen=True)
class SectionRecord:
    term_code: str
    term_name: str
    class_nbr: int | None
    section: str | None
    component: str | None
    session_code: str | None
    status: str | None
    start_dt: str | None
    end_dt: str | None
    units: Number | None
    units_text: str | None


@dataclass(frozen=True)
class PrerequisiteGroup:
    group_id: str
    logic: str
    group_relation: str
    relation_type: str
    strict: bool
    issue: str
    courses: tuple[str, ...]
    raw_clause: str | None
    satisfied: bool | None = None


@dataclass(frozen=True)
class PrerequisiteRule:
    course_id: str
    strict_groups: tuple[PrerequisiteGroup, ...]
    corequisite_groups: tuple[PrerequisiteGroup, ...]
    hints: tuple[PrerequisiteGroup, ...]
    antirequisites: tuple[PrerequisiteGroup, ...]
    raw_clauses: tuple[str, ...]
    prereq_text: str | None
    antireq_text: str | None


@dataclass(frozen=True)
class PrerequisiteEvaluation:
    course_id: str
    status: str
    satisfied_groups: tuple[PrerequisiteGroup, ...]
    unsatisfied_groups: tuple[PrerequisiteGroup, ...]
    options: tuple[tuple[str, ...], ...]
    hints: tuple[str, ...]
    antirequisite_conflicts: tuple[str, ...]
    manual_review: tuple[str, ...]
    prereq_text: str | None
    source: str


@dataclass(frozen=True)
class RequirementTreeNode:
    kind: str
    course_id: str | None
    logic: str | None
    relation: str | None
    state: str
    note: str | None = None
    children: tuple["RequirementTreeNode", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MajorRuleResult:
    rule_id: int
    legacy_rule_id: int | None
    major: str
    category: str | None
    operator: str
    status: str
    counts_toward_completion: bool
    source_phrase: str | None
    source_page: int | None
    note: str | None
    reason: str | None
    required_count: int | None
    required_credits: Number | None
    counted_courses: tuple[str, ...]
    group_label: str | None


@dataclass(frozen=True)
class MajorProgress:
    major: str
    rule_count: int
    satisfied_count: int
    unsatisfied_count: int
    blocked_count: int
    advisory_count: int
    counted_courses: tuple[str, ...]
    remaining: tuple[str, ...]
    completion_ratio: float | None
    has_blocked: bool
    automatic_judgment_note: str | None
    official_audit: bool
    results: tuple[MajorRuleResult, ...]
