"""
core/session.py
Wall-clock session-gap accounting between consecutive benchmark runs.

Two runs separated by a long gap may have executed under different host
conditions (frequency governor state, co-tenants, or a different physical
host after migration). Comparisons that cross such a gap are tagged as
environment-confounded rather than silently trusted.
"""

from datetime import datetime
from typing import Any, List, Optional, Sequence

# Comparisons whose two runs are separated by more than this are treated as
# crossing a measurement session (i.e., potentially confounded by host drift).
SESSION_BREAK_MIN = 15.0


def session_gap_minutes(base_commit: Any, cand_commit: Any) -> Optional[float]:
    """Return minutes between the end of ``base_commit`` and start of ``cand_commit``."""
    try:
        end = datetime.fromisoformat(base_commit["run_finished_utc"])
        start = datetime.fromisoformat(cand_commit["run_started_utc"])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    return round((start - end).total_seconds() / 60.0, 1)


def is_session_break(gap_min: Optional[float], threshold_min: float = SESSION_BREAK_MIN) -> bool:
    """Return True when a known gap strictly exceeds ``threshold_min``."""
    return gap_min is not None and gap_min > threshold_min


def commit_session_gaps(commits: Sequence[Any]) -> List[Optional[float]]:
    """Compute wall-clock gaps (in minutes) across an ordered sequence of commits.

    The first commit has gap ``None``; each subsequent commit records the gap
    between the previous commit's finish time and its own start time.
    """
    if not commits:
        return []
    return [None] + [
        session_gap_minutes(commits[i - 1], commits[i])
        for i in range(1, len(commits))
    ]


def find_session_break_indices(
    commits: Sequence[Any],
    threshold_min: float = SESSION_BREAK_MIN,
) -> List[int]:
    """Return 0-based indices of commits that start after a session break."""
    return [
        idx
        for idx, gap in enumerate(commit_session_gaps(commits))
        if is_session_break(gap, threshold_min)
    ]
