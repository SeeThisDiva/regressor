# Standalone Minimal Regression Reproducer (`fa91c31` vs `64ad0b6`)

Minimal two-revision Cargo reproducer depending directly on `rust-lang/regex` at `fa91c31` vs `64ad0b6`, reproducing the ~95% throughput regression on `r".*.*=.*"` (`rebar` `curated/06-cloud-flare-redos/simplified-long`, 10,001-byte `x=xxxx...\n`), with zero third-party Rust dependencies beyond `regex` and `std`.

## Contents

- `base/Cargo.toml` — pins `regex` to `fa91c31a4291c9dda6afe19829e6fe2e3bbc2da5`
- `cand/Cargo.toml` — pins `regex` to `64ad0b618e043b791ed5385dd5504a436da1ddae`
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
