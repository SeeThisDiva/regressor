"""
tests/test_platform_ci.py
Structural linting and validation tests for Dockerfile, .dockerignore,
docker-compose.yml, action.yml, GitHub Actions workflows, shell scripts,
and incremental continuous collection (`scripts/continuous_collect.py`).
"""

from __future__ import annotations

import gzip
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import pytest
import yaml

from adapters.base import BaseAdapter
from core.models import BuildResult
from scripts.continuous_collect import (
    discover_new_commits,
    load_recorded_state,
    resolve_dataset_path,
    run_continuous_collection,
)

ROOT = Path(__file__).resolve().parent.parent


def _find_bash() -> Optional[str]:
    """Locate a real GNU bash binary (including Git's sh.exe when it is GNU bash)."""
    bash = shutil.which("bash")
    if bash and "WindowsApps" not in bash:
        return bash
    sh = shutil.which("sh")
    if sh:
        for cand in (
            Path(sh).parent / "bash.exe",
            Path(sh).parent / "bash",
            Path(sh).parent.parent / "bin" / "bash.exe",
        ):
            if cand.exists():
                return str(cand)
        proc = subprocess.run([sh, "--version"], capture_output=True, text=True)
        if proc.returncode == 0 and "GNU bash" in proc.stdout:
            return sh
    return None


def _workflow_triggers(data: dict) -> dict:
    """Return workflow `on:` mapping, handling PyYAML's YAML 1.1 `on -> True` key."""
    if "on" in data:
        return data["on"]
    if True in data:
        return data[True]
    raise AssertionError("Workflow missing 'on' trigger definition")


def _extract_run_blocks(workflow: dict) -> List[str]:
    blocks: List[str] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if "run" in step:
                blocks.append(str(step["run"]))
    return blocks


# ---------------------------------------------------------------------------
# 1. Dockerfile, .dockerignore & docker-compose.yml Structural Lint
# ---------------------------------------------------------------------------


def test_dockerfile_up_to_date_non_root_and_offline_ready():
    dockerfile_bytes = (ROOT / "Dockerfile").read_bytes()
    assert b"\r\n" not in dockerfile_bytes, "Dockerfile must use LF line endings"
    text = dockerfile_bytes.decode("utf-8")

    # Modern Rust base image (able to build Nov 2025-Nov 2026 regex commits and Cargo.lock v3/v4)
    m = re.search(r"^FROM\s+rust:(\d+)\.(\d+)-slim-bookworm", text, flags=re.MULTILINE)
    assert m is not None, "Dockerfile must pin a rust:1.xx-slim-bookworm image"
    major, minor = int(m.group(1)), int(m.group(2))
    assert (major, minor) >= (1, 85), f"Rust image {major}.{minor} is too old for 2025-2026 builds"
    assert ":latest" not in text

    # Required clone, pip install, cargo fetch/build, non-root user, and results volume
    assert "ENV CARGO_HOME=/usr/local/cargo" in text
    assert "/work/regressor/regex" in text
    assert "--depth 1" not in text and "--depth=1" not in text, "Full git history is required for worktree builds"
    assert "pip3 install --no-cache-dir --break-system-packages -e /work/regressor" in text
    assert "cargo fetch" in text
    assert "cargo build --release" in text
    assert text.index("cargo fetch") < text.index("cargo build --release")
    assert "useradd -m -u 10001" in text
    assert re.search(r"^USER\s+regressor\b", text, flags=re.MULTILINE)
    assert 'VOLUME ["/work/regressor/noise-bench/results"]' in text
    assert 'ENTRYPOINT ["/work/regressor/scripts/container_entrypoint.sh"]' in text

    # No host credentials or insecure permissions baked into the image
    for forbidden in ("GITHUB_TOKEN", "AWS_SECRET", ".ssh", ".netrc", ".git-credentials", "chmod 777", "sudo "):
        assert forbidden not in text, f"Forbidden token {forbidden!r} found in Dockerfile"


def test_dockerignore_excludes_credentials_and_local_artifacts():
    lines = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for required in (
        ".git",
        ".venv",
        "regex/",
        ".regressor-builds/",
        "noise-bench/target/",
        "noise-bench/results/study2_commits/",
        "noise-bench/results/study3*/",
        "regressor.db*",
        ".env",
        ".env.*",
        "*.pem",
        "*.key",
        ".netrc",
        ".git-credentials",
    ):
        assert required in lines, f".dockerignore missing {required!r}"


def test_docker_compose_valid_and_hardened():
    data = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "services" in data
    services = data["services"]
    assert {"regressor", "regressor-offline"} <= set(services)

    for name in ("regressor", "regressor-offline"):
        svc = services[name]
        assert svc["user"] == "10001:10001"
        assert svc["init"] is True
        assert "ALL" in svc["cap_drop"]
        assert "no-new-privileges:true" in svc["security_opt"]
        vols = svc["volumes"]
        assert any(v.endswith(":/work/regressor/noise-bench/results") for v in vols)
        assert not any(".ssh" in v or "docker.sock" in v or ".gitconfig" in v for v in vols)

    offline = services["regressor-offline"]
    assert offline["network_mode"] == "none"
    assert offline["environment"]["CARGO_NET_OFFLINE"] == "true"
    assert "offline" in offline["profiles"]


# ---------------------------------------------------------------------------
# 2. GitHub Action & Workflows Structural + Security Lint
# ---------------------------------------------------------------------------


def test_action_yml_valid_and_safe():
    data = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    assert {"repo-path", "base", "head"} <= set(data["inputs"])
    assert {"report", "json-report"} <= set(data["outputs"])
    assert data["runs"]["using"] == "composite"

    steps = data["runs"]["steps"]
    assert len(steps) == 2
    for step in steps:
        assert step["shell"] == "bash"
        # Inputs must pass via env:, never interpolated directly in shell script
        assert "${{ inputs." not in step["run"]

    run_script = steps[1]["run"]
    assert "|| rc=$?" in run_script
    assert 'GITHUB_OUTPUT' in run_script
    assert 'GITHUB_STEP_SUMMARY' in run_script


@pytest.mark.parametrize(
    "wf_path",
    [
        ROOT / ".github" / "workflows" / "tests.yml",
        ROOT / ".github" / "workflows" / "container.yml",
        ROOT / ".github" / "workflows" / "continuous.yml",
        ROOT / "examples" / "perf-check.yml",
    ],
)
def test_all_workflows_valid_yaml_and_injection_safe(wf_path: Path):
    text = wf_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    assert "name" in data
    assert "jobs" in data and data["jobs"]
    triggers = _workflow_triggers(data)

    # Never use pull_request_target triggers or write-all permissions
    assert "pull_request_target" not in triggers
    assert "write-all" not in text

    # Never interpolate untrusted event or input contexts directly inside `run:` scripts
    for script in _extract_run_blocks(data):
        assert not re.search(r"\$\{\{\s*(inputs|github\.event)\.", script), (
            f"{wf_path.name} interpolates inputs/event directly inside `run:`"
        )

    # Every `uses:` action reference must be pinned (local ./ or @vN / @stable / SHA)
    for job in data["jobs"].values():
        for step in job.get("steps") or []:
            uses = step.get("uses")
            if uses and not uses.startswith("./"):
                assert re.search(r"@(v\d+|stable|[0-9a-f]{40})$", uses), f"Unpinned action {uses!r} in {wf_path.name}"

    # Any referenced scripts/*.sh or scripts/*.py must exist in repo
    for script in _extract_run_blocks(data):
        for rel in re.findall(r"(?:\./)?(scripts/[A-Za-z0-9_.-]+\.(?:sh|py))", script):
            assert (ROOT / rel).exists(), f"{wf_path.name} references missing script {rel}"


def test_container_workflow_smoke_and_artifact_contract():
    data = yaml.safe_load((ROOT / ".github" / "workflows" / "container.yml").read_text(encoding="utf-8"))
    triggers = _workflow_triggers(data)
    assert {"push", "pull_request", "workflow_dispatch"} <= set(triggers)
    assert data["permissions"] == {"contents": "read"}

    job = data["jobs"]["container-smoke"]
    assert job["runs-on"] == "ubuntu-latest"
    all_runs = "\n".join(_extract_run_blocks(data))
    assert "docker build -t regressor:smoke -f Dockerfile ." in all_runs
    assert "--offline" in all_runs
    assert "--max-commits 2" in all_runs
    assert "compare-interleaved" in all_runs
    assert "--pairs 8" in all_runs

    upload_steps = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert len(upload_steps) == 1
    assert upload_steps[0]["with"]["path"] == "smoke-results/"


def test_continuous_workflow_is_opt_in_and_least_privilege():
    data = yaml.safe_load((ROOT / ".github" / "workflows" / "continuous.yml").read_text(encoding="utf-8"))
    triggers = _workflow_triggers(data)
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    assert data["permissions"] == {"contents": "read"}

    collect = data["jobs"]["collect"]
    assert collect["permissions"] == {"contents": "read"}
    assert "vars.REGRESSOR_CONTINUOUS_ENABLED == 'true'" in collect["if"]
    assert "workflow_dispatch" in collect["if"]

    commit_job = data["jobs"]["commit-dataset"]
    assert commit_job["needs"] == "collect"
    assert commit_job["permissions"] == {"contents": "write"}
    assert "vars.REGRESSOR_CONTINUOUS_COMMIT == 'true'" in commit_job["if"]
    assert "inputs.commit_dataset == true" in commit_job["if"]
    assert triggers["workflow_dispatch"]["inputs"]["commit_dataset"]["default"] is False

    collect_runs = "\n".join(s["run"] for s in collect["steps"] if "run" in s)
    assert "scripts/run_in_container.sh" in collect_runs
    assert "scripts/continuous_collect.py" in collect_runs


# ---------------------------------------------------------------------------
# 3. Shell Scripts Lint & Dry-Run Checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    [
        "scripts/container_entrypoint.sh",
        "scripts/run_in_container.sh",
        "scripts/pin_host.sh",
    ],
)
def test_shell_scripts_lf_and_strict_mode(rel_path: str):
    raw = (ROOT / rel_path).read_bytes()
    assert b"\r\n" not in raw, f"{rel_path} must use LF line endings"
    text = raw.decode("utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert "file://" not in text
    assert "Users/Dev" not in text and "Users\\Dev" not in text


def test_pin_host_and_run_in_container_safety_and_dry_run(tmp_path: Path):
    pin_text = (ROOT / "scripts" / "pin_host.sh").read_text(encoding="utf-8")
    for required in ("cpupower", "performance", "no_turbo", "isolcpus", "taskset", "--apply", "--restore"):
        assert required in pin_text

    run_text = (ROOT / "scripts" / "run_in_container.sh").read_text(encoding="utf-8")
    for required in ("--network none", "CARGO_NET_OFFLINE=true", "--cap-drop ALL", "no-new-privileges:true", "10001:10001"):
        assert required in run_text

    bash = _find_bash()
    if bash is None:
        pytest.skip("bash not available on this host")

    # Syntax-check all bash scripts with bash -n
    for rel in ("scripts/container_entrypoint.sh", "scripts/run_in_container.sh", "scripts/pin_host.sh"):
        p = subprocess.run([bash, "-n", str(ROOT / rel)], capture_output=True, text=True)
        assert p.returncode == 0, f"bash -n failed for {rel}: {p.stderr}"

    # pin_host.sh --dry-run --apply --cpus 2,3 --freq 3.0GHz
    p_pin = subprocess.run(
        [bash, str(ROOT / "scripts" / "pin_host.sh"), "--dry-run", "--apply", "--cpus", "2,3", "--freq", "3.0GHz"],
        capture_output=True,
        text=True,
    )
    assert p_pin.returncode == 0, p_pin.stderr
    assert "cpupower frequency-set -g performance" in p_pin.stdout
    assert "intel_pstate/no_turbo" in p_pin.stdout
    assert "isolcpus=2,3" in p_pin.stdout
    assert "taskset -c 2 nice -n -20" in p_pin.stdout

    # pin_host.sh must refuse to offline CPU 0
    p_cpu0 = subprocess.run(
        [bash, str(ROOT / "scripts" / "pin_host.sh"), "--dry-run", "--apply", "--offline-cpu", "0"],
        capture_output=True,
        text=True,
    )
    assert p_cpu0.returncode == 2

    # run_in_container.sh --dry-run --build --offline --cpuset 2,3 --no-tty -- python3 regressor.py --help
    p_run = subprocess.run(
        [
            bash,
            str(ROOT / "scripts" / "run_in_container.sh"),
            "--dry-run",
            "--build",
            "--offline",
            "--cpuset",
            "2,3",
            "--no-tty",
            "--results-dir",
            str(tmp_path / "res"),
            "--",
            "python3",
            "regressor.py",
            "--help",
        ],
        capture_output=True,
        text=True,
    )
    assert p_run.returncode == 0, p_run.stderr
    tokens = shlex.split(p_run.stdout)
    assert "docker" in tokens and "build" in tokens
    assert "--network" in tokens and "none" in tokens
    assert "CARGO_NET_OFFLINE=true" in tokens
    assert "--cpuset-cpus" in tokens and "2,3" in tokens
    assert "--user" in tokens and "10001:10001" in tokens

    # run_in_container.sh rejects invalid --cpuset
    p_bad_cpu = subprocess.run(
        [bash, str(ROOT / "scripts" / "run_in_container.sh"), "--dry-run", "--cpuset", "2;rm -rf /", "--no-tty", "--", "true"],
        capture_output=True,
        text=True,
    )
    assert p_bad_cpu.returncode == 2


# ---------------------------------------------------------------------------
# 4. Functional Tests for scripts/continuous_collect.py
# ---------------------------------------------------------------------------


def _init_temp_git_repo(repo: Path, n_commits: int = 4) -> List[str]:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=repo, check=True, capture_output=True)
    shas: List[str] = []
    for i in range(n_commits):
        (repo / "lib.txt").write_text(f"v{i}\n", encoding="utf-8")
        subprocess.run(["git", "add", "lib.txt"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"commit {i}"],
            cwd=repo,
            check=True,
            capture_output=True,
            env={"GIT_AUTHOR_DATE": f"2026-11-0{i + 1}T10:00:00Z", "GIT_COMMITTER_DATE": f"2026-11-0{i + 1}T10:00:00Z"},
        )
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
        shas.append(sha)
    return shas


class _FakeContinuousAdapter(BaseAdapter):
    def __init__(self, fail_shas: Optional[set[str]] = None, slow_shas: Optional[set[str]] = None):
        self.fail_shas = fail_shas or set()
        self.slow_shas = slow_shas or set()
        self.built: List[str] = []

    def list_benchmarks(self) -> List[str]:
        return ["compile_moderate"]

    def build(self, commit_ref: str, workdir: Optional[Path] = None) -> BuildResult:
        self.built.append(commit_ref)
        if commit_ref in self.fail_shas:
            return BuildResult(ok=False, seconds=0.1, log_tail="simulated error")
        return BuildResult(ok=True, seconds=0.2, artifact=commit_ref)

    def run(
        self,
        bench_name: str,
        iters: int = 2000,
        warmup: int = 200,
        inject_ns: int = 0,
        artifact: Optional[str] = None,
    ) -> List[float]:
        base = 1200.0 if artifact in self.slow_shas else 1000.0
        return [base + i * 0.1 for i in range(max(iters, 3))]


def test_resolve_dataset_auto_prefers_newest_timestamp(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    def _write_archive(name: str, date: str, sha: str) -> Path:
        p = data_dir / name
        blob = {
            "format": 1,
            "project": "regex",
            "commits": [
                {
                    "sha": sha,
                    "short_sha": sha[:7],
                    "author_date": date,
                    "subject": "test",
                    "build_ok": True,
                    "build_seconds": 1.0,
                    "cpu_model": "x",
                    "rustc_version": "1.99",
                    "run_started_utc": "",
                    "run_finished_utc": "",
                    "runs": {"compile_moderate": [1000.0] * 5},
                }
            ],
        }
        with gzip.open(p, "wt", encoding="utf-8") as fh:
            json.dump(blob, fh)
        return p

    _write_archive("regex_history.json.gz", "2026-01-27T10:00:00+00:00", "a" * 40)
    study2 = _write_archive("regex_study2_history.json.gz", "2026-11-07T10:00:00+00:00", "b" * 40)
    assert resolve_dataset_path("auto", root_dir=tmp_path) == study2


def test_discover_new_commits_and_reject_unsafe_refs(tmp_path: Path):
    if not shutil.which("git"):
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()
    shas = _init_temp_git_repo(repo, n_commits=4)

    discovered = discover_new_commits(repo, shas[1], fetch=False)
    assert [c["sha"] for c in discovered] == shas[2:]

    with pytest.raises(ValueError, match="Invalid or unsafe git ref"):
        discover_new_commits(repo, "--upload-pack=evil", fetch=False)


def test_continuous_collection_incremental_and_idempotent(tmp_path: Path):
    if not shutil.which("git"):
        pytest.skip("git not available")

    repo = tmp_path / "regex"
    repo.mkdir()
    shas = _init_temp_git_repo(repo, n_commits=4)

    baseline = tmp_path / "data" / "regex_study2_history.json.gz"
    baseline.parent.mkdir(parents=True)
    seed_blob = {
        "format": 1,
        "project": "regex",
        "commits": [
            {
                "sha": sha,
                "short_sha": sha[:7],
                "author_date": f"2026-11-0{idx + 1}T10:00:00Z",
                "subject": f"commit {idx}",
                "build_ok": True,
                "build_seconds": 0.5,
                "cpu_model": "test",
                "rustc_version": "rustc 1.99.1",
                "run_started_utc": f"2026-11-0{idx + 1}T10:00:00+00:00",
                "run_finished_utc": f"2026-11-0{idx + 1}T10:01:00+00:00",
                "runs": {"compile_moderate": [1000.0 + r for r in range(6)]},
            }
            for idx, sha in enumerate(shas[:2])
        ],
    }
    with gzip.open(baseline, "wt", encoding="utf-8") as fh:
        json.dump(seed_blob, fh)

    out_gz = tmp_path / "out" / "updated.json.gz"
    db_path = tmp_path / "out" / "continuous.db"
    sum_json = tmp_path / "out" / "summary.json"
    sum_md = tmp_path / "out" / "summary.md"

    adapter = _FakeContinuousAdapter(fail_shas={shas[2]}, slow_shas={shas[3]})
    summary = run_continuous_collection(
        project="regex",
        dataset_arg=str(baseline),
        out_dataset=out_gz,
        db_path=db_path,
        repo_dir=repo,
        fetch=False,
        benchmarks_override=["compile_moderate"],
        reps=6,
        iters=5,
        warmup=0,
        canary_reps=0,
        fdr="by",
        workdir=tmp_path / "builds",
        cleanup_worktrees=False,
        summary_json=sum_json,
        summary_md=sum_md,
        adapter=adapter,
        root_dir=tmp_path,
    )

    assert summary["commits_discovered"] == 2
    assert summary["commits_profiled"] == 1
    assert summary["commits_build_failed"] == 1
    assert summary["total_commits"] == 4
    assert adapter.built == shas[2:]
    assert out_gz.exists() and sum_json.exists() and sum_md.exists()

    last_sha, known, exported_commits = load_recorded_state(out_gz)
    assert last_sha == shas[3]
    assert known == set(shas)
    assert len(exported_commits) == 4
    assert not exported_commits[2]["build_ok"]
    assert bool(exported_commits[3]["build_ok"])

    # Re-running against the exported archive finds zero new commits (idempotent)
    summary2 = run_continuous_collection(
        project="regex",
        dataset_arg=str(out_gz),
        out_dataset=out_gz,
        db_path=db_path,
        repo_dir=repo,
        fetch=False,
        benchmarks_override=["compile_moderate"],
        reps=6,
        iters=5,
        warmup=0,
        canary_reps=0,
        fdr="by",
        workdir=tmp_path / "builds",
        cleanup_worktrees=False,
        adapter=adapter,
        root_dir=tmp_path,
    )
    assert summary2["commits_discovered"] == 0
    assert summary2["commits_profiled"] == 0
    assert summary2["total_commits"] == 4


def test_continuous_collect_cli_help_and_platform_docs_hygiene():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "continuous_collect.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "--since-sha" in proc.stdout
    assert "--max-commits" in proc.stdout

    for rel in (
        "Dockerfile",
        ".dockerignore",
        "docker-compose.yml",
        "action.yml",
        ".github/workflows/container.yml",
        ".github/workflows/continuous.yml",
        "scripts/container_entrypoint.sh",
        "scripts/run_in_container.sh",
        "scripts/pin_host.sh",
        "scripts/continuous_collect.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "file://" not in text, f"{rel} contains file:// URL"
        assert "Users/Dev" not in text and "Users\\Dev" not in text, f"{rel} contains hardcoded user path"
        assert "Dev Gupta" not in text and "YOUR_USER" not in text, f"{rel} contains author/placeholder token"
