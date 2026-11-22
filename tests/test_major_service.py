import json
from pathlib import Path

import pytest

from app.major_service import MajorService, UnknownMajor

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "data" / "major_rule_tests.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def service():
    return MajorService()


def test_all_majors_load(service):
    majors = service.list_majors()
    assert len(majors) == 39
    assert majors == sorted(majors)
    assert "All Majors" in majors
    for major in majors:
        rules = service.get_major_rules(major)
        assert rules
        assert all(rule.source_page for rule in rules)


def test_empty_transcript_is_not_complete(service):
    progress = service.evaluate_major_progress("Data Science", [])
    assert progress.official_audit is False
    assert progress.completion_ratio is not None
    assert progress.completion_ratio < 1
    assert progress.satisfied_count < progress.rule_count


def test_operator_examples_and_advisory_and_blocked(service):
    by_operator = {}
    for case in CASES:
        if case["origin"] != "hand":
            continue
        operator = service._load_rules()[case["rule_id"]]["operator"]
        by_operator.setdefault(operator, []).append(case)
    for operator in ("ALL", "CHOOSE", "ANY", "QUOTA"):
        positive = next(case for case in by_operator[operator] if case["expected"]["status"] == "satisfied")
        negative = next(case for case in by_operator[operator] if case["expected"]["status"] == "unsatisfied")
        assert service.evaluate_rule(positive["rule_id"], positive["completed_courses"])["status"] == "satisfied"
        assert service.evaluate_rule(negative["rule_id"], negative["completed_courses"])["status"] == "unsatisfied"

    advisory = next(
        rule for rule in service._load_rules().values() if rule["operator"] == "ADVISORY"
    )
    progress = service.evaluate_major_progress(advisory["major"], ["MATH101"])
    advisory_results = [item for item in progress.results if item.operator == "ADVISORY"]
    assert advisory_results
    assert all(item.status == "not_applicable" for item in advisory_results)
    assert all(not item.counts_toward_completion for item in advisory_results)

    blocked = service.evaluate_major_progress("All Majors", ["CAPSTONE495", "CAPSTONE496"])
    assert blocked.has_blocked
    assert blocked.blocked_count == 1
    assert blocked.results[-1].status == "blocked" or any(item.status == "blocked" for item in blocked.results)
    assert "manual review" in blocked.automatic_judgment_note.lower()
    assert all(item.status not in {"satisfied", "unsatisfied"} for item in blocked.results if not item.counts_toward_completion and item.status == "blocked")


def test_cross_list_counts_once(service):
    raw = service.evaluate_rule(79, ["HIST210"])
    again = service.evaluate_rule(79, ["ARTS210", "HIST210"])
    assert raw["status"] == "satisfied"
    assert again["status"] == "satisfied"
    assert raw["counted_courses"].count("ARTS210/HIST210") == 1
    assert again["counted_courses"].count("ARTS210/HIST210") == 1


def test_unknown_major(service):
    with pytest.raises(UnknownMajor):
        service.evaluate_major_progress("Not A Major", [])


def test_persisted_rule_cases_match_the_engine(service):
    assert len(CASES) == 670
    failed = []
    for case in CASES:
        result = service.evaluate_rule(case["rule_id"], case["completed_courses"])
        expected = case["expected"]
        if result["status"] != expected["status"] or any(
            result.get(key) != value for key, value in expected.items() if key != "status"
        ):
            failed.append((case["rule_id"], case["case"], result["status"], expected))
    assert failed == []
