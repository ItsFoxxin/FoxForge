from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
import time

from .process import duration_seconds, run_process


PROJECT_ROLES = ("architect", "implementer", "tester", "reviewer", "helper", "reporter")


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
        detected = shutil.which(configured)
        if detected:
            return detected
        raise AgentRunnerError("FOXFORGE_QWEN_EXE does not identify an executable")

    detected = shutil.which("qwen")
    if detected:
        return detected

    raise AgentRunnerError(
        "Qwen Code executable was not found. "
        "Set FOXFORGE_QWEN_EXE to the full path of "
        "qwen, qwen.cmd, or qwen.exe."
    )


def _build_process_command(qwen: str, args: list[str]) -> list[str] | str:
    suffix = Path(qwen).suffix.lower()

    if suffix in {".cmd", ".bat"}:
        if os.name != "nt":
            raise AgentRunnerError("Windows Qwen launchers require Windows")
        if any(ch in qwen for ch in '%!^&|<>\r\n"'):
            raise AgentRunnerError("Unsafe characters in Qwen launcher path")
        comspec = os.environ.get(
            "COMSPEC",
            r"C:\Windows\System32\cmd.exe",
        )
        command_line = subprocess.list2cmdline([qwen, *args])
        # cmd.exe uses different quoting from the Windows C argv convention.
        # Passing this as an argv list would introduce literal backslash-quotes.
        return f'{subprocess.list2cmdline([comspec])} /d /s /c "{command_line}"'

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
    approval_mode: str = "default",
    max_wall_time: str = "20m",
) -> AgentResult:
    if role not in PROJECT_ROLES:
        raise AgentRunnerError(f"Unknown project agent: {role}")
    if not (repo / ".qwen" / "agents" / f"{role}.md").is_file():
        raise AgentRunnerError(f"Missing project agent definition: {role}")
    if approval_mode != "default":
        raise AgentRunnerError("The parent wrapper requires default approval mode")
    timeout = duration_seconds(max_wall_time)
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
    # The model process must never inherit Python's notification credential.
    env = dict(os.environ)
    env.pop("DISCORD_WEBHOOK_URL", None)
    try:
        result = run_process(command, repo, input=prompt, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        result = subprocess.CompletedProcess(
            command, 124, exc.stdout or "", (exc.stderr or "") + "\nAgent timed out",
        )
    except OSError as exc:
        raise AgentRunnerError(f"Could not start {role}: {exc}") from exc

    duration = time.monotonic() - started

    return AgentResult(
        role=role,
        exit_code=result.returncode,
        stdout=result.stdout.strip(),
        stderr=result.stderr.strip(),
        duration_seconds=duration,
    )
