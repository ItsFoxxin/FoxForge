from pathlib import Path

from foxforge.state import RunState


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
