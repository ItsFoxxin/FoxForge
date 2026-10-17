from __future__ import annotations

import os
from pathlib import Path


def runs_root() -> Path:
    configured = os.getenv("FOXFORGE_RUNS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "FoxForge" / "runs"

    return Path.home() / ".foxforge" / "runs"


def create_run_dir(repo: Path, run_id: str) -> Path:
    safe_repo_name = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_"
        for ch in repo.name
    )
    path = runs_root() / safe_repo_name / run_id
    path.mkdir(parents=True, exist_ok=False)
    return path
