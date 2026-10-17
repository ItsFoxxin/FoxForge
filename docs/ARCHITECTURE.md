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
