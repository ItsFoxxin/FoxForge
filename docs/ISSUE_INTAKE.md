# GitHub Issue intake and unattended worker

Python retrieves approved issues, snapshots exact original title/body, claims
the issue, and calls the existing coordinator. Six fresh Qwen roles, Python
tests/counts, exact Reviewer/Reporter validation and the three-repair cap remain
unchanged. Python owns Git, labels, deterministic comments, publishing and
Discord dispatch. Issue prose is untrusted requirements, never Python policy.
This page documents the legacy implementation intake retained in 0.3.0. The
planning-only `foxforge:plan` path is documented separately in
[FOUNDATION_DEPLOYMENT.md](FOUNDATION_DEPLOYMENT.md).

## Setup and permissions

The App needs Metadata read, Contents read/write, Pull requests read/write, and
**Issues read/write**. Administration is not required. Accept updated App
installation permissions. Keep FOXFORGE_GITHUB_APP_ID,
FOXFORGE_GITHUB_INSTALLATION_ID and FOXFORGE_GITHUB_PRIVATE_KEY in the operator's
environment. The last is a PEM file path outside targets. DISCORD_WEBHOOK_URL
is optional with --skip-discord. Never put credentials in issues or worker JSON.

**Mandatory actor authorization:** configure
`FOXFORGE_ALLOWED_GITHUB_USER_IDS` with your verified immutable numeric GitHub
user ID. Multiple comma-separated positive IDs are supported, with surrounding
spaces allowed. Example only: `12345678,87654321`; replace these with actual
approved account IDs. Missing, empty, malformed or nonnumeric entries stop
intake before client creation/task work. No username or owner-name bypass exists.
For the background launcher, set this as a Windows User environment variable,
then restart the worker from a fresh environment after changing authorization.
The allowlist is removed from all Qwen/test child environments.

Create these labels before running:

| Label | Meaning |
| --- | --- |
| foxforge-ready | Explicit approval for a new attempt |
| foxforge-running | Claimed; never assume it is safe to restart |
| foxforge-blocked | Could not safely finish; preserved work needs review |
| foxforge-complete | Local validation, publishing, Reporter validation and issue synchronization succeeded |

Eligible issues are open, not PRs, with only ready among those four labels.
Other labels are preserved. The issue author's server-returned numeric user ID
must be allowlisted before claim, branch creation, dev fetch or Qwen invocation.
An unauthorized author remains unauthorized even with a ready label applied by
an approved owner. Watch skips it and logs only a safe unauthorized result.
The latest ready-label event must also have an allowlisted actor ID, plus the
existing owner/write-collaborator permission check. Missing/unreliable label
actor evidence fails closed; it never substitutes for author authorization.

For public repositories, do **not** auto-apply foxforge-ready in the Issue Form.
The included `.github/ISSUE_TEMPLATE/foxforge-feature.yml` now follows this
policy. Recommended flow: approved user creates issue -> approved user reviews
and applies ready -> Python verifies both immutable actor IDs -> claim.

Issue comments do not rewrite original title/body or Python policy. Current
intake does not execute `/foxforge` comments. The shared
`authorize_comment_command()` gate checks the server-returned comment author's
numeric ID before parsing any command, including retry/resume/cancel and future
verbs. Unauthorized/malformed comments return no command and cause no state
mutation. Future dispatchers must use this gate and still enforce all claim,
retry/resume, branch and validation rules. An authorized retry is accepted by
the authorization gate only; no comment-based retry/resume feature is added.
Comment deduplication considers only the verified App bot's numeric identity;
foreign comments cannot spoof its markers or alter reporting state.

RunState records author/approver numeric IDs for audit, never the whole allowlist.
These policy facts are not added to Qwen prompts. Historical issue states lacking
verified IDs need intervention; no IDs are guessed from stored usernames.

Read-only verification (not performed live during implementation):

```powershell
python -m foxforge.github_app --check --issues --repository ItsFoxxin/FoxForge-issue-smoke
```

This verifies repository/permission grants and prints only safe metadata. It
does not claim an issue or test write operations.

## Manual execution and polling

Prepare a clean disposable clone with origin/dev, the App installed, canonical
project agents/settings and working local Qwen/models. Keep the tool venv, keys,
configuration, logs and artifacts outside the target. The test command is a
trusted operator choice; issues cannot set it. Use an absolute test Python path
when a particular venv is needed.

```powershell
python -m foxforge issue 47 `
  --repo C:\Projects\FoxForge-issue-smoke `
  --test-command "python -m pytest -v" `
  --publish-pr --skip-discord

python -m foxforge watch `
  --repo C:\Projects\FoxForge-issue-smoke `
  --test-command "python -m pytest -v" `
  --publish-pr --poll-interval 60 --skip-discord
```

Installed console commands `foxforge issue` and `foxforge watch` accept the same
options. Explicit --publish-pr is required; credentials alone never publish.
Add **--once** to watch for a bounded test: at most one eligible issue, or none.
Poll intervals are 10–86400 seconds. Selection is oldest creation timestamp,
then issue number. Paginated scans are bounded at 10,000 rows and fail closed
beyond that. One issue runs at a time per worktree; success returns to polling.
Blocked work, dirty state, uncertain claims or API failures stop for review.

Execution stages:

1. Validate origin, worktree, key location, issue and owner approval. Acquire
   per-worktree and repository+issue OS locks; check durable records, RunState,
   local/tracking/remote issue branches, open PRs and GitHub cross-references.
2. Save exact requirements, identity, labels, timestamps, requirements hash and
   approver before any claim write. Reserve a new run ID externally.
3. Add running/remove ready, verify labels, and comment the run/branch facts.
4. Fetch dev with temporary App credentials and Git prompts disabled. Create
   foxforge/47-static-coil from origin/dev. Run the existing coordinator.
5. Recheck requirements/open state/exclusive running label before commit, push
   and PR creation. Publish through the existing layer, targeting dev only.
6. After strict Reporter validation, comment deterministic results, update to
   complete/blocked, and send validated Reporter text to Discord unless skipped.

Python issue comments never copy free-form agent claims. Counts must be verified;
PR URLs come only from validated publishing metadata; reviewer summaries use
the exact verdict enum. Reporter remains the only agent producing notification
text and includes the verified issue URL. Issues stay open: complete is a label,
not an automatic close or merge. No direct dev/main/master push is enabled.

## Edits, interruption and retries

Title/body are never model-rewritten, stripped or silently truncated. Original
updated_at plus a SHA-256 title/body revision are saved. Own labels/comments
can change updated_at without invalidating requirements. Material edits,
closure or claim revocation block publication at the next check. Oversize or
credential-bearing requirements are rejected.

Three failed repairs means BLOCKED, no fourth repair, no test/requirement
weakening, and preserved branch/worktree/artifacts. The normal blocked path
comments verified facts, adds blocked/removes running, sends a validated BLOCKED
notification and exits nonzero. Reporter failure cannot authorize Discord;
Python can still post safe issue facts. Uncertain issue writes suppress success
notification and retain intervention state.

For a new attempt after a verified blocked run: clarify as needed, remove
blocked and reapply ready as owner. A clean worktree is required. A new run ID
and foxforge/47-static-coil-retry-2 preserve earlier work. Only known unchanged
local branches from verified blocked attempts are allowed. Unknown branches,
partial commits/pushes, remote issue branches, associated open PRs or uncertain
records require inspection first. Completed issues are not silently replayed.

Ctrl+C idle records STOPPED. During a task it records INTERRUPTED, preserves
running labels and returns 130. Restart reports the matching local run ID, or
missing trustworthy state, and refuses duplication. No resume feature exists.

Locks/reservations live under %LOCALAPPDATA%\FoxForge\intake on Windows or
~/.foxforge/intake elsewhere, independently of FOXFORGE_RUNS_DIR. Changing output
locations does not erase reservations. Artifacts retain the existing external
run root. Do not delete records to force restarts.

GitHub labels are not a distributed atomic claim API. This version supports one
operator/OS account on one worker host; do not run separate hosts/users against
the same queue. Issue edits cannot be transacted with Git pushes. A late edit
or lost response may leave a commit/push/PR completed before later failure.
Checkpoints retain verified facts; no automatic rollback/reset/delete occurs.

## Gaming laptop: phone-based routine use

Worker and Qwen stay on the laptop. After one-time setup, submit/approve issues
from your phone and inspect GitHub/Discord results. This chat, a visible terminal
and an open lid are unnecessary per task. The laptop must remain awake, powered,
online, with its model service available. Sleeping/off means issues wait.

For plugged-in operation, manually choose lid action Do nothing and sleep Never;
battery sleep can remain enabled. Keep ventilation available. This implementation
changes no power, startup, firewall, account or remote-access settings.

1. Install FoxForge in an external tool venv and prove the manual disposable run,
   including actual Qwen role permissions without YOLO.
2. Copy templates/worker-config.example.json to C:\FoxForge-worker\worker.json.
   Set local target, absolute Python and test command. publish_pr=true is your
   explicit publishing approval. Start with skip_discord=true. No secrets in JSON.
3. Validate without starting the worker or making network requests:

```powershell
powershell.exe -NoProfile -NonInteractive -File C:\Tools\FoxForge-source\scripts\start-worker.ps1 `
  -Config C:\FoxForge-worker\worker.json -ValidateOnly
```

4. Create a Task Scheduler task under the account holding Qwen config and App
   User variables. For startup without unlocking after reboot, choose Run whether
   user is logged on or not and At startup. Enter a password only in Windows'
   own prompt, never source/config. FoxForge does not need highest privileges.
   Set Start in to C:\FoxForge-worker and use:

```text
Program: powershell.exe
Arguments: -NoProfile -NonInteractive -WindowStyle Hidden -File "C:\Tools\FoxForge-source\scripts\start-worker.ps1" -Config "C:\FoxForge-worker\worker.json"
```

Choose Do not start a new instance, remove the default execution-time limit for
this long-running task, and avoid automatic failure-restart loops. Interrupted
claims need review. Review plugged-in/network conditions as intended.

The launcher refreshes existing App/Discord User variables only into process
environment, runs installed Python in isolated mode from an external directory,
and appends worker.log beside external config. The model service must work in
the noninteractive session; a tray app available only after login is insufficient
for cold boot. Verify actual Qwen/model/GPU behavior there. Denied/unavailable
roles fail or time out; prompts are never bypassed with YOLO. No task/model
service was installed or tested live during implementation.

Blocked work can still need human review, potentially through separately
configured remote access. FoxForge does not enable that access or erase failed
work to avoid intervention.

## Recommended live smoke sequence (manual only)

1. Use ItsFoxxin/FoxForge-issue-smoke with dev containing examples/calculator,
   four labels, installed App and canonical local agents. Avoid production first.
2. Run read-only --check --issues. As owner, create #47 with precise calculator
   behavior/tests and ready; run the manual command above.
3. Check original snapshot, claim, bot commit/branch, verified counts, PR base=dev,
   result comment and complete label. No merge/release/deployment occurs.
4. Test an issue edit before publishing, three failed repairs, a clean approved
   retry, --once with no eligible issue and --once with one issue.
5. Validate/start the launcher, lock the laptop/close the terminal, and submit
   from your phone. Verify the scheduled task/model after reboot before relying
   on closed-lid operation. Interrupt a run and confirm restart refuses a duplicate.
6. Inspect facts before enabling Discord. Close disposable PRs manually; do not
   merge them as part of this smoke test.

Live GitHub/App, Qwen/GPU, Discord, scheduling/lid behavior and Linux execution
remain separate unverified boundaries. Environment stripping is not an OS
sandbox: same-account file/shell tools may read unrelated files. Protect keys
and isolate untrusted projects/processes.

Protocol references: [issues](https://docs.github.com/en/rest/issues/issues),
[labels](https://docs.github.com/en/rest/issues/labels),
[events](https://docs.github.com/en/rest/issues/events),
[collaborator permissions](https://docs.github.com/en/rest/collaborators/collaborators#get-repository-permissions-for-a-user),
[App permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps).
