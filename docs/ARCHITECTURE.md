# Architecture

## 0.3.1 platform boundaries

The existing control plane remains a small Python application with SQLite,
static capability definitions and deterministic authorization. `configuration.py`
loads operator-owned task/model policies and protected credential files.
`platform_contracts.py` names task categories and approval scope data; it does not
authenticate approvals or execute tools. Future adapters must implement identity,
scope, freshness, single-use and audit gates outside models. No separate research
or infrastructure orchestration service has been added.

`model_requests` is an additive schema-1 table. Every inference attempt reserves
its request and conservative token units in an immediate transaction before HTTP,
binds the operator policy for the task, and records a sanitized outcome. Unknown
or interrupted consumption is not refunded. Task states refuse automatic resumes
from blocked/terminal states. SQLite is local to one host; backups require all
writers to be quiesced for artifact consistency.

The container entrypoint exposes only diagnostics, storage, capabilities, project
registration, issue discovery and planning. It cannot route to the legacy worker.
Model output is strict proposal data and never reaches a command executor.
FreeLLMAPI is a distinct trusted gateway with separate credentials and storage.
Its provider-side routing/probes are not FoxForge request-budget measurements.
Workload priority scheduling, coding workers, infra tools, research, dashboards,
notification transports and privileged execution remain future work.

## Adaptive planning foundation

The version 0.3 planning path is a separate control-plane entrypoint. A central
capability catalog describes domains, task types, tool operations, risk classes,
and permission profiles. Models may select registered capabilities in a strict
acyclic plan; Python rejects unknown capabilities and never treats the selection
as permission to execute a tool.

SQLite stores registered project identity, issue revision snapshots, numeric
actor authorization evidence, one task per authorization, task state, and audit
events. Repository discovery reads a fixed Git commit and does not execute
repository code. Planning stops at `awaiting_human_review` and writes deterministic
JSON and Markdown artifacts. See [FOUNDATION_DEPLOYMENT.md](FOUNDATION_DEPLOYMENT.md).

The catalog already distinguishes development and documentation domains and the
`read`, `propose`, `write`, `deploy`, and `high_risk` classes. Infrastructure
adapters are intentionally absent. Future adapters must pass the same external
authorization and audit boundary rather than adding privileges through prompts.

Issue intake is an outer Python layer: immutable IssueTask snapshots, bounded
IssueAPI calls, external OS locks/reservations, and a CLI router feed a prepared
RunState into the existing coordinator. Internal hooks validate the claim before
publication and synchronize deterministic issue results after strict Reporter
validation. A sequential watch loop calls the same manual execution path. No
agent or issue prose controls Python policy, Git, credentials or repair limits.
See [ISSUE_INTAKE.md](ISSUE_INTAKE.md) for the lifecycle and recovery boundaries.

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
