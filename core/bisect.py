"""
core/bisect.py
Automated performance bisection over *builds*.

Given a known-good and known-bad commit, binary-search the commits in between.
Each probe builds the midpoint and compares it against the good build with an
interleaved A/B run (core.interleaved), so every decision is made inside a single
time window. Cost: O(log K) builds instead of K.

The first step re-checks that the bad commit actually regresses against the good
one. If it does not reproduce, bisection stops: there is nothing to find. (The
earlier version of this module searched stored historical results and happily
"found" a culprit for a flag that had already failed to reproduce.)
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
    """Reject refs that could be interpreted as git CLI options (starting with '-') or contain shell/control chars."""
    if not ref or ref.startswith("-") or ".." in ref or "@{" in ref or not _SAFE_REF_RE.match(ref):
        raise ValueError(f"Invalid or unsafe git ref: {ref!r}")
    return ref


def git_rev_list(repo: Path, good: str, bad: str) -> List[str]:
    """[good, ..., bad] in first-parent order."""
    validate_git_ref(good)
    validate_git_ref(bad)
    if not shutil.which("git"):
        raise RuntimeError("git not found on PATH")
    out = subprocess.run(["git", "rev-list", "--reverse", "--first-parent", f"{good}..{bad}", "--"],
                         cwd=repo, capture_output=True, text=True, check=True).stdout.split()
    good_sha = subprocess.run(["git", "rev-parse", "--verify", f"{good}^{{commit}}"], cwd=repo, capture_output=True,
                              text=True, check=True).stdout.strip()
    return [good_sha] + out


def _is_borderline(r: Dict[str, Any], alpha: float, min_effect_pct: float) -> bool:
    """True if a probe sits near the significance or effect-size boundary and warrants a repeat."""
    p = r["p_value"]
    shift = r["shift_pct"]
    if r["verdict"] == "flag" and shift > 0:
        # Borderline flag: p-value is within 5x of alpha or 95% CI does not clear min_effect_pct
        if p >= (alpha * 0.2) or not r.get("ci_clears_min_effect", True):
            return True
    if r["verdict"] != "flag" and shift > min_effect_pct and alpha <= p <= min(alpha * 3.0, 0.05):
        return True
    return False


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
    if len(commits) < 2:
        raise ValueError("need at least a good and a bad commit")

    builds: Dict[str, str] = {}

    def artifact(ref: str) -> str:
        if ref not in builds:
            br = adapter.build(ref, workdir=workdir)
            if not br.ok or not br.artifact:
                raise RuntimeError(f"build failed for {ref}: {br.log_tail[-500:]}")
            builds[ref] = br.artifact
        return builds[ref]

    def regressed(ref: str, step: int) -> Dict[str, Any]:
        art_good = artifact(commits[0])
        art_cand = artifact(ref)
        r = run_interleaved(adapter, bench, art_good, art_cand, pairs=pairs,
                            iters=iters, warmup=warmup, alpha=alpha,
                            min_effect_pct=min_effect_pct, seed=seed + step)
        r["repeated"] = False
        if repeat_borderline and _is_borderline(r, alpha, min_effect_pct):
            log(f"    borderline probe on {ref[:10]} (shift={r['shift_pct']:+.2f}%, p={r['p_value']:.2e}); repeating to confirm...")
            r2 = run_interleaved(adapter, bench, art_good, art_cand, pairs=pairs,
                                 iters=iters, warmup=warmup, alpha=alpha,
                                 min_effect_pct=min_effect_pct, seed=seed + step + 1000)
            # The decision comes from the fresh, independent batch alone, under the same rule as
            # the first. Pooling both batches and re-testing at the same alpha would be optional
            # stopping: the second batch only exists because the first looked borderline, so the
            # pooled test's false-positive rate is above alpha. The pooled estimate is kept for
            # reporting only.
            pooled = analyze_paired(r["a_medians"] + r2["a_medians"], r["b_medians"] + r2["b_medians"],
                                    alpha=alpha, min_effect_pct=min_effect_pct)
            first = {k: r[k] for k in ("shift_pct", "shift_ci95_pct", "p_value", "verdict")}
            r = r2
            r["first_batch"] = first
            r["pooled_shift_pct"] = pooled["shift_pct"]
            r["pooled_shift_ci95_pct"] = pooled["shift_ci95_pct"]
            r["repeated"] = True
        r["is_regressed"] = r["verdict"] == "flag" and r["shift_pct"] > 0
        return r

    steps: List[Dict[str, Any]] = []
    check = regressed(commits[-1], 0)
    steps.append({"step": 0, "ref": commits[-1], "role": "confirm bad", **_brief(check)})
    log(f"  confirm bad {commits[-1][:10]}: shift={check['shift_pct']:+.2f}% "
        f"CI{check['shift_ci95_pct']} p={check['p_value']:.2e} -> {'REGRESSED' if check['is_regressed'] else 'not regressed'}")
    if not check["is_regressed"]:
        return {"culprit": None, "reproduced": False, "steps": steps, "builds": len(builds)}

    lo, hi = 0, len(commits) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        r = regressed(commits[mid], len(steps))
        steps.append({"step": len(steps), "ref": commits[mid], "role": "probe", **_brief(r)})
        log(f"  probe {commits[mid][:10]}: shift={r['shift_pct']:+.2f}% p={r['p_value']:.2e} "
            f"-> {'BAD' if r['is_regressed'] else 'good'}")
        if r["is_regressed"]:
            hi = mid
        else:
            lo = mid

    return {"culprit": commits[hi], "last_good": commits[lo], "reproduced": True,
            "steps": steps, "builds": len(builds)}


def _brief(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: r[k] for k in ("shift_pct", "shift_ci95_pct", "p_value", "verdict", "is_regressed", "repeated")}
