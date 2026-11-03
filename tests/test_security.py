import os
import subprocess

import pytest

from foxforge import security
from foxforge.security import child_environment, redact, register_secret
from foxforge.state import RunState


@pytest.mark.parametrize("name", ["FOXFORGE_GITHUB_APP_ID", "FOXFORGE_GITHUB_INSTALLATION_ID", "FOXFORGE_GITHUB_PRIVATE_KEY", "FOXFORGE_PLANNER_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "GIT_ASKPASS", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_VALUE_0", "GIT_TRACE_CURL", "SSH_AUTH_SOCK", "DISCORD_WEBHOOK_URL", "_FOXFORGE_INSTALLATION_TOKEN"])
def test_child_environment_strips_authentication(name, monkeypatch):
    monkeypatch.setenv(name, "credential-must-not-be-inherited")
    env = child_environment()
    assert env.get(name) != "credential-must-not-be-inherited"
    assert os.environ[name] == "credential-must-not-be-inherited"


def test_registered_credentials_and_pem_are_redacted():
    register_secret("installation-secret-for-tests")
    text = "installation-secret-for-tests\n-----BEGIN " + "PRIVATE KEY-----\nexample\n-----END " + "PRIVATE KEY-----"
    output = redact(text)
    assert "installation-secret" not in output and "example" not in output
    assert "REDACTED" in output


def test_planner_api_key_environment_value_is_redacted(monkeypatch):
    monkeypatch.setenv("FOXFORGE_PLANNER_API_KEY", "planner-secret-for-tests")
    assert "planner-secret" not in redact("value=planner-secret-for-tests")


def test_runstate_refuses_to_persist_credentials(tmp_path):
    register_secret("installation-secret-for-tests")
    state = RunState("run", "installation-secret-for-tests", "feature", "HEAD")
    with pytest.raises(ValueError, match="credential"):
        state.save(tmp_path / "state.json")
    assert not (tmp_path / "state.json").exists()


def test_private_key_inside_target_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("FOXFORGE_GITHUB_PRIVATE_KEY", str(tmp_path / "private.pem"))
    with pytest.raises(ValueError, match="outside"):
        security.ensure_key_outside_repo(tmp_path)
