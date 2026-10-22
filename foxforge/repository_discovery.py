"""Commit-pinned, bounded, read-only repository discovery."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import json

from .git_manager import ensure_repo, resolve_ref, run_git


MAX_FILES = 20_000
MAX_CONTEXT_BYTES = 256 * 1024
INTERESTING_NAMES = {
    "AGENTS.md", "README.md", "README", "pyproject.toml", "package.json", "Cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "requirements.txt",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
}


class DiscoveryError(RuntimeError):
    pass


def _interesting(path: str) -> bool:
    item = PurePosixPath(path)
    return item.name in INTERESTING_NAMES or path.startswith(".github/workflows/") or path.startswith("docs/") and item.name in {"ARCHITECTURE.md", "DESIGN.md", "CONTRIBUTING.md"}


def discover_repository(repo: Path, ref: str) -> dict:
    repo = repo.resolve()
    ensure_repo(repo)
    commit = resolve_ref(repo, ref)
    raw = run_git(repo, "ls-tree", "-r", "--name-only", "-z", commit, "--", safe=True).stdout
    files = [name for name in raw.split("\0") if name]
    if len(files) > MAX_FILES or any("\0" in name or len(name) > 1024 for name in files):
        raise DiscoveryError("Repository file inventory exceeds discovery limits")
    selected: dict[str, str] = {}
    used = 0
    for name in sorted(path for path in files if _interesting(path)):
        blob = run_git(repo, "show", f"{commit}:{name}", safe=True).stdout
        size = len(blob.encode("utf-8"))
        if size > 64 * 1024 or used + size > MAX_CONTEXT_BYTES:
            continue
        selected[name] = blob
        used += size
    suffixes: dict[str, int] = {}
    for name in files:
        suffix = PurePosixPath(name).suffix.lower() or "(none)"
        suffixes[suffix] = suffixes.get(suffix, 0) + 1
    manifests = [name for name in files if PurePosixPath(name).name in INTERESTING_NAMES]
    tests = [name for name in files if "test" in PurePosixPath(name).name.lower()][:200]
    return {
        "schema_version": 1,
        "commit": commit,
        "file_count": len(files),
        "suffix_counts": dict(sorted(suffixes.items(), key=lambda item: (-item[1], item[0]))[:30]),
        "manifests": sorted(manifests)[:200],
        "test_files": sorted(tests),
        "context_files": selected,
        "unknowns": [] if "AGENTS.md" in selected else ["No root AGENTS.md was found at the pinned commit."],
    }


def planner_context(discovery: dict) -> str:
    text = json.dumps(discovery, ensure_ascii=True, indent=2)
    if len(text.encode("utf-8")) > MAX_CONTEXT_BYTES * 2:
        raise DiscoveryError("Discovery context is too large")
    return text
