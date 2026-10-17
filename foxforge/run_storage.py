from __future__ import annotations

import os
from pathlib import Path
import re
import hashlib


def runs_root() -> Path:
    configured = os.getenv("FOXFORGE_RUNS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "FoxForge" / "runs"

    return Path.home() / ".foxforge" / "runs"


def create_run_dir(repo: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("Invalid run identifier")
    root = runs_root().resolve()
    if root.is_relative_to(repo.resolve()):
        raise ValueError("Run artifacts must be stored outside the target repository")
    safe_repo_name = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_"
        for ch in repo.name
    )
    repo_key = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:12]
    path = (root / f"{safe_repo_name}-{repo_key}" / run_id).resolve()
    if path.is_relative_to(repo.resolve()) or not path.is_relative_to(root):
        raise ValueError("Run directory resolves outside its allowed storage root")
    path.mkdir(parents=True, exist_ok=False)
    return path
