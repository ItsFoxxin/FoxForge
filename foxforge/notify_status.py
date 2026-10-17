import argparse
import json
from pathlib import Path

from notifier import send_discord


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--state",
        required=True,
        help="Path to verified FoxForge state JSON",
    )

    parser.add_argument(
        "--reporter",
        required=False,
        help="Optional path to reporter output",
    )

    args = parser.parse_args()

    state = json.loads(
        Path(args.state).read_text(encoding="utf-8")
    )

    reporter_text = None

    if args.reporter:
        reporter_text = Path(args.reporter).read_text(
            encoding="utf-8"
        ).strip()

    message = (
        "FoxForge Status\n\n"
        f"Task: {state['task']}\n"
        f"Agents: {', '.join(state['agents_completed'])}\n"
        f"Tests: {state['tests_passed']} passed, "
        f"{state['tests_failed']} failed\n"
        f"Review: {state['review_result']}\n"
        f"Repair cycles: {state['repair_cycles']}\n"
        f"Status: {state['final_status']}"
    )

    if reporter_text:
        message += f"\n\nReporter:\n{reporter_text}"

    success = send_discord(message)

    if success:
        print("Discord status notification sent")
        raise SystemExit(0)

    print("Discord status notification failed")
    raise SystemExit(1)


if __name__ == "__main__":
    main()