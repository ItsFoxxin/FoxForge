# 0.3.1 review and deployment impact

Base: GitHub `dev` commit `358b252` (0.3.0 planning foundation plus the existing
delegation-wrapper fix). Feature branch: `feature/0.3.1-platform-foundations`.

## Reused components

The existing capability catalog, GitHub App authentication, trusted numeric actor
authorization, label/revision binding, duplicate-task protection, schema-1 core
tables, strict dependency graph, commit-pinned discovery and human-review
artifacts remain the foundation. Legacy venv commands and six Qwen agent assets
are retained; no new multi-agent sequence is introduced.

## Changes to review

- `Dockerfile`, `.dockerignore`, `compose.yaml`, `deployment/`: one-shot FoxForge
  runtime, separate FreeLLMAPI service, pinned images/dependencies, non-root UIDs,
  read-only credential/repository mounts and independent persistent data.
- `configuration.py`, `doctor.py`: exact variable names, explicit data/clone
  paths, protected key files, numeric identities, key format/permission checks,
  read-only database checks and optional authenticated model-list probing.
- `planning_provider.py`, `control_plane.py`: task model policy, route identity
  validation, durable request reservations and outcomes, bounded response size,
  retry ceilings, safe rate-limit/timeout failures and blocked-state recovery.
- `storage_ops.py`: non-overwriting SQLite backup and artifact verification;
  no automatic merge, restoration or database selection.
- `container_cli.py`, `repository_discovery.py`, `foundation_cli.py`: reject
  legacy execution dispatch inside the image, read direct Git blobs, constrain
  clone roots, and recheck numeric GitHub repository identity and local origin.
- `platform_contracts.py`: data-only task/tool/approval-scope vocabulary, with no
  privileged executor or new service. Existing artifacts/audits remain durable.

## Validation and required operational verification

Local Windows verification covers the full Python suite, dependency audit,
distribution build, offline wheel installation, installed CLI entrypoints,
model-free storage initialization/verification, offline approved planning, strict
configuration/provider failure tests and static Compose security assertions.
The Windows-specific skip is newline-containing filenames; POSIX key permission
tests run only on Linux. All provider/GitHub unit traffic is mocked.

The release workflow runs validation → Linux/Windows tests → distribution →
Linux container smoke. The container smoke tests non-root/read-only behavior,
SQLite persistence and task/artifact visibility across one-shot invocations,
rejected execution commands, and the actual pinned gateway's readiness and
unauthenticated-request rejection with synthetic configuration and no network.
Docker is unavailable in the local Windows editing session; hosted results must
be checked separately. No paid inference, provider accounts or live credentials
are used in CI.

The deployment operator must still validate the actual Debian VM, source and
image revisions, UID/ownership, egress firewall, GitHub App, selected free provider
terms, real JSON planning response and verified backup/rollback before migration.
Post-response provider validation is not a pre-dispatch provider firewall.
See [the deployment procedure](CONTAINER_DEPLOYMENT.md) for the full trust boundary,
explicit placeholder replacement, migration acceptance checklist and rollback.

## Compatibility and rollback

No core records or artifact paths are rewritten. Schema 1 gains only the
`model_requests` table; previous readers ignore it. Data paths are now required
and new installations need `storage init`. Live inference needs an operator model
policy. The venv stays at `/opt/foxforge` with `/etc/foxforge`; candidate host state
lives under `/var/lib/foxforge-container` and `/etc/foxforge-container` and is
mounted to the previous internal paths. Candidate clones are separate copies.

Migration remains manual: select the authoritative state, stop all its writers,
verify a consistent backup, exercise a separate candidate, obtain human approval,
then take a fresh backup and cut over to a new empty runtime path. A rollback
stops container writers and resumes the untouched old venv/database, retaining
post-cutover tasks in a separate verified archive with an explicit cutoff.

No automatic merge, live deployment, coding worker, shell tool, infrastructure
operation, production access, public dashboard or unattended remediation is added.

## Qwen legacy review

[The source-backed Qwen audit](QWEN_LEGACY_AUDIT.md) inventories the six roles,
invocation/handoffs, local state, tests/publishing, security limits and performance.
It separates model inference from worker runtime and proposes a versioned
language-independent worker protocol and staged 0.4.x migration. The fixed pipeline
and all six assets remain available outside the control-plane image. The image
sets `FOXFORGE_CONTROL_PLANE_ONLY=1`; direct legacy execution/publishing calls
are rejected before side effects as well as at CLI dispatch. This mode guard
supplements mounts/credentials and is not an arbitrary-code sandbox.

Remaining legacy risks include same-account shell/file access, mutable runtime
configuration, non-expiring ready approvals, unsigned local JSON and no aggregate
inference budget. Do not connect approved plans to that execution path. No
provider-independent execution runtime is implemented in 0.3.1.
