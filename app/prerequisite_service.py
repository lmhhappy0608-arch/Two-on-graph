"""Evaluate bulletin prerequisite groups. This is not a shortest-path planner."""

from __future__ import annotations

import re
from collections import defaultdict

from app.course_repository import CourseRepository
from app.database import Database
from app.models import (
    CourseNotFound,
    PrerequisiteEvaluation,
    PrerequisiteGroup,
    PrerequisiteRule,
    RequirementTreeNode,
)

_HARD_RELATIONS = {"prerequisite", "prerequisite_or_corequisite"}
_OPTION_LIMIT = 24


def _signals(text: str | None) -> set[str]:
    if not text or not text.strip():
        return set()
    found = set()
    if re.search(r"permission only", text, re.I):
        found.add("only")
    if re.search(r"\bor\b.{0,80}(consent|permission|instructor|equivalent)", text, re.I):
        found.add("alternative")
    if re.search(r"standing|placed out|placement", text, re.I):
        found.add("additional")
    if re.search(r"consent|permission|instructor", text, re.I) and "alternative" not in found and "only" not in found:
        found.add("additional")
    return found


def _group_key(group_id: str) -> tuple[int, str]:
    match = re.search(r"(\d+)", group_id or "")
    return (int(match.group(1)) if match else 10**9, group_id or "")


def _met(edge: dict, completed: set[str], concurrent: set[str]) -> bool:
    course_id = edge["source_course"]
    if edge["relation_type"] == "prerequisite_or_corequisite":
        return course_id in completed or course_id in concurrent
    return course_id in completed


def _group_satisfied(edges: list[dict], completed: set[str], concurrent: set[str]) -> bool:
    flags = [_met(edge, completed, concurrent) for edge in edges]
    logic = edges[0]["logic_within_group"]
    if logic == "or":
        return any(flags)
    return all(flags)


def _fold(groups: list[list[dict]], completed: set[str], concurrent: set[str]) -> bool:
    if not groups:
        return True
    result = _group_satisfied(groups[0], completed, concurrent)
    for edges in groups[1:]:
        current = _group_satisfied(edges, completed, concurrent)
        if edges[0]["group_relation"] == "or":
            result = result or current
        else:
            result = result and current
    return result


def _alternatives(edges: list[dict]) -> list[set[str]]:
    courses = [edge["source_course"] for edge in edges]
    if edges[0]["logic_within_group"] == "or":
        return [{course_id} for course_id in courses]
    return [set(courses)]


def _option_sets(groups: list[list[dict]]) -> list[set[str]]:
    if not groups:
        return [set()]
    options = _alternatives(groups[0])
    for edges in groups[1:]:
        branch = _alternatives(edges)
        if edges[0]["group_relation"] == "or":
            options = options + branch
        else:
            options = [left | right for left in options for right in branch]
        if len(options) > _OPTION_LIMIT:
            return options[:_OPTION_LIMIT]
    return options


def _as_group(edges: list[dict], satisfied: bool | None) -> PrerequisiteGroup:
    first = edges[0]
    clauses = [edge["raw_clause"] for edge in edges if edge.get("raw_clause")]
    return PrerequisiteGroup(
        group_id=first["group_id"] or "",
        logic=first["logic_within_group"] or "single",
        group_relation=first["group_relation"] or "and",
        relation_type=first["relation_type"],
        strict=bool(first["strict"]),
        issue=first["issue"],
        courses=tuple(edge["source_course"] for edge in edges),
        raw_clause=clauses[0] if clauses else None,
        satisfied=satisfied,
    )


def build_requirement_tree(
    course_id: str,
    completed: set[str],
    edges_by_target: dict[str, list[dict]],
    names: dict[str, str | None],
    max_depth: int | None = None,
    path: tuple[str, ...] = (),
) -> RequirementTreeNode:
    if course_id in path:
        return RequirementTreeNode(
            kind="course",
            course_id=course_id,
            logic=None,
            relation=None,
            state="cycle",
            note="A cycle was detected in this dependency path. Expansion stopped at this course.",
        )
    state = "completed" if course_id in completed else "missing"
    if course_id in completed or (max_depth is not None and max_depth <= 0):
        return RequirementTreeNode(
            kind="course",
            course_id=course_id,
            logic=None,
            relation=None,
            state=state if course_id in completed else "depth_limit",
        )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for edge in edges_by_target.get(course_id, []):
        if edge["relation_type"] not in _HARD_RELATIONS:
            continue
        if not edge["strict"] or edge["issue"] != "ok":
            continue
        grouped[edge["group_id"] or ""].append(edge)
    children = []
    next_path = path + (course_id,)
    for group_id in sorted(grouped, key=_group_key):
        edges = grouped[group_id]
        group_state = "satisfied" if _group_satisfied(edges, completed, set()) else "unsatisfied"
        members = []
        for edge in edges:
            child = build_requirement_tree(
                edge["source_course"],
                completed,
                edges_by_target,
                names,
                None if max_depth is None else max_depth - 1,
                next_path,
            )
            members.append(
                RequirementTreeNode(
                    kind="course",
                    course_id=child.course_id,
                    logic=child.logic,
                    relation=edge["relation_type"],
                    state=child.state,
                    note=child.note,
                    children=child.children,
                )
            )
        children.append(
            RequirementTreeNode(
                kind="group",
                course_id=None,
                logic=edges[0]["logic_within_group"],
                relation=edges[0]["group_relation"],
                state=group_state,
                note=edges[0].get("raw_clause"),
                children=tuple(members),
            )
        )
    if not children and course_id not in completed and _signals(names.get(course_id)):
        state = "needs_manual_review"
    return RequirementTreeNode(
        kind="course",
        course_id=course_id,
        logic=None,
        relation=None,
        state=state,
        children=tuple(children),
    )


class PrerequisiteService:
    def __init__(self, database: Database | None = None):
        self.database = database or Database()
        self.courses = CourseRepository(self.database)

    def _canonical_set(self, codes: list[str] | None) -> set[str]:
        found = set()
        for code in codes or []:
            canonical = self.courses.resolve_course_code(code)
            if canonical is not None:
                found.add(canonical)
        return found

    def _edges_for(self, course_id: str) -> list[dict]:
        return self.database.query(
            """
            SELECT source_course, target_course, relation_type, group_id,
                   logic_within_group, group_relation, strict, issue, raw_clause
            FROM graph_edges
            WHERE target_course = ?
            ORDER BY id
            """,
            (course_id,),
        )

    def _all_prerequisite_edges(self) -> dict[str, list[dict]]:
        rows = self.database.query(
            """
            SELECT source_course, target_course, relation_type, group_id,
                   logic_within_group, group_relation, strict, issue, raw_clause
            FROM graph_edges
            WHERE relation_type IN ('prerequisite', 'prerequisite_or_corequisite')
            ORDER BY target_course, id
            """
        )
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[row["target_course"]].append(row)
        return grouped

    def get_prerequisite_rule(self, course_id_or_alias: str) -> PrerequisiteRule:
        course_id = self.courses.resolve_course_code(course_id_or_alias)
        if course_id is None:
            raise CourseNotFound(course_id_or_alias)
        detail = self.courses.get_course(course_id)
        buckets = {"strict": [], "coreq": [], "hint": [], "anti": []}
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for edge in self._edges_for(course_id):
            grouped[(edge["relation_type"], edge["group_id"] or "")].append(edge)
        clauses = []
        for (_relation, group_id) in sorted(grouped, key=lambda item: (_group_key(item[1]), item[0])):
            edges = grouped[(_relation, group_id)]
            group = _as_group(edges, None)
            for edge in edges:
                if edge.get("raw_clause") and edge["raw_clause"] not in clauses:
                    clauses.append(edge["raw_clause"])
            relation = edges[0]["relation_type"]
            deciding = bool(edges[0]["strict"]) and edges[0]["issue"] == "ok"
            if relation == "antirequisite":
                buckets["anti"].append(group)
            elif not deciding:
                buckets["hint"].append(group)
            elif relation == "prerequisite_or_corequisite":
                buckets["coreq"].append(group)
            else:
                buckets["strict"].append(group)
        return PrerequisiteRule(
            course_id=course_id,
            strict_groups=tuple(buckets["strict"]),
            corequisite_groups=tuple(buckets["coreq"]),
            hints=tuple(buckets["hint"]),
            antirequisites=tuple(buckets["anti"]),
            raw_clauses=tuple(clauses),
            prereq_text=detail.prereq_text if detail else None,
            antireq_text=detail.antireq_text if detail else None,
        )

    def evaluate_prerequisites(
        self,
        target_course: str,
        completed_courses: list[str],
        concurrent_courses: list[str] | None = None,
    ) -> PrerequisiteEvaluation:
        course_id = self.courses.resolve_course_code(target_course)
        if course_id is None:
            raise CourseNotFound(target_course)
        completed = self._canonical_set(completed_courses)
        concurrent = self._canonical_set(concurrent_courses)
        detail = self.courses.get_course(course_id)
        grouped: dict[str, list[dict]] = defaultdict(list)
        antireq = []
        hints = []
        for edge in self._edges_for(course_id):
            if edge["relation_type"] == "antirequisite":
                antireq.append(edge)
                continue
            if edge["relation_type"] not in _HARD_RELATIONS:
                continue
            if edge["strict"] and edge["issue"] == "ok":
                grouped[edge["group_id"] or ""].append(edge)
            else:
                hints.append(edge)
        hard_groups = [grouped[key] for key in sorted(grouped, key=_group_key)]
        hard_ok = _fold(hard_groups, completed, concurrent)
        satisfied = []
        missing = []
        for edges in hard_groups:
            group = _as_group(edges, _group_satisfied(edges, completed, concurrent))
            if group.satisfied:
                satisfied.append(group)
            else:
                missing.append(group)
        conflicts = tuple(
            sorted({edge["source_course"] for edge in antireq if edge["source_course"] in completed})
        )
        text = detail.prereq_text if detail else None
        signals = _signals(text)
        hint_groups: dict[str, list[dict]] = defaultdict(list)
        for edge in hints:
            hint_groups[edge["group_id"] or ""].append(edge)
        hint_met = any(
            _group_satisfied(edges, completed, concurrent) for edges in hint_groups.values()
        )
        status = _status(bool(hard_groups), hard_ok, signals, hint_met, bool(hints), bool(conflicts))
        hint_lines = tuple(
            edge["raw_clause"] or edge["source_course"]
            for edge in hints
            if edge.get("raw_clause") or edge.get("source_course")
        )
        manual = []
        if "only" in signals:
            manual.append("Manual review required: the bulletin states that permission is required.")
        if "alternative" in signals:
            manual.append("Manual review required: instructor consent or an equivalent course may satisfy this condition.")
        if "additional" in signals:
            manual.append("Manual review required: the bulletin includes standing, placement, or another unstructured condition.")
        return PrerequisiteEvaluation(
            course_id=course_id,
            status=status,
            satisfied_groups=tuple(satisfied),
            unsatisfied_groups=tuple(missing),
            options=tuple(tuple(sorted(item)) for item in _option_sets(hard_groups)),
            hints=tuple(dict.fromkeys(hint_lines)),
            antirequisite_conflicts=conflicts,
            manual_review=tuple(manual),
            prereq_text=text,
            source="graph_edges",
        )

    def get_recursive_requirements(
        self,
        target_course: str,
        completed_courses: list[str],
        max_depth: int | None = None,
    ) -> RequirementTreeNode:
        course_id = self.courses.resolve_course_code(target_course)
        if course_id is None:
            raise CourseNotFound(target_course)
        completed = self._canonical_set(completed_courses)
        texts = {
            row["course_id"]: row["prereq_text"]
            for row in self.database.query(
                "SELECT course_id, prereq_text FROM courses"
            )
        }
        return build_requirement_tree(
            course_id,
            completed,
            self._all_prerequisite_edges(),
            texts,
            max_depth,
        )


def _status(
    has_hard_groups: bool,
    hard_ok: bool,
    signals: set[str],
    hint_met: bool,
    has_hints: bool,
    conflict: bool,
) -> str:
    if has_hard_groups:
        if not hard_ok:
            manual_alternative = bool(signals & {"only", "alternative"}) and "additional" not in signals
            status = "needs_manual_review" if manual_alternative else "unsatisfied"
        else:
            status = "needs_manual_review" if signals & {"only", "additional"} else "satisfied"
    elif signals & {"only", "additional"}:
        status = "needs_manual_review"
    elif hint_met:
        status = "satisfied"
    elif has_hints or signals:
        status = "needs_manual_review"
    else:
        status = "satisfied"
    if conflict and status == "satisfied":
        return "needs_manual_review"
    return status
