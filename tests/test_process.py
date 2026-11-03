import subprocess
import sys
import os

import pytest

from foxforge.process import duration_seconds, run_process


@pytest.mark.parametrize("text,seconds", [("20m", 1200), ("0.1s", .1), ("1h", 3600), ("12", 12)])
def test_duration(text, seconds):
    assert duration_seconds(text) == seconds


@pytest.mark.parametrize("text", ["", "0", "-1m", "inf", "1d", "1m & echo unsafe"])
def test_invalid_duration(text):
    with pytest.raises(ValueError):
        duration_seconds(text)


def test_process_timeout_preserves_output(tmp_path, monkeypatch):
    # Allow interpreter startup on loaded runners, while still exercising the
    # real timeout/kill path long before the child could finish its sleep.
    command = [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(20)"]
    children = []
    real_popen = subprocess.Popen

    def track_child(args, *positional, **kwargs):
        child = real_popen(args, *positional, **kwargs)
        if args == command:
            children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", track_child)
    with pytest.raises(subprocess.TimeoutExpired) as error:
        run_process(command, tmp_path, timeout=3)
    assert error.value.timeout == 3
    assert "started" in error.value.stdout
    assert len(children) == 1
    child = children[0]
    assert child.returncode is not None and child.returncode != 0
    assert child.poll() == child.returncode
    assert child.wait(timeout=0) == child.returncode
    if os.name != "nt":
        # Popen must already have reaped the child, not merely signalled it.
        with pytest.raises(ChildProcessError):
            os.waitpid(child.pid, os.WNOHANG)


def test_process_stdin_is_not_shell_code(tmp_path):
    result = run_process([sys.executable, "-c", "import sys; print(sys.stdin.read())"], tmp_path, input="x & echo unsafe\n🦊", timeout=10)
    assert result.returncode == 0
    assert "x & echo unsafe" in result.stdout
    assert "🦊" in result.stdout
