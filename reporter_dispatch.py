from __future__ import annotations

import argparse
from pathlib import Path

from .notifier import send_discord
from .state import RunState
from .state_validator import (
    validate_reporter_output,
    validate_state_for_report,
)


def dispatch_report(
    state_path: Path,
    reporter_path: Path,
) -> bool:
    state = RunState.load(state_path)
    reporter_output = reporter_path.read_text(
        encoding="utf-8"
    ).strip()

    if not reporter_output:
        raise ValueError("Reporter output is empty")

    validate_state_for_report(state)
    validate_reporter_output(
        state,
        reporter_output,
    )

    return send_discord(reporter_output)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and send a FoxForge Reporter notification"
    )
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--reporter", required=True, type=Path)
    args = parser.parse_args()

    try:
        if dispatch_report(args.state, args.reporter):
            print("Reporter notification sent")
            return 0

        print("Reporter notification failed")
        return 1

    except Exception as exc:
        print(f"Reporter dispatch failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
