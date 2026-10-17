from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import os
import re
import shlex
import subprocess
import ctypes

from .process import run_process
from .security import child_environment, redact


@dataclass
class TestResult:
    command: list[str]
    exit_code: int
    passed: int
    failed: int
    output: str
    counts_verified: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and self.counts_verified and self.passed > 0 and self.failed == 0


def split_command(command: str) -> list[str]:
    if os.name == "nt":
        # Use Windows' own argv parser, including embedded quotes/backslashes.
        parser = ctypes.windll.shell32.CommandLineToArgvW
        parser.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        parser.restype = ctypes.POINTER(ctypes.c_wchar_p)
        count = ctypes.c_int()
        pointer = parser(command.lstrip(), ctypes.byref(count)) if command.strip() else None
        if not pointer:
            raise ValueError("Invalid or empty authoritative test command")
        try:
            argv = [pointer[index] for index in range(count.value)]
        finally:
            free = ctypes.windll.kernel32.LocalFree
            free.argtypes = [ctypes.c_void_p]
            free.restype = ctypes.c_void_p
            free(pointer)
    else:
        argv = shlex.split(command, posix=True)
    if not argv or not argv[0]:
        raise ValueError("Authoritative test command is empty")
    return argv


def parse_test_counts(output: str) -> tuple[int, int, bool]:
    """Read a final pytest, unittest, GUT, or explicit validation summary.

    Unknown formats never manufacture a verified zero-test success. Collection
    errors are included in the failure count. Per-test chatter is not a summary.
    """
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
    for line in reversed(clean.splitlines()):
        summary = line.strip().strip("= ")
        if re.fullmatch(
            r"(?:\d+ (?:passed|failed|errors?|skipped|deselected|warnings?|xfailed|xpassed)(?:, )?)+"
            r"(?: in \d+(?:\.\d+)?s(?: \([^\n]*\))?)?", summary,
        ):
            counts = {kind: int(number) for number, kind in re.findall(r"(\d+) ([a-z]+)", summary)}
            return counts.get("passed", 0), counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0), True
        explicit = re.fullmatch(r"Tests: (\d+) passed, (\d+) failed", summary)
        if explicit:
            return int(explicit[1]), int(explicit[2]), True
    ran = re.search(r"^Ran (\d+) tests? in [\d.]+s\s*$", clean, re.MULTILINE)
    outcome = re.search(r"^(OK|FAILED)(?: \(([^\n]*)\))?\s*$", clean, re.MULTILINE)
    if ran and outcome:
        details = {name.strip(): count for name, count in re.findall(r"([a-z ]+)=(\d+)", outcome[2] or "")}
        failures = int(details.get("failures", 0)) + int(details.get("errors", 0))
        skipped = int(details.get("skipped", 0)) + int(details.get("expected failures", 0))
        return max(0, int(ran[1]) - failures - skipped), failures, True
    # GUT summary used by GDScript targets.
    gut = re.search(r"^Passing Tests\s+(\d+)\s*$", clean, re.MULTILINE)
    gut_failed = re.search(r"^Failing Tests\s+(\d+)\s*$", clean, re.MULTILINE)
    if gut and gut_failed:
        return int(gut[1]), int(gut_failed[1]), True
    return 0, 0, False


def run_tests(repo: Path, command: str, timeout: float = 1200) -> TestResult:
    argv = split_command(command)
    env = child_environment()
    try:
        result = run_process(argv, repo, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        return TestResult(argv, 124, 0, 0, redact(f"{exc.stdout or ''}\n{exc.stderr or ''}\nAuthoritative tests timed out"))
    except OSError as exc:
        return TestResult(argv, 127, 0, 0, redact(f"Could not start authoritative tests: {exc}"))
    output = (result.stdout + ("\n" + result.stderr if result.stderr else "")).strip()
    if redact(output) != output:
        return TestResult(argv, 1, 0, 0, redact(output) + "\nCredential material found in test output")
    passed, failed, verified = parse_test_counts(output)
    if not verified:
        output += "\nFoxForge could not verify test counts from a supported summary."
    return TestResult(argv, result.returncode, passed, failed, output, verified)


def count_added_tests(diff_text: str) -> int:
    """Count new test definitions per file; edits to existing tests do not add tests."""
    added: Counter = Counter()
    removed: Counter = Counter()
    path = ""
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            path = line
        match = re.match(r"^([+-])\s*(?:(?:async\s+)?def|func)\s+(test_[A-Za-z0-9_]*)\s*\(", line)
        if match:
            (added if match[1] == "+" else removed)[(path, match[2])] += 1
    return sum((added - removed).values())


def count_test_definitions(text: str) -> int:
    return len(re.findall(r"^\s*(?:(?:async\s+)?def|func)\s+test_[A-Za-z0-9_]*\s*\(", text, re.MULTILINE))


def is_likely_test_file(path: str) -> bool:
    parsed = Path(path.replace("\\", "/"))
    name = parsed.stem.lower()
    return parsed.suffix.lower() in {".py", ".gd"} and (
        name.startswith("test_") or name.endswith("_test") or
        any(part.lower() in {"tests", "test"} for part in parsed.parts[:-1])
    )
