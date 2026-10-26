import json

import pytest

from foxforge import planning_provider
from foxforge.planning_provider import PlanningProviderError, request_plan
from foxforge.configuration import ConfigurationError
from foxforge.control_plane import ControlPlane


PLAN = {"schema_version": 1, "summary": "Inspect first.", "acceptance_criteria": ["Known."],
        "assumptions": [], "unknowns": [],
        "subtasks": [{"id": "inspect", "title": "Inspect", "description": "Read the repository.",
                      "capability": "repository.discovery", "depends_on": [],
                      "acceptance_criteria": ["Known."], "owned_paths": [], "validation": ["Review evidence."]}]}


class Response:
    headers = {"X-Routed-Via": "test-provider/tested-model"}
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


@pytest.fixture
def planner(tmp_path, monkeypatch):
    from foxforge.configuration import ModelPolicy
    monkeypatch.setattr(ModelPolicy, "from_env", classmethod(lambda cls: ModelPolicy("development.plan", ("tested-model",), ("test-provider",))))
    monkeypatch.setenv("FOXFORGE_PLANNER_BASE_URL", "http://127.0.0.1:3001/v1")
    monkeypatch.setenv("FOXFORGE_PLANNER_API_KEY", "synthetic-planner-key")
    monkeypatch.setenv("FOXFORGE_PLANNER_MODEL", "tested-model")
    store = ControlPlane(tmp_path / "data" / "foxforge.db")
    project = store.register_project(repository_id=1, repository="owner/repo", local_path=tmp_path, default_branch="dev")
    task, _ = store.authorize_and_create_task(project, {"number": 1, "revision": "a" * 64}, actor_id=1, event_id=1)
    store.update_task(task["id"], state="active", activity="planning")
    return {"store": store, "task_id": task["id"]}


def test_openai_compatible_plan_is_validated(monkeypatch, planner):
    calls = []
    monkeypatch.setenv("FOXFORGE_PLANNER_BASE_URL", "http://127.0.0.1:3001/v1")
    monkeypatch.setenv("FOXFORGE_PLANNER_API_KEY", "synthetic-planner-key")
    monkeypatch.setenv("FOXFORGE_PLANNER_MODEL", "tested-model")
    monkeypatch.setattr(planning_provider.request, "build_opener", lambda *handlers: Opener(calls))
    plan, telemetry = request_plan(requirement="Plan it", discovery_context="{}", timeout=9, **planner)
    assert plan == PLAN and telemetry["routed_via"] == "test-provider/tested-model"
    req, timeout = calls[0]
    assert req.full_url == "http://127.0.0.1:3001/v1/chat/completions" and timeout == 9
    body = json.loads(req.data)
    assert "tools" not in body and body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 8000 and body["temperature"] == 0


def test_plain_http_remote_endpoint_is_rejected_before_request(monkeypatch, planner):
    monkeypatch.setenv("FOXFORGE_PLANNER_BASE_URL", "http://planner.example/v1")
    monkeypatch.setenv("FOXFORGE_PLANNER_API_KEY", "synthetic-planner-key")
    monkeypatch.setenv("FOXFORGE_PLANNER_MODEL", "tested-model")
    monkeypatch.setattr(planning_provider.request, "build_opener", lambda *handlers: pytest.fail("network attempted"))
    with pytest.raises(ConfigurationError):
        request_plan(requirement="Plan it", discovery_context="{}", **planner)


@pytest.mark.parametrize("status,code", [(401, "authentication_failed"), (429, "rate_limited"), (503, "unavailable"), (404, "unavailable")])
def test_gateway_failures_are_durable_and_no_retry_by_default(monkeypatch, planner, status, code):
    from urllib.error import HTTPError
    calls = []
    class Failed:
        def open(self, *args, **kwargs):
            calls.append(1)
            raise HTTPError("http://gateway/v1", status, "secret must not be echoed", {"Retry-After": "60"}, None)
    monkeypatch.setattr(planning_provider.request, "build_opener", lambda *handlers: Failed())
    with pytest.raises(PlanningProviderError, match=code):
        request_plan(requirement="Plan it", discovery_context="{}", **planner)
    with planner["store"].connect() as db:
        assert db.execute("SELECT outcome FROM model_requests").fetchone()[0] == code
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["route", "tool", "invalid_json", "unknown_capability", "secret", "oversized"])
def test_untrusted_gateway_responses_fail_closed(monkeypatch, planner, kind):
    class BadResponse(Response):
        headers = {"X-Routed-Via": "unapproved/model"} if kind == "route" else Response.headers
        def read(self, size):
            if kind == "oversized":
                return b"x" * size
            plan = json.loads(json.dumps(PLAN))
            if kind == "unknown_capability":
                plan["subtasks"][0]["capability"] = "infrastructure.root"
            if kind == "secret":
                plan["summary"] = "synthetic-planner-key"
            msg = {"content": "not-json" if kind == "invalid_json" else json.dumps(plan)}
            if kind == "tool":
                msg["tool_calls"] = [{"function": {"name": "shell"}}]
            return json.dumps({"choices": [{"message": msg}]}).encode()
    class BadOpener:
        def open(self, *a, **k): return BadResponse()
    monkeypatch.setattr(planning_provider.request, "build_opener", lambda *handlers: BadOpener())
    with pytest.raises(PlanningProviderError):
        request_plan(requirement="Plan it", discovery_context="{}", **planner)
    with planner["store"].connect() as db:
        assert db.execute("SELECT outcome FROM model_requests").fetchone()[0] != "succeeded"


def test_timeout_and_budget_prevent_repeated_requests(monkeypatch, planner):
    class TimedOut:
        def open(self, *a, **k): raise TimeoutError("synthetic-planner-key")
    monkeypatch.setattr(planning_provider.request, "build_opener", lambda *handlers: TimedOut())
    with pytest.raises(PlanningProviderError, match="timeout"):
        request_plan(requirement="Plan it", discovery_context="{}", **planner)
    from foxforge.control_plane import ControlPlaneError
    with pytest.raises(ControlPlaneError, match="budget"):
        request_plan(requirement="Plan it", discovery_context="{}", **planner)
