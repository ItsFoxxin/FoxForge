"""Worker protocol v1: bounded JSON, explicit scopes, Ed25519 authentication.

No commands, Python objects, credentials or transport implementations belong here.
The prototype accepts only the built-in disposable fixture, never issue tasks.
"""
from __future__ import annotations

import hashlib
import json
import re
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

MAX_MESSAGE = 65536
OPERATIONS = {"repository.read", "workspace.write", "validation.execute"}
MAXIMA = {"requests": 2, "tokens": 4096, "output_bytes": 32768,
          "artifact_bytes": 8192, "memory_mb": 256, "disk_mb": 16, "pids": 32}
KINDS = {"accepted", "checkpoint", "tool", "result", "failure", "cancelled"}


class ProtocolError(ValueError):
    pass


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise ProtocolError("Unexpected or missing protocol fields")


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ProtocolError("Protocol integer outside policy bounds")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", value):
        raise ProtocolError("Invalid protocol identity")


def sha256(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ProtocolError("Invalid SHA256")


def path(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", value):
        raise ProtocolError("Path must be a portable relative path")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if len(value) > 160 or any(part in {".", ".."} or part.startswith(".") or part.endswith(".") or part.split(".")[0].upper() in reserved for part in value.split("/")):
        raise ProtocolError("Unsafe scoped path")


def strings(value, validate, maximum=16):
    if not isinstance(value, list) or len(value) > maximum or len({canonical(x) for x in value}) != len(value):
        raise ProtocolError("Invalid or duplicate protocol list")
    for item in value:
        validate(item)


def canonical(value) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError):
        raise ProtocolError("Invalid JSON value") from None
    if len(raw) > MAX_MESSAGE:
        raise ProtocolError("Protocol message is oversized")
    return raw


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def decode(raw: bytes):
    if not isinstance(raw, bytes) or len(raw) > MAX_MESSAGE:
        raise ProtocolError("Protocol message is oversized")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolError("Duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("Non-finite JSON")))
    except (ValueError, UnicodeError, RecursionError):
        raise ProtocolError("Malformed protocol JSON") from None


def public_key(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def sign(payload: dict, key_id: str, key: Ed25519PrivateKey) -> bytes:
    identifier(key_id)
    body = {"version": 1, "key_id": key_id, "payload": payload}
    signature = key.sign(b"FoxForge-worker-v1\0" + canonical(body)).hex()
    return canonical({**body, "signature": signature})


def verify(raw: bytes, expected_key_id: str, public: str) -> dict:
    value = decode(raw)
    fields(value, "version key_id payload signature")
    if type(value["version"]) is not int or value["version"] != 1 or value["key_id"] != expected_key_id:
        raise ProtocolError("Protocol version or signing identity mismatch")
    identifier(value["key_id"])
    if not isinstance(value["signature"], str) or not re.fullmatch(r"[0-9a-f]{128}", value["signature"]):
        raise ProtocolError("Malformed signature")
    sha256(public)
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public)).verify(
            bytes.fromhex(value["signature"]), b"FoxForge-worker-v1\0" + canonical({k: v for k, v in value.items() if k != "signature"}))
    except (InvalidSignature, ValueError):
        raise ProtocolError("Unauthenticated worker message") from None
    if not isinstance(value["payload"], dict):
        raise ProtocolError("Expected object payload")
    return value["payload"]


def validate_identity(value):
    fields(value, "worker_id public_key capabilities concurrency")
    identifier(value["worker_id"])
    sha256(value["public_key"])
    strings(value["capabilities"], lambda x: identifier(x.replace(".", "_")) if isinstance(x, str) else identifier(x))
    if not value["capabilities"]:
        raise ProtocolError("Worker needs an approved capability")
    integer(value["concurrency"], 1, 1)  # deliberately one slot in the prototype


def validate_assignment(value):
    fields(value, "kind assignment_id task_id attempt_id worker_id repository capability operations read_paths write_paths policy_version profile_digest issued_at expires_at budgets parameters approval")
    if value["kind"] != "assignment" or type(value["policy_version"]) is not int or value["policy_version"] != 1:
        raise ProtocolError("Unsupported assignment policy")
    for field in ("assignment_id", "task_id", "attempt_id", "worker_id"):
        identifier(value[field])
    if not value["task_id"].startswith("fixture_"):
        raise ProtocolError("Only synthetic fixture tasks may execute in 0.4.0")
    repo = value["repository"]
    fields(repo, "id name base_sha")
    integer(repo["id"], 1, 2**53-1)
    if repo["name"] != "foxforge-fixtures/calculator" or not isinstance(repo["base_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", repo["base_sha"]):
        raise ProtocolError("Unapproved fixture repository")
    if value["capability"] != "quality.assurance":
        raise ProtocolError("Prototype authorizes only fixture quality assurance")
    strings(value["operations"], lambda x: operation(x))
    strings(value["read_paths"], path)
    strings(value["write_paths"], path)
    sha256(value["profile_digest"])
    integer(value["issued_at"], 1, 2**53-1)
    integer(value["expires_at"], value["issued_at"]+1, value["issued_at"]+300)
    fields(value["budgets"], " ".join(MAXIMA))
    for name, maximum in MAXIMA.items():
        integer(value["budgets"][name], 0 if name in {"requests", "tokens"} else 1, maximum)
    fields(value["parameters"], "fixture scenario")
    if value["parameters"]["fixture"] != "calculator" or value["parameters"]["scenario"] not in SCENARIOS:
        raise ProtocolError("Only registered synthetic scenarios are permitted")
    scope = value["approval"]
    fields(scope, "actor_id task_id action repository_id base_sha parameters_digest expires_at")
    integer(scope["actor_id"], 1, 2**53-1)
    expected = {"actor_id": scope["actor_id"], "task_id": value["task_id"], "action": "fixture.execute",
                "repository_id": repo["id"], "base_sha": repo["base_sha"],
                "parameters_digest": digest(execution_parameters(value)), "expires_at": value["expires_at"]}
    if scope != expected:
        raise ProtocolError("Approval does not bind the exact action and revision")
    canonical(value)


SCENARIOS = {"success", "readonly-denial", "unavailable", "output", "deadline", "memory", "disk", "network", "processes"}


def execution_parameters(value):
    return {name: value[name] for name in ("parameters", "capability", "operations", "read_paths",
            "write_paths", "profile_digest", "policy_version", "budgets")}


def operation(value):
    if not isinstance(value, str) or value not in OPERATIONS:
        raise ProtocolError("Unregistered tool operation")


def validate_evidence(value):
    fields(value, "operation target parameters_digest outcome")
    operation(value["operation"])
    path(value["target"])
    sha256(value["parameters_digest"])
    if value["outcome"] not in {"allowed", "denied", "succeeded", "failed"}:
        raise ProtocolError("Invalid tool outcome")


def validate_event(value):
    fields(value, "kind assignment_id attempt_id worker_id assignment_digest sequence usage data")
    if value["kind"] not in KINDS:
        raise ProtocolError("Invalid worker event kind")
    for name in ("assignment_id", "attempt_id", "worker_id"):
        identifier(value[name])
    sha256(value["assignment_digest"])
    integer(value["sequence"], 1, 64)
    fields(value["usage"], "requests tokens")
    for name in ("requests", "tokens"):
        integer(value["usage"][name], 0, MAXIMA[name])
    data = value["data"]
    if value["kind"] == "accepted":
        fields(data, "checkpoint")
        if data["checkpoint"] != "accepted":
            raise ProtocolError("Invalid acceptance")
    elif value["kind"] == "checkpoint":
        fields(data, "checkpoint")
        if data["checkpoint"] not in {"sandbox_starting", "sandbox_finished"}:
            raise ProtocolError("Unregistered milestone")
    elif value["kind"] == "tool":
        validate_evidence(data)
    else:
        fields(data, "status reason artifacts")
        if data["status"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
            raise ProtocolError("Invalid execution status")
        identifier(data["reason"])
        if not isinstance(data["artifacts"], list) or len(data["artifacts"]) > 4:
            raise ProtocolError("Too many artifacts")
        paths = set()
        for artifact in data["artifacts"]:
            fields(artifact, "path sha256 size")
            path(artifact["path"])
            sha256(artifact["sha256"])
            integer(artifact["size"], 0, MAXIMA["artifact_bytes"])
            if artifact["path"] in paths:
                raise ProtocolError("Duplicate artifact")
            paths.add(artifact["path"])
        permitted_status = {"result": {"succeeded"}, "failure": {"failed", "interrupted"}, "cancelled": {"cancelled"}}
        if data["status"] not in permitted_status[value["kind"]]:
            raise ProtocolError("Result kind/status mismatch")
    canonical(value)


def validate_cancel(value):
    fields(value, "kind assignment_id attempt_id worker_id assignment_digest expires_at")
    if value["kind"] != "cancel":
        raise ProtocolError("Invalid cancellation")
    for name in ("assignment_id", "attempt_id", "worker_id"):
        identifier(value[name])
    sha256(value["assignment_digest"])
    integer(value["expires_at"], 1, 2**53-1)


def _strict(function):
    from functools import wraps
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            raise ProtocolError("Malformed protocol structure") from None
    return wrapped


for _name in ("validate_identity", "validate_assignment", "validate_event", "validate_cancel", "verify"):
    globals()[_name] = _strict(globals()[_name])
