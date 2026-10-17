from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import os
import tempfile
from .security import redact


@dataclass
class RunState:
    run_id: str
    task: str
    branch: str
    base_ref: str

    agents_completed: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)

    tests_added: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    test_exit_code: int | None = None
    test_counts_verified: bool = False

    review_result: str = "NOT_RUN"
    repair_cycles: int = 0

    final_status: str = "RUNNING"
    notification_status: str = "NOT_SENT"

    publish_requested: bool = False
    github_repository: str | None = None
    validated_head_sha: str | None = None
    validated_tree_hash: str | None = None
    publishing_status: str = "NOT_REQUESTED"
    publishing_error: str | None = None
    commit_sha: str | None = None
    remote_branch: str | None = None
    pull_request_number: int | None = None
    pull_request_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path) -> None:
        payload = json.dumps(self.to_dict(), indent=2) + "\n"
        if redact(payload) != payload:
            raise ValueError("Refusing to persist credential material in RunState")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=path.name + ".", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path) -> "RunState":
        try:
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid RunState file: {path}") from exc
