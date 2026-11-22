import pytest

from app.models import CourseNotFound
from app.prerequisite_service import PrerequisiteService, build_requirement_tree


@pytest.fixture(scope="module")
def service():
    return PrerequisiteService()


def test_single_or_prerequisite(service):
    unmet = service.evaluate_prerequisites("MATH206", [])
    assert unmet.status == "unsatisfied"
    met = service.evaluate_prerequisites("MATH206", ["math 101"])
    assert met.status == "satisfied"
    assert service.evaluate_prerequisites("MATH206", ["MATH105"]).status == "satisfied"


def test_and_combination(service):
    unmet = service.evaluate_prerequisites("COMPSCI306", ["COMPSCI201"])
    assert unmet.status == "unsatisfied"
    met = service.evaluate_prerequisites(
        "COMPSCI306",
        ["COMPSCI201"],
        concurrent_courses=["COMPSCI205"],
    )
    assert met.status == "satisfied"


def test_or_combination_and_alias(service):
    rule = service.get_prerequisite_rule("STATS202")
    assert any(group.logic == "or" for group in rule.strict_groups)
    assert service.evaluate_prerequisites("STATS202", ["STATS101"]).status == "satisfied"
    assert service.evaluate_prerequisites("STATS202", []).status == "unsatisfied"


def test_nested_and_or_for_stats303(service):
    first = ["COMPSCI309/STATS302", "MATH304", "MATH305"]
    via_alias = service.evaluate_prerequisites(
        "STATS303",
        first,
        concurrent_courses=["STATS211"],
    )
    assert via_alias.status == "satisfied"
    second = service.evaluate_prerequisites(
        "STATS303",
        ["MATH405", "COMPSCI201", "MATH304", "MATH305", "STATS211"],
    )
    assert second.status == "satisfied"
    partial = service.evaluate_prerequisites(
        "STATS303",
        ["MATH405", "MATH304", "MATH305", "STATS211"],
    )
    assert partial.status == "unsatisfied"


def test_corequisite_can_be_concurrent(service):
    assert service.evaluate_prerequisites("COMPSCI203", [], ["MATH202"]).status == "satisfied"
    assert service.evaluate_prerequisites("COMPSCI203", []).status == "unsatisfied"


def test_nonstrict_edge_does_not_block(service):
    result = service.evaluate_prerequisites("CHINESE102A", [])
    assert result.status != "unsatisfied"
    assert result.hints


def test_antirequisite_conflict_is_separate(service):
    result = service.evaluate_prerequisites("MATH206", ["MATH101", "MATH205"])
    assert "MATH205" in result.antirequisite_conflicts
    assert result.status == "needs_manual_review"
    rule = service.get_prerequisite_rule("COMPSCI101")
    assert {course for group in rule.antirequisites for course in group.courses} == {
        "COMPSCI201",
        "STATS102",
    }
    assert rule.strict_groups == ()


def test_unknown_course(service):
    with pytest.raises(CourseNotFound):
        service.evaluate_prerequisites("ZZZ999", [])


def test_recursive_tree_keeps_both_or_branches_and_stops_at_depth(service):
    tree = service.get_recursive_requirements("STATS303", [])
    group_courses = []
    for group in tree.children:
        group_courses.append({child.course_id for child in group.children})
    assert {"COMPSCI309/STATS302"} in group_courses
    assert {"MATH405", "COMPSCI201"} in group_courses
    limited = service.get_recursive_requirements("STATS202", [], max_depth=1)
    flattened = _course_ids(limited)
    assert "MATH101" not in flattened
    assert "MATH206" in flattened


def test_cycle_guard_and_repeated_course_in_two_branches():
    edges = {
        "T": [
            _edge("A", "T", "G1", "or", "and"),
            _edge("B", "T", "G1", "or", "and"),
        ],
        "A": [_edge("C", "A", "G1", "single", "and")],
        "B": [_edge("C", "B", "G1", "single", "and")],
        "LOOP": [_edge("LOOP", "LOOP", "G1", "single", "and")],
    }
    tree = build_requirement_tree("T", set(), edges, {})
    branches = tree.children[0].children
    assert [node.course_id for node in branches] == ["A", "B"]
    assert [node.children[0].children[0].course_id for node in branches] == ["C", "C"]
    cycle = build_requirement_tree("LOOP", set(), edges, {})
    assert cycle.children[0].children[0].state == "cycle"


def _edge(source, target, group_id, logic, relation):
    return {
        "source_course": source,
        "target_course": target,
        "relation_type": "prerequisite",
        "group_id": group_id,
        "logic_within_group": logic,
        "group_relation": relation,
        "strict": 1,
        "issue": "ok",
        "raw_clause": source,
    }


def _course_ids(node):
    found = set()
    if node.course_id:
        found.add(node.course_id)
    for child in node.children:
        found.update(_course_ids(child))
    return found
