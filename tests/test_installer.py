from pathlib import Path
import shutil
import subprocess

import pytest


def test_installer_preserves_customized_agents(tmp_path):
    powershell = shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell is needed to exercise the optional installer")
    target = tmp_path / "target with spaces"
    target.mkdir()
    script = Path(__file__).resolve().parents[1] / "scripts" / "install-target.ps1"
    command = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-RepoPath", str(target)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    agents = target / ".qwen" / "agents"
    assert len(list(agents.glob("*.md"))) == 6
    templates = script.parents[1] / "templates" / "qwen-agents"
    for definition in templates.glob("*.md"):
        assert (agents / definition.name).read_bytes() == definition.read_bytes()
    assert (target / ".qwen" / "settings.json").is_file()
    reporter = agents / "reporter.md"
    reporter.write_text("customized", encoding="utf-8")
    result = subprocess.run(command, capture_output=True, timeout=30)
    assert result.returncode != 0 and reporter.read_text() == "customized"
    subprocess.run([*command, "-Force"], check=True, capture_output=True, timeout=30)
    assert "tools: []" in reporter.read_text(encoding="utf-8")
    assert (target / ".gitignore").read_text(encoding="utf-8").count(".foxforge/") == 1
