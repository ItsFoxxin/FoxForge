from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_compose_enforces_storage_credential_and_execution_boundaries():
    value = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    fox, gateway = value["services"]["foxforge"], value["services"]["freellmapi"]
    assert fox["restart"] == "no" and fox["profiles"] == ["cli"]
    assert fox["user"] == "10001:10001" and gateway["user"] == "1000:1000"
    for service in (fox, gateway):
        assert service["read_only"] and service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert not service.get("privileged") and service["mem_limit"] and service["pids_limit"]
        assert not any("docker.sock" in str(mount) for mount in service["volumes"])
    assert re.search(r"@sha256:[0-9a-f]{64}$", gateway["image"])
    assert gateway["ports"] == ["127.0.0.1:3001:3001"]
    mounts = {row["target"]: row for row in fox["volumes"]}
    assert mounts["/etc/foxforge"]["read_only"]
    assert mounts["/var/lib/foxforge/repos"]["read_only"]
    assert not mounts["/var/lib/foxforge/control-plane"].get("read_only", False)
    assert value["networks"]["control"]["internal"]
    assert not any("freellmapi" in str(row["source"]) for row in fox["volumes"])


def test_image_does_not_copy_worktree_or_credentials():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER 10001:10001" in text
    assert "foxforge.container_cli" in text and "sleep" not in text
    assert "COPY . ." not in text
    assert all("@sha256:" in line for line in text.splitlines() if line.startswith("FROM "))
