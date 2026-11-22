# Windows & Cross-Platform Profiling for Differential Flamegraphs

`noise-bench/analyze/flamegraph.py` consumes Brendan Gregg folded stack files (`frame1;frame2 <count>`) and produces interactive differential SVGs (`Red = hotter in candidate`, `Blue = cooler in candidate`). On Linux, folded stacks can be recorded directly with `perf record` + `stackcollapse-perf.pl`.

## Windows 11 Non-Admin Status (`blondie` / `samply`)

On this Windows 11 host (`x86_64-pc-windows-gnu`, Rust `1.99.1`), ETW kernel CPU sampling profilers (`cargo-flamegraph` using the `blondie` backend, and `samply`) require Administrator elevation (`SeSystemProfilePrivilege`) to start a kernel trace session:

- `whoami /priv` shows no `SeSystemProfilePrivilege` (`BUILTIN\Administrators` is deny-only).
- Probing ETW kernel tracing via `logman start "NT Kernel Logger" -p "Windows Kernel Trace" "(process,thread,profile)" -ets` fails with:
  `Error: Access is denied. Try running this command as an administrator.`

Accordingly, ETW-based profilers are blocked without elevation here.

## Working Windows Profiling Path (`win_profile.py`)

`noise-bench/analyze/win_profile.py` provides two **elevation-free** Windows profiling modes for `noise-bench.exe` release binaries built with `debug = true` (`noise-bench/Cargo.toml`):

### Prerequisite

```bash
rustup component add llvm-tools
```

This provides 64-bit `llvm-nm` and `llvm-objdump` capable of reading PE32+ (`coff-x86-64`) symbols and DWARF inline tables (`--debug-inlined-funcs=ascii`), whereas legacy 32-bit MinGW `objdump` cannot parse 64-bit PE executables.

### 1. User-Mode CPU Stack Sampling (`sample` mode — default)

Spawns `noise-bench.exe` as an owned child process (requires no Admin/ETW), samples the main thread at ~1,000 Hz via Win32 `OpenProcess` / `OpenThread` / `SuspendThread` / `GetThreadContext` / `ReadProcessMemory`, unwinds x64 frames offline from PE `.pdata`/`.xdata` exception tables (including loaded Windows DLLs with export-table symbol resolution), and expands DWARF inline Rust call chains via `llvm-objdump --debug-inlined-funcs=ascii`:

```bash
python noise-bench/analyze/win_profile.py diff \
  .regressor-builds/<base_prefix>/target/release/noise-bench.exe \
  .regressor-builds/<cand_prefix>/target/release/noise-bench.exe \
  --mode sample \
  --bench find_iter_userid \
  --iters 15000 --warmup 200 --freq 1000 \
  --base-folded noise-bench/profiles/parent_<base>.folded \
  --cand-folded noise-bench/profiles/candidate_<cand>.folded \
  --out-svg assets/flamegraphs/flamegraph_diff_<cand>.svg \
  --title "<base> vs <cand> (<bench>)"
```

### 2. Static Instruction-Count & Spill Attribution (`insn` mode — deterministic, zero runtime noise)

Disassembles the benchmark symbol(s) and statically reachable `regex` / `memchr` / `aho_corasick` callees via `llvm-nm` + `llvm-objdump --debug-inlined-funcs=ascii`, counting per-function static instructions, natural-loop instructions, and `(%rsp)` stack-spill loads/stores, and emitting instruction-attributed `.folded` stacks + a JSON instruction diff:

```bash
python noise-bench/analyze/win_profile.py diff \
  .regressor-builds/<base_prefix>/target/release/noise-bench.exe \
  .regressor-builds/<cand_prefix>/target/release/noise-bench.exe \
  --mode insn \
  --bench find_iter_userid \
  --base-folded noise-bench/profiles/parent_<base>_insn.folded \
  --cand-folded noise-bench/profiles/candidate_<cand>_insn.folded \
  --out-svg assets/flamegraphs/flamegraph_diff_<cand>_insn.svg \
  --asm-json noise-bench/profiles/asm_diff_<cand>.json \
  --title "<base> vs <cand> (Static Instruction Attribution)"
```

Use `sample` mode to attribute where wall-clock CPU time is spent, and `insn` mode alongside assembly inspection to distinguish true algorithmic work (`+N` executed instructions) from LTO binary-layout shifts (`+0` instructions).
