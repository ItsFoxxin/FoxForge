# Security

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

A future GitHub App should use:

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

The future planned maximum authority (not implemented in the coordinator) is:

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
Discord messages. GitHub App authentication remains planned and unimplemented.
