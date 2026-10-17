# GitHub App Plan

FoxForge is intended to use a GitHub App identity such as:

```text
foxforge[bot]
```

This is not wired into v0.1 yet.

## Initial repository permissions

Start with the smallest set needed for branch/PR automation:

```text
Metadata:      Read-only
Contents:      Read and write
Pull requests: Read and write
```

Install the App only on repositories FoxForge is allowed to modify.

## Local secrets

Recommended environment variables:

```text
FOXFORGE_GITHUB_APP_ID
FOXFORGE_GITHUB_INSTALLATION_ID
FOXFORGE_GITHUB_PRIVATE_KEY
```

`FOXFORGE_GITHUB_PRIVATE_KEY` should point to a local `.pem` file outside the repo.

## Planned authentication flow

```text
private key
   ↓
GitHub App JWT
   ↓
installation access token
   ↓
authenticated Git/API operations
```

## Planned authority

The bot may eventually:

- create `foxforge/*` branches
- create FoxForge-authored commits
- push those branches
- open pull requests targeting `dev`
- update its own PR

The bot should not initially:

- merge pull requests
- push directly to `dev`
- push directly to `main`
- publish releases
