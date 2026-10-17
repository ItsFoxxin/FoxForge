import json
from unittest.mock import MagicMock

import pytest

from foxforge import notifier, reporter_dispatch
from foxforge.state import RunState
from foxforge.state_validator import REQUIRED_AGENTS, expected_reporter_lines, StateValidationError


@pytest.fixture
def report_files(tmp_path):
    state = RunState("run", "task", "foxforge/task", "HEAD", agents_completed=REQUIRED_AGENTS.copy(),
        tests_passed=2, test_exit_code=0, test_counts_verified=True, review_result="PASS", final_status="READY_FOR_PLAYTEST")
    state_path, report_path = tmp_path / "state.json", tmp_path / "report.txt"
    state.save(state_path)
    report_path.write_text("\n".join(expected_reporter_lines(state)), encoding="utf-8")
    return state_path, report_path


def test_dispatch_only_sends_validated_report(report_files, monkeypatch):
    sent = []
    monkeypatch.setattr(reporter_dispatch, "send_discord", lambda message: sent.append(message) or True)
    assert reporter_dispatch.dispatch_report(*report_files)
    assert len(sent) == 1
    report_files[1].write_text("forged")
    with pytest.raises(StateValidationError):
        reporter_dispatch.dispatch_report(*report_files)
    assert len(sent) == 1


def test_invalid_state_rejected_before_dispatch(report_files, monkeypatch):
    state_path, _ = report_files
    content = json.loads(state_path.read_text())
    content["repair_cycles"] = -1
    state_path.write_text(json.dumps(content))
    monkeypatch.setattr(reporter_dispatch, "send_discord", lambda message: pytest.fail("Invalid state sent"))
    with pytest.raises(StateValidationError):
        reporter_dispatch.dispatch_report(*report_files)


def test_discord_payload_disables_mentions(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/fake/fake")
    response = MagicMock()
    response.__enter__.return_value.status = 204
    requests = []
    def send(request, **kwargs):
        requests.append(request)
        return response
    monkeypatch.setattr(notifier.urllib.request, "urlopen", send)
    assert notifier.send_discord("Reporter @everyone")
    assert json.loads(requests[0].data)["allowed_mentions"] == {"parse": []}


def test_discord_timeout_is_failure(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/fake/fake")
    def timeout(*args, **kwargs):
        raise TimeoutError("connection timed out")
    monkeypatch.setattr(notifier.urllib.request, "urlopen", timeout)
    assert not notifier.send_discord("valid")


@pytest.mark.parametrize("url,message", [("not-a-url", "hello"), ("https://example.invalid", "hello"), ("https://discord.com/api/webhooks/fake/fake", "🦊" * 1001)])
def test_invalid_notification_does_not_make_request(monkeypatch, url, message):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", url)
    monkeypatch.setattr(notifier.urllib.request, "urlopen", lambda *a, **k: pytest.fail("Unexpected HTTP request"))
    assert not notifier.send_discord(message)
