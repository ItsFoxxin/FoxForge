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
    Count newly-added Python pytest or Godot/GUT test functions in a diff.
    """
    pattern = re.compile(
        r"^\+\s*(?:def|func)\s+test_[A-Za-z0-9_]*\s*\(",
        flags=re.MULTILINE,
    )
    return len(pattern.findall(diff_text))


def count_test_definitions(text: str) -> int:
    patterns = [
        r"^\s*def\s+test_[A-Za-z0-9_]*\s*\(",
        r"^\s*func\s+test_[A-Za-z0-9_]*\s*\(",
    ]

    return sum(
        len(re.findall(pattern, text, flags=re.MULTILINE))
        for pattern in patterns
    )


def is_likely_test_file(path: str) -> bool:
    name = Path(path).name.lower()
    return (
        "test" in name
        and Path(path).suffix.lower() in {".py", ".gd"}
    )
