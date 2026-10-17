from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import subprocess


@dataclass
class TestResult:
    command: list[str]
    exit_code: int
    passed: int
    failed: int
    output: str

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


def split_command(command: str) -> list[str]:
    # posix=False preserves Windows-style backslashes.
    return shlex.split(command, posix=False)


def run_tests(repo: Path, command: str) -> TestResult:
    argv = split_command(command)

    result = subprocess.run(
        argv,
        cwd=repo,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    passed = _last_count(output, r"(\d+)\s+passed")
    failed = _last_count(output, r"(\d+)\s+failed")

    return TestResult(
        command=argv,
        exit_code=result.returncode,
        passed=passed,
        failed=failed,
        output=output.strip(),
    )


def _last_count(text: str, pattern: str) -> int:
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    if not matches:
        return 0
    return int(matches[-1])


def count_added_tests(diff_text: str) -> int:
    """
    Counts newly-added Python pytest or Godot/GUT test functions.

    This is intentionally conservative:
      +def test_name(...)
      +func test_name(...)
    """
    pattern = re.compile(
        r"^\+\s*(?:def|func)\s+test_[A-Za-z0-9_]*\s*\(",
        flags=re.MULTILINE,
    )
    return len(pattern.findall(diff_text))
