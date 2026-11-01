"""Deterministic review artifact rendering for validated plans."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from .denkit import css
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


def _html(value) -> str:
    return escape(str(value), quote=True)


def _items(values: list[str], empty: str = "None recorded.") -> str:
    return "".join(f"<li>{_html(value)}</li>" for value in (values or [empty]))


def render_html(task: dict, plan: dict, telemetry: dict) -> str:
    """Render a self-contained, script-free DenKit review document."""
    subtasks = []
    for item in plan["subtasks"]:
        dependencies = ", ".join(item["depends_on"]) or "none"
        subtasks.append(
            '<article class="task">'
            f"<h3>{_html(item['id'])}: {_html(item['title'])}</h3>"
            f"<p>{_html(item['description'])}</p>"
            '<div class="task-meta">'
            f'<span class="chip">Capability: {_html(item["capability"])}</span>'
            f'<span class="chip">Dependencies: {_html(dependencies)}</span>'
            "</div></article>"
        )
    route = telemetry.get("routed_via") or "not reported"
    model = telemetry.get("configured_model", "plan-file")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <meta name="theme-color" content="#0B1423">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
  <title>FoxForge plan · {_html(task['repository'])} #{_html(task['issue_number'])}</title>
  <style>{css()}</style>
</head>
<body>
  <a class="skip-link" href="#plan">Skip to plan</a>
  <div class="shell">
    <header class="masthead">
      <div class="brand" aria-label="FoxForge">FoxForge · DenKit v0.1</div>
      <div>
        <h1>Implementation plan</h1>
        <p class="lede">{_html(plan['summary'])}</p>
      </div>
      <div class="status">Awaiting human review</div>
    </header>
    <dl class="meta" aria-label="Plan metadata">
      <div><dt>Task</dt><dd><code>{_html(task['id'])}</code></dd></div>
      <div><dt>Repository</dt><dd><code>{_html(task['repository'])}</code></dd></div>
      <div><dt>Issue</dt><dd><code>#{_html(task['issue_number'])}</code></dd></div>
      <div><dt>Pinned commit</dt><dd><code>{_html(task['base_sha'])}</code></dd></div>
    </dl>
    <main id="plan">
      <section class="card"><h2>Acceptance criteria</h2><ul>{_items(plan['acceptance_criteria'])}</ul></section>
      <section class="card"><h2>Proposed work</h2><div class="task-grid">{''.join(subtasks)}</div></section>
      <section class="card"><h2>Assumptions</h2><ul>{_items(plan['assumptions'])}</ul></section>
      <section class="card"><h2>Unknowns</h2><ul>{_items(plan['unknowns'])}</ul></section>
      <section class="card"><h2>Model telemetry</h2>
        <p>Configured model: <code>{_html(model)}</code></p>
        <p>Actual route: <code>{_html(route)}</code></p>
      </section>
      <aside class="card notice" aria-label="Authorization notice">
        <strong>Review boundary</strong>
        <p>This artifact is a proposal awaiting human review. It authorizes no implementation, Git write, pull request, deployment, or infrastructure operation.</p>
      </aside>
    </main>
  </div>
</body>
</html>
"""


def write_artifacts(directory: Path, task: dict, plan: dict, discovery: dict, telemetry: dict) -> None:
    atomic_json(directory / "plan.json", plan)
    atomic_json(directory / "repository-discovery.json", discovery)
    atomic_json(directory / "model-telemetry.json", telemetry)
    (directory / "plan.md").write_text(render_markdown(task, plan, telemetry), encoding="utf-8")
    (directory / "plan.html").write_text(render_html(task, plan, telemetry), encoding="utf-8")
