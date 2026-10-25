"""
tests/test_stage5_api_hardening.py
Input validation on the ad-hoc compare endpoint.
"""

from pathlib import Path

import pytest

from core.db import Database


@pytest.fixture
def client(tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from server.app import create_app

    db_path = tmp_path / "t.db"
    db = Database(str(db_path))
    pid = db.register_project(name="demo", repo_url="https://example.invalid/demo.git",
                              build_cmd="", adapter="PyMicroAdapter", config_toml="")
    for sha, base in (("aaaaaaa", 1000.0), ("bbbbbbb", 1100.0)):
        cid = db.insert_commit(project_id=pid, sha=sha * 2, short_sha=sha, author_date="2026-01-01",
                               subject=f"commit {sha}", build_ok=True, build_seconds=1.0,
                               cpu_model="test", rustc_version="n/a",
                               run_started_utc="2026-01-01T10:00:00+00:00",
                               run_finished_utc="2026-01-01T10:10:00+00:00")
        for i in range(6):
            db.insert_run(commit_id=cid, benchmark="b", rep_index=i + 1,
                          sample_file_path="", median_ns=base + i)
    return TestClient(create_app(db_path=str(db_path)))


def _post(client, base, cand):
    return client.post("/api/compare", json={"project": "demo", "base_sha": base, "cand_sha": cand})


def test_compare_rejects_short_or_empty_prefixes(client):
    assert _post(client, "", "bbbbbbb").status_code == 400
    assert _post(client, "aaaaaaa", "b").status_code == 400
    assert _post(client, "aaa", "bbbbbbb").status_code == 400


def test_compare_rejects_same_commit(client):
    r = _post(client, "aaaa", "aaaaaaa")
    assert r.status_code == 400
    assert "same commit" in r.json()["detail"]


def test_compare_valid_pair_still_works(client):
    r = _post(client, "aaaa", "bbbb")
    assert r.status_code == 200
    comp = r.json()["comparisons"]
    assert len(comp) == 1 and comp[0]["verdict"] == "flag"


def test_import_data_rejects_corrupt_or_malformed_files_cleanly(tmp_path, monkeypatch, capsys):
    import gzip
    import json
    import sys

    import regressor

    db_path = str(tmp_path / "imp.db")

    # 1. Corrupt gzip
    bad_gz = tmp_path / "bad.json.gz"
    bad_gz.write_bytes(b"not a gzip stream")
    monkeypatch.setattr(sys, "argv", ["regressor", "--db", db_path, "import-data", str(bad_gz)])
    assert regressor.main() == 1
    assert "Error: cannot read" in capsys.readouterr().err

    # 2. Wrong JSON schema
    bad_shape = tmp_path / "shape.json.gz"
    with gzip.open(bad_shape, "wt", encoding="utf-8") as f:
        json.dump({"hello": "world"}, f)
    monkeypatch.setattr(sys, "argv", ["regressor", "--db", db_path, "import-data", str(bad_shape)])
    assert regressor.main() == 1
    assert "not a regressor export file" in capsys.readouterr().err

    # 3. Non-positive run median inside commit
    bad_med = tmp_path / "med.json.gz"
    with gzip.open(bad_med, "wt", encoding="utf-8") as f:
        json.dump({
            "project": "regex",
            "commits": [{
                "sha": "16d47c523964", "short_sha": "16d47c5", "author_date": "2023-11-22",
                "subject": "test", "build_ok": True, "build_seconds": 1.0,
                "cpu_model": "x", "rustc_version": "1.82",
                "run_started_utc": "", "run_finished_utc": "",
                "runs": {"compile_moderate": [100.0, 0.0, 105.0]},
            }],
        }, f)
    monkeypatch.setattr(sys, "argv", ["regressor", "--db", db_path, "import-data", str(bad_med)])
    assert regressor.main() == 1
    assert "invalid median" in capsys.readouterr().err


def test_cli_rejects_non_positive_counts_and_unknown_changepoint_benchmark(tmp_path, monkeypatch, capsys):
    import sys
    from pathlib import Path

    import regressor

    for bad_argv in (
        ["regressor", "batch", "regex", "--rolling-window", "0"],
        ["regressor", "compare-interleaved", "--base", "a", "--cand", "b", "--pairs", "0"],
        ["regressor", "compare-interleaved", "--base", "a", "--cand", "b", "--iters", "-5"],
    ):
        monkeypatch.setattr(sys, "argv", bad_argv)
        with pytest.raises(SystemExit) as exc:
            regressor.main()
        assert exc.value.code == 2

    data = Path(__file__).resolve().parent.parent / "data" / "regex_history.json.gz"
    db_path = str(tmp_path / "cp.db")
    monkeypatch.setattr(sys, "argv", ["regressor", "--db", db_path, "import-data", str(data)])
    assert regressor.main() == 0
    monkeypatch.setattr(sys, "argv", ["regressor", "--db", db_path, "changepoint", "regex", "--benchmark", "no_such_bench"])
    assert regressor.main() == 1
    assert "has no runs" in capsys.readouterr().err


def test_packaging_and_dockerfile_configuration():
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    st = pyproject.get("tool", {}).get("setuptools", {})
    assert st.get("py-modules") == ["regressor"]
    assert set(st.get("packages", [])) == {"core", "adapters", "server"}

    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "/work/regressor/regex" in dockerfile
    assert "pip3 install --no-cache-dir --break-system-packages -e /work/regressor" in dockerfile


def test_security_headers_and_csp_present(client):
    for path in ("/", "/api/projects"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "SAMEORIGIN"
        assert r.headers.get("referrer-policy") == "same-origin"
        assert "geolocation=()" in r.headers.get("permissions-policy", "")
        csp = r.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'self'" in csp
        assert "object-src 'none'" in csp
        assert "base-uri 'self'" in csp


def test_compare_rejects_mass_assignment_and_oversized_fields(client):
    # Extra unexpected fields rejected by ConfigDict(extra="forbid")
    r_extra = client.post(
        "/api/compare",
        json={"project": "demo", "base_sha": "aaaa", "cand_sha": "bbbb", "role": "admin"},
    )
    assert r_extra.status_code == 422

    # Oversized SHA prefix (> 64 chars) rejected with 400 on both /api/compare and /distribution
    assert _post(client, "a" * 65, "bbbbbbb").status_code == 400
    assert client.get(f"/api/commits/{'a' * 65}/distribution").status_code == 400
    assert client.get(f"/api/commits/aaaaaaa/distribution?project={'p' * 65}").status_code == 400


def test_flamegraph_svgs_guard_prototype_pollution_and_selector_injection():
    from pathlib import Path

    fg_dir = Path(__file__).resolve().parent.parent / "assets" / "flamegraphs"
    for svg_path in fg_dir.glob("*.svg"):
        text = svg_path.read_text(encoding="utf-8")
        assert "Object.create(null)" in text
        assert "__proto__" in text
        assert "/^[0-9.]+$/.test(params.x)" in text


def test_markdown_report_sanitizes_html_and_table_injection():
    from core.report import render_markdown

    results = [{
        "benchmark": "bench|name`<script>alert(1)</script>",
        "baseline_median_ns": 1000.0,
        "candidate_median_ns": 1050.0,
        "shift_pct": 5.0,
        "shift_ci95_pct": [3.0, 7.0],
        "p_value": 1e-4,
        "final_verdict": "flag",
        "pairs": 20,
        "alpha": 0.01,
        "min_effect_pct": 1.0,
    }]
    md = render_markdown(
        base="a`<img src=x>",
        cand="b|table",
        results=results,
        env={"platform": "Linux<script>", "cpu": "x86|64"},
        canary={"shift_pct": 0.5, "status": "OK<bold>", "is_drifted": False},
    )
    assert "<script>" not in md
    assert "<img" not in md
    assert "&lt;script&gt;" in md
    assert "\\|" in md


def test_markdown_docs_contain_no_local_file_urls_or_author_paths():
    for unwanted in ("FINAL.md", "SESSION.md", "HANDOFF.md", "CHECKPOINTS.md"):
        assert not Path(unwanted).exists(), f"{unwanted} should be deleted"
    for md_name in ("README.md", "PROJECT_EXPLANATION.md", "SETUP.md", "LICENSE", "pyproject.toml"):
        p = Path(md_name)
        assert p.exists(), f"{md_name} is missing"
        text = p.read_text(encoding="utf-8")
        assert "file://" not in text, f"{md_name} contains a file:// URL"
        assert "Users/Dev" not in text and "Users\\Dev" not in text, f"{md_name} contains a hardcoded author path"
        assert "Dev Gupta" not in text and "dev@example" not in text, f"{md_name} still references 'Dev'"
        assert "YOUR_USER" not in text, f"{md_name} still has a YOUR_USER placeholder"


def test_docs_invariants_and_cli_commands_match_codebase(tmp_path: Path, monkeypatch):
    import shlex

    import regressor
    from core.session import SESSION_BREAK_MIN

    readme_text = Path("README.md").read_text(encoding="utf-8")
    explanation_text = Path("PROJECT_EXPLANATION.md").read_text(encoding="utf-8")

    # 1. Verify true baseline flags, 201-min gap, and 15-min session threshold are consistent
    assert SESSION_BREAK_MIN == 15.0
    for sha in ("16d47c5", "0a446ec", "dd96592"):
        assert sha in readme_text
    assert "201 min" in readme_text
    for doc_name, text in (("README.md", readme_text), ("PROJECT_EXPLANATION.md", explanation_text)):
        for fabricated in ("compile_simple", "a41df97", "309-minute", "309 min"):
            assert fabricated not in text, f"Fabricated token {fabricated!r} found in {doc_name}"

    # 2. Extract every `python regressor.py ...` command from README.md, PROJECT_EXPLANATION.md, and SETUP.md
    cmds = []
    for md_name in ("README.md", "PROJECT_EXPLANATION.md", "SETUP.md"):
        lines = Path(md_name).read_text(encoding="utf-8").splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("python regressor.py "):
                full = line
                while full.endswith("\\") and i + 1 < len(lines):
                    i += 1
                    full = full[:-1].strip() + " " + lines[i].strip()
                # Strip inline comment
                if " #" in full:
                    full = full.split(" #", 1)[0].strip()
                cmds.append((md_name, full))
            i += 1

    assert len(cmds) >= 20
    db_file = tmp_path / "doc_verify.db"

    # Run every documented command through the real CLI parser (and execute safe/fast ones end to end)
    for md_name, cmd in cmds:
        tokens = shlex.split(cmd)[2:]  # strip `python regressor.py`
        assert tokens, f"Empty command in {md_name}: {cmd}"
        subcmd = tokens[0]
        monkeypatch.setattr("sys.argv", ["regressor.py", "--db", str(db_file), *tokens])
        if subcmd in ("init", "import-data", "batch", "analyze", "changepoint", "dedupe"):
            rc = regressor.main()
            assert rc == 0, f"Documented command failed ({rc}) in {md_name}: {cmd}"
        elif subcmd == "export-data":
            out_file = tmp_path / "exp.json.gz"
            monkeypatch.setattr("sys.argv", ["regressor.py", "--db", str(db_file), "export-data", "regex", "--out", str(out_file)])
            assert regressor.main() == 0
        else:
            called = []
            monkeypatch.setattr(regressor, f"cmd_{subcmd.replace('-', '_')}", lambda args: (called.append(args), 0)[1])
            assert regressor.main() == 0, f"Parser rejected command in {md_name}: {cmd}"
            assert len(called) == 1


def test_verify_sh_is_posix_sh_compatible():
    sh_text = Path("scripts/verify.sh").read_text(encoding="utf-8")
    assert "pipefail" not in sh_text



