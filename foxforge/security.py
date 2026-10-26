"""Keep publishing credentials out of model/test children and persisted text."""

from __future__ import annotations

import os
import re
from pathlib import Path


_secrets: set[str] = set()
_TOKEN = re.compile(r"(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+|freellmapi-[A-Za-z0-9_-]+|sk-cp-[A-Za-z0-9_-]+)")
_PEM = re.compile(r"-----BEGIN (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----.*?(?:-----END (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----|\Z)", re.DOTALL)


def register_secret(value: str) -> None:
    if value:
        _secrets.add(value)


def redact(text: str) -> str:
    values = set(_secrets)
    for name, value in os.environ.items():
        upper = name.upper()
        if value and len(value) >= 8 and (
            upper in {"DISCORD_WEBHOOK_URL", "GITHUB_TOKEN", "GH_TOKEN", "FOXFORGE_GITHUB_PRIVATE_KEY"}
            or upper.endswith("_TOKEN") or upper.endswith("_API_KEY") or upper.startswith("GIT_CONFIG_VALUE_")
        ):
            values.add(value)
    for value in sorted(values, key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    return _TOKEN.sub("[REDACTED]", _PEM.sub("[REDACTED PRIVATE KEY]", text))


def child_environment() -> dict[str, str]:
    """Fresh environment; never mutate os.environ with installation tokens."""
    blocked = ("FOXFORGE_GITHUB_", "FOXFORGE_PLANNER_", "_FOXFORGE_", "GITHUB_", "GH_", "GIT_", "GCM_")
    env = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(blocked)
        and key.upper() not in {"FOXFORGE_ALLOWED_GITHUB_USER_IDS", "FOXFORGE_PLANNER_API_KEY", "DISCORD_WEBHOOK_URL", "SSH_ASKPASS", "SSH_AUTH_SOCK", "SSH_AGENT_PID", "BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "CDPATH", "PROMPT_COMMAND", "PS4", "SSLKEYLOGFILE"}
    }
    # Do not let an agent's Git subprocess use host credential helpers implicitly.
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    return env


def ensure_key_outside_repo(repo: Path) -> None:
    configured = os.getenv("FOXFORGE_GITHUB_PRIVATE_KEY")
    if configured:
        path = Path(configured).expanduser()
        lexical = Path(os.path.abspath(path))
        if lexical.is_relative_to(repo.resolve()) or path.resolve().is_relative_to(repo.resolve()):
            raise ValueError("The GitHub App private key must be outside the target repository")


def require_execution_worker() -> None:
    """Reject legacy execution in the supported control-plane image.

    This deployment-mode guard supplements the restricted entrypoint and mounts;
    it is not a sandbox against an administrator who changes the image/environment.
    An absent variable preserves the existing opt-in venv execution workflow.
    """
    if "FOXFORGE_CONTROL_PLANE_ONLY" in os.environ:
        raise RuntimeError("Legacy execution requires a separate authorized worker; control-plane mode forbids it")
