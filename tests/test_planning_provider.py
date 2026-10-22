import json

import pytest

from foxforge import planning_provider
from foxforge.planning_provider import PlanningProviderError, request_plan


PLAN = {"schema_version": 1, "summary": "Inspect first.", "acceptance_criteria": ["Known."],
        "assumptions": [], "unknowns": [],
        "subtasks": [{"id": "inspect", "title": "Inspect", "description": "Read the repository.",
                      "capability": "repository.discovery", "depends_on": [],
                      "acceptance_criteria": ["Known."], "owned_paths": [], "validation": ["Review evidence."]}]}


class Response:
    headers = {"X-Routed-Via": "test-provider/test-model"}
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, size):
        return json.dumps({"choices": [{"message": {"content": json.dumps(PLAN)}}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 20}}).encode()


class Opener:
    def __init__(self, calls): self.calls = calls
    def open(self, req, timeout):
        self.calls.append((req, timeout))
        return Response()


def test_openai_compatible_plan_is_validated(monkeypatch):
    calls = []
    monkeypatch.setenv("FOXFORGE_PLANNER_BASE_URL", "http://127.0.0.1:3001/v1")
    monkeypatch.setenv("FOXFORGE_PLANNER_API_KEY", "synthetic-planner-key")
    monkeypatch.setenv("FOXFORGE_PLANNER_MODEL", "tested-model")
    monkeypatch.setattr(planning_provider.request, "build_opener", lambda *handlers: Opener(calls))
    plan, telemetry = request_plan(requirement="Plan it", discovery_context="{}", timeout=9)
    assert plan == PLAN and telemetry["routed_via"] == "test-provider/test-model"
    req, timeout = calls[0]
    assert req.full_url == "http://127.0.0.1:3001/v1/chat/completions" and timeout == 9
    body = json.loads(req.data)
    assert "tools" not in body and body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 8000 and body["temperature"] == 0


def test_plain_http_remote_endpoint_is_rejected_before_request(monkeypatch):
    monkeypatch.setenv("FOXFORGE_PLANNER_BASE_URL", "http://planner.example/v1")
    monkeypatch.setenv("FOXFORGE_PLANNER_API_KEY", "synthetic-planner-key")
    monkeypatch.setenv("FOXFORGE_PLANNER_MODEL", "tested-model")
    monkeypatch.setattr(planning_provider.request, "build_opener", lambda *handlers: pytest.fail("network attempted"))
    with pytest.raises(PlanningProviderError):
        request_plan(requirement="Plan it", discovery_context="{}")
