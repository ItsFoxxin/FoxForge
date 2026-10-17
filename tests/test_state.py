from pathlib import Path

from foxforge.state import RunState
import pytest


def test_state_round_trip(tmp_path: Path) -> None:
    state = RunState(
        run_id="run-1",
        task="example",
        branch="dev",
        base_ref="HEAD",
        agents_completed=["architect"],
        tests_passed=3,
    )

    path = tmp_path / "state.json"
    state.save(path)

    loaded = RunState.load(path)

    assert loaded == state


def test_atomic_save_preserves_old_state_if_replace_fails(tmp_path, monkeypatch):
    state = RunState("run", "task", "feature", "HEAD")
    path = tmp_path / "state.json"
    state.save(path)
    original = path.read_bytes()
    state.tests_passed = 10
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        state.save(path)
    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("text", ["[]", "{", '{"unexpected": true}'])
def test_invalid_state_file(tmp_path, text):
    path = tmp_path / "state.json"
    path.write_text(text)
    with pytest.raises(ValueError, match="Invalid RunState"):
        RunState.load(path)
