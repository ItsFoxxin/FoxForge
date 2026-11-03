# Qwen agents and legacy orchestration audit — 0.3.1

Reviewed against `dev` base `358b252` and this release's feature branch. This is a
source and test audit, not a live Qwen execution certification. The six agent
files, installer, legacy CLI, state format and publishing workflow remain in
place. No worker service, agent removal or automatic migration is implemented.

## Decision

Keep the Python control plane and the existing planning foundation. Preserve Qwen
as a legacy, explicitly opted-in execution path outside the control-plane image.
Move execution behind a separately authorized, isolated worker in 0.4.x before
connecting adaptive plans to implementation. A gateway supplies model inference;
it does not supply a safe editing, shell, testing or Git runtime.

The current legacy coordinator is a fixed six-role pipeline. It is **not** the
future adaptive orchestrator. Reuse its safety invariants and tested utilities,
not its mandatory role ordering, as the basis of the new scheduler.

## Source inventory and actual execution

| Source | Responsibility and dependency | Recommendation |
| --- | --- | --- |
| [`agent_runner.py`](../foxforge/agent_runner.py#L34) | Finds `FOXFORGE_QWEN_EXE` or `qwen`; constructs CLI arguments, stdin prompt and `AgentResult` | Retain as a future Qwen-specific worker adapter, not the universal model interface |
| [`coordinator.py`](../foxforge/coordinator.py#L158) | Creates run, invokes roles, tracks branch/HEAD, tests, repairs, validates/report/publishes | Preserve legacy behavior; extract invariants into future worker/controller boundaries |
| [`process.py`](../foxforge/process.py#L23) | Blocking subprocess, UTF-8 pipes, process-group deadline/interrupt cleanup | Reuse inside workers after output/resource bounds; never expose as a model tool in the control plane |
| [`test_runner.py`](../foxforge/test_runner.py#L30) | Operator command parsing, process launch, supported test-summary verification | Worker-only execution; preserve zero-exit/nonzero-tests gate |
| [`git_manager.py`](../foxforge/git_manager.py#L43), [`publishing.py`](../foxforge/publishing.py#L146) | Local Git lifecycle; Python-owned commit/push/PR, content and ownership checks | Retain utilities; isolate writes and credentials from model/test processes |
| [`issue_intake.py`](../foxforge/issue_intake.py#L210), [`issue_api.py`](../foxforge/issue_api.py#L80) | Legacy ready-label eligibility, claims, sequential polling, retry history, comments | Keep separate from planning; later consolidate verified event logic, not execution authority |
| [`state.py`](../foxforge/state.py#L12), [`state_validator.py`](../foxforge/state_validator.py#L8) | Legacy `RunState`, atomic snapshots, exact completion/report validation | Preserve readable history; do not import role-order requirements into adaptive tasks |
| [`intake_storage.py`](../foxforge/intake_storage.py#L16), [`run_storage.py`](../foxforge/run_storage.py#L9) | External local JSON records, exclusive local locks, per-repository/run artifacts | Keep for legacy; later reference existing runs from SQLite, never silently merge stores |
| [`security.py`](../foxforge/security.py#L20), [`github_app.py`](../foxforge/github_app.py#L111) | Redaction, child credential filtering, App tokens/scopes/identity | Reuse, while adding OS boundaries; redaction alone is not secret isolation |
| [`reporter_dispatch.py`](../foxforge/reporter_dispatch.py#L15), [`notifier.py`](../foxforge/notifier.py#L10) | Validate exact report against persisted facts before Python Discord transport | Reuse transport and canonical report validation; no notifications sent during review |
| [`templates/qwen-agents`](../templates/qwen-agents), [`qwen-settings.json`](../templates/qwen-settings.json) | Six Qwen frontmatter/prompts, model IDs and delegation permission | Keep versioned assets; future installer materializes central profiles for Qwen only |
| [`install-target.ps1`](../scripts/install-target.ps1), [`start-worker.ps1`](../scripts/start-worker.ps1) | Copy templates/settings; launch opt-in Windows poller from external config | Preserve; Windows-specific tooling is not the Debian container scheduler |
| [`control_plane.py`](../foxforge/control_plane.py), [`foundation_cli.py`](../foxforge/foundation_cli.py), [`capabilities.py`](../foxforge/capabilities.py) | New SQLite planning tasks, authorizations/audit, central capability catalog | Authoritative foundation for new work; no bridge to legacy execution in 0.3.1 |
| [`planning_provider.py`](../foxforge/planning_provider.py), [`plan_schema.py`](../foxforge/plan_schema.py) | Bounded OpenAI-compatible request; strict capability/dependency-plan validation | Model transport and proposal parser, not agent runtime |

### Invocation and handoffs

`run_project_agent` accepts only six role names, requires the corresponding target
`.qwen/agents/<role>.md`, and requires parent approval mode `default`. Each call
starts a fresh Qwen process in the target repository. The parent receives only
`agent` as its core/allowed tool, a subagent-depth limit of 1 and a wall-time
limit (default 20 minutes). Prompts go through stdin, not command arguments.
Windows `.cmd` launchers have explicit quoting/path checks. Python independently
kills the process group on timeout and treats timeout as failure.

The wrapper **asks a model** to delegate to the named foreground project agent.
FoxForge does not inspect a structured tool trace to prove which agent actually
ran. `AgentResult` contains role, exit code, stdout/stderr and elapsed time, not
provider/model identity, tool events, token consumption or verified delegation.
A role file's existence is checked; its contents, settings, extensions and hooks
are not attested at invocation. Template tests do not validate arbitrary installed
repository configurations. The installer refuses existing agent files unless
`-Force` is explicit and preserves an existing settings file unchanged.

The sequence in [`coordinator.run`](../foxforge/coordinator.py#L303) is:

1. Architect proposal → implementer, using the original task plus architect text.
2. Tester changes tests; Python runs the configured authoritative test command.
3. Reviewer receives counts and tester text, and returns one final exact
   `REVIEW_RESULT: PASS` or `REVIEW_RESULT: FAIL` line.
4. Up to three repairs repeat implementer → tester → Python tests → reviewer.
   Repair input includes full prior test output and reviewer text.
5. Helper drafts support material from Python's facts. Python optionally publishes
   after validation. Reporter formats the final facts; Python validates and sends.

Task prose and model outputs are relayed as strings, not shared typed contracts.
No peer-to-peer protocol or concurrent role execution exists. The wrapper now
labels relayed content as untrusted instead of calling it "verified context";
this clarification is not a security boundary. The architect proposal is not
human approval, even though the previous handoff described it as approved.

## Evaluation of the six roles

The following tools are declared in the shipped frontmatter, not OS permissions.
All six roles are currently mandatory for successful legacy completion.

| Role / template | Model and approval mode | Declared tools | Future capability mapping |
| --- | --- | --- | --- |
| [`architect`](../templates/qwen-agents/architect.md) | `qwen3.5:9b-q4_K_M`, `plan` | read_file, grep_search, glob | `architecture.planning`; reusable reasoning, runtime-independent output |
| [`implementer`](../templates/qwen-agents/implementer.md) | same model, `auto-edit` | read_file, edit, write_file, grep_search, glob, run_shell_command | `development.general` in a scoped writable workspace |
| [`tester`](../templates/qwen-agents/tester.md) | same model, `auto-edit` | same six tools | `quality.assurance`; distinguish test authoring from trusted validation execution |
| [`reviewer`](../templates/qwen-agents/reviewer.md) | same model, `plan` | read_file, grep_search, glob | `code.review`, independent read-only candidate review |
| [`helper`](../templates/qwen-agents/helper.md) | `qwen2.5-coder:7b`, `plan` | none | Optional documentation/summary capability; not a generic shell/tool authority |
| [`reporter`](../templates/qwen-agents/reporter.md) | `qwen2.5-coder:7b`, `plan` | none | Optional natural-language presentation; Python retains factual status and transport |

Keep the useful specialization and restrictive defaults. Model IDs and Qwen
frontmatter are backend preferences, not central capabilities. Do not assume
these local model IDs exist at FreeLLMAPI or support reliable tool calls.
The helper's draft is saved, but publishing derives the actual commit subject
from issue/task text in Python; it does not consume the helper draft as authority.
A future optional specialist interface can replace the mandatory helper step.
Reporting can use deterministic rendering where exact facts suffice, with optional
model summaries. Neither helper nor reporter should gain general tools merely to
justify an agent role. No roles are deleted or bypassed in this release.

## Security findings

Severity describes using the legacy runtime on untrusted repositories, not a
claim that the planning-only image currently exposes that runtime to a model.

| Finding and evidence | Impact | 0.3.1 disposition / required migration |
| --- | --- | --- |
| **High: no execution sandbox.** `agent_runner.run_project_agent`, `test_runner.run_tests`, `process.run_process` set cwd/environment but no filesystem, UID, network or container isolation | Shell/test code can access anything the caller can access, including files outside the checkout | Keep out of control plane. Dedicated low-privilege worker VM/container, restricted mounts/egress and no control-plane secrets are prerequisites for future execution |
| **High: mutable runtime configuration.** `agent_runner.py` checks role file existence; installer keeps custom settings; Qwen reads project configuration | Repository instructions, agent files or Qwen hooks/settings can change execution behavior; prompt/tool lists are insufficient against hostile configuration | Review installed legacy configuration manually. Future worker uses centrally versioned adapter configuration, approved profile hash and disabled/unapproved customization channels |
| **High: credential isolation is incomplete.** `security.child_environment` strips GitHub/planner/Discord env, but retains most host variables and has no file boundary | Same-account file/shell/test tools may read private keys outside the repository, other provider credentials, or local state; moving a key outside the repo is insufficient | No control-plane credentials or writable audit store on workers. Use explicit child env allowlist and scoped inference credential in future; do not blindly remove credentials required by the existing Qwen backend |
| **High: separate approval systems.** `ready_approval` has no `not_before` or maximum age, unlike `foundation_cli.plan_task` | Legacy ready label can predate a material issue edit before claim; initial `--publish-pr` is broad opt-in, not a new per-action human approval | Never map `foxforge:plan` to legacy execution. Keep legacy approvals explicitly separate; require revision-bound, expiring, action-scoped authorization before future worker rollout |
| **Medium: changes detected after execution.** `coordinator.require_agent` checks branch/HEAD and compares diff before/after read-only roles | Cannot prevent ignored/outside-repo writes, temporary changes restored before check, or destructive shell commands. Tester-only/production-only writes are prompt rules | Preserve checks as defense in depth; enforce worker mounts/path access and validate actual patch, including symlinks, before integration |
| **Medium: tests and local state share the execution trust domain.** `state.save`, `intake_storage`, `test_runner` | Same UID can alter JSON or tests; a supported-looking test summary can be forged. Reviewer PASS is a model judgment | Future controller-owned audit/leases plus independent trusted CI against exact candidate SHA; local results remain evidence with provenance |
| **Medium: no total run budget/output bound.** `coordinator.REPAIR_LIMIT`, `process.communicate`, text handoffs | Retries are bounded, but aggregate latency/tokens and captured output are not; large output can exhaust memory/context | Keep bounded repair/deadline behavior; add controller-owned total budgets and bounded artifact references before future workers |
| **Medium: Git code execution surface.** `git_manager.run_git`, `publishing.commit_validated_changes` | Disabling hooks/fsmonitor/signing and checking auth overrides reduces risk, but local Git filters/config remain executable behavior; test commands execute arbitrary project code | Do not perform legacy staging/checkouts on the control plane. Future worker sanitizes configuration and validates patches in isolation; broker writes using separate credentials |
| **Low: relayed prose overstates trust.** Wrapper called model context verified; implementation handoff called architect text approved | Confuses model proposals with verified facts and approval | Corrected labels in 0.3.1; strict deterministic authorization still required |

Publishing already has valuable controls: opt-in `--publish-pr`, `foxforge/*`
branch validation, dev-targeting PR ownership, App-derived bot identity, frozen
HEAD/tree checks, expected-ref push lease plus ancestry checks, credential-like
file/content rejection, and persisted partial side effects. Tokens are ephemeral
in child environment/ASKPASS rather than remote URLs/argv. No merge or production
deploy is implemented. These controls do not prevent a same-user agent from
attempting its own network/Git operations with credentials it can otherwise read.

Issue intake checks numeric author/approver allowlists, current label events and
collaborator permissions, origin and running claims, and rechecks the material
issue revision before publishing. It reserves history under local locks and does
not blindly retry ambiguous remote POSTs. `foxforge-ready` execution and
`foxforge:plan` proposal authorization remain different operations. There is no
new webhook receiver or automatic event-to-execution authorization in this release.

### Immediate scoped changes

- The image sets `FOXFORGE_CONTROL_PLANE_ONLY=1`. Legacy coordinator, issue/watch,
  agent/test launch and publishing entrypoints (including commit/push/fetch/PR
  primitives) fail before preflight or side effects when the variable is present.
  The allowlisted container CLI, read-only repository/config mounts and lack of
  Qwen/host socket are additional boundaries. Direct Python imports cannot bypass
  these supported entrypoints. An administrator can replace the image/environment;
  this is deployment-mode enforcement, not a sandbox for arbitrary Python code.
- Clarify untrusted relayed context and architect proposal wording. No new tools,
  model grants, role changes or legacy state conversions are added.
- Test direct entrypoint rejection even with malformed inputs, fail-closed mode
  values, unchanged legacy behavior when the flag is absent, and real-image
  rejection of an imported test launcher. Preserve existing gate tests.

Legacy venv execution remains opt-in and is **not certified for hostile code**.
Do not run it using the control-plane service account, credential directory or
production/Proxmox/Docker access. The new image never invokes repository tests or
AI shell commands; discovery reads bounded commit-pinned Git objects only.

## Provider-independent design (0.4.x proposal, not implemented)

Keep three responsibilities distinct:

- **Capability:** central intent/output contract and required operation risks,
  such as `architecture.planning`, `quality.assurance` or documentation proposals.
  A capability declaration is never an authorization grant.
- **Model adapter:** inference transport, explicit model/provider policy, context
  limits, structured validation, measured/unknown usage and compatible fallback.
  FreeLLMAPI belongs here. The current OpenAI-compatible planner does no tool loop.
- **Worker runtime adapter:** OS-isolated workspace, deterministic tool broker,
  model/runtime interaction, patch/evidence collection and cancellation. Qwen
  Code can be one adapter; an alternative coding runtime or optional Codex adapter
  must satisfy the same external policy and isolation contract.

Use one small Python controller initially. Add a worker protocol only when a real
worker is introduced. Do not add a runtime factory, queue service or second
orchestrator merely for speculative integrations. Existing `platform_contracts.py`
is scope vocabulary, not an implemented remote authorization protocol.

The proposed language-independent wire envelope uses versioned JSON with strict
unknown-field/size checks. No Python objects, executable pickles or model-created
commands are accepted as worker authority:

| Message | Required content and checks |
| --- | --- |
| Assignment | protocol version; task/subtask and attempt IDs; correlation/lease ID; registered repository numeric ID; exact base SHA; worker-owned workspace ID; central capability/profile version/hash; approved task/action/target/parameter digest; allowed tool operation IDs and paths; deadline, request/token/retry/delegation limits; relevant-file/artifact references and interface-contract hashes |
| Acceptance/checkpoint | authenticated worker identity; lease/sequence; pinned SHA; accepted policy/profile; real milestones; bounded artifact digests; consumed/reserved budgets; structured failure class. Controller persists before dependent work advances |
| Result | attempt/lease, base/candidate SHA, patch manifest/digest, actual model/provider/runtime versions, success/blocked/error reason, per-tool target/outcome/duration and redacted parameters digest, test command provenance and exit/evidence, measured usage or explicit unknown, artifact digests |
| Cancel/approval | task/attempt/action/target/parameters scope, expiry, verified actor and replay protection. Models cannot mint, enlarge or approve assignments |

The controller checks transport identity, authorization freshness/scope, worker
capability, concurrency and resource reservations before dispatch. Workers enforce
allowlists locally and reject broader model requests. An assignment is inert
until accepted under a live controller lease; replayed/stale attempts cannot
publish. Untrusted output is independently parsed and validated before storing
or integrating it. Audit every tool attempt with correlation/sequence, decision,
operation/target, redacted parameters or digest, outcome and artifact references;
keep secrets and raw sensitive output out of logs. Tool-operation evidence must
come from the broker, not a model's claimed history.

A worker never receives App private keys or installation write tokens. A future
separate publishing operation obtains explicit human approval for the exact
candidate SHA/action and uses a least-privilege controller-owned broker. CI must
run trusted workflow definitions without privileged secrets against untrusted
changes. Do not run an untrusted checkout just to integrate it on the controller.
Future documentation, research and infrastructure-read adapters can use the same
scope/audit contracts; read, propose, write and high-risk operations remain distinct.
Infrastructure alerts create discovered tasks, not resource authorization.

## Persistence and migration compatibility

Legacy runs use `RunState` JSON and output files under `FOXFORGE_RUNS_DIR` (otherwise
local-app-data/home), plus separate intake history and OS locks. Atomic replacement
protects against torn snapshots, not hostile modification. Interrupted work is
retained for intervention, not transparently resumed. The Windows worker polls
serially while holding its worktree lock; this is not distributed scheduling.
`foxforge/run-state.json` and `run-reporter.txt` are shipped sample artifacts, not
an active SQLite database or proof that the current checkout has been validated.

The newer planning path persists projects, discoveries, revision/event-bound
authorizations, task states, audit events and model-request reservations in SQLite.
It produces a validated dependency graph and stops at `awaiting_human_review`.
It does not read old run snapshots as execution authority. Do not merge old run
history into planning authorizations, reuse a ready label as a planning approval,
or interpret a reviewed plan as approved implementation. Preserve old histories
as immutable referenced artifacts with their original schema and provenance.

Qwen needs a CLI/runtime, its settings and compatible model routing; FreeLLMAPI
alone cannot replace it. No Qwen/Node/model runtime is added to the FoxForge image.
The legacy PowerShell installer/launcher stays in distributions for existing
users, but is not launched by Debian systemd discovery. New deployments use the
one-shot container and separate gateway; existing venvs remain independently
operational until the documented backup/candidate/approval migration gates pass.

## Performance and language recommendation

Keep Python. No benchmark here demonstrates that control-plane CPU is the
bottleneck. Inference/network, subprocess tests, repeated Git scans and provider
waits dominate the code's blocking paths. `watch` is sequential; each role starts
a fresh CLI process. This helps avoid cross-role conversation contamination but
repeats task/context loading. Repair handoffs copy unbounded test/reviewer text;
read-only role checks repeatedly compute whole diffs, and publishing fingerprints
read file contents. `communicate` captures full child stdout/stderr in memory.

At the default 20-minute agent/test deadlines, six initial role calls plus nine
repair calls and four test invocations permit roughly 380 minutes (6h20) of
serial subprocess time, excluding Git/API overhead. This is a bound calculation,
not a measured benchmark or a guarantee that all paths reach it. There is no
aggregate legacy token/request budget. The new planning ledger does not meter
Qwen descendants or gateway background probes.

Before replacing Python, measure per-stage model/CLI startup and inference latency,
request/tokens, context bytes, subprocess output, Git scan time, peak worker memory,
queue wait and useful completed work per resource unit. Prefer bounded artifact
references, commit-aware retrieval, optional delegation and short structured
handoffs. Later implement ready-DAG scheduling with fair per-project/global/provider
limits and separate workspaces; do not increase host concurrency over the legacy
shared worktree. A JSON protocol lets Go/Rust workers be introduced without
changing controller semantics; no new language dependency is justified now.

## Recommended implementation order and deprecation gates

1. **0.3.1:** ship the planning-only image, explicit storage/diagnostics, durable
   inference budget, narrow legacy guards and this audit. All six roles and legacy
   tests remain. Verify pinned gateway, backup/restore and migration manually;
   no execution adapter is connected.
2. **0.4.x worker prerequisite:** threat model and implement a single isolated
   worker with centrally pinned configuration, scoped inference access, no host
   sockets/control-plane secrets, limited filesystem/network/CPU/RAM/output, total
   deadlines/budgets and cancellation. Add authenticated lease/audit envelopes.
3. **0.4.x Qwen adapter:** move invocation into that worker; pin/verify an approved
   Qwen release and test real named-agent delegation, permissions, hooks/settings,
   provider/tool compatibility, child budget enforcement and failure recovery.
   Preserve installer customizations by inventory/hash and explicit operator review.
4. **0.4.x adaptive execution:** add bounded capability selection and ready-DAG
   dispatch, independent workspaces, actual Git conflict detection, integration CI,
   revision-bound execution approval and SHA-bound PR approval. Prove failed or
   quota-limited work does not stop unrelated tasks; do not mandate every role.
5. **Only after parity and explicit migration approval:** optionally deprecate the
   fixed coordinator, mandatory helper/reporter model steps, copied generic agent
   definitions and Windows polling launcher. Retain a read-only legacy-history
   viewer/export and a tested rollback path. Do not remove JSON validation gates
   until equivalent controller/worker tests and independent CI protect them.

Retain tests in `test_agent_runner`, `test_agent_definitions`, `test_coordinator`,
`test_process`, `test_test_runner`, `test_git_manager`, `test_publishing`,
`test_state*`, `test_intake_storage`, `test_issue_intake`, `test_actor_authorization`,
`test_reporter_dispatch`, `test_installer` and `test_worker_launcher`. New adaptive
tests should assert isolation, current validation, authorization, budget and
completion invariants, rather than copying the six-role sequence into the scheduler.

## Evidence and unverified boundaries

The suite exercises real temporary Git repositories, subprocess quoting/deadlines,
local state/locks and mocked model/GitHub/Discord flows. It does not invoke a real
Qwen model, confirm actual subagent tool enforcement, validate custom installed
settings, or test a remote isolated worker. Hosted container checks exercise the
real pinned gateway readiness/auth rejection without inference or live credentials.
A real approved provider's structured planning/tool behavior remains deployment
verification, not established by a green mock test.

The current official [Qwen subagent documentation](https://qwenlm.github.io/qwen-code-docs/en/users/features/sub-agents/)
explains tool allowlists and approval-mode inheritance. The
[headless documentation](https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/headless.md)
describes run limits and warns that automatic approval is not a sandbox. The
[configuration reference](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/)
documents wall-time, tool-call and nesting controls. These were consulted during
this audit; they are moving upstream references, not proof about an unspecified
locally installed CLI version. Pin and exercise the chosen release before worker
migration. In particular, a parent delegation count is not a verified accounting
of all tools or inference inside its child agent.
