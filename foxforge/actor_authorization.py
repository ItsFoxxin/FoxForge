"""Fail-closed GitHub actor policy. Usernames never grant authorization."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re

from .issue_tasks import IssueError


ALLOWLIST_ENV = "FOXFORGE_ALLOWED_GITHUB_USER_IDS"


class ActorAuthorizationError(IssueError):
    pass


def valid_user_id(value) -> bool:
    return type(value) is int and 0 < value <= 2**63 - 1


@dataclass(frozen=True)
class ActorPolicy:
    allowed_ids: frozenset[int]

    def __post_init__(self):
        if not isinstance(self.allowed_ids, frozenset) or not self.allowed_ids or any(not valid_user_id(value) for value in self.allowed_ids):
            raise ActorAuthorizationError("GitHub actor allowlist is missing or invalid")

    @classmethod
    def from_env(cls) -> "ActorPolicy":
        raw = os.environ.get(ALLOWLIST_ENV)
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 16384:
            raise ActorAuthorizationError("GitHub actor allowlist is missing or invalid")
        values = raw.split(",")
        if any(not re.fullmatch(r"[0-9]{1,19}", item.strip()) for item in values):
            raise ActorAuthorizationError("GitHub actor allowlist is missing or invalid")
        ids = frozenset(int(item.strip()) for item in values)
        if not ids or any(not valid_user_id(value) for value in ids):
            raise ActorAuthorizationError("GitHub actor allowlist is missing or invalid")
        return cls(ids)

    def allows(self, user_id) -> bool:
        return valid_user_id(user_id) and user_id in self.allowed_ids

    def require(self, user_id) -> None:
        if not self.allows(user_id):
            # No external prose, username, body or configuration value is logged.
            raise ActorAuthorizationError("UNAUTHORIZED_GITHUB_ACTOR")


def authorize_comment_command(comment, policy: ActorPolicy) -> str | None:
    """Authorization gate for future dispatchers; this NEVER executes commands.

    Check the server-returned comment user ID before even interpreting its body.
    Current intake does not dispatch comment commands. Future retry/resume/cancel
    handlers must use this gate and retain their own deterministic safety gates.
    """
    if not isinstance(comment, dict) or not isinstance(comment.get("user"), dict):
        return None
    if not policy.allows(comment["user"].get("id")):
        return None
    body = comment.get("body")
    if not isinstance(body, str):
        return None
    match = re.fullmatch(r"\s*/foxforge ([a-z][a-z0-9-]*)\s*", body)
    return match[1] if match else None
