"""Route issue commands without changing the existing task CLI contract."""

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"projects", "issues", "tasks", "capabilities"}:
        from .foundation_cli import main as foundation_main
        return foundation_main(argv)
    if argv and argv[0] in {"issue", "watch"}:
        from .issue_intake import main as issue_main
        return issue_main(argv[0], argv[1:])
    from .coordinator import main as task_main
    return task_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
