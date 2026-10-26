# Changelog

## 0.3.1

- Add a digest-pinned Python 3.13/Debian container with a restricted one-shot CLI,
  non-root UID, read-only repositories/config, and bounded writable storage.
- Deploy FreeLLMAPI separately at reviewed commit
  `5646971602a89436ce4921b0f04b99ac7bcc3728`, pinned image digest, loopback dashboard,
  non-root runtime, independent encrypted state, and no updater/socket integration.
- Add secret-file credentials, task-specific model/provider policies, explicit
  model IDs, bounded input/output/request reservations, retry ceilings and timeout
  handling. Default to one request and zero retries. Record sanitized outcomes,
  latency and reported token counters; rate limits never automatically retry.
- Add `doctor` with optional authenticated model-list probing; require explicit
  existing storage paths and intentional initialization for a new database.
- Add SQLite-consistent non-overwriting backups, integrity/count/hash checks and
  recovery verification. Keep schema 1 and existing records; add `model_requests`.
- Recheck registered numeric repository identity and local origin during planning,
  constrain repositories to the configured storage root, and use direct bounded
  Git-object discovery without executing project code.
- Preserve 0.3.0 planning/authorization/artifacts and legacy venv commands.
- Audit all six Qwen roles and legacy execution/state/Git/approval boundaries;
  document a provider-independent worker protocol and 0.4.x migration gates.
  Reject direct legacy execution/publishing calls in control-plane image mode
  and distinguish relayed model proposals from authorization.
- Add minimal task/tool/approval-scope data contracts, release CI, tests, Debian
  migration/rollback instructions and explicit gateway trust limitations.

Deployment impact: `FOXFORGE_DATA_DIR` and `FOXFORGE_REPOS_DIR` are required.
Implicit home databases are no longer created. Live inference additionally needs
`FOXFORGE_MODEL_POLICY_FILE` and an approved model/route. Container host data/config
paths differ from the old venv while internal paths are preserved. Migration is
manual and gated on verified backups, candidate tests and human approval.

Deferred: coding or multi-agent workers, arbitrary shell tools, autonomous GitHub
modification/PRs, infrastructure administration, service remediation, research
workflows, Discord approvals, workload-priority scheduling, a full dashboard,
and unattended deployment. No live migration or merge is performed by this release.
