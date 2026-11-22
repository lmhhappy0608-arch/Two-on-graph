#!/usr/bin/env python3
"""Evaluate nested major-requirement rules.

Verified rules can return satisfied or unsatisfied. Blocked and partial rules
return a non-decision so they cannot be shown as a finished degree audit.
"""

from __future__ import annotations

from collections import defaultdict


def _course_item(course_id: str, catalog: dict) -> dict:
    meta = catalog.get(course_id)
    if meta is None:
        raise KeyError(course_id)
    return {
        "id": course_id,
        "units": meta["units"],
        "level": meta["level"],
        "department": meta.get("department") or "",
    }


def expand_completed(completed: list[str], catalog: dict) -> set[str]:
    found = set()
    alias_to = {}
    for course_id, meta in catalog.items():
        alias_to[course_id] = course_id
        for alias in meta.get("aliases", ()):
            alias_to[alias] = course_id
    for code in completed:
        key = str(code).upper().replace(" ", "")
        if key in alias_to:
            found.add(alias_to[key])
    return found


def _materialize(item: dict, catalog: dict, completed: set[str]) -> dict | None:
    if item["item_type"] == "course":
        if item["course_id"] not in completed:
            return None
        row = _course_item(item["course_id"], catalog)
        row["group"] = item.get("group_name") or ""
        row["department"] = item.get("department") or row["department"]
        if item.get("units") is not None:
            row["units"] = item["units"]
        return row
    if item["item_type"] == "one_of":
        hits = [course_id for course_id in item["course_ids"] if course_id in completed]
        if not hits:
            return None
        row = _course_item(hits[0], catalog)
        row["id"] = item.get("slot_id") or hits[0]
        row["group"] = item.get("group_name") or ""
        row["department"] = item.get("department") or row["department"]
        if item.get("units") is not None:
            row["units"] = item["units"]
        return row
    raise ValueError(item["item_type"])


def _options(rule: dict, catalog: dict, completed: set[str]) -> list[dict]:
    rows = []
    seen = set()
    for item in rule.get("items", []):
        if item["item_type"] == "child_rule":
            continue
        row = _materialize(item, catalog, completed)
        if row is None or row["id"] in seen:
            continue
        seen.add(row["id"])
        rows.append(row)
    return rows


def _constraint_ok(picked: list[dict], constraints: list[dict], total_count, total_credits) -> bool:
    if total_count is not None and len(picked) < total_count:
        return False
    if total_credits is not None and sum(row["units"] or 0 for row in picked) < total_credits:
        return False
    for constraint in constraints:
        kind = constraint["constraint_type"]
        if kind == "group_min_count":
            count = sum(1 for row in picked if row["group"] == constraint["group"])
            if count < int(constraint["value"]):
                return False
        elif kind == "group_min_credits":
            credits = sum((row["units"] or 0) for row in picked if row["group"] == constraint["group"])
            if credits < int(constraint["value"]):
                return False
        elif kind == "level_min_count":
            count = sum(1 for row in picked if (row["level"] or 0) >= int(constraint["min_level"]))
            if count < int(constraint["value"]):
                return False
        elif kind == "level_min_credits":
            credits = sum(
                (row["units"] or 0)
                for row in picked
                if (row["level"] or 0) >= int(constraint["min_level"])
            )
            if credits < int(constraint["value"]):
                return False
        elif kind == "level_band_min_count":
            count = sum(1 for row in picked if 200 <= (row["level"] or 0) <= 299)
            if count < int(constraint["value"]):
                return False
        elif kind == "department_min_count":
            count = sum(
                1
                for row in picked
                if row["group"] == constraint.get("group", row["group"])
                and row["department"] == constraint["department"]
            )
            if count < int(constraint["value"]):
                return False
        else:
            raise ValueError(kind)
    return True


def _add_state(state: tuple, row: dict) -> tuple:
    count, credits, level_count, level_credits, band200, groups = state
    credits += int(row["units"] or 0)
    count += 1
    level = row["level"] or 0
    if level >= 300:
        level_count += 1
        level_credits += int(row["units"] or 0)
    if 200 <= level <= 299:
        band200 += 1
    group_name = row["group"]
    group_count, group_credits, departments = groups.get(group_name, (0, 0, frozenset()))
    departments = departments | {row["department"]}
    groups = dict(groups)
    groups[group_name] = (group_count + 1, group_credits + int(row["units"] or 0), departments)
    return (count, credits, level_count, level_credits, band200, groups)


def _state_ok(state: tuple, rule: dict) -> bool:
    count, credits, level_count, level_credits, band200, groups = state
    if rule.get("required_count") is not None and count < rule["required_count"]:
        return False
    if rule.get("required_credits") is not None and credits < rule["required_credits"]:
        return False
    for constraint in rule.get("constraints") or []:
        kind = constraint["constraint_type"]
        group_count, group_credits, departments = groups.get(constraint.get("group"), (0, 0, frozenset()))
        if kind == "group_min_count" and group_count < int(constraint["value"]):
            return False
        if kind == "group_min_credits" and group_credits < int(constraint["value"]):
            return False
        if kind == "level_min_count" and level_count < int(constraint["value"]):
            return False
        if kind == "level_min_credits" and level_credits < int(constraint["value"]):
            return False
        if kind == "level_band_min_count":
            if int(constraint.get("min_level") or 0) != 200:
                raise ValueError("only the 200-level band is counted")
            if band200 < int(constraint["value"]):
                return False
        if kind == "department_min_count":
            if int(constraint["value"]) != 1:
                raise ValueError("department minimum above 1 needs a counted state")
            if constraint["department"] not in departments:
                return False
    return True


def _enumerate_states(options: list[dict]) -> list[tuple]:
    states = [(0, 0, 0, 0, 0, {})]
    for row in options:
        states.extend(_add_state(state, row) for state in list(states))
    return states


def _subset_exists(options: list[dict], rule: dict) -> bool:
    if len(options) <= 12:
        return any(_state_ok(state, rule) for state in _enumerate_states(options))
    split = len(options) // 2
    left = _enumerate_states(options[:split])
    right = _enumerate_states(options[split:])
    for first in left:
        for second in right:
            groups = dict(first[5])
            for name, (count, credits, departments) in second[5].items():
                old_count, old_credits, old_departments = groups.get(name, (0, 0, frozenset()))
                groups[name] = (old_count + count, old_credits + credits, old_departments | departments)
            combined = (
                first[0] + second[0],
                first[1] + second[1],
                first[2] + second[2],
                first[3] + second[3],
                first[4] + second[4],
                groups,
            )
            if _state_ok(combined, rule):
                return True
    return False


def _gap(options: list[dict], rule: dict) -> str:
    if rule.get("required_count") is not None:
        have = len(options)
        need = rule["required_count"]
        if have < need:
            return f"Complete {need - have} more course(s)"
    if rule.get("required_credits") is not None:
        have = sum(int(row["units"] or 0) for row in options)
        need = rule["required_credits"]
        if have < need:
            return f"Complete {need - have} more credit(s)"
    for constraint in rule.get("constraints") or []:
        kind = constraint["constraint_type"]
        if kind == "group_min_count":
            have = sum(1 for row in options if row["group"] == constraint["group"])
            if have < int(constraint["value"]):
                return f"Complete {int(constraint['value']) - have} more course(s) from {constraint['group']}"
        elif kind == "group_min_credits":
            have = sum(int(row["units"] or 0) for row in options if row["group"] == constraint["group"])
            if have < int(constraint["value"]):
                return f"Complete {int(constraint['value']) - have} more credit(s) from {constraint['group']}"
        elif kind == "level_min_count":
            have = sum(1 for row in options if (row["level"] or 0) >= int(constraint["min_level"]))
            if have < int(constraint["value"]):
                return f"Complete {int(constraint['value']) - have} more course(s) at the {constraint['min_level']} level or above"
        elif kind == "level_band_min_count":
            have = sum(1 for row in options if 200 <= (row["level"] or 0) <= 299)
            if have < int(constraint["value"]):
                return f"Complete {int(constraint['value']) - have} more course(s) at the 200 level"
        elif kind == "level_min_credits":
            have = sum(
                int(row["units"] or 0)
                for row in options
                if (row["level"] or 0) >= int(constraint["min_level"])
            )
            if have < int(constraint["value"]):
                return f"Complete {int(constraint['value']) - have} more credit(s) at the {constraint['min_level']} level or above"
        elif kind == "department_min_count":
            have = sum(
                1
                for row in options
                if row["department"] == constraint["department"]
                and row["group"] == constraint.get("group", row["group"])
            )
            if have < int(constraint["value"]):
                group = constraint.get('group', '')
                prefix = f"{group}: " if group else ""
                return f"{prefix}complete {int(constraint['value']) - have} more {constraint['department']} course(s)"
    return "The selected courses do not satisfy the group, level, or department constraints"


def evaluate(rule: dict, completed: list[str], catalog: dict, rules_by_id: dict | None = None) -> dict:
    status = rule.get("status")
    if status == "blocked":
        return {
            "status": "blocked",
            "reason": "This requirement needs manual review",
            "counted_courses": [],
        }
    if status != "verified":
        return {
            "status": "not_verified",
            "reason": "This requirement has not been verified and cannot be evaluated automatically.",
            "counted_courses": [],
        }
    if rule.get("operator") == "ADVISORY":
        return {
            "status": "not_applicable",
            "reason": "This is an advisory course list and does not count toward major completion.",
            "counted_courses": [],
        }
    done = expand_completed(completed, catalog)
    if rule.get("operator") == "ANY":
        failures = []
        for item in rule.get("items", []):
            child = rules_by_id[item["child_rule_id"]]
            result = evaluate(child, completed, catalog, rules_by_id)
            if result["status"] == "satisfied":
                result["selected_option"] = child.get("group_label") or child.get("note")
                return result
            failures.append(result.get("reason") or child.get("group_label"))
        return {
            "status": "unsatisfied",
            "reason": "Courses do not satisfy one concentration",
            "detail": failures,
            "counted_courses": [],
        }
    if rule.get("operator") == "ALL" and any(item["item_type"] == "child_rule" for item in rule.get("items", [])):
        counted = []
        for item in rule["items"]:
            if item["item_type"] != "child_rule":
                continue
            child = rules_by_id[item["child_rule_id"]]
            result = evaluate(child, completed, catalog, rules_by_id)
            if result["status"] != "satisfied":
                return result
            counted.extend(result["counted_courses"])
        return {"status": "satisfied", "reason": "", "counted_courses": counted}
    options = _options(rule, catalog, done)
    if _subset_exists(options, rule):
        return {
            "status": "satisfied",
            "reason": "",
            "counted_courses": [row["id"] for row in options],
        }
    return {
        "status": "unsatisfied",
        "reason": _gap(options, rule),
        "counted_courses": [row["id"] for row in options],
    }


def has_cycle(rules: list[dict]) -> bool:
    children = defaultdict(list)
    for rule in rules:
        for item in rule.get("items", []):
            if item["item_type"] == "child_rule":
                children[rule["rule_id"]].append(item["child_rule_id"])
    visiting = set()
    visited = set()

    def walk(rule_id: int) -> bool:
        if rule_id in visiting:
            return True
        if rule_id in visited:
            return False
        visiting.add(rule_id)
        for child in children.get(rule_id, []):
            if walk(child):
                return True
        visiting.remove(rule_id)
        visited.add(rule_id)
        return False

    return any(walk(rule["rule_id"]) for rule in rules)
