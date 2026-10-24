"""Strict planning contract; plans describe work but never grant authority."""

from __future__ import annotations

import json
import re

from .capabilities import get_capability


MAX_PLAN_BYTES = 256 * 1024
MAX_SUBTASKS = 24
PLAN_FIELDS = {"schema_version", "summary", "acceptance_criteria", "assumptions", "unknowns", "subtasks"}
SUBTASK_FIELDS = {"id", "title", "description", "capability", "depends_on", "acceptance_criteria", "owned_paths", "validation"}


class PlanValidationError(ValueError):
    pass


def _strings(value, name: str, *, maximum: int = 64, item_limit: int = 2000) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise PlanValidationError(f"Invalid {name}")
    if any(not isinstance(item, str) or not item.strip() or len(item) > item_limit or "\0" in item for item in value):
        raise PlanValidationError(f"Invalid {name}")
    return value


def validate_plan(value) -> dict:
    if not isinstance(value, dict) or set(value) != PLAN_FIELDS or type(value.get("schema_version")) is not int or value.get("schema_version") != 1:
        raise PlanValidationError("Plan must match schema version 1")
    if not isinstance(value["summary"], str) or not value["summary"].strip() or len(value["summary"]) > 4000:
        raise PlanValidationError("Invalid plan summary")
    criteria = _strings(value["acceptance_criteria"], "acceptance criteria", maximum=32)
    if not criteria:
        raise PlanValidationError("Plan requires acceptance criteria")
    _strings(value["assumptions"], "assumptions", maximum=32)
    _strings(value["unknowns"], "unknowns", maximum=32)
    subtasks = value["subtasks"]
    if not isinstance(subtasks, list) or not 1 <= len(subtasks) <= MAX_SUBTASKS:
        raise PlanValidationError("Plan requires a bounded non-empty subtask list")
    identifiers: set[str] = set()
    for task in subtasks:
        if not isinstance(task, dict) or set(task) != SUBTASK_FIELDS:
            raise PlanValidationError("Subtask fields do not match schema")
        ident = task["id"]
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", ident) or ident in identifiers:
            raise PlanValidationError("Invalid or duplicate subtask ID")
        identifiers.add(ident)
        for field in ("title", "description"):
            if not isinstance(task[field], str) or not task[field].strip() or len(task[field]) > 4000:
                raise PlanValidationError(f"Invalid subtask {field}")
        if not isinstance(task["capability"], str):
            raise PlanValidationError("Invalid capability ID")
        try:
            get_capability(task["capability"])
        except ValueError as exc:
            raise PlanValidationError(str(exc)) from None
        _strings(task["depends_on"], "dependencies", maximum=MAX_SUBTASKS, item_limit=48)
        linked = _strings(task["acceptance_criteria"], "subtask acceptance criteria", maximum=32)
        if any(item not in criteria for item in linked):
            raise PlanValidationError("Subtask references unknown acceptance criteria")
        _strings(task["owned_paths"], "owned paths", maximum=64, item_limit=512)
        _strings(task["validation"], "validation", maximum=32)
    graph = {task["id"]: task["depends_on"] for task in subtasks}
    if any(dep not in identifiers or dep == ident for ident, deps in graph.items() for dep in deps):
        raise PlanValidationError("Subtask dependency is missing or self-referential")
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(node: str) -> None:
        if node in visiting:
            raise PlanValidationError("Subtask dependency graph contains a cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)
    for node in graph:
        visit(node)
    return value


def parse_plan(text: str) -> dict:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_PLAN_BYTES:
        raise PlanValidationError("Plan response is too large")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PlanValidationError("Duplicate JSON key in plan")
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=unique)
    except (json.JSONDecodeError, RecursionError):
        raise PlanValidationError("Plan response is not valid JSON") from None
    return validate_plan(value)
