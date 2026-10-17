import pytest

from foxforge.run_storage import create_run_dir


def test_artifact_root_inside_target_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("FOXFORGE_RUNS_DIR", str(tmp_path / "runs"))
    with pytest.raises(ValueError, match="outside"):
        create_run_dir(tmp_path, "run-1")


def test_identically_named_repositories_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setenv("FOXFORGE_RUNS_DIR", str(tmp_path / "runs"))
    a = create_run_dir(tmp_path / "a" / "repo", "run-1")
    b = create_run_dir(tmp_path / "b" / "repo", "run-1")
    assert a != b and a.exists() and b.exists()


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "", ".", "C:\\temp"])
def test_run_id_cannot_escape_root(tmp_path, monkeypatch, run_id):
    monkeypatch.setenv("FOXFORGE_RUNS_DIR", str(tmp_path / "runs"))
    with pytest.raises(ValueError):
        create_run_dir(tmp_path / "target", run_id)
