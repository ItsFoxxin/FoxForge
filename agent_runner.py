from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
import time


@dataclass
class AgentResult:
    role: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


class AgentRunnerError(RuntimeError):
    pass


def find_qwen() -> str:
    configured = os.getenv("FOXFORGE_QWEN_EXE")
    if configured:
        return configured

    detected = shutil.which("qwen")
    if detected:
        return detected

    raise AgentRunnerError(
        "Qwen Code executable was not found. "
        "Set FOXFORGE_QWEN_EXE to the full path of "
        "qwen, qwen.cmd, or qwen.exe."
    )


def _build_process_command(qwen: str, args: list[str]) -> list[str]:
    suffix = Path(qwen).suffix.lower()

    if suffix in {".cmd", ".bat"}:
        comspec = os.environ.get(
            "COMSPEC",
            r"C:\Windows\System32\cmd.exe",
        )
        command_line = subprocess.list2cmdline([qwen, *args])
        return [comspec, "/d", "/s", "/c", command_line]

    return [qwen, *args]


def build_delegate_prompt(
    role: str,
    task: str,
    context: str,
) -> str:
    return f"""
You are a FoxForge delegation wrapper.

Your ONLY job is to invoke the project-level `{role}` agent using the Agent
tool, in the foreground, and wait for it to finish.

Do not inspect repository files yourself.
Do not edit files yourself.
Do not run shell commands yourself.
Do not substitute a built-in/general-purpose agent.
Do not perform the `{role}` agent's work yourself.

Give the project-level `{role}` agent this task:

--- TASK ---
{task}
--- END TASK ---

Give it this verified context from FoxForge:

--- CONTEXT ---
{context}
--- END CONTEXT ---

When the project-level agent completes, print its result faithfully.
Do not add new technical claims.
""".strip()


def run_project_agent(
    repo: Path,
    role: str,
    task: str,
    context: str = "",
    approval_mode: str = "auto",
    max_wall_time: str = "20m",
) -> AgentResult:
    qwen = find_qwen()

    prompt = build_delegate_prompt(
        role=role,
        task=task,
        context=context,
    )

    # Only the parent delegation wrapper gets the Agent tool pre-approved.
    # The project-level role is still constrained by its own .qwen/agents
    # tool allowlist.
    args = [
        "--output-format",
        "text",
        "--approval-mode",
        approval_mode,
        "--allowed-tools",
        "agent",
        "--max-subagent-depth",
        "1",
        "--max-wall-time",
        max_wall_time,
    ]

    command = _build_process_command(qwen, args)
    started = time.monotonic()

    # Send the actual prompt through stdin. Do not also use -p/--prompt.
    result = subprocess.run(
        command,
        cwd=repo,
        input=prompt,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    duration = time.monotonic() - started

    return AgentResult(
        role=role,
        exit_code=result.returncode,
        stdout=result.stdout.strip(),
        stderr=result.stderr.strip(),
        duration_seconds=duration,
    )
