import subprocess
import sys

import pytest

from foxforge.process import duration_seconds, run_process


@pytest.mark.parametrize("text,seconds", [("20m", 1200), ("0.1s", .1), ("1h", 3600), ("12", 12)])
def test_duration(text, seconds):
    assert duration_seconds(text) == seconds


@pytest.mark.parametrize("text", ["", "0", "-1m", "inf", "1d", "1m & echo unsafe"])
def test_invalid_duration(text):
    with pytest.raises(ValueError):
        duration_seconds(text)


def test_process_timeout_preserves_output(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired) as error:
        run_process([sys.executable, "-c", "import time; print('started', flush=True); time.sleep(20)"], tmp_path, timeout=.5)
    assert "started" in error.value.stdout


def test_process_stdin_is_not_shell_code(tmp_path):
    result = run_process([sys.executable, "-c", "import sys; print(sys.stdin.read())"], tmp_path, input="x & echo unsafe\n🦊", timeout=10)
    assert result.returncode == 0
    assert "x & echo unsafe" in result.stdout
    assert "🦊" in result.stdout
