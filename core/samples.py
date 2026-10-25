"""
core/samples.py
Strict parsing of benchmark sample output.

The old pattern `[float(x) for x in text.split() if x.isdigit()]` silently dropped any token
that was not a bare non-negative integer (decimals, scientific notation, error text), so a
truncated or malformed run produced a shorter list, or an empty one whose median is NaN,
and nothing complained. Here malformed output raises.
"""

from typing import List, Optional


def parse_samples(text: str, expected: Optional[int] = None, source: str = "benchmark output") -> List[float]:
    tokens = text.split()
    if not tokens:
        raise ValueError(f"{source}: no samples produced")
    try:
        vals = [float(t) for t in tokens]
    except ValueError as exc:
        bad = next(t for t in tokens if not _is_number(t))
        raise ValueError(f"{source}: non-numeric token {bad!r}") from exc
    if any(v != v or v in (float("inf"), float("-inf")) for v in vals):
        raise ValueError(f"{source}: non-finite sample")
    if any(v <= 0 for v in vals):
        raise ValueError(f"{source}: non-positive sample (durations must be > 0)")
    if expected is not None and len(vals) != expected:
        raise ValueError(f"{source}: expected {expected} samples, got {len(vals)}")
    return vals


def _is_number(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False
