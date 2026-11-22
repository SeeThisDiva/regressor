#!/usr/bin/env python3
"""Instantiate a standalone minimal Cargo reproducer from `reports/upstream/repro-template/`."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT_DIR / "reports" / "upstream" / "repro-template"


def _rust_escape(raw: str) -> str:
    return (
        raw.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def stamp_repro(
    out_dir: Path,
    base_sha: str,
    cand_sha: str,
    pattern: str,
    haystack_seed: str,
    haystack_repeat: int,
    batch_size: int,
    mode: str,
) -> Path:
    """Copy `repro-template` to `out_dir` and substitute target revision and workload parameters."""
    if not TEMPLATE_DIR.is_dir():
        raise FileNotFoundError(f"Repro template not found: {TEMPLATE_DIR}")
    shutil.copytree(TEMPLATE_DIR, out_dir, dirs_exist_ok=True)

    replacements = {
        "__BASE_SHA__": base_sha,
        "__CAND_SHA__": cand_sha,
        "__PATTERN__": pattern,
        "__HAYSTACK_SEED__": _rust_escape(haystack_seed),
        "__HAYSTACK_REPEAT__": str(haystack_repeat),
        "__BATCH_SIZE__": str(batch_size),
        "__BENCH_MODE__": mode,
    }
    for rel in ("base/Cargo.toml", "cand/Cargo.toml", "src/main.rs"):
        target = out_dir / rel
        text = target.read_text(encoding="utf-8")
        for key, val in replacements.items():
            text = text.replace(key, val)
        target.write_text(text, encoding="utf-8")

    readme = out_dir / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8")
        .replace("<BASE_SHA>", base_sha)
        .replace("<CAND_SHA>", cand_sha),
        encoding="utf-8",
    )
    return out_dir


def main() -> int:
    ap = argparse.ArgumentParser(description="Create a standalone two-rev Cargo reproducer from template.")
    ap.add_argument("--out", required=True, help="Output directory (e.g. reports/upstream/<sha>/repro)")
    ap.add_argument("--base", required=True, help="Baseline regex git SHA")
    ap.add_argument("--cand", required=True, help="Candidate regex git SHA")
    ap.add_argument("--pattern", required=True, help="Regex pattern string")
    ap.add_argument("--seed", required=True, help="Haystack seed string")
    ap.add_argument("--repeat", type=int, default=2000, help="Haystack repeat count (default: 2000)")
    ap.add_argument("--batch", type=int, default=1, help="Inner batch size per timed sample (default: 1)")
    ap.add_argument(
        "--mode",
        choices=("compile", "find_iter", "is_match", "captures_iter"),
        default="find_iter",
        help="Benchmark mode (default: find_iter)",
    )
    args = ap.parse_args()

    out = stamp_repro(
        Path(args.out),
        base_sha=args.base,
        cand_sha=args.cand,
        pattern=args.pattern,
        haystack_seed=args.seed,
        haystack_repeat=args.repeat,
        batch_size=args.batch,
        mode=args.mode,
    )
    print(f"[stamp_repro] created standalone reproducer at {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
