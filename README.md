# FoxForge

FoxForge is a local-first multi-agent coding orchestrator built around Qwen Code.

It separates AI reasoning from deterministic orchestration:

- AI agents plan, implement, test, review, summarize, and report.
- Python owns Git state, authoritative test execution, run-state files, repair limits, and notification gating.
- Each role runs in a fresh Qwen Code process to avoid one giant coordinator context.
- Target repositories keep their own project-specific `.qwen/agents/` definitions.

FoxForge is currently an early development project. The first validation target is a disposable calculator sandbox before any production project is connected.

## Agent roles

FoxForge expects six project-level Qwen agents:

1. `architect`
2. `implementer`
3. `tester`
4. `reviewer`
5. `helper`
6. `reporter`

The included templates are under `templates/qwen-agents/`.

## Basic flow

```text
task
  ↓
Architect
  ↓
Implementer
  ↓
Tester
  ↓
Python runs authoritative tests
  ↓
Reviewer
  ↓
repair loop (max 3)
  ↓
Helper
  ↓
Reporter
  ↓
Python validates state + reporter output
  ↓
Discord status
```

## Install for development

Requires:

- Python 3.11+
- Git
- Qwen Code
- A local or remote model configured in Qwen Code

Create a virtual environment and install FoxForge in editable mode:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .[dev]
```

Run tests:

```powershell
python -m pytest -v
```

## Configure Qwen Code

FoxForge launches Qwen Code headlessly. Qwen must already be configured and working from the command line.

If `qwen` is not on `PATH`, set:

```powershell
[System.Environment]::SetEnvironmentVariable(
    "FOXFORGE_QWEN_EXE",
    "C:\path\to\qwen.cmd",
    "User"
)
```

On Windows, FoxForge first checks:

```text
C:\Program Files\Git\cmd\git.exe
```

You can override the Git executable:

```powershell
[System.Environment]::SetEnvironmentVariable(
    "FOXFORGE_GIT_EXE",
    "C:\path\to\git.exe",
    "User"
)
```

## Prepare a target repository

Copy the Qwen agent templates into the target repo:

```powershell
.\scripts\install-target.ps1 -RepoPath C:\Projects\agent-lab
```

The script creates:

```text
<repo>\.qwen\agents\
```

and adds `.foxforge/` to the target repo's `.gitignore`.

## Run a sandbox task

Example:

```powershell
python -m foxforge `
  --repo C:\Projects\agent-lab `
  --task "Add square(a: int) -> int to calculator.py. Preserve existing behavior." `
  --test-command ".venv\Scripts\python.exe -m pytest -v" `
  --base-ref HEAD `
  --skip-discord
```

FoxForge stores run artifacts outside the target repository by default:

```text
%LOCALAPPDATA%\FoxForge\runs\<repo>\<run-id>\
```

or, when `LOCALAPPDATA` is unavailable:

```text
~\.foxforge\runs\<repo>\<run-id>\
```

## Discord

Set the webhook as a user environment variable. Never commit it.

```powershell
[System.Environment]::SetEnvironmentVariable(
    "DISCORD_WEBHOOK_URL",
    "YOUR_WEBHOOK_URL",
    "User"
)
```

Omit `--skip-discord` when you want the Reporter result dispatched.

## Branch workflow for target projects

For a project such as Dead Circuit:

```text
main
  ↑
dev
  ↑
foxforge/<task>
codex/<task>
dependabot/*
```

FoxForge task branches should be created from `origin/dev` and target `dev` through pull requests.

FoxForge does not auto-merge to `main`.

## GitHub bot integration

A GitHub App is the intended future identity for FoxForge. See:

```text
docs/GITHUB_APP.md
```

Bot authentication and PR creation are intentionally not wired into the coordinator yet. Local orchestration should be proven first.
