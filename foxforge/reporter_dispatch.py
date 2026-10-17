import argparse
import json
from pathlib import Path

from notifier import send_discord


def load_state(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_reporter_output(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def validate_state(state: dict) -> None:
    required = [
        "task",
        "agents_completed",
        "files_changed",
        "tests_added",
        "tests_passed",
        "tests_failed",
        "review_result",
        "repair_cycles",
        "final_status",
    ]

    missing = [key for key in required if key not in state]

    if missing:
        raise ValueError(
            f"Missing required state fields: {', '.join(missing)}"
        )


def build_message(state: dict, reporter_output: str) -> str:
    agents = ", ".join(state["agents_completed"])
    files = ", ".join(state["files_changed"])

    return (
        "FoxForge Status\n\n"
        f"Task: {state['task']}\n"
        f"Agents completed: {agents}\n"
        f"Files changed: {files}\n"
        f"Tests added: {state['tests_added']}\n"
        f"Tests: {state['tests_passed']} passed, "
        f"{state['tests_failed']} failed\n"
        f"Review: {state['review_result']}\n"
        f"Repair cycles: {state['repair_cycles']}\n"
        f"Status: {state['final_status']}\n\n"
        "Reporter output:\n"
        f"{reporter_output}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a verified FoxForge reporter notification"
    )

    parser.add_argument(
        "--state",
        required=True,
        help="Path to verified FoxForge state JSON",
    )

    parser.add_argument(
        "--reporter",
        required=True,
        help="Path to reporter output text",
    )

    args = parser.parse_args()

    try:
        state = load_state(args.state)
        reporter_output = load_reporter_output(args.reporter)

        validate_state(state)

        if not reporter_output:
            raise ValueError("Reporter output is empty")

        message = build_message(state, reporter_output)

        if send_discord(message):
            print("Reporter notification sent")
            raise SystemExit(0)

        print("Reporter notification failed")
        raise SystemExit(1)

    except Exception as exc:
        print(f"Reporter dispatch failed: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()