"""Bounded subprocess execution shared by agents and authoritative tests."""

from __future__ import annotations

import math
import os
import re
import signal
import subprocess
from pathlib import Path


def duration_seconds(value: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", value)
    if not match:
        raise ValueError("Duration must be a positive number with optional s, m, or h")
    seconds = float(match[1]) * {"": 1, "s": 1, "m": 60, "h": 3600}[match[2]]
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Duration must be positive and finite")
    return seconds


def run_process(
    command: list[str] | str, repo: Path, *, timeout: float, input: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Kill this process's group on timeout or interruption, then reap it."""
    env = dict(os.environ) if env is None else dict(env)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt" else {"start_new_session": True}
    )
    with subprocess.Popen(
        command, cwd=repo, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", env=env, **options,
    ) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=10, check=False,
                    )
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except (OSError, subprocess.SubprocessError):
                process.kill()
            if process.poll() is None:
                process.kill()
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired as drain_error:
                # A detached descendant may retain a pipe even after the parent
                # has died. Never let diagnostic collection remove the deadline.
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
                stdout = drain_error.stdout or ""
                stderr = drain_error.stderr or ""
                if isinstance(stdout, bytes):
                    stdout = stdout.decode("utf-8", errors="replace")
                if isinstance(stderr, bytes):
                    stderr = stderr.decode("utf-8", errors="replace")
            # Preserve captured diagnostics on the exception for callers.
            if isinstance(exc, subprocess.TimeoutExpired):
                raise subprocess.TimeoutExpired(command, timeout, stdout, stderr) from None
            raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
