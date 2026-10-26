"""Actionable, secret-free diagnostics. No inference or database creation."""

import argparse
import json
import os
from pathlib import Path
import stat

from .actor_authorization import ActorPolicy
from .configuration import ModelPolicy, PlannerConfig, directory, private_file
from .control_plane import data_root
from .github_app import AppConfig
from .storage_ops import inspect_database


def legacy_locations() -> list[Path]:
    locations = [Path.home() / ".foxforge" / "control-plane", Path("/var/lib/foxforge/control-plane")]
    if os.getenv("LOCALAPPDATA"):
        locations.append(Path(os.environ["LOCALAPPDATA"]) / "FoxForge" / "control-plane")
    return [path.resolve() for path in locations if (path / "foxforge.db").is_file()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only FoxForge installation checks; no model calls")
    parser.add_argument("--gateway", action="store_true", help="Explicit authenticated GET /v1/models (no inference)")
    parser.add_argument("--require-mounts", action="store_true", help="Require data, repository and config mount points")
    args = parser.parse_args(argv)
    checks = []

    def check(name, operation, remedy):
        try:
            operation()
        except Exception:
            checks.append({"check": name, "ok": False, "remedy": remedy})
        else:
            checks.append({"check": name, "ok": True})

    def github_key():
        config = AppConfig.from_env()
        private_file(config.private_key)
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
        key = load_pem_private_key(config.private_key.read_bytes(), password=None)
        if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
            raise ValueError

    def writable_root():
        path = data_root()
        if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            raise ValueError
        if os.name != "nt" and (path.stat().st_uid != os.geteuid() or stat.S_IMODE(path.stat().st_mode) & 0o007):
            raise ValueError

    def conflicts():
        if any(p != data_root() for p in legacy_locations()):
            raise ValueError

    def repositories():
        path = directory("FOXFORGE_REPOS_DIR")
        if not os.access(path, os.R_OK | os.X_OK):
            raise ValueError

    check("data_directory", writable_root, "Set FOXFORGE_DATA_DIR to the intended existing absolute directory; fix owner and restrict permissions (0750 or 0700).")
    check("database", lambda: inspect_database(data_root() / "foxforge.db"), "Verify the intended database using storage verify; run storage init only for an intentional new installation.")
    check("conflicting_state", conflicts, "Multiple known state directories contain databases. Back up and inspect each; never merge or overwrite them. Quarantine unused copies after selecting the authoritative state.")
    check("github_app_and_key", github_key, "Set FOXFORGE_GITHUB_APP_ID, FOXFORGE_GITHUB_INSTALLATION_ID (positive numeric IDs), FOXFORGE_GITHUB_PRIVATE_KEY (absolute readable RSA PEM path, 0600/0640).")
    check("github_approvers", ActorPolicy.from_env, "Set FOXFORGE_ALLOWED_GITHUB_USER_IDS to comma-separated positive numeric user IDs.")
    check("repository_storage", repositories, "Set FOXFORGE_REPOS_DIR to the existing clone directory, readable by the service UID; container mount must be read-only.")
    check("planner", lambda: PlannerConfig.from_env(ModelPolicy.from_env()), "Set FOXFORGE_PLANNER_BASE_URL, FOXFORGE_PLANNER_MODEL, FOXFORGE_MODEL_POLICY_FILE and FOXFORGE_PLANNER_API_KEY_FILE. Use the exact variable names in deployment/container.env.example.")
    if args.require_mounts:
        def mounts():
            for path in (data_root(), directory("FOXFORGE_REPOS_DIR"), directory("FOXFORGE_CONFIG_DIR")):
                if not path.is_mount():
                    raise ValueError
        check("persistent_mounts", mounts, "Mount data and repositories at their configured paths and /etc/foxforge read-only; do not run against the image filesystem.")
    if args.gateway:
        from .planning_provider import probe_gateway
        check("gateway", probe_gateway, "Check private DNS/network, gateway health, unified bearer credential and exact configured model. No model request was made.")
    print(json.dumps({"ok": all(row["ok"] for row in checks), "checks": checks,
                      "inference_requests": 0, "network_checked": args.gateway}, indent=2))
    return 0 if all(row["ok"] for row in checks) else 1
