"""
core/report.py
Markdown report formatter for PR comments and GitHub Actions step summaries.
"""

import html
from typing import Any, Dict, List, Optional


def _safe_md(val: Any) -> str:
    """Sanitize a value for safe inclusion inside Markdown table cells, inline code, or HTML tags."""
    s = str(val).replace("\r", " ").replace("\n", " ").replace("`", "'").replace("|", "\\|")
    return html.escape(s, quote=True)


def _report_heading(results: List[Dict[str, Any]]) -> str:
    flagged = [r for r in results if r["final_verdict"] == "flag"]
    if not flagged:
        return "No significant change"
    if any(r["shift_pct"] > 0 for r in flagged):
        return "Possible regression"
    return "Significant change"


def render_markdown(
    base: str,
    cand: str,
    results: List[Dict[str, Any]],
    env: Dict[str, Any],
    canary: Optional[Dict[str, Any]] = None,
) -> str:
    """Render an interleaved A/B comparison summary as sanitized GitHub-flavored Markdown."""
    head = _report_heading(results)
    base_s = _safe_md(base[:10])
    cand_s = _safe_md(cand[:10])
    pairs = results[0]["pairs"] if results else 0

    lines = [
        "<!-- regressor-report -->",
        f"### regressor: {head}",
        "",
        f"`{base_s}` (base) vs `{cand_s}` (PR), interleaved A/B, "
        f"{pairs} pairs per benchmark, order randomized per pair.",
        "",
        "| Benchmark | Base median | PR median | Shift (HL) | 95% CI | Wilcoxon p | Verdict |",
        "|---|---:|---:|---:|---|---:|---|",
    ]
    for r in results:
        verdict = "**flag**" if r["final_verdict"] == "flag" else "ok"
        lo, hi = r["shift_ci95_pct"]
        bench_s = _safe_md(r["benchmark"])
        # At the exact-test floor the p-value only indicates every pair moved the same way.
        p_cell = f"{r['p_value']:.1e}" + (" (floor)" if r.get("p_at_floor") else "")
        lines.append(
            f"| `{bench_s}` | {r['baseline_median_ns']:,.0f} ns | {r['candidate_median_ns']:,.0f} ns | "
            f"{r['shift_pct']:+.2f}% | [{lo:+.2f}%, {hi:+.2f}%] | {p_cell} | {verdict} |"
        )

    if any(r.get("p_at_floor") for r in results):
        lines += [
            "",
            "(floor) = the smallest p-value the exact Wilcoxon test can produce with this many non-zero pairs: "
            "every pair moved in the same direction. Use the shift and its CI, not p, to compare such results.",
        ]

    if canary is not None:
        status_s = _safe_md(canary["status"])
        note = (
            ". A flagged shift in this window may be the host, not the code."
            if canary["is_drifted"]
            else "."
        )
        lines += ["", f"Canary (fixed workload, before vs after): {canary['shift_pct']:+.2f}% -> **{status_s}**{note}"]

    first = results[0] if results else {}
    min_eff = first.get("min_effect_pct", 1.0)
    effect_rule = (
        f"the 95% CI bound clears {min_eff}%"
        if first.get("require_ci_bound")
        else f"|shift| > {min_eff}%"
    )
    lines += [
        "",
        f"Flag rule: Wilcoxon p < {first.get('alpha', 0.01)} after Benjamini-Hochberg across benchmarks, "
        f"and {effect_rule}.",
        "",
        "<sub>"
        f"Runner: {_safe_md(env.get('platform', '?'))} · CPU: {_safe_md(env.get('cpu', '?'))} · "
        "Timing only (no hardware counters). Shared CI runners are noisy; interleaving cancels slow drift "
        "but not noise that differs between the two binaries' runs."
        "</sub>",
    ]
    return "\n".join(lines) + "\n"
