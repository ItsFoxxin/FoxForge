import copy

import pytest

from foxforge.actor_authorization import ActorAuthorizationError, ActorPolicy, authorize_comment_command
from foxforge.security import child_environment


@pytest.mark.parametrize("value", [None, "", " ", ",", "5,", ",5", "5,,6", "0", "-5", "+5", "5.0", "owner", "٥", "5;6", "9223372036854775808", "5,invalid"])
def test_missing_or_malformed_allowlist_fails_closed(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("FOXFORGE_ALLOWED_GITHUB_USER_IDS", raising=False)
    else:
        monkeypatch.setenv("FOXFORGE_ALLOWED_GITHUB_USER_IDS", value)
    with pytest.raises(ActorAuthorizationError, match="missing or invalid"):
        ActorPolicy.from_env()


def test_multiple_numeric_ids_and_whitespace(monkeypatch):
    monkeypatch.setenv("FOXFORGE_ALLOWED_GITHUB_USER_IDS", " 12345678, 87654321,12345678 ")
    policy = ActorPolicy.from_env()
    assert policy.allowed_ids == frozenset({12345678, 87654321})
    assert policy.allows(12345678) and policy.allows(87654321)
    assert not policy.allows(555) and not policy.allows("12345678") and not policy.allows(True)


@pytest.mark.parametrize("command", ["retry", "resume", "cancel", "future-command"])
def test_comment_authorization_precedes_command_interpretation(command):
    policy = ActorPolicy(frozenset({12345678}))
    unauthorized = {"id": 17, "user": {"id": 999, "login": "owner"}, "body": f"/foxforge {command}"}
    snapshot = copy.deepcopy(unauthorized)
    assert authorize_comment_command(unauthorized, policy) is None
    assert unauthorized == snapshot  # No parsing side effects or state mutation.
    authorized = {**unauthorized, "user": {"id": 12345678, "login": "renamed-owner"}}
    assert authorize_comment_command(authorized, policy) == command


@pytest.mark.parametrize("user", [None, {}, {"id": True}, {"id": "12345678"}, {"id": -1}])
def test_invalid_comment_identity_is_ignored(user):
    assert authorize_comment_command({"user": user, "body": "/foxforge retry"}, ActorPolicy(frozenset({12345678}))) is None


def test_allowlist_is_not_inherited_by_agents(monkeypatch):
    monkeypatch.setenv("FOXFORGE_ALLOWED_GITHUB_USER_IDS", "12345678,87654321")
    assert "FOXFORGE_ALLOWED_GITHUB_USER_IDS" not in child_environment()
