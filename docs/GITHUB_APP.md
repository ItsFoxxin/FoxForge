# GitHub App Publishing

## Issue intake permission

Issue intake also requires FOXFORGE_ALLOWED_GITHUB_USER_IDS, a comma-separated
allowlist of immutable numeric account IDs. Both the issue author and ready
label actor must be approved. No GitHub username or App installation permission
substitutes for this local policy. Missing/invalid values fail closed. This does
not change the permissions needed by ordinary non-issue task publishing.

The optional issue/watch workflow additionally requests **Issues: read/write**.
Existing Metadata read, Contents read/write and Pull requests read/write remain;
Administration is not required. Accept updated installation permissions.
`python -m foxforge.github_app --check --issues --repository owner/name` verifies
read-only issue permission grants. Normal task publishing does not request
Issues permission. Issue intake uses ephemeral App authentication for its dev
fetch as well as its push, avoiding host Git credential prompts. See
[ISSUE_INTAKE.md](ISSUE_INTAKE.md) for labels, owner approval, manual/polling
commands, mutation checks, partial failures and Windows background setup.

FoxForge supports explicit Python-owned publishing after local validation.
The six roles and three-repair limit are unchanged. The publishing step runs
after Helper and before Reporter, so Reporter receives verified publication
metadata. Local READY_FOR_PLAYTEST and publishing status are separate facts.

## Install and configure

Install from the checked-out source with Python 3.11+:

```powershell
python -m pip install -e ".[dev]"
```

The runtime dependency is `PyJWT[crypto]>=2.10,<3`; RSA signing is performed by
PyJWT and cryptography, not a custom cryptographic implementation.

Configure the GitHub App with repository permissions:

- Metadata: read (implicit)
- Contents: read and write
- Pull requests: read and write

Install it only on repositories FoxForge may publish to. Keep the RSA private
key (unencrypted PEM, at least 2048 bits) outside every target repository.
Configure these process/User environment variables without committing values:

```text
FOXFORGE_GITHUB_APP_ID
FOXFORGE_GITHUB_INSTALLATION_ID
FOXFORGE_GITHUB_PRIVATE_KEY
```

The private-key variable is a file path, not PEM contents. Open a fresh terminal
if User variables were created after the current shell started.
`DISCORD_WEBHOOK_URL` remains optional for notification delivery and is never
passed to Qwen or authoritative tests.

## Read-only authentication verification

```powershell
python -m foxforge.github_app --check --repository ItsFoxxin/FoxForge
```

This signs an RS256 JWT, checks installation ownership, exchanges it for a
repository-scoped token with **read-only** Contents/Pull requests permissions,
and queries repository metadata. The token exchange is an authentication POST;
no repository content, branch, PR, or installation settings are modified.
Only repository name, installation ID, and token expiry are printed. The JWT,
token, key path, key contents, and response bodies are not displayed.
The token is cached only in process memory and refreshed with less than one
minute remaining. Nothing is written to an authentication cache or Git config.

## Explicit publishing

```powershell
python -m foxforge `
  --repo C:\Projects\YourProject `
  --task "Implement the requested change and add regression tests." `
  --test-command "python -m pytest -v" `
  --create-branch `
  --branch-name foxforge/example-task `
  --base-branch dev `
  --publish-pr
```

Credentials alone never enable publishing. Without `--publish-pr`, the local
workflow stays local. Existing non-publishing CLI/report behavior is preserved.

Publishing requires verified nonzero passing tests, no failures, a zero test
exit code, a valid Reviewer PASS, at most three repairs, local
READY_FOR_PLAYTEST, and successful completion of the first five roles. Python
freezes HEAD and a content/mode fingerprint after authoritative tests, then
checks it before staging, commit, and push. A mutation after tests blocks the
operation. Only nonignored files are staged; credential-like files/material,
submodules, and special files fail closed. Hooks and commit/push signing are
disabled for publishing operations so they cannot run with App credentials.

Python creates a bot-authored commit using the App slug and bot user ID queried
from GitHub. Author and committer identity are set only for the command's
environment. Global and repository Git configuration are not changed.

The origin must identify the expected github.com repository over HTTPS or
`git@github.com:` SSH syntax. Pushes always use a token-free canonical HTTPS
URL, not a persisted authenticated remote URL. Existing Git access is still
needed for the ordinary origin fetch used to prepare a branch; the App push
credential mechanism does not configure SSH or a persistent fetch helper.

Only `foxforge/*` branches are accepted. Python checks current branch identity,
origin/dev ancestry, origin identity, and remote ownership.
In addition, preexisting commits beyond origin/dev must carry the same App bot
identity and exact FoxForge branch/repository ownership trailers. Forking from
unrelated main/local history is rejected. New branches use an
explicit empty-ref lease so a racing foreign branch cannot be overwritten.
Existing remote branches require an open, same-repository PR created by this
App bot with FoxForge's ownership marker and targeting dev; unknown, foreign,
or main-targeting PRs are rejected. Existing history must fast-forward. The
explicit expected-SHA lease rejects concurrent remote changes and does not
permit a history rewrite after that ancestry check.

A temporary ASKPASS launcher/script contains no token and is cleaned up in a
finally path. The token is supplied only in the controlled Git child's
environment. Git credential helpers, host/global Git config, tracing,
redirects, hooks, signing, and unsafe repository URL/auth overrides are
restricted. The helper refuses requests for any other host/repository.
Raw Git/HTTP auth error output is not persisted or displayed.

A deterministic PR title/body uses verified RunState facts. The PR base is
always dev. A verified existing owned PR is reused without overwriting its
title/body. Creation races are rechecked safely; other failures remain failures.
No PR merge, direct dev/main/master push, release, or deployment is implemented.

RunState stores only safe metadata: publish_requested, github_repository,
validated_head_sha, validated_tree_hash, publishing_status, publishing_error,
commit_sha, remote_branch, pull_request_number, and pull_request_url. Each
completed remote step is saved immediately. Local validation can remain
READY_FOR_PLAYTEST while publishing is FAILED; the overall command exits 1.
A commit/push/PR can survive a later failure. FoxForge does not reset or delete
it automatically. Inspect state and retry deliberately; collisions and unowned
remote branches remain blocked.

Reporter receives only those safe facts and the existing test/review facts.
Python validates every reported publishing field and PR URL before display or
Discord dispatch. Reporter does not receive the credentials or own Git actions.

## Disposable push/PR smoke test (manual, not run during implementation)

Prerequisite: create a dedicated GitHub repository
`ItsFoxxin/FoxForge-publish-smoke`, install the App on it, and prepare its `dev`
branch with the files from `examples/calculator/`. Use a disposable directory
that does not already exist. Keep the App private key outside the clone. Qwen
must already work locally, with the models named by the agent templates.

The following commands intentionally create a task commit, push that task
branch, and open a PR **only when you run the final command yourself**.
They never directly push dev/main/master.

```powershell
$foxforge = 'C:\Projects\FoxForge'
$target = 'C:\Projects\FoxForge-publish-smoke'
$tools = 'C:\Projects\FoxForge-publish-tools'
python -m venv $tools
$python = Join-Path $tools 'Scripts\python.exe'
& $python -m pip install -e "${foxforge}[dev]"
& $python -m foxforge.github_app --check --repository ItsFoxxin/FoxForge-publish-smoke

git clone --branch dev https://github.com/ItsFoxxin/FoxForge-publish-smoke.git $target
New-Item -ItemType Directory -Path (Join-Path $target '.qwen\agents') | Out-Null
Copy-Item -Path (Join-Path $foxforge 'templates\qwen-agents\*.md') -Destination (Join-Path $target '.qwen\agents')
Copy-Item -LiteralPath (Join-Path $foxforge 'templates\qwen-settings.json') -Destination (Join-Path $target '.qwen\settings.json')
# Local ignore metadata keeps model configuration out of the disposable task PR.
Add-Content -LiteralPath (Join-Path $target '.git\info\exclude') -Value "`n.qwen/" -Encoding utf8
$branch = 'foxforge/app-smoke-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$testCommand = '"' + $python + '" -m pytest -v'
& $python -m foxforge --repo $target `
  --task 'Add square(a: int) -> int to calculator.py and meaningful regression tests. Preserve all existing behavior.' `
  --test-command $testCommand --create-branch --branch-name $branch `
  --base-branch dev --publish-pr --skip-discord
```

Check saved state and the PR URL. Confirm base=dev, bot author/committer, exact
commit SHA, verified test/review facts, and publishing_status=PUBLISHED. Close
the disposable PR manually after inspection. Do not use a production repository
for this first test.

## Validation and limits

All GitHub HTTP and push operations are mocked in CI. Tests generate synthetic
RSA keys and use disposable local Git repositories for commit/credential-fill
checks; real GitHub credentials and Qwen are not required. Authentication,
permissions, actual bot attribution, protected-branch rules, and live PR behavior
still need the manual smoke test above. Workflow-file changes require additional
GitHub Workflows authority, which FoxForge does not request automatically.
No same-worktree concurrency, submodule publishing, or OS sandbox is provided.
A process with shell/file permissions under the same OS account could still
read unrelated credential files; environment stripping is defense in depth,
not a substitute for isolating untrusted targets and model processes.

Protocol references: [GitHub App JWTs](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app),
[installation access tokens](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app),
[pull requests](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request),
[Git credentials](https://git-scm.com/docs/gitcredentials).
