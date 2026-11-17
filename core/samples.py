"""
core/samples.py
Strict parsing of benchmark sample output.

Rejects empty, non-numeric, non-finite, non-positive, or wrong-length sample
outputs rather than silently dropping malformed tokens.
"""

import math
import statistics
from pathlib import Path
from typing import List, Optional, Union


def parse_samples(text: str, expected: Optional[int] = None, source: str = "benchmark output") -> List[float]:
    """Parse whitespace-delimited positive finite durations from benchmark output."""
    tokens = text.split()
    if not tokens:
        raise ValueError(f"{source}: no samples produced")

    vals: List[float] = []
    for tok in tokens:
        try:
            vals.append(float(tok))
        except ValueError as exc:
            raise ValueError(f"{source}: non-numeric token {tok!r}") from exc

    if not all(math.isfinite(v) for v in vals):
        raise ValueError(f"{source}: non-finite sample")
    if any(v <= 0 for v in vals):
        raise ValueError(f"{source}: non-positive sample (durations must be > 0)")
    if expected is not None and len(vals) != expected:
        raise ValueError(f"{source}: expected {expected} samples, got {len(vals)}")
    return vals


def read_sample_median(path: Union[Path, str], expected: Optional[int] = None) -> float:
    """Read a sample file and return the median of its parsed duration values."""
    sample_path = Path(path)
    vals = parse_samples(sample_path.read_text(encoding="utf-8"), expected=expected, source=str(sample_path))
    return float(statistics.median(vals))
