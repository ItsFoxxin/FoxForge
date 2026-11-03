import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("change,expected", [(None, 0), ("no_approval", 1), ("unknown_secret_field", 1), ("internal_config", 1)])
def test_worker_launcher_validation_has_no_runtime_side_effects(tmp_path, change, expected):
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if not powershell:
        pytest.skip("PowerShell is needed only for the Windows launcher")
    repo = tmp_path / "target"
    repo.mkdir()
    config = {"repository_path": str(repo), "python_executable": sys.executable,
              "test_command": "python -m pytest -v", "publish_pr": True, "poll_interval": 60, "skip_discord": True}
    if change == "no_approval":
        config["publish_pr"] = False
    elif change == "unknown_secret_field":
        config["token"] = "synthetic-value-must-not-be-printed"
    directory = repo if change == "internal_config" else tmp_path
    path = directory / "worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "scripts" / "start-worker.ps1"
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-File", str(script), "-Config", str(path), "-ValidateOnly"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == expected
    assert "synthetic-value" not in result.stdout + result.stderr
    assert not (directory / "worker.log").exists()
