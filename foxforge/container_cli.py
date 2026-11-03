"""The control-plane image cannot dispatch the legacy execution worker."""

import os
import sys

from .cli import main


def run(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    os.umask(0o077)
    if not argv or argv[0] not in {"doctor", "storage", "capabilities", "projects", "issues", "tasks"}:
        print("Control-plane container permits diagnostics, storage, discovery and planning only", file=sys.stderr)
        return 2
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(run())
