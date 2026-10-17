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
explicit --publish-pr: Python bot commit/push/PR
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


## Optional publication after local validation

Add `--publish-pr` to opt in. After Helper, Python validates the frozen
HEAD/content snapshot, authenticates as the installed App, commits, pushes only
the foxforge/* task ref, and opens/reuses an owned PR targeting dev. Reporter then
receives the verified commit/branch/PR metadata. Three repair cycles remains the
maximum; a failed local gate never reaches App authentication or publishing.

READY_FOR_PLAYTEST describes local validation. publishing_status separately
records NOT_REQUESTED, PENDING, COMMITTED, PUSHED, PUBLISHED, FAILED, or BLOCKED.
Every completed publishing step is persisted. A publication failure leaves the
local validation outcome intact and exits nonzero. Python never resets an
already-created commit/branch/PR automatically. Unknown remote branch ownership
and orphan branches without an owned PR require human review before retry.

The CLI never publishes just because environment variables exist. Use
`python -m foxforge.github_app --check --repository owner/name` for an
independent read-only authentication/access check. Exact preparation and manual
push/PR smoke-test commands are in GITHUB_APP.md. The implementation session and
normal CI do not perform real GitHub writes.
