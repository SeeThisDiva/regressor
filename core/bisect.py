"""
core/bisect.py
Automated performance bisection over builds.

Given a known-good and known-bad commit, binary-search the commits between them.
Each probe builds the midpoint and compares it against the good build with an
interleaved A/B run (``core.interleaved``) inside a single time window, requiring
O(log K) builds instead of K.

Bisection first confirms that the bad commit reproduces a regression against the
good commit; if it does not reproduce, bisection stops immediately rather than
searching stale historical data.
"""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from adapters.base import BaseAdapter
from core.interleaved import analyze_paired, run_interleaved

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9_./~^-]+$")


def validate_git_ref(ref: str) -> str:
    """Reject refs that could act as git CLI options or contain unsafe syntax."""
    if not ref or ref.startswith("-") or ".." in ref or "@{" in ref or not _SAFE_REF_RE.match(ref):
        raise ValueError(f"Invalid or unsafe git ref: {ref!r}")
    return ref


def git_rev_list(repo: Path, good: str, bad: str) -> List[str]:
    """Return ``[good, ..., bad]`` commit SHAs in chronological first-parent order."""
    validate_git_ref(good)
    validate_git_ref(bad)
    if not shutil.which("git"):
        raise RuntimeError("git not found on PATH")
    out = subprocess.run(
        ["git", "rev-list", "--reverse", "--first-parent", f"{good}..{bad}", "--"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    good_sha = subprocess.run(
        ["git", "rev-parse", "--verify", f"{good}^{{commit}}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return [good_sha] + out


def _is_borderline(r: Dict[str, Any], alpha: float, min_effect_pct: float) -> bool:
    """Return True if a probe sits near the significance or effect-size boundary."""
    p = r["p_value"]
    shift = r["shift_pct"]
    if r["verdict"] == "flag" and shift > 0:
        # Borderline flag: p-value is within 5x of alpha or 95% CI does not clear min_effect_pct.
        if p >= (alpha * 0.2) or not r.get("ci_clears_min_effect", True):
            return True
    if r["verdict"] != "flag" and shift > min_effect_pct and alpha <= p <= min(alpha * 3.0, 0.05):
        return True
    return False


def _brief(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: r[k] for k in ("shift_pct", "shift_ci95_pct", "p_value", "verdict", "is_regressed", "repeated")}


def _probe_commit(
    adapter: BaseAdapter,
    bench: str,
    art_good: str,
    art_cand: str,
    ref: str,
    pairs: int,
    iters: int,
    warmup: int,
    alpha: float,
    min_effect_pct: float,
    seed: int,
    repeat_borderline: bool,
    log: Callable[[str], None],
) -> Dict[str, Any]:
    """Run an interleaved probe (and optional independent confirmation batch on borderline outcomes)."""
    probe_kwargs = {
        "pairs": pairs,
        "iters": iters,
        "warmup": warmup,
        "alpha": alpha,
        "min_effect_pct": min_effect_pct,
    }
    result = run_interleaved(adapter, bench, art_good, art_cand, seed=seed, **probe_kwargs)
    result["repeated"] = False

    if repeat_borderline and _is_borderline(result, alpha, min_effect_pct):
        log(
            f"    borderline probe on {ref[:10]} "
            f"(shift={result['shift_pct']:+.2f}%, p={result['p_value']:.2e}); repeating to confirm..."
        )
        confirm = run_interleaved(adapter, bench, art_good, art_cand, seed=seed + 1000, **probe_kwargs)
        # Decide from the independent confirmation batch alone so optional stopping does not
        # inflate the false-positive rate; keep the pooled estimate for reporting only.
        pooled = analyze_paired(
            result["a_medians"] + confirm["a_medians"],
            result["b_medians"] + confirm["b_medians"],
            alpha=alpha,
            min_effect_pct=min_effect_pct,
        )
        first = {k: result[k] for k in ("shift_pct", "shift_ci95_pct", "p_value", "verdict")}
        result = confirm
        result["first_batch"] = first
        result["pooled_shift_pct"] = pooled["shift_pct"]
        result["pooled_shift_ci95_pct"] = pooled["shift_ci95_pct"]
        result["repeated"] = True

    result["is_regressed"] = result["verdict"] == "flag" and result["shift_pct"] > 0
    return result


def bisect_builds(
    adapter: BaseAdapter,
    commits: List[str],
    bench: str,
    pairs: int = 12,
    iters: int = 1500,
    warmup: int = 150,
    workdir: Optional[Path] = None,
    alpha: float = 0.01,
    min_effect_pct: float = 1.0,
    seed: int = 0,
    repeat_borderline: bool = True,
    log: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """Binary-search ``commits`` (good -> bad) using interleaved A/B probes against ``commits[0]``."""
    if len(commits) < 2:
        raise ValueError("need at least a good and a bad commit")

    builds: Dict[str, str] = {}

    def get_artifact(ref: str) -> str:
        if ref not in builds:
            br = adapter.build(ref, workdir=workdir)
            if not br.ok or not br.artifact:
                raise RuntimeError(f"build failed for {ref}: {br.log_tail[-500:]}")
            builds[ref] = br.artifact
        return builds[ref]

    def run_probe(ref: str, step: int) -> Dict[str, Any]:
        return _probe_commit(
            adapter=adapter,
            bench=bench,
            art_good=get_artifact(commits[0]),
            art_cand=get_artifact(ref),
            ref=ref,
            pairs=pairs,
            iters=iters,
            warmup=warmup,
            alpha=alpha,
            min_effect_pct=min_effect_pct,
            seed=seed + step,
            repeat_borderline=repeat_borderline,
            log=log,
        )

    steps: List[Dict[str, Any]] = []
    check = run_probe(commits[-1], 0)
    steps.append({"step": 0, "ref": commits[-1], "role": "confirm bad", **_brief(check)})
    log(
        f"  confirm bad {commits[-1][:10]}: shift={check['shift_pct']:+.2f}% "
        f"CI{check['shift_ci95_pct']} p={check['p_value']:.2e} -> "
        f"{'REGRESSED' if check['is_regressed'] else 'not regressed'}"
    )
    if not check["is_regressed"]:
        return {"culprit": None, "reproduced": False, "steps": steps, "builds": len(builds)}

    lo, hi = 0, len(commits) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        res = run_probe(commits[mid], len(steps))
        steps.append({"step": len(steps), "ref": commits[mid], "role": "probe", **_brief(res)})
        log(
            f"  probe {commits[mid][:10]}: shift={res['shift_pct']:+.2f}% p={res['p_value']:.2e} "
            f"-> {'BAD' if res['is_regressed'] else 'good'}"
        )
        if res["is_regressed"]:
            hi = mid
        else:
            lo = mid

    return {
        "culprit": commits[hi],
        "last_good": commits[lo],
        "reproduced": True,
        "steps": steps,
        "builds": len(builds),
    }
