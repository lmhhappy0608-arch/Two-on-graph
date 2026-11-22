import pytest

from app.course_repository import CourseRepository
from app.models import CourseNotFound


@pytest.fixture(scope="module")
def repo():
    return CourseRepository()


def test_exact_canonical_code(repo):
    found = repo.search_courses("MATH206")
    assert found[0].course_id == "MATH206"
    assert found[0].match_rank == 0
    assert found[0].course_name == "Probability and Statistics"


def test_lowercase_and_spaced_code(repo):
    found = repo.search_courses("math 206")
    assert [item.course_id for item in found if item.match_rank == 0] == ["MATH206"]


def test_alias_resolves_to_one_canonical_course(repo):
    assert repo.resolve_course_code("stats302") == "COMPSCI309/STATS302"
    assert repo.resolve_course_code("COMPSCI 309") == "COMPSCI309/STATS302"
    assert repo.resolve_course_code("COMPSCI309/STATS302") == "COMPSCI309/STATS302"
    found = repo.search_courses("STATS302")
    assert [item.course_id for item in found] == ["COMPSCI309/STATS302"]
    assert found[0].matched_alias == "STATS302"


def test_unknown_code_is_not_fuzzy_matched(repo):
    assert repo.resolve_course_code("ZZZ999") is None
    assert repo.get_course("ZZZ999") is None
    assert repo.search_courses("ZZZ999") == []


def test_name_search(repo):
    found = repo.search_courses("Probability and Statistics")
    assert any(item.course_id == "MATH206" for item in found)


def test_empty_search_does_not_return_the_catalog(repo):
    assert repo.search_courses("   ") == []
    assert len(repo.list_canonical_ids()) == 824


def test_missing_name_stays_missing(repo):
    detail = repo.get_course("DKU101")
    assert detail is not None
    assert detail.course_name is None
    assert "course_name" in detail.missing_fields


def test_half_credit_is_preserved(repo):
    detail = repo.get_course("PHYSEDU101A")
    assert detail is not None
    assert detail.units == 0.5


def test_recorded_sections_use_the_four_recorded_terms(repo):
    sections = repo.get_recorded_sections("ARHU101")
    assert {item.term_code for item in sections} == {"2258", "2261", "2268", "2271"}
    assert {item.term_name for item in sections} == {
        "2025 Fall",
        "2026 Spring",
        "2026 Fall",
        "2027 Spring",
    }
    assert all(item.class_nbr is not None for item in sections)


def test_unknown_section_lookup_is_not_an_empty_history(repo):
    with pytest.raises(CourseNotFound):
        repo.get_recorded_sections("ZZZ999")


def test_every_canonical_course_alias_and_section_code_resolves(repo):
    for course_id in repo.list_canonical_ids():
        detail = repo.get_course(course_id)
        assert detail is not None
        assert detail.course_id == course_id
    for row in repo.database.query("SELECT alias_code, course_id FROM course_aliases"):
        assert repo.resolve_course_code(row["alias_code"]) == row["course_id"]
    for row in repo.database.query(
        "SELECT DISTINCT course_code, canonical_course_id FROM class_sections"
    ):
        assert repo.resolve_course_code(row["course_code"]) == row["canonical_course_id"]
