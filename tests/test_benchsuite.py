"""
tests/test_benchsuite.py
Tests for the rebar-derived 25-benchmark suite, RegexAdapter configuration
loading, isolated worktree synchronization, vendored haystack bounds, and
Rust harness execution/listing semantics.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from adapters.regex_adapter import RegexAdapter
from core.models import BuildResult

ROOT = Path(__file__).resolve().parent.parent
NOISE_BENCH = ROOT / "noise-bench"
HAYSTACKS = NOISE_BENCH / "haystacks"
LEGACY_BENCHMARKS = ("find_iter_userid", "is_match_status", "compile_moderate")
SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def test_regex_toml_and_adapter_list_benchmarks_match():
    raw = tomllib.loads((ROOT / "projects" / "regex.toml").read_text(encoding="utf-8"))
    benches = raw["benchmarks"]

    adapter = RegexAdapter()
    assert adapter.list_benchmarks() == benches
    assert 20 <= len(benches) <= 28
    assert len(set(benches)) == len(benches)

    # All 3 historical benchmarks remain intact.
    for legacy in LEGACY_BENCHMARKS:
        assert legacy in benches

    rebar_benches = [b for b in benches if b not in LEGACY_BENCHMARKS]
    assert len(rebar_benches) >= 18
    for name in rebar_benches:
        assert name.startswith("rebar_")
        assert SNAKE_CASE_RE.match(name), f"Invalid snake_case benchmark name: {name}"


def test_regex_adapter_list_benchmarks_reads_custom_toml_and_falls_back(tmp_path: Path):
    custom_toml = tmp_path / "custom.toml"
    custom_toml.write_text('name = "regex"\nbenchmarks = ["bench_alpha", "bench_beta"]\n', encoding="utf-8")

    adapter = RegexAdapter(noise_bench_dir=str(tmp_path), project_toml=str(custom_toml))
    assert adapter.list_benchmarks() == ["bench_alpha", "bench_beta"]

    missing_toml = tmp_path / "missing.toml"
    fallback_adapter = RegexAdapter(noise_bench_dir=str(tmp_path), project_toml=str(missing_toml))
    fallback = fallback_adapter.list_benchmarks()
    assert all(b in fallback for b in LEGACY_BENCHMARKS)
    assert len(fallback) == 25


def test_haystacks_are_lightweight_and_attributed():
    assert HAYSTACKS.is_dir()
    files = [p for p in HAYSTACKS.rglob("*") if p.is_file()]
    data_files = [p for p in files if p.name != "README.md"]
    assert len(data_files) >= 10

    total_bytes = sum(p.stat().st_size for p in files)
    assert total_bytes < 2 * 1024 * 1024, f"Vendored haystacks too large: {total_bytes} bytes"

    readme = (HAYSTACKS / "README.md").read_text(encoding="utf-8")
    assert "BurntSushi/rebar" in readme
    assert "UNLICENSE" in readme
    for p in data_files:
        assert p.name in readme, f"Missing attribution in haystacks/README.md for {p.name}"


def test_benchmarks_md_documents_every_benchmark():
    doc_path = NOISE_BENCH / "BENCHMARKS.md"
    assert doc_path.exists(), "noise-bench/BENCHMARKS.md is missing"
    doc = doc_path.read_text(encoding="utf-8")
    assert "file://" not in doc

    benches = RegexAdapter().list_benchmarks()
    for name in benches:
        assert f"`{name}`" in doc, f"Benchmark {name} missing from noise-bench/BENCHMARKS.md"


def test_build_isolated_syncs_src_haystacks_and_cargo_lock(tmp_path: Path, monkeypatch):
    # Fake git repo and noise-bench directory so no real git or cargo invocation is needed.
    nb_dir = tmp_path / "noise-bench"
    (nb_dir / "src").mkdir(parents=True)
    (nb_dir / "haystacks").mkdir(parents=True)
    (nb_dir / "Cargo.toml").write_text('[package]\nname = "noise-bench"\nversion = "0.1.0"\n', encoding="utf-8")
    (nb_dir / "Cargo.lock").write_text("# lock v1\n", encoding="utf-8")
    (nb_dir / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    (nb_dir / "haystacks" / "sample.txt").write_text("hello\n", encoding="utf-8")

    repo_dir = tmp_path / "regex"
    (repo_dir / ".git").mkdir(parents=True)
    workdir = tmp_path / "builds"
    sha = "0123456789abcdef0123456789abcdef01234567"

    # Pre-create the isolated regex worktree directory so git worktree add isn't needed.
    wt_src = workdir / sha[:12] / "regex"
    wt_src.mkdir(parents=True)
    # Also create a stale file in isolated bench/src that should be pruned on sync.
    stale_file = workdir / sha[:12] / "noise-bench" / "src" / "stale.rs"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text("// stale", encoding="utf-8")

    adapter = RegexAdapter(noise_bench_dir=str(nb_dir), regex_repo_dir=str(repo_dir))
    monkeypatch.setattr(shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(
        adapter,
        "_sh",
        lambda cmd, cwd, env=None, timeout=1800: (0, sha + "\n"),
    )
    monkeypatch.setattr(
        adapter,
        "_run_cargo_build",
        lambda cwd, artifact, t0, env=None: BuildResult(ok=True, seconds=0.1, artifact=artifact),
    )

    res = adapter.build(sha[:7], workdir=workdir)
    assert res.ok is True

    wt_bench = workdir / sha[:12] / "noise-bench"
    assert (wt_bench / "Cargo.toml").read_text(encoding="utf-8") == (nb_dir / "Cargo.toml").read_text(encoding="utf-8")
    assert (wt_bench / "Cargo.lock").read_text(encoding="utf-8") == "# lock v1\n"
    assert (wt_bench / "src" / "main.rs").read_text(encoding="utf-8") == "fn main() {}\n"
    assert (wt_bench / "haystacks" / "sample.txt").read_text(encoding="utf-8") == "hello\n"
    assert not stale_file.exists()

    # Unchanged files keep their mtime on repeated build so Cargo skips pointless rebuilds.
    old_mtime = (wt_bench / "src" / "main.rs").stat().st_mtime_ns
    os.utime(wt_bench / "src" / "main.rs", ns=(old_mtime - 10_000_000_000, old_mtime - 10_000_000_000))
    recorded = (wt_bench / "src" / "main.rs").stat().st_mtime_ns
    res2 = adapter.build(sha[:7], workdir=workdir)
    assert res2.ok is True
    assert (wt_bench / "src" / "main.rs").stat().st_mtime_ns == recorded


def test_rust_harness_binary_lists_and_runs_all_benchmarks():
    adapter = RegexAdapter()
    if not adapter.bin_path.exists():
        pytest.skip("noise-bench release binary not built")

    bin_benches = adapter.query_binary_benchmarks()
    assert bin_benches == adapter.list_benchmarks()

    # Positional `list-benchmarks` also works.
    p = subprocess.run([str(adapter.bin_path), "list-benchmarks"], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0
    assert [ln.strip() for ln in p.stdout.splitlines() if ln.strip()] == bin_benches

    # Run a quick 3-iteration smoke check on every benchmark + check --format=csv and --format=json.
    for bench in bin_benches:
        samples = adapter.run(bench, iters=3, warmup=1, inject_ns=0)
        assert len(samples) == 3
        assert all(s > 0.0 for s in samples)

    csv_out = subprocess.run(
        [str(adapter.bin_path), bin_benches[0], "2", "1", "0", "--format=csv"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert csv_out.returncode == 0
    lines = csv_out.stdout.strip().splitlines()
    assert lines[0] == "elapsed_ns,tsc_ticks"
    assert len(lines) == 3

    json_out = subprocess.run(
        [str(adapter.bin_path), bin_benches[0], "2", "1", "0", "--format=json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert json_out.returncode == 0
    parsed = json.loads(json_out.stdout)
    assert len(parsed) == 2 and all("elapsed_ns" in row and "tsc_ticks" in row for row in parsed)
