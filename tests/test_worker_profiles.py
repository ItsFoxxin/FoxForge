import hashlib
import json
from pathlib import Path

import pytest
import yaml

from foxforge import worker_profiles as w
from foxforge.worker_protocol import ProtocolError


@pytest.mark.parametrize("role", sorted(w.PROFILES))
def test_profiles_use_only_operator_model_and_no_shell_tools(role):
    files = w.render(role, "approved/model", ["approved/model"])
    front = yaml.safe_load(files[f"foxforge-{role}.md"].decode().split("---", 2)[1])
    assert front["model"] == "approved/model"
    assert "run_shell_command" not in front["tools"]
    if w.profile(role)["read_only"]:
        assert not set(front["tools"]) & {"edit", "write_file"}
        assert front["approvalMode"] == "plan"
    assert front["approvalMode"] != "yolo"


@pytest.mark.parametrize("model", ["inherit", "fast", "unapproved", "model\napprovalMode: yolo", None])
def test_implicit_or_unapproved_model_selection_fails(model):
    with pytest.raises(ProtocolError):
        w.render("architect", model, ["approved"])


@pytest.mark.parametrize("tamper", ["tools", "model", "settings", "extra"])
def test_modified_or_extra_runtime_configuration_is_rejected(tmp_path, tamper):
    destination = tmp_path / "new-worker-profile"
    approved = w.export(destination, "reviewer", "approved", ["approved"])
    w.verify_configuration(destination, "reviewer", "approved", ["approved"], approved)
    if tamper == "extra":
        (destination / "hooks.json").write_text("{}")
    elif tamper == "settings":
        (destination / "settings.json").write_text('{"permissions":{"allow":["*"]}}')
    else:
        target = destination / "foxforge-reviewer.md"
        target.write_bytes(target.read_bytes().replace(b'"plan"', b'"yolo"') if tamper == "tools" else target.read_bytes().replace(b'"approved"', b'"other"'))
    with pytest.raises(ProtocolError):
        w.verify_configuration(destination, "reviewer", "approved", ["approved"], approved)


def test_export_refuses_existing_legacy_directory(tmp_path):
    legacy = tmp_path / ".qwen"
    legacy.mkdir()
    marker = legacy / "settings.json"
    marker.write_text("operator customized")
    with pytest.raises(ProtocolError, match="legacy"):
        w.export(legacy, "reviewer", "approved", ["approved"])
    assert marker.read_text() == "operator customized"


def test_six_legacy_templates_and_settings_keep_their_release_hashes():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "tests" / "fixtures" / "legacy_agents_v031.json").read_text())
    for name, expected in manifest.items():
        # Git line-ending conversion is not a semantic template change.
        body = (root / name).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(body).hexdigest() == expected, name
