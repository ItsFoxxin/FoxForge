"""Same-user local locks and durable issue reservations outside target repos."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .issue_tasks import IssueError
from .security import redact


def intake_root() -> Path:
    # Independent of FOXFORGE_RUNS_DIR: separate run-output choices must not
    # allow two workers of this OS user to bypass the shared claim locks.
    local = os.getenv("LOCALAPPDATA")
    return (Path(local) / "FoxForge" / "intake" if local else Path.home() / ".foxforge" / "intake").resolve()


def key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_key(repository: str, number: int) -> str:
    return key(f"{repository.casefold()}#{number}")


def worktree_key(repo: Path) -> str:
    return key(os.path.normcase(str(repo.resolve())))


def atomic_json(path: Path, value: dict) -> None:
    payload = json.dumps(value, indent=2) + "\n"
    if redact(payload) != payload:
        raise IssueError("Refusing credential material in intake storage")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def outside_repo(repo: Path) -> Path:
    root = intake_root()
    if root.is_relative_to(repo.resolve()):
        raise IssueError("Intake locks and records must be outside the target repository")
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def local_lock(repo: Path, name: str):
    path = outside_repo(repo) / "locks" / (name + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    # OS advisory locks are released on process death. The durable reservation
    # is deliberately retained, so a crash never implies permission to restart.
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise IssueError("Another local worker owns this issue or worktree; intervention required") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def record_path(repo: Path, repository: str, number: int) -> Path:
    return outside_repo(repo) / "issues" / (issue_key(repository, number) + ".json")


def load_record(repo: Path, repository: str, number: int) -> dict:
    path = record_path(repo, repository, number)
    if not path.exists():
        return {"repository": repository, "issue": number, "attempts": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["repository"].casefold() != repository.casefold() or type(data["issue"]) is not int or data["issue"] != number or not isinstance(data["attempts"], list):
            raise ValueError
        return data
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise IssueError("Issue reservation is unreadable or ambiguous; intervention required") from None
