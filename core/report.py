"""
core/report.py
Markdown report formatter, triage/flamegraph integration, and publishable summary reporting.
"""

import html
import json
import math
import re
from pathlib import Path
from statistics import NormalDist
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

from core.db import Database

ROOT_DIR = Path(__file__).resolve().parent.parent
_SAFE_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SAFE_SVG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.svg$")
_HEX_TOKEN_RE = re.compile(r"^[0-9a-f]{7,40}$")
_STUDY1_FLAMEGRAPH_HINTS = {
    "flamegraph_diff.svg": ["0a446ec"],
    "flamegraph_candidate_0a446ec.svg": ["0a446ec"],
    "flamegraph_parent_16d47c5.svg": ["16d47c5"],
    "flamegraph_diff_8f5d947.svg": ["8f5d947"],
}
VALID_TRIAGE_STATUSES = ("confirmed", "false_positive", "layout_artifact", "unreviewed")


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


def validate_project_name(project_name: str) -> str:
    """Reject empty names or path-traversal sequences before resolving project files."""
    if not project_name or ".." in project_name or not _SAFE_PROJECT_RE.match(project_name):
        raise ValueError(f"Invalid project name: {project_name!r}")
    return project_name


def load_project_noise_floor_multiplier(
    project_name: str,
    projects_dir: Optional[Path] = None,
    default: float = 3.0,
) -> float:
    """Return configured ``noise_floor_multiplier`` from ``projects/<project_name>.toml``."""
    if tomllib is None:
        return default
    validate_project_name(project_name)
    base_dir = (projects_dir or (ROOT_DIR / "projects")).resolve()
    conf = (base_dir / f"{project_name}.toml").resolve()
    if conf.parent != base_dir or not conf.is_file():
        return default
    try:
        raw = tomllib.loads(conf.read_text(encoding="utf-8"))
        return float(raw.get("noise_floor_multiplier", default))
    except (OSError, ValueError, KeyError):
        return default


def sanitize_issue_url(url: Any) -> Optional[str]:
    """Allow only well-formed HTTP/HTTPS URLs without whitespace or control chars."""
    if not isinstance(url, str):
        return None
    cleaned = url.strip()
    if not cleaned or any(ch.isspace() or ord(ch) < 32 for ch in cleaned):
        return None
    parsed = urlsplit(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return cleaned


def sanitize_flamegraph_name(name: Any, assets_dir: Optional[Path] = None) -> Optional[str]:
    """Return a validated SVG filename inside ``assets/flamegraphs/``, or ``None`` if invalid/missing."""
    if not isinstance(name, str) or not name.strip():
        return None
    norm = name.strip().replace("\\", "/")
    if ".." in norm.split("/"):
        return None
    allowed_prefixes = ("assets/flamegraphs/", "/flamegraphs/", "flamegraphs/")
    if "/" in norm and not norm.startswith(allowed_prefixes):
        return None
    candidate = Path(norm).name
    if not _SAFE_SVG_NAME_RE.match(candidate):
        return None
    if assets_dir is not None:
        resolved_dir = assets_dir.resolve()
        target = (resolved_dir / candidate).resolve()
        if target.parent != resolved_dir or not target.is_file():
            return None
    return candidate


def _infer_flamegraph_kind(stem: str) -> str:
    lower = stem.lower()
    if "diff" in lower:
        return "diff"
    if "candidate" in lower or "cand" in lower:
        return "candidate"
    if "parent" in lower or "base" in lower:
        return "parent"
    return "profile"


def discover_flamegraphs(assets_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Scan ``assets/flamegraphs/*.svg`` and extract metadata and commit SHA hints."""
    fg_dir = (assets_dir or (ROOT_DIR / "assets" / "flamegraphs")).resolve()
    if not fg_dir.is_dir():
        return []

    found: List[Dict[str, Any]] = []
    for path in sorted(fg_dir.glob("*.svg"), key=lambda p: p.name):
        if not path.is_file() or not _SAFE_SVG_NAME_RE.match(path.name):
            continue
        tokens = [tok.lower() for tok in re.split(r"[_.-]+", path.stem)]
        hints = [tok for tok in tokens if _HEX_TOKEN_RE.match(tok)]
        for extra in _STUDY1_FLAMEGRAPH_HINTS.get(path.name, ()):
            if extra not in hints:
                hints.append(extra)
        found.append({
            "filename": path.name,
            "url": f"/flamegraphs/{path.name}",
            "kind": _infer_flamegraph_kind(path.stem),
            "commit_hints": hints,
            "title": path.stem.replace("_", " "),
        })
    return found


def load_triage_entries(
    project_name: str,
    projects_dir: Optional[Path] = None,
    assets_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Load full triage records from ``projects/<project_name>.triage.json``."""
    validate_project_name(project_name)
    base_dir = (projects_dir or (ROOT_DIR / "projects")).resolve()
    path = (base_dir / f"{project_name}.triage.json").resolve()
    if path.parent != base_dir:
        raise ValueError(f"Invalid project name: {project_name!r}")
    if not path.exists():
        return []

    fg_dir = (assets_dir or (ROOT_DIR / "assets" / "flamegraphs")).resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []

    entries: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        bench = str(item.get("benchmark") or "").strip()
        commit = str(item.get("commit") or "").strip()
        if not bench or not commit:
            continue
        status = str(item.get("status") or "unreviewed").strip() or "unreviewed"
        note = str(item.get("note") or "")
        issue_url = sanitize_issue_url(item.get("issue_url"))
        fg_raw = item.get("flamegraph") or item.get("flamegraph_svg")
        flamegraph = sanitize_flamegraph_name(fg_raw, assets_dir=fg_dir if fg_dir.is_dir() else None)
        entries.append({
            "benchmark": bench,
            "commit": commit,
            "status": status,
            "note": note,
            "issue_url": issue_url,
            "flamegraph": flamegraph,
        })
    return entries


def _sha_matches(entry_sha: str, full_sha: str, short_sha: str = "") -> int:
    """Return a positive match score if ``entry_sha`` identifies ``full_sha``/``short_sha``, else 0."""
    e = (entry_sha or "").strip().lower()
    f = (full_sha or "").strip().lower()
    s = (short_sha or "").strip().lower()
    if not e:
        return 0
    if e == f and f:
        return 1000 + len(e)
    if e == s and s:
        return 900 + len(e)
    if len(e) >= 4 and ((f and f.startswith(e)) or (s and s.startswith(e))):
        return 500 + len(e)
    if len(s) >= 4 and e.startswith(s):
        return 400 + len(s)
    if len(f) >= 4 and e.startswith(f):
        return 400 + len(f)
    return 0


def _find_best_triage_match(
    entries: Sequence[Mapping[str, Any]],
    benchmark: str,
    sha: str,
    short_sha: str = "",
) -> Tuple[int, Optional[Dict[str, Any]]]:
    """Return ``(index, best_entry)`` for ``(benchmark, sha/short_sha)``, or ``(-1, None)``."""
    best_idx = -1
    best_score = 0
    best_entry: Optional[Dict[str, Any]] = None
    for idx, entry in enumerate(entries):
        if entry.get("benchmark") != benchmark:
            continue
        score = _sha_matches(str(entry.get("commit", "")), sha, short_sha)
        if score > best_score:
            best_score = score
            best_idx = idx
            best_entry = dict(entry)
    return best_idx, best_entry


def match_triage_entry(
    entries: Sequence[Mapping[str, Any]],
    benchmark: str,
    sha: str,
    short_sha: str = "",
) -> Optional[Dict[str, Any]]:
    """Return the best matching triage entry for ``(benchmark, sha/short_sha)``, or ``None``."""
    _, best_entry = _find_best_triage_match(entries, benchmark, sha, short_sha)
    return best_entry


def match_commit_flamegraphs(
    sha: str,
    short_sha: str,
    triage_entry: Optional[Mapping[str, Any]],
    all_flamegraphs: Sequence[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    """Find flamegraph SVGs associated with a commit via triage metadata or filename SHA hints."""
    matched: List[Dict[str, str]] = []
    seen: set = set()
    by_name = {fg["filename"]: fg for fg in all_flamegraphs}

    explicit = triage_entry.get("flamegraph") if triage_entry else None
    if explicit and explicit in by_name:
        fg = by_name[explicit]
        matched.append({"filename": fg["filename"], "url": fg["url"], "kind": fg["kind"]})
        seen.add(fg["filename"])

    for fg in all_flamegraphs:
        if fg["filename"] in seen:
            continue
        if any(_sha_matches(hint, sha, short_sha) > 0 for hint in fg.get("commit_hints", ())):
            matched.append({"filename": fg["filename"], "url": fg["url"], "kind": fg["kind"]})
            seen.add(fg["filename"])

    return matched


def wilson_ci(k: int, n: int, level: float = 0.95) -> List[float]:
    """Wilson score confidence interval for a binomial proportion ``k / n``, in percent."""
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"Invalid counts for Wilson CI: k={k}, n={n}")
    if not (0.0 < level < 1.0):
        raise ValueError(f"Invalid confidence level: {level}")
    if n == 0:
        return [0.0, 100.0]

    z = NormalDist().inv_cdf(0.5 + level / 2.0)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * n * n)))) / denom
    low = max(0.0, center - half)
    high = min(1.0, center + half)
    return [round(100.0 * low, 2), round(100.0 * high, 2)]


def _resolve_commit_record(
    comp: Mapping[str, Any],
    commits_by_id: Mapping[int, Dict[str, Any]],
    commits_by_sha: Mapping[str, Dict[str, Any]],
) -> tuple[str, str]:
    """Return ``(cand_full_sha, cand_short_sha)`` for a comparison row."""
    cid = comp.get("cand_commit_id")
    if cid is not None and cid in commits_by_id:
        c = commits_by_id[cid]
        return str(c.get("sha") or c.get("short_sha") or ""), str(c.get("short_sha") or "")
    cand_full = str(comp.get("cand_full_sha") or comp.get("cand_sha") or "")
    cand_short = str(comp.get("cand_sha") or cand_full[:7])
    if cand_full in commits_by_sha:
        c = commits_by_sha[cand_full]
        return str(c.get("sha") or cand_full), str(c.get("short_sha") or cand_short)
    return cand_full, cand_short


def compute_summary_from_records(
    project: str,
    commits: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
    triage_entries: Sequence[Mapping[str, Any]],
    benchmarks: Optional[Sequence[str]] = None,
    flamegraphs: Optional[Sequence[Mapping[str, Any]]] = None,
    study: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute publishable summary metrics by joining commits, comparisons, triage JSON, and flamegraphs."""
    commit_dicts = [dict(c) for c in commits]
    comp_dicts = [dict(c) for c in comparisons]
    triage_list = [dict(t) for t in triage_entries]
    all_fgs = [dict(f) for f in (flamegraphs if flamegraphs is not None else discover_flamegraphs())]

    commits_by_id = {c["id"]: c for c in commit_dicts if "id" in c}
    commits_by_sha = {c["sha"]: c for c in commit_dicts if c.get("sha")}

    bench_set = set(benchmarks or ())
    if not bench_set:
        bench_set = {str(c["benchmark"]) for c in comp_dicts if c.get("benchmark")}

    flagged_pre_fdr = 0
    regressions_flagged = 0
    confirmed_flagged = 0
    confirmed_unflagged = 0
    false_positives = 0
    layout_artifacts_flagged = 0
    layout_artifacts_unflagged = 0
    unreviewed = 0

    flagged_items: List[Dict[str, Any]] = []
    matched_triage_indices: set = set()
    upstream_issues: List[Dict[str, str]] = []
    seen_issue_keys: set = set()
    matched_fg_map: Dict[str, Dict[str, Any]] = {}

    def _record_issue(issue_url: Optional[str], commit_sha: str, bench: str, status: str, note: str) -> None:
        if not issue_url:
            return
        key = (issue_url, commit_sha, bench)
        if key not in seen_issue_keys:
            seen_issue_keys.add(key)
            upstream_issues.append({
                "issue_url": issue_url,
                "commit": commit_sha,
                "benchmark": bench,
                "status": status,
                "note": note,
            })

    for comp in comp_dicts:
        bench = str(comp.get("benchmark") or "")
        cand_full, cand_short = _resolve_commit_record(comp, commits_by_id, commits_by_sha)

        best_idx, triage_entry = _find_best_triage_match(triage_list, bench, cand_full, cand_short)
        if best_idx >= 0:
            matched_triage_indices.add(best_idx)

        status = (
            str(triage_entry.get("status") or "unreviewed")
            if triage_entry
            else str(comp.get("resolution_status") or "unreviewed")
        )
        note = (
            str(triage_entry.get("note") or "")
            if triage_entry
            else str(comp.get("resolution_note") or "")
        )
        issue_url = sanitize_issue_url(triage_entry.get("issue_url")) if triage_entry else None
        comp_fgs = match_commit_flamegraphs(cand_full, cand_short, triage_entry, all_fgs)
        for fg in comp_fgs:
            matched_fg_map[fg["filename"]] = fg

        is_pre = comp.get("verdict") == "flag"
        is_post = bool(is_pre and comp.get("fdr_significant"))
        if is_pre:
            flagged_pre_fdr += 1
        if is_post:
            regressions_flagged += 1
            if status == "confirmed":
                confirmed_flagged += 1
            elif status == "false_positive":
                false_positives += 1
            elif status == "layout_artifact":
                layout_artifacts_flagged += 1
            else:
                unreviewed += 1

            _record_issue(issue_url, cand_short or cand_full[:7], bench, status, note)
            flagged_items.append({
                "base_sha": str(comp.get("base_sha") or ""),
                "cand_sha": cand_short,
                "cand_full_sha": cand_full,
                "benchmark": bench,
                "shift_pct": round(float(comp.get("shift_pct", 0.0)), 2),
                "p_value": float(comp.get("p_value", 1.0)),
                "noise_floor_pct": round(float(comp.get("noise_floor_pct", 0.0)), 2),
                "session_gap_min": comp.get("session_gap_min"),
                "status": status,
                "note": note,
                "issue_url": issue_url,
                "flamegraphs": comp_fgs,
            })
        elif status == "confirmed":
            confirmed_unflagged += 1
            _record_issue(issue_url, cand_short or cand_full[:7], bench, status, note)
        elif status == "layout_artifact":
            layout_artifacts_unflagged += 1
            _record_issue(issue_url, cand_short or cand_full[:7], bench, status, note)

    # Include triage entries that match commits AND benchmarks in this dataset even if not in
    # flagged comparisons (for example, sub-threshold candidates investigated separately like 8f5d947).
    confirmed_extra = 0
    layout_artifacts_extra = 0
    for idx, t in enumerate(triage_list):
        if idx in matched_triage_indices:
            continue
        t_bench = str(t.get("benchmark") or "")
        if t_bench not in bench_set:
            continue
        t_commit = str(t.get("commit") or "")
        matched_commit = next(
            (
                c
                for c in commit_dicts
                if _sha_matches(t_commit, str(c.get("sha") or ""), str(c.get("short_sha") or "")) > 0
            ),
            None,
        )
        if matched_commit is None:
            continue
        t_status = str(t.get("status") or "unreviewed")
        if t_status == "confirmed":
            confirmed_extra += 1
        elif t_status == "layout_artifact":
            layout_artifacts_extra += 1
        _record_issue(
            sanitize_issue_url(t.get("issue_url")),
            str(matched_commit.get("short_sha") or t_commit[:7]),
            str(t.get("benchmark") or ""),
            t_status,
            str(t.get("note") or ""),
        )
        for fg in match_commit_flamegraphs(
            str(matched_commit.get("sha") or ""),
            str(matched_commit.get("short_sha") or t_commit),
            t,
            all_fgs,
        ):
            matched_fg_map[fg["filename"]] = fg

    confirmed_real = confirmed_flagged + confirmed_unflagged + confirmed_extra
    layout_artifacts = layout_artifacts_flagged + layout_artifacts_unflagged + layout_artifacts_extra

    fp_rate = round(false_positives / regressions_flagged, 4) if regressions_flagged > 0 else None
    fp_rate_pct = round(100.0 * false_positives / regressions_flagged, 2) if regressions_flagged > 0 else None
    fp_wilson = wilson_ci(false_positives, regressions_flagged, level=0.95)
    unique_issue_urls = list(dict.fromkeys(u["issue_url"] for u in upstream_issues))

    return {
        "project": project,
        "study": study or "db",
        "commits_analyzed": len(commit_dicts),
        "benchmarks_count": len(bench_set),
        "comparisons": len(comp_dicts),
        "flagged_pre_fdr": flagged_pre_fdr,
        "regressions_flagged": regressions_flagged,
        "confirmed_real": confirmed_real,
        "false_positives": false_positives,
        "layout_artifacts": layout_artifacts,
        "unreviewed": unreviewed,
        "flagged_breakdown": {
            "confirmed": confirmed_flagged,
            "false_positive": false_positives,
            "layout_artifact": layout_artifacts_flagged,
            "unreviewed": unreviewed,
        },
        "fp_rate": fp_rate,
        "fp_rate_pct": fp_rate_pct,
        "fp_rate_wilson_ci95_pct": fp_wilson,
        "upstream_issues": upstream_issues,
        "upstream_issue_urls": unique_issue_urls,
        "flamegraphs": sorted(matched_fg_map.values(), key=lambda f: f["filename"]),
        "available_flamegraphs": [{"filename": f["filename"], "url": f["url"], "kind": f["kind"]} for f in all_fgs],
        "flagged_items": flagged_items,
    }


def compute_project_summary(
    db: Database,
    project_name: str,
    projects_dir: Optional[Path] = None,
    assets_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load DB commits/comparisons plus triage JSON for ``project_name`` and compute summary metrics."""
    validate_project_name(project_name)
    proj_id = db.get_project_id(project_name)
    if not proj_id:
        raise ValueError(f"Project '{project_name}' not found in database.")

    commits = db.get_project_commits(proj_id)
    comparisons = db.get_project_comparisons(proj_id)
    benchmarks = db.get_project_benchmarks(proj_id)
    triage_entries = load_triage_entries(project_name, projects_dir=projects_dir, assets_dir=assets_dir)
    flamegraphs = discover_flamegraphs(assets_dir=assets_dir)
    return compute_summary_from_records(
        project=project_name,
        commits=commits,
        comparisons=comparisons,
        triage_entries=triage_entries,
        benchmarks=benchmarks,
        flamegraphs=flamegraphs,
        study="db",
    )


def format_summary_text(summary: Mapping[str, Any]) -> str:
    """Format a publishable summary report for terminal output."""
    bar = "=" * 75
    flagged = summary["regressions_flagged"]
    fp = summary["false_positives"]
    ci_lo, ci_hi = summary["fp_rate_wilson_ci95_pct"]
    fp_str = (
        f"{fp}/{flagged} ({summary['fp_rate_pct']:.1f}%, 95% Wilson CI [{ci_lo:.2f}%, {ci_hi:.2f}%])"
        if flagged > 0 and summary["fp_rate_pct"] is not None
        else "N/A (0 flagged)"
    )
    lines = [
        "",
        bar,
        f"  regressor Publishable Summary — Project: '{summary['project']}' ({summary.get('study', 'db')})",
        bar,
        f"  Commits analyzed:          {summary['commits_analyzed']}",
        f"  Benchmarks covered:        {summary['benchmarks_count']}",
        f"  Pairwise comparisons:      {summary['comparisons']}",
        f"  Regressions flagged (FDR): {flagged} (pre-FDR: {summary['flagged_pre_fdr']})",
        f"  Confirmed real:            {summary['confirmed_real']}",
        f"  False positives:           {fp}",
        f"  FP rate (FP/flagged):      {fp_str}",
        f"  Layout artifacts:          {summary['layout_artifacts']}",
        f"  Unreviewed flags:          {summary['unreviewed']}",
    ]
    issues = summary.get("upstream_issues") or []
    if issues:
        lines.append(f"  Upstream issue links ({len(issues)}):")
        for item in issues:
            lines.append(f"    - {item['commit']} ({item['benchmark']}): {item['issue_url']}")
    else:
        lines.append("  Upstream issue links:      None filed")
    lines.append(bar)
    lines.append("")
    return "\n".join(lines)


def render_summary_markdown(summary: Mapping[str, Any]) -> str:
    """Render the publishable summary as sanitized GitHub-flavored Markdown."""
    proj_s = _safe_md(summary["project"])
    study_s = _safe_md(summary.get("study", "db"))
    flagged = summary["regressions_flagged"]
    fp = summary["false_positives"]
    ci_lo, ci_hi = summary["fp_rate_wilson_ci95_pct"]
    if flagged > 0 and summary["fp_rate_pct"] is not None:
        fp_cell = f"{fp}/{flagged} ({summary['fp_rate_pct']:.2f}%, Wilson 95% CI [{ci_lo:.2f}%, {ci_hi:.2f}%])"
    else:
        fp_cell = "N/A (0 flagged)"

    lines = [
        "<!-- regressor-summary -->",
        f"### regressor Summary: `{proj_s}` (`{study_s}`)",
        "",
        f"**{summary['commits_analyzed']} commits** analyzed across **{summary['benchmarks_count']} benchmarks** "
        f"({summary['comparisons']} pairwise comparisons): **{flagged}** flagged, "
        f"**{summary['confirmed_real']}** confirmed real, **{fp}** false positives "
        f"(FP rate: {fp_cell}), **{summary['layout_artifacts']}** layout artifacts.",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Commits analyzed | {summary['commits_analyzed']} |",
        f"| Benchmarks covered | {summary['benchmarks_count']} |",
        f"| Pairwise comparisons | {summary['comparisons']} |",
        f"| Regressions flagged (post-FDR) | {flagged} (pre-FDR: {summary['flagged_pre_fdr']}) |",
        f"| Confirmed real | {summary['confirmed_real']} |",
        f"| False positives | {fp} |",
        f"| FP rate (FP/flagged, 95% Wilson CI) | {fp_cell} |",
        f"| Layout artifacts | {summary['layout_artifacts']} |",
        f"| Unreviewed flags | {summary['unreviewed']} |",
        f"| Upstream issues linked | {len(summary.get('upstream_issue_urls') or [])} |",
        "",
        "#### Upstream Issue Links",
        "",
    ]
    issues = summary.get("upstream_issues") or []
    if issues:
        for item in issues:
            url = sanitize_issue_url(item.get("issue_url"))
            if not url:
                continue
            commit_s = _safe_md(item.get("commit", ""))
            bench_s = _safe_md(item.get("benchmark", ""))
            status_s = _safe_md(item.get("status", ""))
            lines.append(f"- [`{commit_s}` `{bench_s}` ({status_s})]({url})")
    else:
        lines.append("- None filed.")

    flagged_items = summary.get("flagged_items") or []
    if flagged_items:
        lines += [
            "",
            "#### Flagged Transitions",
            "",
            "| Candidate | Benchmark | Shift | p-value | Noise Floor | Status | Note |",
            "|---|---|---:|---:|---:|---|---|",
        ]
        for item in flagged_items:
            lines.append(
                f"| `{_safe_md(item['cand_sha'])}` | `{_safe_md(item['benchmark'])}` | "
                f"{item['shift_pct']:+.2f}% | {item['p_value']:.2e} | {item['noise_floor_pct']:.2f}% | "
                f"`{_safe_md(item['status'])}` | {_safe_md(item.get('note', ''))} |"
            )

    return "\n".join(lines) + "\n"
