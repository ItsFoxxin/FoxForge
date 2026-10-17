# Workflow

## Sandbox workflow

Use the current branch and compare against `HEAD`:

```powershell
python -m foxforge `
  --repo C:\Projects\agent-lab `
  --task "Add square(a: int) -> int to calculator.py." `
  --test-command ".venv\Scripts\python.exe -m pytest -v" `
  --base-ref HEAD `
  --skip-discord
```

## Project workflow

For a target project using `dev` as the integration branch:

```powershell
python -m foxforge `
  --repo C:\Projects\YourProject `
  --task-file C:\Tasks\task.txt `
  --test-command "python -m pytest -v" `
  --create-branch `
  --base-branch dev `
  --base-ref origin/dev
```

The intended branch lifecycle is:

```text
origin/dev
   ↓
foxforge/<task>
   ↓
agents + deterministic validation
   ↓
READY_FOR_PLAYTEST
   ↓
future: bot-authored commit/push/PR
   ↓
PR -> dev
   ↓
human acceptance/playtest
   ↓
dev -> main -> release
```

Individual agents never own Git branch lifecycle.

## Repair loop

A repair cycle is triggered when:

- the authoritative test command exits non-zero, or
- the Reviewer does not return `REVIEW_RESULT: PASS`.

Maximum repair cycles: 3.

The repair sequence is:

```text
Implementer
  ↓
Tester
  ↓
Python tests
  ↓
Reviewer
```

After the limit, the run becomes `BLOCKED`.

Sandbox runs require a non-protected task/sandbox branch with an existing commit.
Unverified or zero passing test counts also trigger repair. A BLOCKED run exits 1.

