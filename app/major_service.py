"""Major lists and completion checks. Evaluation stays in major_rule_engine."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
if str(_DATA_DIR) not in sys.path:
    sys.path.insert(0, str(_DATA_DIR))

from major_rule_engine import evaluate

from app.database import Database
from app.models import MajorProgress, MajorRuleResult, Number


class UnknownMajor(LookupError):
    """The requested major is not in major_rules."""


def _number(value) -> Number | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


class MajorService:
    def __init__(self, database: Database | None = None):
        self.database = database or Database()
        self._rules: dict[int, dict] | None = None
        self._catalog: dict | None = None

    def list_majors(self) -> list[str]:
        rows = self.database.query(
            "SELECT DISTINCT major FROM major_rules ORDER BY major"
        )
        return [row["major"] for row in rows]

    def get_major_rules(self, major: str) -> tuple[MajorRuleResult, ...]:
        self._require_major(major)
        return tuple(self._result_shell(rule) for rule in self._roots(major))

    def evaluate_rule(self, rule_id: int, completed_courses: list[str]) -> dict:
        rules = self._load_rules()
        if rule_id not in rules:
            raise KeyError(rule_id)
        return evaluate(rules[rule_id], completed_courses, self._load_catalog(), rules)

    def evaluate_major_progress(self, major: str, completed_courses: list[str]) -> MajorProgress:
        self._require_major(major)
        results = []
        counted: list[str] = []
        remaining = []
        for rule in self._roots(major):
            raw = self.evaluate_rule(rule["rule_id"], completed_courses)
            result = self._result_from_engine(rule, raw)
            results.append(result)
            if result.counts_toward_completion and result.status == "satisfied":
                for course_id in result.counted_courses:
                    if course_id not in counted:
                        counted.append(course_id)
            if result.counts_toward_completion and result.status == "unsatisfied":
                label = result.group_label or result.category or result.operator
                remaining.append(f"{label}: {result.reason or 'Requirement not satisfied'}")
        completion = [item for item in results if item.counts_toward_completion]
        satisfied = [item for item in completion if item.status == "satisfied"]
        unsatisfied = [item for item in completion if item.status == "unsatisfied"]
        blocked = [item for item in results if item.status == "blocked"]
        advisory = [item for item in results if item.operator == "ADVISORY"]
        ratio = None if not completion else len(satisfied) / len(completion)
        note = "This is not an official degree audit."
        if blocked:
            note += " One or more requirements need manual review."
        return MajorProgress(
            major=major,
            rule_count=len(completion),
            satisfied_count=len(satisfied),
            unsatisfied_count=len(unsatisfied),
            blocked_count=len(blocked),
            advisory_count=len(advisory),
            counted_courses=tuple(counted),
            remaining=tuple(remaining),
            completion_ratio=ratio,
            has_blocked=bool(blocked),
            automatic_judgment_note=note,
            official_audit=False,
            results=tuple(results),
        )

    def _require_major(self, major: str) -> None:
        if major not in self.list_majors():
            raise UnknownMajor(major)

    def _roots(self, major: str) -> list[dict]:
        rules = [rule for rule in self._load_rules().values() if rule["major"] == major]
        child_ids = {
            item["child_rule_id"]
            for rule in rules
            for item in rule["items"]
            if item["item_type"] == "child_rule"
        }
        return [rule for rule in rules if rule["rule_id"] not in child_ids]

    def _result_shell(self, rule: dict) -> MajorRuleResult:
        status = rule["status"]
        if rule["operator"] == "ADVISORY":
            status = "not_applicable"
        elif status == "blocked":
            status = "blocked"
        else:
            status = "not_evaluated"
        return self._pack(rule, status, None, ())

    def _result_from_engine(self, rule: dict, raw: dict) -> MajorRuleResult:
        return self._pack(rule, raw["status"], raw.get("reason"), tuple(raw.get("counted_courses") or ()))

    def _pack(self, rule: dict, status: str, reason: str | None, counted: tuple[str, ...]) -> MajorRuleResult:
        completion = (
            rule["status"] == "verified"
            and rule["operator"] != "ADVISORY"
            and bool(rule["counts_toward_completion"])
        )
        return MajorRuleResult(
            rule_id=rule["rule_id"],
            legacy_rule_id=rule.get("legacy_rule_id"),
            major=rule["major"],
            category=rule.get("category"),
            operator=rule["operator"],
            status=status,
            counts_toward_completion=completion,
            source_phrase=rule.get("source_phrase"),
            source_page=rule.get("source_page"),
            note=rule.get("note"),
            reason=reason,
            required_count=rule.get("required_count"),
            required_credits=_number(rule.get("required_credits")),
            counted_courses=counted,
            group_label=rule.get("group_label"),
        )

    def _load_catalog(self) -> dict:
        if self._catalog is None:
            aliases: dict[str, set[str]] = {}
            for row in self.database.query("SELECT alias_code, course_id FROM course_aliases"):
                aliases.setdefault(row["course_id"], set()).add(row["alias_code"])
            catalog = {}
            for row in self.database.query("SELECT course_id, units, level FROM courses"):
                course_id = row["course_id"]
                catalog[course_id] = {
                    "units": row["units"],
                    "level": row["level"],
                    "department": "",
                    "aliases": aliases.get(course_id, {course_id}),
                }
                catalog[course_id]["department"] = "".join(
                    character for character in course_id.split("/")[0] if character.isalpha()
                )
            self._catalog = catalog
        return self._catalog

    def _load_rules(self) -> dict[int, dict]:
        if self._rules is None:
            rules = {}
            for row in self.database.query(
                """
                SELECT rule_id, legacy_rule_id, major, category, operator, required_count,
                       required_credits, status, counts_toward_completion, group_label,
                       source_phrase, source_page, note
                FROM major_rules
                ORDER BY rule_id
                """
            ):
                rules[row["rule_id"]] = {
                    **row,
                    "items": [],
                    "constraints": [],
                }
            for item in self.database.query(
                """
                SELECT rule_id, item_type, course_id, child_rule_id, group_name, members,
                       department, units
                FROM major_rule_items
                ORDER BY id
                """
            ):
                rule = rules[item["rule_id"]]
                if item["item_type"] == "group":
                    members = json.loads(item["members"])
                    rule["items"].append(
                        {
                            "item_type": "one_of",
                            "course_ids": members,
                            "group_name": item["group_name"] or "",
                            "department": item["department"],
                            "units": item["units"],
                            "slot_id": members[0],
                        }
                    )
                elif item["item_type"] == "child_rule":
                    rule["items"].append(
                        {"item_type": "child_rule", "child_rule_id": item["child_rule_id"]}
                    )
                else:
                    rule["items"].append(
                        {
                            "item_type": "course",
                            "course_id": item["course_id"],
                            "group_name": item["group_name"] or "",
                            "department": item["department"],
                            "units": item["units"],
                        }
                    )
            for constraint in self.database.query(
                """
                SELECT rule_id, constraint_type, value, group_name, min_level, max_level, department
                FROM major_rule_constraints
                ORDER BY id
                """
            ):
                rules[constraint["rule_id"]]["constraints"].append(
                    {
                        "constraint_type": constraint["constraint_type"],
                        "value": constraint["value"],
                        "group": constraint["group_name"],
                        "min_level": constraint["min_level"],
                        "max_level": constraint["max_level"],
                        "department": constraint["department"],
                    }
                )
            self._rules = rules
        return self._rules
