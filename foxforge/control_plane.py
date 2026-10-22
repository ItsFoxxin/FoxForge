"""Small durable control plane for the planning-only FoxForge milestone."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from .security import redact


SCHEMA_VERSION = 1


class ControlPlaneError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def data_root() -> Path:
    configured = os.getenv("FOXFORGE_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local = os.getenv("LOCALAPPDATA")
    return ((Path(local) / "FoxForge" / "control-plane") if local else (Path.home() / ".foxforge" / "control-plane")).resolve()


class ControlPlane:
    def __init__(self, path: Path | None = None):
        self.path = (path or data_root() / "foxforge.db").resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    @contextmanager
    def transaction(self):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schema_info(version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS projects(
                    repository_id INTEGER PRIMARY KEY,
                    repository TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    local_path TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    default_branch TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discoveries(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repository_id INTEGER NOT NULL REFERENCES projects(repository_id),
                    issue_number INTEGER NOT NULL,
                    revision TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    UNIQUE(repository_id, issue_number, revision)
                );
                CREATE TABLE IF NOT EXISTS authorizations(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repository_id INTEGER NOT NULL REFERENCES projects(repository_id),
                    issue_number INTEGER NOT NULL,
                    revision TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    actor_id INTEGER NOT NULL,
                    source_event_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(repository_id, operation, source_event_id)
                );
                CREATE TABLE IF NOT EXISTS tasks(
                    id TEXT PRIMARY KEY,
                    authorization_id INTEGER NOT NULL UNIQUE REFERENCES authorizations(id),
                    repository_id INTEGER NOT NULL REFERENCES projects(repository_id),
                    issue_number INTEGER NOT NULL,
                    revision TEXT NOT NULL,
                    state TEXT NOT NULL,
                    activity TEXT NOT NULL,
                    base_sha TEXT,
                    discovery_json TEXT,
                    plan_json TEXT,
                    artifact_dir TEXT,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT REFERENCES tasks(id),
                    event_type TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            versions = [row[0] for row in db.execute("SELECT version FROM schema_info")]
            if not versions:
                db.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
            elif versions != [SCHEMA_VERSION]:
                raise ControlPlaneError("Unsupported control-plane schema version")

    @staticmethod
    def _safe_json(value) -> str:
        text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        if redact(text) != text:
            raise ControlPlaneError("Refusing credential material in control-plane storage")
        return text

    def register_project(self, *, repository_id: int, repository: str, local_path: Path, default_branch: str) -> dict:
        if type(repository_id) is not int or repository_id <= 0:
            raise ControlPlaneError("Invalid repository ID")
        local = str(local_path.resolve())
        if not default_branch or len(default_branch) > 255 or any(ch in default_branch for ch in "\r\n\0"):
            raise ControlPlaneError("Invalid default branch")
        now = utc_now()
        with self.transaction() as db:
            existing = db.execute("SELECT * FROM projects WHERE repository_id=? OR repository=? COLLATE NOCASE", (repository_id, repository)).fetchone()
            if existing:
                if (existing["repository_id"], existing["repository"].casefold(), existing["local_path"], existing["default_branch"]) != (repository_id, repository.casefold(), local, default_branch):
                    raise ControlPlaneError("Registered project identity conflicts with existing data")
                return dict(existing)
            db.execute("INSERT INTO projects VALUES (?,?,?,?,?)", (repository_id, repository, local, default_branch, now))
        return self.project(repository)

    def project(self, repository: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE repository=? COLLATE NOCASE", (repository,)).fetchone()
        if not row:
            raise ControlPlaneError("Project is not registered")
        return dict(row)

    def projects(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY repository COLLATE NOCASE")]

    def record_discovery(self, project: dict, snapshot: dict) -> int:
        now = utc_now()
        payload = self._safe_json(snapshot)
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO discoveries(repository_id,issue_number,revision,snapshot_json,discovered_at) VALUES (?,?,?,?,?)",
                       (project["repository_id"], snapshot["number"], snapshot["revision"], payload, now))
            row = db.execute("SELECT id FROM discoveries WHERE repository_id=? AND issue_number=? AND revision=?",
                             (project["repository_id"], snapshot["number"], snapshot["revision"])).fetchone()
        return row[0]

    def authorize_and_create_task(self, project: dict, snapshot: dict, *, actor_id: int, event_id: int) -> tuple[dict, bool]:
        if any(type(value) is not int or value <= 0 for value in (actor_id, event_id)):
            raise ControlPlaneError("Invalid authorization identity")
        now = utc_now()
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO authorizations(repository_id,issue_number,revision,operation,actor_id,source_event_id,created_at) VALUES (?,?,?,?,?,?,?)",
                       (project["repository_id"], snapshot["number"], snapshot["revision"], "plan", actor_id, event_id, now))
            auth = db.execute("SELECT * FROM authorizations WHERE repository_id=? AND operation='plan' AND source_event_id=?",
                              (project["repository_id"], event_id)).fetchone()
            if auth["issue_number"] != snapshot["number"] or auth["revision"] != snapshot["revision"] or auth["actor_id"] != actor_id:
                raise ControlPlaneError("Authorization evidence conflicts with existing data")
            existing = db.execute("SELECT * FROM tasks WHERE authorization_id=?", (auth["id"],)).fetchone()
            if existing:
                return dict(existing), False
            task_id = "task_" + uuid4().hex
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (task_id, auth["id"], project["repository_id"], snapshot["number"], snapshot["revision"],
                        "queued", "planning", None, None, None, None, None, now, now))
            self._audit(db, task_id, "task.created", "allowed", {"operation": "plan", "actor_id": actor_id, "event_id": event_id})
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row), True

    def update_task(self, task_id: str, *, state: str, activity: str, base_sha: str | None = None,
                    discovery: dict | None = None, plan: dict | None = None, artifact_dir: Path | None = None,
                    error_code: str | None = None) -> dict:
        allowed_states = {"queued", "active", "blocked", "awaiting_human_review", "failed", "cancelled"}
        allowed_activities = {"planning", "analyzing", "replanning", "idle"}
        if state not in allowed_states or activity not in allowed_activities:
            raise ControlPlaneError("Invalid task state")
        with self.transaction() as db:
            if not db.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
                raise ControlPlaneError("Task does not exist")
            db.execute("UPDATE tasks SET state=?,activity=?,base_sha=COALESCE(?,base_sha),discovery_json=COALESCE(?,discovery_json),plan_json=COALESCE(?,plan_json),artifact_dir=COALESCE(?,artifact_dir),error_code=?,updated_at=? WHERE id=?",
                       (state, activity, base_sha, self._safe_json(discovery) if discovery is not None else None,
                        self._safe_json(plan) if plan is not None else None, str(artifact_dir.resolve()) if artifact_dir else None,
                        error_code, utc_now(), task_id))
            self._audit(db, task_id, "task.state", "recorded", {"state": state, "activity": activity, "error_code": error_code})
        return self.task(task_id)

    def task(self, task_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT t.*, p.repository,p.local_path,p.default_branch FROM tasks t JOIN projects p ON p.repository_id=t.repository_id WHERE t.id=?", (task_id,)).fetchone()
        if not row:
            raise ControlPlaneError("Task does not exist")
        result = dict(row)
        for key in ("discovery_json", "plan_json"):
            result[key[:-5]] = json.loads(result[key]) if result[key] else None
        return result

    def _audit(self, db: sqlite3.Connection, task_id: str | None, event_type: str, outcome: str, detail: dict) -> None:
        db.execute("INSERT INTO audit_events(task_id,event_type,outcome,detail_json,created_at) VALUES (?,?,?,?,?)",
                   (task_id, event_type, outcome, self._safe_json(detail), utc_now()))

    def artifacts(self, task_id: str) -> Path:
        root = self.path.parent / "artifacts"
        path = (root / task_id).resolve()
        if not path.is_relative_to(root):
            raise ControlPlaneError("Artifact path escaped its storage root")
        path.mkdir(parents=True, exist_ok=True)
        return path


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
