from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json


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

    review_result: str = "NOT_RUN"
    repair_cycles: int = 0

    final_status: str = "RUNNING"
    notification_status: str = "NOT_SENT"

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "RunState":
        return cls(**json.loads(path.read_text(encoding="utf-8")))
