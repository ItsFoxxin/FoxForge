# Architecture

FoxForge separates probabilistic agent work from deterministic orchestration.

## AI-owned work

- Architect: plan
- Implementer: production code
- Tester: tests only
- Reviewer: independent technical review
- Helper: low-risk metadata
- Reporter: final status formatting

## Python-owned work

- locating Git
- branch creation
- changed-file detection
- authoritative test execution
- test count derivation
- repair-cycle count
- run-state persistence
- final status computation
- Reporter/state agreement validation
- Discord dispatch

## Context isolation

Each role is launched in a fresh Qwen Code process.

This prevents the coordinator from accumulating a very large chat context across
all stages and gives each technical role a separate reasoning context.

## Run artifacts

Run artifacts are stored outside the target repository.

Typical Windows location:

```text
%LOCALAPPDATA%\FoxForge\runs\<repo>\<run-id>\
```

Artifacts can include:

```text
task.txt
architect.txt
implementer.txt
tester.txt
tests.txt
reviewer.txt
helper.txt
reporter.txt
state.json
error.txt
```

Repair cycles receive suffixed files such as:

```text
implementer-repair-1.txt
tester-repair-1.txt
tests-repair-1.txt
reviewer-repair-1.txt
```

## Deterministic completion

Python freezes the comparison base to a commit SHA, enforces process deadlines,
verifies test counts, and requires the Reviewer's single final verdict line.
At most three repair cycles run. Progress snapshots are written atomically;
READY_FOR_PLAYTEST requires a zero test exit code, verified nonzero passing
counts, no failures, Reviewer PASS, and all six completed roles.
Reporter supplies the only final notification text. Python validates it exactly
before displaying/dispatching it. BLOCKED or failed notification delivery returns
a nonzero CLI exit status. Artifacts are stored under a repository path hash and
unique run ID outside the target worktree.

## Explicit publishing extension

After the existing Helper stage and local READY_FOR_PLAYTEST gate, --publish-pr
allows Python to authenticate, commit a frozen validated snapshot, conditionally
push the owned foxforge/* ref, and create/reuse a PR to dev. Reporter remains the
last role and receives only verified public metadata. Python validates that
metadata against persisted RunState before any Discord dispatch. Publishing
failures and local validation status remain distinct; partial side effects are
persisted and never automatically reset. No agent gains Git lifecycle tools or
GitHub credentials, and no automatic main integration is implemented.
