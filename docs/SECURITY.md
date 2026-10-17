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

Initial maximum authority should be:

```text
create foxforge/* branch
commit
push
open PR -> dev
stop
```
