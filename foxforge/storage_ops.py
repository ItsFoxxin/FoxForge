"""Explicit, non-overwriting backups and read-only recovery verification."""

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing

from .control_plane import SCHEMA_VERSION, ControlPlaneError


TABLES = ("projects", "discoveries", "authorizations", "tasks", "audit_events")


def inspect_database(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ControlPlaneError("Database is missing or is a symlink; choose and verify the intended state directory")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ControlPlaneError("Database integrity or foreign-key check failed")
        if db.execute("SELECT version FROM schema_info").fetchall() != [(SCHEMA_VERSION,)]:
            raise ControlPlaneError("Unsupported control-plane schema version")
        counts = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in TABLES}
        for name in ("model_requests", "workers_v1", "worker_attempts_v1", "worker_events_v1"):
            if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
                counts[name] = db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        tasks = db.execute("SELECT id,artifact_dir FROM tasks WHERE artifact_dir IS NOT NULL").fetchall()
        if "worker_attempts_v1" in counts:
            for task_id, result in db.execute("SELECT task_id,result_json FROM worker_attempts_v1 WHERE result_json IS NOT NULL"):
                if json.loads(result)["data"]["artifacts"]:
                    tasks.append((task_id, None))
    return {"schema_version": SCHEMA_VERSION, "counts": counts, "artifact_task_ids": [row[0] for row in tasks]}


def artifact_hashes(root: Path) -> dict:
    result = {}
    if root.is_symlink():
        raise ControlPlaneError("Artifact symlinks are not allowed in backups")
    if root.exists():
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ControlPlaneError("Artifact symlinks are not allowed in backups")
            if path.is_file():
                with path.open("rb") as stream:
                    result[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def verify_directory(root: Path) -> dict:
    result = inspect_database(root / "foxforge.db")
    hashes = artifact_hashes(root / "artifacts")
    for task_id in result["artifact_task_ids"]:
        if not any(name.startswith(task_id + "/") for name in hashes):
            raise ControlPlaneError("Task artifacts are missing from the selected directory")
    manifest = root / "backup-manifest.json"
    if manifest.exists():
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if value != {"database": result, "artifacts": hashes}:
            raise ControlPlaneError("Backup manifest verification failed")
    return result


def backup(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists() or destination.is_symlink() or destination.is_relative_to(source):
        raise ControlPlaneError("Backup destination must be new and outside the source directory")
    # Operators must quiesce ALL writers to keep artifacts and SQLite coherent.
    before = verify_directory(source)
    hashes = artifact_hashes(source / "artifacts")
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    with closing(sqlite3.connect((source / "foxforge.db").as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination / "foxforge.db")) as dst:
            src.backup(dst)
    if (source / "artifacts").exists():
        shutil.copytree(source / "artifacts", destination / "artifacts")
    if inspect_database(destination / "foxforge.db") != before or artifact_hashes(destination / "artifacts") != hashes:
        raise ControlPlaneError("Source changed during backup; preserve and investigate the incomplete copy")
    (destination / "backup-manifest.json").write_text(json.dumps({"database": before, "artifacts": hashes}, indent=2), encoding="utf-8")
    verify_directory(destination)
    return before
