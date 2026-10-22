import copy
import json
from pathlib import Path

import pytest

from foxforge.plan_schema import PlanValidationError, parse_plan, validate_plan


def valid_plan():
    return {"schema_version": 1, "summary": "Make the smallest safe change.",
            "acceptance_criteria": ["The behavior is verified."], "assumptions": [], "unknowns": [],
            "subtasks": [{"id": "inspect", "title": "Inspect", "description": "Inspect existing behavior.",
                          "capability": "repository.discovery", "depends_on": [],
                          "acceptance_criteria": ["The behavior is verified."], "owned_paths": [],
                          "validation": ["Confirm relevant files were found."]}]}


def test_accepts_one_node_plan():
    assert validate_plan(valid_plan())["subtasks"][0]["id"] == "inspect"


@pytest.mark.parametrize("change", ["cycle", "unknown", "extra", "duplicate"])
def test_rejects_unsafe_or_ambiguous_plans(change):
    value = valid_plan()
    if change == "cycle":
        value["subtasks"][0]["depends_on"] = ["inspect"]
        text = json.dumps(value)
    elif change == "unknown":
        value["subtasks"][0]["capability"] = "infrastructure.destroy"
        text = json.dumps(value)
    elif change == "extra":
        value["permission"] = "admin"
        text = json.dumps(value)
    else:
        text = json.dumps(value)[:-1] + ',"summary":"override"}'
    with pytest.raises(PlanValidationError):
        parse_plan(text)


def test_rejects_missing_acceptance_reference():
    value = copy.deepcopy(valid_plan())
    value["subtasks"][0]["acceptance_criteria"] = ["invented"]
    with pytest.raises(PlanValidationError):
        validate_plan(value)


def test_packaged_example_matches_schema():
    path = Path(__file__).resolve().parents[1] / "examples" / "planning" / "plan.example.json"
    assert parse_plan(path.read_text(encoding="utf-8"))["schema_version"] == 1
