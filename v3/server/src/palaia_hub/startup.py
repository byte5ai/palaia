"""Problems the hub found while starting, for the dashboard to show.

A hub that cannot use part of its configuration keeps running without that
part rather than exiting (issue #561: an exiting hub in a container restarts
into the same error forever, and the dashboard that could fix it is gone with
it). Each such decision is recorded here, in plain language with the fix, and
``GET /api/setup`` lists them.
"""

from __future__ import annotations

PROBLEMS: list[str] = []


def report_problem(message: str) -> None:
    """Record a start-up problem (once)."""
    if message not in PROBLEMS:
        PROBLEMS.append(message)


__all__ = ["PROBLEMS", "report_problem"]
