"""Small data contracts for future adapters; no privileged execution engine."""

from dataclasses import dataclass
from enum import Enum


class TaskType(str, Enum):
    DEVELOPMENT_PLAN = "development.plan"
    DOCUMENTATION = "documentation.propose"
    INFRASTRUCTURE_READ = "infrastructure.inspect"
    RESEARCH = "research"


@dataclass(frozen=True)
class ToolOperation:
    identifier: str
    risk: str
    target: str


@dataclass(frozen=True)
class ApprovalScope:
    """Scope data only, never an authentication token or permission grant.

    Future adapters must obtain approvals from a verified identity, enforce
    freshness/single use, compare the complete scope, and audit before execution.
    No tool dispatcher or privileged adapter exists in this release.
    """
    task_id: str
    action: str
    target: str
    parameters_digest: str
