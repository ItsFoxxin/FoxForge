"""Deterministic review artifact rendering for validated plans."""

from __future__ import annotations

import json
from pathlib import Path

from .intake_storage import atomic_json


def _inline(value) -> str:
    return str(value).replace("`", "'").replace("\r", " ").replace("\n", " ")[:512]


def render_markdown(task: dict, plan: dict, telemetry: dict) -> str:
    lines = ["# FoxForge implementation plan", "", f"Task: `{task['id']}`", f"Repository: `{task['repository']}`",
             f"Issue: `#{task['issue_number']}`", f"Pinned commit: `{task['base_sha']}`", "", "## Summary", "", plan["summary"],
             "", "## Acceptance criteria", ""]
    lines.extend(f"- {item}" for item in plan["acceptance_criteria"])
    lines.extend(["", "## Proposed work", ""])
    for item in plan["subtasks"]:
        dependencies = ", ".join(item["depends_on"]) or "none"
        lines.extend([f"### {item['id']}: {item['title']}", "", item["description"], "",
                      f"Capability: `{item['capability']}`  ", f"Dependencies: `{dependencies}`", ""])
    lines.extend(["## Assumptions", ""])
    lines.extend(f"- {item}" for item in plan["assumptions"] or ["None recorded."])
    lines.extend(["", "## Unknowns", ""])
    lines.extend(f"- {item}" for item in plan["unknowns"] or ["None recorded."])
    lines.extend(["", "## Model telemetry", "", f"Configured model: `{_inline(telemetry.get('configured_model', 'plan-file'))}`",
                  f"Actual route: `{_inline(telemetry.get('routed_via') or 'not reported')}`",
                  "", "This artifact is a proposal awaiting human review. It authorizes no implementation, Git write, PR, deployment, or infrastructure operation.", ""])
    return "\n".join(lines)


def write_artifacts(directory: Path, task: dict, plan: dict, discovery: dict, telemetry: dict) -> None:
    atomic_json(directory / "plan.json", plan)
    atomic_json(directory / "repository-discovery.json", discovery)
    atomic_json(directory / "model-telemetry.json", telemetry)
    (directory / "plan.md").write_text(render_markdown(task, plan, telemetry), encoding="utf-8")
