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
- Qwen Code and a configured model are needed only for actual agent runs; tests and CI use mocks.

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
%LOCALAPPDATA%\FoxForge\runs\<repo>-<path-hash>\<run-id>\
```

or, when `LOCALAPPDATA` is unavailable:

```text
~/.foxforge/runs/<repo>-<path-hash>/<run-id>/
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

For a target project:

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

## Deterministic validation and CLI behavior

Use `python -m foxforge` or the installed `foxforge` command, rather than executing
package files directly. The legacy `python -m foxforge.notifier` and
`python -m foxforge.notify_status` entrypoints now require `--state` and `--reporter`
and use the same validation as `python -m foxforge.reporter_dispatch`.

Run agents only on a task or sandbox branch. For a disposable sandbox, create
`foxforge/sandbox` before running. `main`, `master`, `dev`, and detached HEAD are
rejected. All runs require a clean starting worktree so existing edits are not
attributed to the current task. `--create-branch` branches from `origin/dev`
after fetching origin. No commits, pushes, merges, or releases are performed.
The base reference is resolved to a commit SHA before agent execution.

Both `--max-agent-time` and `--max-test-time` default to `20m`. Python enforces
these deadlines and attempts to terminate each process tree on timeout.
The parent wrapper uses default approval mode and preapproves only `agent`.
No YOLO fallback is used. Confirm the CLI flags and Agent permission spelling
against the locally installed Qwen Code version before a real model run.

Test counts come from a final pytest, unittest, GUT, or explicit
`Tests: <passed> passed, <failed> failed` summary. Unrecognized formats and
zero passing tests cannot produce `READY_FOR_PLAYTEST`. Collection errors count
as failures. A custom validator must emit the explicit summary using its own
authoritative counts, and exit nonzero on failure. `Tests added` counts new
Python/GDScript test definitions (including untracked files), not parametrized
cases. Rewriting an existing definition does not add a test.

Run state is saved atomically after each completed stage and after test/review
results. BLOCKED runs exit 1; a notification failure also exits 1 while retaining
the independently computed validation status. Tasks and filenames with line
breaks are escaped in Reporter facts so the report stays line-based.
Discord messages exceeding 2,000 UTF-16 units are rejected; mentions are disabled.

Set `FOXFORGE_RUNS_DIR` to override external storage. Paths inside the target
repository are rejected. Repository path hashes and unique run identifiers
prevent collisions between projects with the same name or concurrent starts.
Do not run concurrent tasks in the same target worktree.

Agent installation preserves existing definitions by default. Explicitly pass
`-Force` to `scripts/install-target.ps1` only after reviewing customizations.
A wheel also installs templates and the installer under
`<python-prefix>/share/foxforge/`.

CI runs validation, model-free tests, then packaging on Windows and Linux.
The package check installs the wheel in a fresh environment outside the source
checkout and checks imports, templates, and module/console entrypoints.
