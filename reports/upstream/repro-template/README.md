# Standalone Minimal Regression Reproducer Template

Minimal two-revision Cargo reproducer depending directly on `rust-lang/regex` at two git revisions (`base` vs `cand`), with zero third-party Rust dependencies beyond `regex` and `std`.

## Contents

- `base/Cargo.toml` — pins `regex` to `<BASE_SHA>`
- `cand/Cargo.toml` — pins `regex` to `<CAND_SHA>`
- `src/main.rs` — shared benchmark binary (`std::time::Instant` + `std::hint::black_box`)
- `run_repro.py` — builds both binaries and runs N randomized interleaved `AB`/`BA` process pairs (paired Wilcoxon signed-rank + Walsh Hodges-Lehmann + 95% bootstrap CI)

## Quick Manual Check

```bash
cargo run --release --manifest-path base/Cargo.toml -- 2000 200
cargo run --release --manifest-path cand/Cargo.toml -- 2000 200
```

## Interleaved A/B Reproduction

```bash
python run_repro.py --pairs 30 --iters 2000 --warmup 200
```
