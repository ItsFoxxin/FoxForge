# FoxForge 0.4.0 on Debian 13

This guide deploys the **planning-only control plane**. The optional 0.4.0
[fixture worker prototype](WORKER_FOUNDATION.md) runs only on a separate disposable
Linux Docker host/CI runner. Do not run it on the production control-plane VM or
mount a Docker socket into this stack. No live worker migration is included.

This is an operator-run deployment guide, not an automatic migration. The existing
0.3.0 venv, `/etc/foxforge`, clones and authoritative database remain intact.
Container candidate paths deliberately differ on the host. Inside the image the
original `/var/lib/foxforge/control-plane` and `/var/lib/foxforge/repos` paths are
preserved so stored project and artifact references continue to work.

The supplied VM facts are `srv-foxforge-01`, VM 104, Debian 13, `10.0.30.50`,
2 vCPU, 4 GB RAM, 40 GB disk. No additional VM or network addressing is required.
Confirm free disk space for images, an independent backup, and candidate copies.
Do not infer network trust from an IP address; outbound administrative-network
restrictions must be enforced by the VM/network operator.

## Prerequisites and approved revision

Install Docker Engine and the Compose plugin using [Docker's Debian instructions](https://docs.docker.com/engine/install/debian/),
which support Debian 13. Install `docker-ce`, `docker-ce-cli`, `containerd.io`,
`docker-buildx-plugin`, `docker-compose-plugin` from the reviewed Docker repository.
Inspect existing packages before replacing conflicting container packages.
Use `sudo docker`; do not add the FoxForge service account to the host docker group.

```bash
sudo apt-get install --no-install-recommends git python3 python3-venv openssl
sudo docker version
sudo docker compose version
df -h /var/lib /opt
```

Deploy only after the PR is reviewed. In a shell with `set -e`, set
`APPROVED_SHA` to the approved full 40-character commit SHA (not a branch name):

```bash
set -e
APPROVED_SHA=REPLACE_WITH_APPROVED_40_CHARACTER_SHA
sudo install -d -m 0755 /opt/foxforge-container
sudo git clone --no-checkout https://github.com/ItsFoxxin/FoxForge.git /opt/foxforge-container/source
sudo git -C /opt/foxforge-container/source checkout --detach "$APPROVED_SHA"
test "$(sudo git -C /opt/foxforge-container/source rev-parse HEAD)" = "$APPROVED_SHA"
test -z "$(sudo git -C /opt/foxforge-container/source status --porcelain)"
cd /opt/foxforge-container/source
sudo docker build -t foxforge:0.4.0 .
sudo docker image inspect foxforge:0.4.0 --format '{{.Id}}'
```

The Python base and gateway image are pinned by digest. Runtime Python dependencies
are exact versions in `deployment/requirements-runtime.txt`. OS packages receive
Debian security updates during build; record the resulting local image ID and save
the image with `docker image save` before an upgrade. This is not a claim of a
bit-for-bit reproducible OS build. Never run the upstream curl-to-shell installer,
Watchtower, or an updater with the Docker socket in this stack.

## Configuration and credential boundaries

The FoxForge container is UID/GID `10001:10001`. The gateway is `1000:1000`,
overriding upstream's root entrypoint. The latter must already own its data path;
do not run startup as root to repair permissions. The original service account
can keep its existing UID and original configuration.

```bash
sudo install -d -o 10001 -g 10001 -m 0750 /var/lib/foxforge-container
sudo install -d -o 10001 -g 10001 -m 0750 /var/lib/foxforge-container/repos
sudo install -d -o root -g 10001 -m 0750 /etc/foxforge-container
sudo install -d -o root -g root -m 0700 /etc/freellmapi
sudo install -d -o 1000 -g 1000 -m 0700 /var/lib/freellmapi
sudo install -o root -g 10001 -m 0640 deployment/container.env.example /etc/foxforge-container/container.env
sudo install -o root -g 10001 -m 0640 deployment/model-policy.example.json /etc/foxforge-container/model-policy.json
sudo install -o root -g 10001 -m 0640 /etc/foxforge/github-app.pem /etc/foxforge-container/github-app.pem
```

Use `sudoedit` to populate the files. All `REPLACE_WITH_...` values are placeholders
and must be replaced. `FOXFORGE_GITHUB_PRIVATE_KEY` names the **container path**
`/etc/foxforge/github-app.pem`; it does not contain PEM material.
The GitHub App remains selected-repository-only with Contents, Issues and Pull
requests **read** plus implicit Metadata read. Trusted numeric user IDs authorize
the `foxforge:plan` label event; usernames and issue authors do not grant authority.
Test read-only authentication with the existing venv before copying its key.

Create `/etc/freellmapi/gateway.env` as root mode `0600`. Set `ENCRYPTION_KEY` to
64 random hex characters generated once, for example by directing
`openssl rand -hex 32` into a protected temporary file and using `sudoedit`.
Never type a secret into an `export` command, URL, command argument, Git file, or
ticket. Back up this encryption key separately and securely. Losing it makes
encrypted provider credentials unreadable; simply changing it is not rotation.

Provider keys live only in the gateway's database. `/etc/freellmapi` and the
gateway data directory are **never mounted into FoxForge**. FoxForge receives
only its unified gateway credential in `/etc/foxforge-container/gateway-api-key`,
root:10001 mode `0640`. `FOXFORGE_PLANNER_API_KEY_FILE` references its container
path. Inline `FOXFORGE_PLANNER_API_KEY` remains supported for a venv, but setting
both forms is rejected. Secrets read from files are registered for redaction.

## Gateway onboarding

The pinned upstream contract was inspected at
[`5646971602a89436ce4921b0f04b99ac7bcc3728`](https://github.com/tashfeenahmed/freellmapi/tree/5646971602a89436ce4921b0f04b99ac7bcc3728).
The source is MIT licensed. Use its [installation guide](https://github.com/tashfeenahmed/freellmapi/blob/5646971602a89436ce4921b0f04b99ac7bcc3728/docs/en/install/01-install.md),
[API contract](https://github.com/tashfeenahmed/freellmapi/blob/5646971602a89436ce4921b0f04b99ac7bcc3728/docs/en/api/01-rest-api.md)
and [environment reference](https://github.com/tashfeenahmed/freellmapi/blob/5646971602a89436ce4921b0f04b99ac7bcc3728/docs/en/env/01-variables.md).
Provider terms and free-tier quotas remain separate obligations; a free label
does not establish coding quality, JSON reliability, zero cost, or unlimited quota.

```bash
sudo docker compose up -d freellmapi
sudo docker compose ps freellmapi
```

From the approved management client, tunnel to the VM's loopback listener:

```bash
ssh -N -L 3001:127.0.0.1:3001 REPLACE_WITH_SSH_USER@10.0.30.50
```

Open `http://127.0.0.1:3001` on that client. Create the dashboard account using
upstream's first-run setup flow, add only approved provider accounts on **Keys**,
and retrieve the unified credential. Setup/recovery codes may appear in gateway
logs; treat those logs as privileged. Do not post log dumps in tickets.

The dashboard and API share port 3001. The host bind is loopback only; do not
change it to `0.0.0.0` or publish it through a public reverse proxy. No duplicate
provider dashboard is implemented. The gateway's supported routing/fallback,
quota, usage and model toggles are managed through its own UI.

**Provider trust boundary:** there is no documented per-request provider allowlist
in the reviewed gateway API. Exact model IDs may resolve across providers, and
gateway fallback can make multiple upstream attempts per client request. Use a
dedicated gateway containing only approved free provider keys, disable all
unapproved/keyless routes and model groups in its dashboard, disable response
caching for auditable route telemetry, and review routing after catalog updates.
FoxForge rejects a returned `X-Routed-Via` provider outside its policy, but this
post-response check cannot undo an upstream disclosure. No paid accounts should
be configured. An operator-managed egress allowlist is needed for a stronger
pre-dispatch provider boundary. Do not claim the FoxForge allowlist enforces that
boundary inside an independently reconfigured gateway.

Set the exact tested model ID in both the model policy and `FOXFORGE_PLANNER_MODEL`.
Include every approved actual routed model ID in the policy too; unexpected
provider or model identities are rejected and recorded as durable failures.
Unqualified `auto` and `fusion` are refused. Named profiles are permitted only if
explicitly listed in policy; inspect their complete chain first. Start with one
request and zero retries. `MAX_CONSECUTIVE_UPSTREAM_FAILS=1` in Compose limits
gateway failover failures; it is not an exact bound on every provider-internal
probe, catalog update, background health check, or provider SDK behavior.

The `control` network is private to the stack; the two egress bridges allow
GitHub and provider access. Docker bridges do not enforce destination allowlists.
VM/firewall policy must prevent access to production and administrative networks.
The explicit `FOXFORGE_PLANNER_HTTP_HOSTS=freellmapi` exception permits bearer
authentication over the trusted Docker bridge. Use HTTPS for remote gateways.

## Verify backup and prepare the migration candidate

First inspect the current venv service environment and identify the authoritative
database. In particular inspect `/var/lib/foxforge/control-plane`, the service
account's `~/.foxforge/control-plane`, any root-created `~/.foxforge/control-plane`,
and paths previously configured through `LOCALAPPDATA` or `FOXFORGE_DATA_DIR`.
Do not merge databases. Keep each in a separately named backup until the owner
selects the authoritative history. `doctor` checks known current-user locations;
it cannot discover arbitrary past environment values or other users' home paths.

Use the new package as an offline maintenance tool without changing the 0.3.0 venv:

```bash
sudo python3 -m venv /opt/foxforge-container/tools
sudo /opt/foxforge-container/tools/bin/python -m pip install /opt/foxforge-container/source
sudo systemctl stop foxforge-discovery.timer foxforge-discovery.service
# Also wait for every manual planning command to finish; the timer is not the only writer.
sudo install -d -o foxforge -g foxforge -m 0700 /var/backups/foxforge
```

Set `BACKUP` to a new timestamped path; the command refuses an existing destination.
The command-line environment assignment below contains a nonsecret path only.

```bash
BACKUP=/var/backups/foxforge/REPLACE_WITH_UNIQUE_UTC_TIMESTAMP
sudo -u foxforge env FOXFORGE_DATA_DIR=/var/lib/foxforge/control-plane \
  /opt/foxforge-container/tools/bin/foxforge storage backup --writers-stopped --destination "$BACKUP"
sudo -u foxforge /opt/foxforge-container/tools/bin/foxforge storage verify --directory "$BACKUP"
sudo systemctl start foxforge-discovery.timer
```

Backup uses SQLite's backup API, copies artifacts without following symlinks,
checks integrity/foreign keys, task and authorization counts, and artifact hashes.
It retains an incomplete destination on failure for investigation and never
overwrites it. `--writers-stopped` is an operator assertion, not a global lock.
Pause every writer before the snapshot. Protect backups as sensitive source/data.

Create an independent candidate (do not reuse an existing directory):

```bash
test ! -e /var/lib/foxforge-container/control-plane
sudo install -d -o 10001 -g 10001 -m 0750 /var/lib/foxforge-container/control-plane
sudo cp -a "$BACKUP/foxforge.db" /var/lib/foxforge-container/control-plane/foxforge.db
sudo cp -a "$BACKUP/artifacts" /var/lib/foxforge-container/control-plane/artifacts
sudo cp -a /var/lib/foxforge/repos/. /var/lib/foxforge-container/repos/
sudo chown -R 10001:10001 /var/lib/foxforge-container/control-plane /var/lib/foxforge-container/repos
sudo docker compose --profile cli config --quiet
sudo docker compose run --rm --no-deps foxforge storage verify --directory /var/lib/foxforge/control-plane
sudo docker compose run --rm --no-deps foxforge projects list
sudo docker compose run --rm --no-deps foxforge tasks show task_REPLACE_WITH_EXISTING_TASK_ID
sudo docker compose run --rm --no-deps foxforge doctor --require-mounts
sudo docker compose run --rm --no-deps foxforge doctor --require-mounts --gateway
sudo docker compose run --rm --no-deps foxforge issues discover --project ItsFoxxin/FoxForge
```

When no artifacts have ever been generated, provision an empty candidate
`artifacts` directory instead of copying a nonexistent one. Do not copy the backup
manifest into a writable runtime directory; it describes the immutable backup.

The diagnostics command creates no database and invokes no model. Its optional
gateway check authenticates `GET /v1/models` and confirms the configured ID exists;
it is not a quota or inference readiness guarantee. Missing planner configuration
makes the overall doctor result fail while deterministic discovery can still work.

For a completely new installation only, provision the empty data directory and
run `docker compose run --rm --no-deps foxforge storage init`, then register the
authorized clones. Other CLI commands refuse to create a missing database.

## Planning acceptance and human cutover

Use a dedicated open test issue. Apply `foxforge:plan` as an allowlisted numeric
actor with repository write/admin/maintain access after its last activity.
Model-free discovery must show zero requests. Copy the included example JSON into
the protected config directory as `offline-plan.json`, root:10001 mode `0640`:

```bash
sudo docker compose run --rm --no-deps foxforge tasks plan \
  --project ItsFoxxin/FoxForge --issue REPLACE_WITH_TEST_ISSUE_NUMBER \
  --plan-file /etc/foxforge/offline-plan.json
```

Inspect the durable task and all artifacts, verify existing history remains
accessible, and compare candidate repository content with its immutable input.
For one deliberate live planning test, use a new test issue or remove/reapply the
label to create a fresh authorization event. Reusing a consumed event returns the
existing task and makes no model request. Omit `--plan-file` to test the approved
model. A successful plan ends at `awaiting_human_review`; no execution is scheduled.

The client reserves input UTF-8 bytes plus the requested maximum output tokens
as conservative budget units before each call. This is **not an exact tokenizer**.
Actual usage counters are persisted only when reported by the gateway. Unknown
usage remains unknown. A crash retains its reservation; no automatic resume is
performed. Defaults are one request, zero retries, 8000 output tokens, 120-second
socket timeout. A slow-trickle HTTP body may outlive the socket timeout; the
container/service operator must supply an outer wall-clock limit if needed.
429s record bounded `Retry-After` telemetry and stop; timeouts and invalid output
stop. Only definite unavailability may consume a configured extra retry slot.
Budget changes cannot be applied to a task after its first reservation.

**Human approval is required before cutover.** Record backup verification,
container checks, GitHub auth/discovery, old task IDs, artifact availability,
offline/live plan results, pinned image IDs and rollback rehearsal first.
After approval, stop old writers, take a fresh consistent backup, and create a
new empty cutover data directory from that backup. Point `FOXFORGE_STATE_PATH`
in a root-owned `.env` next to Compose at this new host directory. Re-run storage
verification and doctor. Never replay the stale candidate over newer live state.

Only then install the supplied container discovery service/timer as root, review
the `WorkingDirectory` and project, and run:

```bash
sudo systemd-analyze verify /etc/systemd/system/foxforge-container-discovery.service /etc/systemd/system/foxforge-container-discovery.timer
sudo systemctl daemon-reload
sudo systemctl start foxforge-container-discovery.service
sudo systemctl status foxforge-container-discovery.service
sudo systemctl enable --now foxforge-container-discovery.timer
```

These host units invoke Docker through an operator-controlled root-owned checkout;
they are not container privileges granted to a model. Protect their files and
Compose checkout from the application UID. No timer invokes inference.

## Upgrades, backups and rollback

Before an upgrade, stop both generations of writers and archive each control
plane separately with `storage backup --writers-stopped`. Stop the gateway before
backing up `/var/lib/freellmapi` plus its protected encryption-key configuration;
its SQLite/credentials must be restored as a matching set. Never change its key
as an upgrade step. Retain old image digests and save images; do not use `down -v`.

Restore a FoxForge backup into a **new** directory, verify the manifest and task
history there, then copy only the verified database and artifacts into another
fresh runtime path. Schema 1 is retained; `model_requests` is an additive table.
The old package ignores that table and continues to read core records, but this
is not a guarantee for arbitrary future schema changes.

If candidate checks fail, stop the candidate containers and leave 0.3.0 running.
If cutover must be reversed, stop the container discovery timer and all manual
writers. Archive new container tasks separately. Restart the old venv timer
against its untouched original database and `/etc/foxforge` configuration.
Clearly record the cutoff: tasks created after cutover are preserved in the
container backup, not silently merged into the old database. Rehearse read-only
`projects list` and a known `tasks show` with the old venv before resuming writes.

The image's entrypoint refuses legacy `issue`, `watch`, shell and publishing
commands. Existing venv execution workflows remain legacy opt-in paths. This
control-plane deployment adds no execution workers, deployment tools, infrastructure credentials,
Docker socket mounts, public dashboard, or production automation.

`FOXFORGE_CONTROL_PLANE_ONLY=1` is baked into the image. Leave it set: legacy
agent/test/coordinator/issue execution and publishing APIs reject calls before
side effects, including calls made by bypassing the normal CLI. Any present
value enables the guard. This does not sandbox administrator-supplied Python.
Do not add Qwen, shell tools or worker credentials to this control plane. Review
the [legacy audit and future worker requirements](QWEN_LEGACY_AUDIT.md) before
considering execution migration; none is performed by this deployment.
