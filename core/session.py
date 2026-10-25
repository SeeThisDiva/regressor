"""
core/session.py
Wall-clock session-gap accounting between consecutive benchmark runs.

Two runs separated by a long gap may have executed under different host
conditions (frequency governor state, co-tenants, or a different physical
host after migration). Comparisons that cross such a gap are tagged as
environment-confounded rather than silently trusted.
"""

from datetime import datetime
from typing import Optional

# Comparisons whose two runs are separated by more than this are treated as
# crossing a measurement session, i.e. confounded by host drift.
SESSION_BREAK_MIN = 15.0


def session_gap_minutes(base_commit, cand_commit) -> Optional[float]:
    """Minutes between the end of the base run and the start of the candidate run."""
    try:
        end = datetime.fromisoformat(base_commit["run_finished_utc"])
        start = datetime.fromisoformat(cand_commit["run_started_utc"])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    return round((start - end).total_seconds() / 60.0, 1)


def is_session_break(gap_min: Optional[float], threshold_min: float = SESSION_BREAK_MIN) -> bool:
    """True when a known gap exceeds the session-break threshold."""
    return gap_min is not None and gap_min > threshold_min
