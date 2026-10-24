"""Operator configuration. External content cannot alter this policy."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from .security import register_secret


class ConfigurationError(ValueError):
    pass


def secret(name: str) -> str:
    value, filename = os.getenv(name), os.getenv(name + "_FILE")
    if value is not None and filename:
        raise ConfigurationError(f"Use only {name} or {name}_FILE")
    if filename:
        path = Path(filename)
        if not path.is_absolute() or not path.is_file() or path.stat().st_size > 16384:
            raise ConfigurationError(f"Check {name}_FILE: expected a readable absolute file path")
        private_file(path)
        value = path.read_text(encoding="utf-8").strip()
    if not value or value.startswith("REPLACE_") or len(value) > 16384 or any(ch.isspace() for ch in value):
        raise ConfigurationError(f"Missing or malformed {name}; use a protected file")
    register_secret(value)
    return value


def private_file(path: Path) -> None:
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o137:
        raise ConfigurationError("Credential file is accessible to other users; require 0600 or 0640")


def directory(name: str) -> Path:
    raw = os.getenv(name)
    if not raw or not Path(raw).is_absolute():
        raise ConfigurationError(f"{name} must name an explicit absolute existing directory")
    path = Path(raw)
    if path.is_symlink() or not path.is_dir():
        raise ConfigurationError(f"{name} directory is missing or is a symlink; provision it explicitly")
    return path.resolve()


@dataclass(frozen=True)
class ModelPolicy:
    task_type: str
    models: tuple[str, ...]
    providers: tuple[str, ...]
    max_requests: int = 1
    max_retries: int = 0
    max_output_tokens: int = 8000
    max_input_bytes: int = 300000
    max_reserved_tokens: int = 310000
    timeout_seconds: int = 120

    @classmethod
    def from_env(cls, task_type: str = "development.plan") -> "ModelPolicy":
        filename = os.getenv("FOXFORGE_MODEL_POLICY_FILE", "")
        try:
            path = Path(filename)
            if not path.is_absolute() or path.stat().st_size > 65536:
                raise ValueError
            value = json.loads(path.read_text(encoding="utf-8"))
            if set(value) != {"schema_version", "tasks"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
                raise ValueError
            row = value["tasks"][task_type]
            fields = {"models", "providers", "max_requests", "max_retries", "max_output_tokens", "max_input_bytes", "max_reserved_tokens", "timeout_seconds"}
            if set(row) != fields:
                raise ValueError
            for name in ("models", "providers"):
                if not isinstance(row[name], list) or not 1 <= len(row[name]) <= 32:
                    raise ValueError
                if any(not isinstance(s, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", s) or s.startswith("REPLACE_") for s in row[name]):
                    raise ValueError
            bounds = {"max_requests": (1, 3), "max_retries": (0, 2), "max_output_tokens": (256, 8000),
                      "max_input_bytes": (1024, 524288), "max_reserved_tokens": (1024, 1600000), "timeout_seconds": (1, 120)}
            if any(type(row[k]) is not int or not lo <= row[k] <= hi for k, (lo, hi) in bounds.items()):
                raise ValueError
            if row["max_retries"] >= row["max_requests"]:
                raise ValueError
            return cls(task_type, tuple(row.pop("models")), tuple(row.pop("providers")), **row)
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            raise ConfigurationError("Invalid FOXFORGE_MODEL_POLICY_FILE; provide the versioned task policy with bounded limits") from None


@dataclass(frozen=True)
class PlannerConfig:
    base_url: str
    model: str
    key: str = field(repr=False)

    @classmethod
    def from_env(cls, policy: ModelPolicy) -> "PlannerConfig":
        base = os.getenv("FOXFORGE_PLANNER_BASE_URL", "").rstrip("/")
        model = os.getenv("FOXFORGE_PLANNER_MODEL", "")
        try:
            url = urlsplit(base)
            _ = url.port
            if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
                    or url.query or url.fragment or not url.path.endswith("/v1") or any(ord(c) < 33 for c in base)):
                raise ValueError
            http_hosts = {"127.0.0.1", "localhost", "::1"}
            # An explicit host exception is needed for private container networking.
            http_hosts.update(s.strip() for s in os.getenv("FOXFORGE_PLANNER_HTTP_HOSTS", "").split(",") if s.strip())
            if url.scheme == "http" and url.hostname not in http_hosts:
                raise ValueError
            if model not in policy.models or model.casefold() in {"auto", "fusion"}:
                raise ValueError
        except ValueError:
            raise ConfigurationError("Planner endpoint or model is not authorized by the task policy") from None
        return cls(base, model, secret("FOXFORGE_PLANNER_API_KEY"))
