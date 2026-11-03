# Deploy the FoxForge planning foundation

This page records the **0.3.0 venv deployment**. For 0.3.1, use
[CONTAINER_DEPLOYMENT.md](CONTAINER_DEPLOYMENT.md). Version 0.3.1 requires an
explicit existing `FOXFORGE_DATA_DIR` and intentional `storage init` for new
installations, `FOXFORGE_REPOS_DIR`, and a task model policy for live inference.
Keep a working 0.3.0 installation intact until the new candidate is approved.

This guide deploys the first adaptive FoxForge milestone: authorized project registration, model-free issue discovery, trusted `foxforge:plan` authorization, commit-pinned repository discovery, strict plan generation, and human-review artifacts.

It does not enable code modification, shell execution in target repositories, branch pushes, pull requests, previews, production deployments, Proxmox operations, or infrastructure maintenance.

## Recommended host boundary

Use a dedicated, non-production Linux VM in the Fox Den. Give it no Proxmox API token, production credentials, Docker socket, production mounts, or administrative-network access. Run FoxForge as an unprivileged `foxforge` account. The planning foundation needs outbound HTTPS to GitHub and the selected model endpoint, local read access to explicitly registered repository clones, and write access to its own data directory.

Required software on Debian 13:

- Python 3.11 or newer (Debian 13 supplies Python 3.13)
- Git
- SQLite command-line tools for backup and integrity checks
- A dedicated filesystem location for repository clones
- A GitHub App installation scoped to authorized repositories
- An OpenAI-compatible planning endpoint only when performing live plans

## 1. Install the application

Choose and record the full 40-character commit SHA that passed review and release checks. Do not substitute the current branch head at deployment time. The commands below require `origin/dev` to equal that approved commit and install from a detached checkout.

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends ca-certificates git python3 python3-venv sqlite3
python3 --version
python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version'

sudo useradd --system --create-home --home-dir /var/lib/foxforge --shell /usr/sbin/nologin foxforge
sudo install -d -o foxforge -g foxforge -m 0750 /opt/foxforge /var/lib/foxforge/repos /var/lib/foxforge/control-plane
sudo chown foxforge:foxforge /var/lib/foxforge
sudo chmod 0750 /var/lib/foxforge
APPROVED_COMMIT_SHA=REPLACE_WITH_REVIEWED_40_CHARACTER_SHA
test "${#APPROVED_COMMIT_SHA}" -eq 40
sudo -u foxforge git clone --branch dev --no-checkout https://github.com/ItsFoxxin/FoxForge.git /opt/foxforge/source
test "$(sudo -u foxforge git -C /opt/foxforge/source rev-parse origin/dev)" = "$APPROVED_COMMIT_SHA"
sudo -u foxforge git -C /opt/foxforge/source checkout --detach "$APPROVED_COMMIT_SHA"
test "$(sudo -u foxforge git -C /opt/foxforge/source rev-parse HEAD)" = "$APPROVED_COMMIT_SHA"
test -z "$(sudo -u foxforge git -C /opt/foxforge/source status --porcelain)"
sudo -u foxforge python3 -m venv /opt/foxforge/venv
sudo -u foxforge /opt/foxforge/venv/bin/python -m pip --version
sudo -u foxforge /opt/foxforge/venv/bin/python -m pip install /opt/foxforge/source
stat -c '%U:%G %a %n' /var/lib/foxforge /var/lib/foxforge/repos /var/lib/foxforge/control-plane /opt/foxforge /opt/foxforge/source /opt/foxforge/venv
sudo -u foxforge test -w /var/lib/foxforge/control-plane
```

`REPLACE_WITH_REVIEWED_40_CHARACTER_SHA` is an example placeholder and must be replaced with the approved release SHA before running the commands. Record that SHA and the output of the equality checks in the deployment change record. For a private clone, use a repository-scoped read-only credential or deploy key supplied outside the remote URL. Do not put a token in the URL, a command argument, Git configuration, or shell history.

Run the packaged smoke checks:

```bash
/opt/foxforge/venv/bin/foxforge capabilities list
/opt/foxforge/venv/bin/python -m compileall -q /opt/foxforge/venv/lib/python*/site-packages/foxforge
```

Run the full test suite from a separate source checkout before promoting a revision. Installing the runtime package alone does not install development test dependencies.

## 2. Create the GitHub App

Create a GitHub App owned by `ItsFoxxin` and install it only on repositories FoxForge may inspect. The current read-only planning client requests:

- Contents: read
- Issues: read
- Pull requests: read
- Metadata: implicit read

Do not grant Administration, Actions write, Contents write, Issues write, Pull requests write, or deployment permissions for this milestone. Do not configure a webhook yet; this version uses authenticated polling and verifies label history through GitHub.

Create the exact repository label `foxforge:plan`. Do not add it automatically from a public issue form or automation; an authorized person applies it after reviewing the current issue text.

Generate a private key and store it outside the source and repository clone trees:

```bash
sudo install -d -o root -g foxforge -m 0750 /etc/foxforge
sudo install -o root -g foxforge -m 0640 foxforge-app.private-key.pem /etc/foxforge/github-app.pem
```

Find the immutable numeric GitHub user ID for each trusted approver through an authenticated GitHub response. Do not use a username as the authorization value.

## 3. Configure the service environment

Use `sudoedit` or another editor that does not place secret values in command arguments or shell history. Create `/etc/foxforge/foxforge.env` with mode `0640`, owned by `root:foxforge`:

```ini
FOXFORGE_DATA_DIR=/var/lib/foxforge/control-plane
FOXFORGE_GITHUB_APP_ID=REPLACE_WITH_APP_ID
FOXFORGE_GITHUB_INSTALLATION_ID=REPLACE_WITH_INSTALLATION_ID
FOXFORGE_GITHUB_PRIVATE_KEY=/etc/foxforge/github-app.pem
FOXFORGE_ALLOWED_GITHUB_USER_IDS=REPLACE_WITH_NUMERIC_ID
```

Every `REPLACE_WITH_...` value below is a placeholder. Replace it on the VM; do not commit the populated files. Keep planner configuration in a separate `/etc/foxforge/planner.env` so the model-free discovery timer never receives the planner credential:

```ini
FOXFORGE_PLANNER_BASE_URL=http://127.0.0.1:3001/v1
FOXFORGE_PLANNER_API_KEY=REPLACE_WITH_LOCAL_GATEWAY_KEY
FOXFORGE_PLANNER_MODEL=REPLACE_WITH_TESTED_MODEL_ID
```

Plain HTTP is accepted only for loopback endpoints. Remote planners require HTTPS. The configured model must be tested for JSON reliability and the repository's data classification. FreeLLMAPI can provide this local OpenAI-compatible endpoint, but remains optional. Do not enable automatic routing across unreviewed providers; record the actual `X-Routed-Via` value when the gateway supplies it.

Protect both files:

```bash
sudo chown root:foxforge /etc/foxforge/foxforge.env
sudo chmod 0640 /etc/foxforge/foxforge.env
sudo chown root:foxforge /etc/foxforge/planner.env
sudo chmod 0640 /etc/foxforge/planner.env
stat -c '%U:%G %a %n' /etc/foxforge /etc/foxforge/github-app.pem /etc/foxforge/foxforge.env /etc/foxforge/planner.env
sudo -u foxforge test -r /etc/foxforge/github-app.pem
sudo -u foxforge test -r /etc/foxforge/foxforge.env
sudo -u foxforge test ! -w /etc/foxforge/foxforge.env
```

Do not pass private keys, tokens, or API keys with `env`, command-line options, or shell `export` commands. Systemd and the service-account shell read them from the protected files. For the remaining GitHub and model-free commands, open a shell as the service account and load only the base environment. This prevents root-owned database or artifact files:

```bash
sudo -u foxforge /bin/bash
set -a
. /etc/foxforge/foxforge.env
set +a
```

## 4. Prepare and register a repository

Create a local read-only clone as the service account and fetch the configured development branch. Avoid credential-bearing remote URLs.

```bash
git clone https://github.com/ItsFoxxin/FoxForge.git /var/lib/foxforge/repos/FoxForge
git -C /var/lib/foxforge/repos/FoxForge fetch origin dev
```

Register the project from the service-account shell:

```bash
/opt/foxforge/venv/bin/foxforge projects register \
  --repository ItsFoxxin/FoxForge \
  --repo /var/lib/foxforge/repos/FoxForge \
  --default-branch dev
```

Registration fails if the GitHub App cannot verify the repository, the local origin identifies another repository, or `origin/dev` does not resolve to a commit.

## 5. Discover issues safely

Issue discovery stores snapshots and makes zero model requests:

```bash
/opt/foxforge/venv/bin/foxforge issues discover --project ItsFoxxin/FoxForge
```

Any GitHub user allowed to create an issue may report work. The issue becomes eligible for planning only when an allowlisted actor applies `foxforge:plan`. The label event, numeric actor ID, repository, issue number, and current title/body revision are bound to the resulting task. Editing the issue requires a fresh planning approval.

## 6. Validate the offline path

Before connecting a model, copy the included example plan and run it against an approved test issue:

```bash
cp /opt/foxforge/source/examples/planning/plan.example.json /var/lib/foxforge/test-plan.json
/opt/foxforge/venv/bin/foxforge tasks plan \
  --project ItsFoxxin/FoxForge \
  --issue 123 \
  --plan-file /var/lib/foxforge/test-plan.json
```

This path still validates the approval, pinned repository commit, capability IDs, acceptance-criteria references, dependency graph, limits, persistence, and artifact rendering. `--plan-file` is an operator/testing input; it is not proof that a live provider works.

After the offline test passes, omit `--plan-file` for one budgeted live planning run:

```bash
set -a
. /etc/foxforge/planner.env
set +a
/opt/foxforge/venv/bin/foxforge tasks plan --project ItsFoxxin/FoxForge --issue 123
unset FOXFORGE_PLANNER_BASE_URL FOXFORGE_PLANNER_API_KEY FOXFORGE_PLANNER_MODEL
```

The command returns a task ID and artifact directory. Review `plan.md`, `plan.json`, `repository-discovery.json`, and `model-telemetry.json`. The final state must be `awaiting_human_review`. No next action is authorized by that state.

Inspect the durable record later:

```bash
/opt/foxforge/venv/bin/foxforge tasks show task_REPLACE_WITH_ID
```

## 7. Optional model-free discovery timer

Automate only discovery in this milestone. Create `/etc/systemd/system/foxforge-discovery.service` for the first registered repository:

```ini
[Unit]
Description=FoxForge model-free issue discovery
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=foxforge
Group=foxforge
EnvironmentFile=/etc/foxforge/foxforge.env
ExecStart=/opt/foxforge/venv/bin/foxforge issues discover --project ItsFoxxin/FoxForge
UMask=0077
NoNewPrivileges=yes
PrivateDevices=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/foxforge/control-plane
```

Create `/etc/systemd/system/foxforge-discovery.timer`:

```ini
[Unit]
Description=Poll GitHub issues for FoxForge

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

Validate and run one discovery before enabling the timer. `systemd-analyze verify` checks unit syntax and dependencies; the explicit start and status check validate this VM's paths, permissions, environment, and network access:

```bash
sudo systemd-analyze verify /etc/systemd/system/foxforge-discovery.service /etc/systemd/system/foxforge-discovery.timer
sudo systemctl daemon-reload
sudo systemctl start foxforge-discovery.service
sudo systemctl status foxforge-discovery.service
sudo systemctl enable --now foxforge-discovery.timer
```

Do not automate `tasks plan` yet. A model request consumes resources and requires the trusted, revision-bound approval plus deliberate operator invocation in this milestone.

## 8. Backup, update, and recovery

The authoritative state is `FOXFORGE_DATA_DIR/foxforge.db` plus the `artifacts/` directory. The example below stops scheduled discovery, creates a SQLite-consistent backup, copies artifacts, and verifies the database before restarting discovery. `REPLACE_WITH_TIMESTAMP` is a placeholder for a filesystem-safe UTC timestamp.

```bash
sudo systemctl stop foxforge-discovery.timer
sudo systemctl stop foxforge-discovery.service
BACKUP_DIR=/var/backups/foxforge/REPLACE_WITH_TIMESTAMP
sudo install -d -o foxforge -g foxforge -m 0700 "$BACKUP_DIR"
sudo -u foxforge sqlite3 /var/lib/foxforge/control-plane/foxforge.db ".timeout 15000" ".backup '$BACKUP_DIR/foxforge.db'"
sudo -u foxforge install -d -m 0700 "$BACKUP_DIR/artifacts"
if sudo -u foxforge test -d /var/lib/foxforge/control-plane/artifacts; then sudo -u foxforge cp -a /var/lib/foxforge/control-plane/artifacts/. "$BACKUP_DIR/artifacts/"; fi
sudo -u foxforge sqlite3 -readonly "$BACKUP_DIR/foxforge.db" "PRAGMA integrity_check; PRAGMA foreign_key_check;"
sudo systemctl start foxforge-discovery.timer
```

`PRAGMA integrity_check` must print `ok`; `PRAGMA foreign_key_check` must print no rows. A database-only backup does not preserve review artifacts.

Verify restoration without replacing live state. Copy the backup into a new service-owned directory, point only the verification commands at it, and inspect at least one known task when the backup contains tasks:

```bash
sudo install -d -o foxforge -g foxforge -m 0700 /var/lib/foxforge/restore-test
sudo -u foxforge install -d -m 0700 /var/lib/foxforge/restore-test/artifacts
sudo -u foxforge cp -a "$BACKUP_DIR/foxforge.db" /var/lib/foxforge/restore-test/foxforge.db
sudo -u foxforge cp -a "$BACKUP_DIR/artifacts/." /var/lib/foxforge/restore-test/artifacts/
sudo -u foxforge sqlite3 -readonly /var/lib/foxforge/restore-test/foxforge.db "PRAGMA integrity_check; PRAGMA foreign_key_check;"
sudo -u foxforge /bin/bash -c 'set -a; . /etc/foxforge/foxforge.env; set +a; FOXFORGE_DATA_DIR=/var/lib/foxforge/restore-test /opt/foxforge/venv/bin/foxforge projects list'
sudo -u foxforge /bin/bash -c 'set -a; . /etc/foxforge/foxforge.env; set +a; FOXFORGE_DATA_DIR=/var/lib/foxforge/restore-test /opt/foxforge/venv/bin/foxforge tasks show task_REPLACE_WITH_KNOWN_ID'
```

The second command intentionally contains a task-ID placeholder. Omit it only when the backup contains no tasks. Remove the restore-test copy only after recording the verification result. Restoring onto the live path requires the timer and service to remain stopped until the complete database and artifact set is in place and ownership is verified.

For updates:

1. Review and test the exact candidate revision.
2. Stop scheduled discovery.
3. Back up the complete control-plane directory.
4. Install the candidate into a new virtual environment.
5. Run capability and database-open smoke checks.
6. Switch the service path and run one model-free discovery.
7. Retain the previous environment until the new revision is verified.

This initial schema has no automatic migration beyond schema version 1. An unknown schema version fails closed.

If a planning request fails after task creation, FoxForge records `blocked` with `PLANNING_FAILED`. It does not automatically repeat a potentially billable model call. Inspect the task and provider before a future explicit recovery mechanism is added.

## Operational boundaries

- `awaiting_human_review` means a plan exists; it does not mean implementation is approved.
- Issue discovery does not authorize a model call.
- `foxforge:plan` authorizes planning for one exact issue revision, not implementation.
- The model cannot add repositories, tools, permissions, providers, or resource budget.
- Infrastructure alerts, documentation changes, deployments, and maintenance are not implemented.
- SQLite coordinates one control-plane host. Do not place the database on a shared network filesystem or let multiple hosts write it.
- Local Git worktrees are not a security sandbox. This milestone does not execute repository code.
