# FoxForge worker protocol v1

Normative reference implementation: `foxforge/worker_protocol.py`. Scope: signed,
bounded JSON for the 0.4.0 **synthetic fixture** prototype. Transport is intentionally
separate; no HTTP or queue service is required. No object deserialization, raw
command string, credential, runtime-specific prompt or Docker parameter is accepted.

## Encoding and authentication

All wire messages are UTF-8 JSON objects, at most 65,536 bytes including signature.
Duplicate keys, non-finite numbers, unsupported versions, missing/extra fields,
incorrect scalar types, excessive nesting and oversized input fail closed.
Boolean values do not satisfy integer fields. Typed protocol strings use ASCII
identifiers/paths; numeric IDs/timestamps fit positive 53-bit JSON integers.
Arrays preserve order and scoped lists reject duplicates.

The exact envelope is:

```json
{"version":1,"key_id":"controller","payload":{},"signature":"REPLACE_WITH_128_HEX_SIGNATURE"}
```

This is a **shape example**, not a valid assignment/signature. Canonicalize the
object `{version,key_id,payload}` with lexicographically sorted object keys at
every level, JSON ASCII escaping, no whitespace and decimal integers. Sign
`ASCII("FoxForge-worker-v1") + 0x00 + canonical_bytes` using Ed25519. Public keys
are 32-byte lowercase hex; signatures are 64-byte lowercase hex. The controller
key ID is `controller`; worker key IDs must match their enrolled worker ID.
No private signing key belongs in a message, artifact, log or execution container.

Verify against an independently pinned key before interpreting payload authority.
A worker's self-declared key never enrolls it. Pinning a key is a separate trusted
operator action. Authentication does not prove the worker or its test results
are trustworthy; see [the threat model](WORKER_FOUNDATION.md).

## Identity and registration

An identity payload has exactly `worker_id`, `public_key`, `capabilities`, and
`concurrency`. Worker IDs match `[a-z][a-z0-9_-]{0,79}`. This prototype permits only
`["quality.assurance"]` and one concurrent attempt per worker. The controller
supports a configured global ceiling of 1–4, default 1. Registration verifies a
signed identity against the public key approved out of band; key/capability
replacement or reactivation never happens implicitly.

## Assignment

Exact fields:

| Field | Contract |
| --- | --- |
| `kind` | `assignment` |
| `assignment_id`, `task_id`, `attempt_id`, `worker_id` | Immutable identifiers; task must start `fixture_`; one durable attempt per fixture task |
| `repository` | Exactly `{id,name,base_sha}`; registered built-in `foxforge-fixtures/calculator`, numeric ID 1 and deterministic 40-hex Git base commit |
| `capability` | `quality.assurance`; selected operations must also exist in the central capability catalog |
| `operations` | Unique subset of `repository.read`, `workspace.write`, `validation.execute` |
| `read_paths`, `write_paths` | Unique portable relative paths; the worker accepts only fixture files; writes only `test_calculator.py` |
| `policy_version`, `profile_digest` | Policy 1 and exact SHA256 of the centrally defined mock profile; Qwen-specific config is absent from this wire contract |
| `issued_at`, `expires_at` | UTC Unix seconds; live lease, no future issue time, maximum lifetime 300 seconds |
| `budgets` | Exact integer fields below; no defaults taken from a model |
| `parameters` | Exactly `{fixture:"calculator",scenario:<registered scenario>}`; no shell, endpoint or image selector |
| `approval` | Exact scope below, signed by controller; never inferred from a plan, issue label or model response |

Approval fields are `actor_id`, `task_id`, `action`, `repository_id`, `base_sha`,
`parameters_digest`, `expires_at`. Action is `fixture.execute`. Every field must
match the assignment, and the actor must be in the trusted operator set before
the controller issues it. `parameters_digest` hashes a canonical object containing
`parameters`, `capability`, `operations`, `read_paths`, `write_paths`, `profile_digest`,
`policy_version`, and `budgets`. Thus path/tool/budget changes invalidate approval.

Budgets: `requests` 0–2; `tokens` 0–4096; `output_bytes` 1–32768;
`artifact_bytes` 1–8192; `memory_mb` 1–256; `disk_mb` 1–16; `pids` 1–32.
The supervisor adds fixed one-CPU, no-swap and file-descriptor limits independently.
Configurations too small for the runtime fail safely rather than raising limits.
Mock inference charges one request and 200 synthetic token units before launch;
real inference/unknown provider-token accounting is outside this milestone.

Paths reject absolute names, backslashes, drive prefixes, empty/dot segments,
dotfiles, trailing dots and Windows device names. Scope checks are in the broker
in addition to parsing; a valid relative path alone does not authorize access.
File ownership declarations and agent prose are never permission grants.

## Events, checkpoints, evidence and results

Every worker event has exactly `kind`, `assignment_id`, `attempt_id`, `worker_id`,
`assignment_digest`, `sequence`, `usage`, and `data`. `assignment_digest` is SHA256
of the full canonical assignment including approval. Sequence is a strictly
increasing integer 1–64, beginning with `accepted`. `usage` has exactly cumulative
`requests` and `tokens`; counters cannot decrease or exceed assignment limits.

| Kind | Exact `data` shape |
| --- | --- |
| `accepted` | `{checkpoint:"accepted"}`; controller must acknowledge before sandbox dispatch |
| `checkpoint` | `{checkpoint:"sandbox_starting"}` or `{checkpoint:"sandbox_finished"}` |
| `tool` | `{operation,target,parameters_digest,outcome}`; operation is registered, target is scoped, digest binds parameters; outcome `allowed`, `denied`, `succeeded` or `failed` |
| `result` | `{status:"succeeded",reason,artifacts}`; requires prior broker validation-success evidence |
| `failure` | `{status:"failed" or "interrupted",reason,artifacts}` |
| `cancelled` | `{status:"cancelled",reason,artifacts}` |

`reason` is a bounded identifier/code, never raw exceptions, provider bodies,
commands or credentials. Tool denials are audited. Invalid protocol messages log
only a bounded message digest and safe rejection code, not their untrusted content.

Artifact references are unique `{path,sha256,size}` objects, at most four and at
most the task's aggregate byte limit. Content travels separately; this prototype
uses bounded base64 in the sandbox response and byte buffers at controller ingest.
The controller verifies exact names, sizes and hashes before persisting flat
artifacts and terminal state. Unreferenced files and symlinks are refused. A signed
result with forged content, wrong assignment/attempt, unapproved tool success,
expired lease or duplicate sequence cannot advance state.

## Cancellation, interruption and replay

Cancellation is a controller-signed payload with exactly `kind:"cancel"`,
`assignment_id`, `attempt_id`, `worker_id`, `assignment_digest`, and `expires_at`.
Every field must match the live assignment. An unauthorized or stale cancellation
does not control a worker. The controller marks cancellation immediately and
rejects later results; it does not depend on a late worker result to revoke authority.
The transport must deliver cancellation to the supervisor, which removes the
container, not merely its attached Docker client. CI exercises local delivery;
network delivery/acknowledgment is deferred.

The worker records assignment/attempt/digest in its durable local inbox before
execution. Replays, even after restart, are rejected. The controller independently
tracks acceptance, sequence, state and scope in SQLite. On deadline or lost worker,
explicit recovery marks expired nonterminal attempts `interrupted`; it never
restarts code, erases history or silently reuses an uncertain attempt. Controller
success with a lost acknowledgment is still success; retrying that same result
does not perform any external effect twice.

This protocol authenticates a prepared fixture attempt. It does not authorize Git
writes, production credentials, live issue execution, deployment or extra tools.
New task types/runtime adapters require separately reviewed policies and protocol
evolution. Python-specific callables used by tests are not wire fields or plugins
that a model can supply.
