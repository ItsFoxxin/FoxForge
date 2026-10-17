from foxforge.test_runner import (
    count_test_definitions,
    is_likely_test_file,
)
import os
import shlex
import subprocess
import sys

import pytest

from foxforge import test_runner


def test_count_python_test_definitions() -> None:
    text = """
def test_one():
    pass

def helper():
    pass

def test_two():
    pass
"""
    assert count_test_definitions(text) == 2


def test_count_gdscript_test_definitions() -> None:
    text = """
func test_one():
    pass

func helper():
    pass

func test_two():
    pass
"""
    assert count_test_definitions(text) == 2


def test_likely_test_file() -> None:
    assert is_likely_test_file("tests/test_math.py")
    assert is_likely_test_file("test_player.gd")
    assert not is_likely_test_file("player.gd")


@pytest.mark.parametrize("text,counts", [
    ("===== 12 passed, 1 warning in 0.12s =====", (12, 0, True)),
    ("1 failed, 2 passed, 1 error in 0.01s", (2, 2, True)),
    ("2 skipped in 0.1s", (0, 0, True)),
    ("chatter: 99 passed\n2 passed in 1.00s", (2, 0, True)),
    ("not a summary: 99 passed", (0, 0, False)),
    ("Ran 3 tests in 0.001s\n\nOK", (3, 0, True)),
    ("Ran 3 tests in 0.001s\n\nFAILED (failures=1, errors=1)", (1, 2, True)),
    ("Passing Tests 4\nFailing Tests 1", (4, 1, True)),
    ("Tests: 7 passed, 0 failed", (7, 0, True)),
])
def test_authoritative_summary_formats(text, counts):
    assert test_runner.parse_test_counts(text) == counts


def test_quoted_command_round_trip():
    argv = [sys.executable, "-c", 'print("3 passed")', "a path with spaces"]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    assert test_runner.split_command(command) == argv


def test_empty_command_rejected():
    with pytest.raises(ValueError):
        test_runner.split_command("   ")


def test_real_authoritative_process(tmp_path):
    argv = [sys.executable, "-c", 'print("3 passed in 0.01s")']
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    result = test_runner.run_tests(tmp_path, command)
    assert result.succeeded and result.passed == 3


def test_missing_test_executable_is_failure(tmp_path):
    result = test_runner.run_tests(tmp_path, "foxforge-no-such-test-runner")
    assert result.exit_code == 127 and not result.succeeded and not result.counts_verified


def test_zero_exit_without_counts_never_passes(tmp_path):
    argv = [sys.executable, "-c", 'print("build succeeded")']
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    result = test_runner.run_tests(tmp_path, command)
    assert result.exit_code == 0 and not result.succeeded


def test_count_added_ignores_rewritten_test_definitions():
    text = "diff --git a/tests/test_a.py b/tests/test_a.py\n-def test_old():\n+def test_old():\n+async def test_new():\n"
    assert test_runner.count_added_tests(text) == 1
