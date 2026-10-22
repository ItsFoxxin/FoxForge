# Security

## Adaptive planning authorization

The planning foundation separates issue authors from trusted approvers. Reading
and storing an issue invokes no model. Planning requires a current
`foxforge:plan` label applied by an allowlisted numeric GitHub user with verified
repository write, maintain, or admin permission. Approval is bound to the issue
revision and must be no older than seven days; later issue activity requires a
fresh label event. FoxForge re-reads the issue after validating the event and
refuses task creation if the issue changed during that check. A consumed
approval creates at most one durable task.

Planning uses only commit-pinned repository reads. Capability and tool risk are
registered in Python; model output cannot grant write, deployment, infrastructure,
or credential access. The current milestone does not execute repository code.
The optional planner endpoint receives selected repository context, so operators
must approve its provider and data policy before a live run.

## Issue intake

Issues are untrusted external requirements. Both issue author and ready-label
actor must have immutable numeric IDs in FOXFORGE_ALLOWED_GITHUB_USER_IDS.
Missing/malformed allowlists fail closed; usernames/ownership cannot bypass it.
Unauthorized authors cause no claim, task fetch/branch, publishing or Qwen run.
Public Issue Forms must not automatically apply ready; the supplied form does
not. Foreign comment content/markers are ignored for bot comment deduplication;
future comment dispatchers must use authorize_comment_command() before parsing
or changing state. That gate does not implement retry/resume execution. Python
alone owns claims, labels, deterministic issue comments, Git and final gates.
Issue prose cannot configure commands, credentials, YOLO, protected branches or
the three-repair cap. GitHub/Discord credentials remain absent from Qwen/test
environments. Intake fetch and push use temporary App credentials with prompts
disabled; config/logs/state/keys stay outside targets. No Administration grant.

The numeric allowlist is also stripped from agent/test environments and omitted
from prompts. Author/approver IDs are audit state only. Changes to Windows User
configuration require restarting the worker; do not infer IDs from usernames.

OS locks and durable reservations coordinate same-user local workers. Separate
hosts/users are not a distributed lease. Uncertain writes, interrupted runs and
dirty blocked work stop for review; no automatic resume/reset/delete exists.
See [ISSUE_INTAKE.md](ISSUE_INTAKE.md) for operating and sandbox limits.

## Secrets

Never store these in the repository:

- Discord webhook URLs
- GitHub App private keys
- GitHub access tokens
- API keys
- private SSH keys

Use environment variables or an OS-backed secret store.

## Discord

FoxForge reads:

```text
DISCORD_WEBHOOK_URL
```

The Reporter does not receive or use the webhook. Python performs dispatch after
validating Reporter output against verified run state.

## GitHub App

GitHub App publishing uses:

- repository-scoped installation
- least-privilege permissions
- short-lived installation access tokens
- a private key stored outside the repository

See `GITHUB_APP.md`.

## Agent permissions

Each `.qwen/agents/*.md` file has an explicit tool allowlist.

Read-only roles do not receive edit or shell tools.
Reporter receives no tools.

The parent delegation wrapper should only need the Agent tool.

## Merge authority

FoxForge should not auto-merge to `main`.

With explicit --publish-pr, Python may perform:

```text
create foxforge/* branch
commit
push
open PR -> dev
stop
```

## Enforcement limits

The parent wrapper uses default approval mode and preapproves the Agent tool;
there is no YOLO fallback. Read-only roles are checked for tracked/untracked Git
diff changes, and every role is checked for branch/HEAD changes. These checks
reject detected violations but do not roll back agent edits or Git operations.
Qwen tool allowlists are not an operating-system sandbox: edit/shell roles still
require a trusted, disposable target and local verification of Qwen permission
behavior. Ignored files, external files, submodules, and binary content are not
fully protected by these Git diff checks. Do not expose unrelated secrets to an
agent process. Python removes DISCORD_WEBHOOK_URL from agent/test environments.

All notification CLI aliases route through Reporter/state validation. The
low-level Python HTTP function remains an internal transport, not a standalone
arbitrary-message CLI. Webhook dispatch is mocked in CI; normal checks send no
Discord messages. GitHub App authentication and opt-in publishing are implemented in Python; live use still requires local verification.

## Publishing credentials and authority

GitHub App RSA signing uses PyJWT[crypto]. Installation tokens are scoped to the
expected repository and permissions, cached in memory, and refreshed before
expiry. Signing/auth errors discard response bodies and secret exception data.
No JWT, token, key content, or authenticated remote URL is written to RunState,
helper files, Git config, logs, Reporter facts, or Discord. Known secrets, PEM
material, and recognizable GitHub tokens are redacted from outputs; leaked
agent/test output fails validation.

Qwen and authoritative test environments remove FOXFORGE_GITHUB_*, GITHUB_*,
GH_*, GIT_* credential/trace overrides, private helper variables, SSH agent/helper
variables, and DISCORD_WEBHOOK_URL. Host/system Git configuration and interactive
credential prompts are disabled for these children. Model provider credentials
needed by Qwen are not treated as publishing credentials.

Python alone commits/pushes. It uses API-derived bot identity per command,
external temporary token-free ASKPASS helpers, disabled Git hooks/signing,
explicit current-branch/HEAD/content checks, canonical GitHub HTTPS destinations,
and expected-ref leases after ancestry/ownership checks. Remote branches without
an owned dev-targeting FoxForge PR are not overwritten. No direct dev, main, or
master push, PR merge, release, or deployment is enabled.

The App private key must be outside every target before agents start. Environment
stripping does not sandbox a same-account shell/file tool: isolate untrusted
repositories and model processes from unrelated credential files. Runtime run
JSON is not signed against hostile local modification, and one worktree must
not be shared by concurrent tasks. See GITHUB_APP.md for manual verification and
partial-failure/ownership limitations. Normal tests mock all GitHub HTTP/pushes.
