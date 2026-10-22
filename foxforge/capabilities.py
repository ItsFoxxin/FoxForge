"""Central, versioned capability definitions for adaptive planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ToolPermission:
    operation: str
    risk: str

    def __post_init__(self) -> None:
        if self.risk not in {"read", "propose", "write", "deploy", "high_risk"}:
            raise ValueError("Invalid tool risk")


@dataclass(frozen=True)
class Capability:
    identifier: str
    version: int
    domain: str
    task_types: tuple[str, ...]
    description: str
    tools: tuple[ToolPermission, ...]
    permission_profile: str
    structured_output: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


CAPABILITIES = {
    item.identifier: item
    for item in (
        Capability("repository.discovery", 1, "development", ("inspect_repository",),
                   "Inspect repository structure and conventions without executing project code.",
                   (ToolPermission("repository.read", "read"),), "repository_read_only"),
        Capability("architecture.planning", 1, "development", ("design", "decompose"),
                   "Design a bounded implementation plan and dependency graph.",
                   (ToolPermission("repository.read", "read"),), "repository_read_only"),
        Capability("development.general", 1, "development", ("implement",),
                   "Implement repository changes in an isolated workspace.",
                   (ToolPermission("repository.read", "read"), ToolPermission("workspace.write", "write")),
                   "isolated_workspace_write"),
        Capability("quality.assurance", 1, "development", ("validate", "test"),
                   "Design and run repository validation in an isolated workspace.",
                   (ToolPermission("repository.read", "read"), ToolPermission("workspace.write", "write"),
                    ToolPermission("validation.execute", "write")), "isolated_validation"),
        Capability("code.review", 1, "development", ("review",),
                   "Independently review a candidate and its validation evidence.",
                   (ToolPermission("repository.read", "read"),), "repository_read_only"),
        Capability("documentation", 1, "documentation", ("document",),
                   "Propose or implement bounded documentation changes.",
                   (ToolPermission("repository.read", "read"), ToolPermission("documentation.propose", "propose")),
                   "documentation_propose"),
    )
}


def get_capability(identifier: str) -> Capability:
    try:
        return CAPABILITIES[identifier]
    except KeyError:
        raise ValueError(f"Unknown capability: {identifier}") from None


def public_catalog() -> list[dict]:
    return [CAPABILITIES[key].to_dict() for key in sorted(CAPABILITIES)]
