"""
Deprecated compatibility entry point.

FoxForge notifications must flow through reporter_dispatch so the Reporter
output is validated against deterministic run state before Discord delivery.
"""

from __future__ import annotations

from .reporter_dispatch import main


if __name__ == "__main__":
    raise SystemExit(main())
