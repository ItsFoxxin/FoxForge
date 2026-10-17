from pathlib import Path
import json
import re

import pytest

from foxforge.agent_runner import PROJECT_ROLES


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("role", PROJECT_ROLES)
def test_project_agents_match_templates_and_keep_boundaries(role):
    text = (ROOT / ".qwen" / "agents" / f"{role}.md").read_text(encoding="utf-8")
    assert text == (ROOT / "templates" / "qwen-agents" / f"{role}.md").read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    tools = re.findall(r"^  - (\w+)$", frontmatter, re.MULTILINE)
    if role in {"helper", "reporter"}:
        assert "tools: []" in frontmatter
    if role in {"architect", "reviewer", "helper", "reporter"}:
        assert not set(tools) & {"edit", "write_file", "run_shell_command"}
    else:
        assert set(tools) == {"read_file", "edit", "write_file", "grep_search", "glob", "run_shell_command"}
    assert "yolo" not in frontmatter.lower()


def test_repository_settings_only_allow_delegation():
    settings = json.loads((ROOT / ".qwen" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Agent"]
