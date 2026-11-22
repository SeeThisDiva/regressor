# Year-Window Commit Pre-Read (`2025-11-07` .. `3d79fe9`)

Range inspected: `5ea3eb1..3d79fe9` (**51 commits** total in `rust-lang/regex`; no commits landed between `2025-10-13` `5ea3eb1` and `2025-12-16` `6a81006`, so `5ea3eb1..3d79fe9` covers the complete year ending `2026-11-07`).

Of the 51 commits:
- **25 commits** touch Rust source paths (`src/`, `regex-automata/src/`, `regex-syntax/src/`, `regex-lite/src/`):
  - **20** modify executable logic or public APIs
  - **5** are doc/comment/formatting/constant-cleanup only (`2c7b172`, `a7f2ff6`, `c420333`, `e018953`, `72d650c`)
- **26 commits** touch only `Cargo.toml`, `CHANGELOG.md`, `README.md`, `AI_POLICY.md`, `.ignore`, `.github/`, or `tests/` / `testdata/` (acting as built-in null controls when every commit is benchmarked).

---

## High-Priority Hot-Path Suspects (Pre-Flag Inspection)

| Commit | Date | Summary | Plausible Performance Impact |
|---|---|---|---|
| `64ad0b6` | 2026-06-07 (merged 07-15) | `automata: fix bug in reverse suffix/inner optimization` | **High (Search + Compile).** Adds `meta/prefix.rs` and `has_no_earlier_match` safety checks in `reverse_inner.rs`, `reverse_suffix.rs`, and `strategy.rs`. Commit message explicitly notes regressions where patterns (e.g. `(.*?,){13}z`, `[\s\S]{0,100}@\w+`, `\s*[\sA-Za-z]{0,12}ing\s`) fall back from `ReverseSuffix`/`ReverseInner` to `Core`. Also modifies `util/look.rs` (`is_word_character` inlining). |
| `fa91c31` | 2026-07-15 | `automata: fix a bug caught by Codex review` | **High (Search inner loop).** Adds `if mat.is_none()` guard before prefix `pre.find(...)` at start states in both `dfa/search.rs` (`find_fwd_imp`) and `hybrid/search.rs` (`find_fwd_imp`). Can alter branch behavior and defer prefilter jumps when a greedy match is pending. |
| `9825c74` | 2026-06-09 | `syntax: avoid re-canonicalizing the entire IntervalSet on push (#1308)` | **High (Compile path).** Replaces `push + canonicalize()` in `regex-syntax/src/hir/interval.rs` with `binary_search` + adjacent union + `Vec::splice`. Large speedup expected on big character classes (Unicode `\w`, `\pL`), minor difference on small classes. |
| `c21ed55` -> `92e0f22` -> `94ac45b` | 2026-08-04 .. 2026-10-28 | Pool capacity & `available_parallelism` series | **High (Compile + Pool init).** `c21ed55` raised `DEFAULT_POOL_CAPACITY` from `8` to `available_parallelism()` (16 stacks on this host) and called `available_parallelism()` per `Regex::new`. `92e0f22` cached `available_parallelism()` in `Lazy`. `94ac45b` reverted default capacity back to `8` (#1389). |
| `ad23cc2` | 2026-10-27 | `meta: fix off-by-one error` | **Moderate/High (DFA accel search).** Advances `accel::find_fwd` start offset from `at` to `at + 1` in `meta/stopat.rs` (used by `ReverseInner` forward confirmation). |
| `3d79fe9` | 2026-11-07 | `syntax: don't lift alternation prefixes that can match more than one way` | **Moderate (Compile + Strategy/Prefilter).** Restricts `lift_common_prefix` in `regex-syntax/src/hir/mod.rs` to `Literal \| Class \| Look`, preventing factoring of repeated prefixes like `ab*b\|ab*c` or `\w+foo\|\w+bar`. |
| `a1e367b` | 2026-10-19 | `automata/dfa/onepass: fix a bug when WhichCaptures::None is used` | **Moderate (One-pass search).** Tightens `slots.len() >= min && min >= 2` in `onepass.rs`, routing zero-capture cases through a 2-slot stack buffer. |
| `10afd70` / `821a8eb` | 2026-07-11 .. 07-14 | `ReverseInner` literal refactor | **Low/Moderate (Compile).** `10afd70` calls a second `prefilter_with_literals` pass on `concat_suffix`; `821a8eb` restructures control flow in `strategy.rs` (tagged no behavior change). |
| `8c34f41` | 2026-06-10 | `automata: avoid reverse suffix optimization for non-leftmost-first` | **Low/Moderate (Search for `MatchKind::All`).** Standard `regex::Regex` uses `LeftmostFirst`; `RegexSet` / `MatchKind::All` disables `ReverseSuffix`. |

---

## Remaining Source-Touching Commits (Low Hot-Path Risk / Null Controls)

- `4733e28` (2026-01-27): `onepass::DFA::try_search_slots` — bounds `explicit_slots_len` by `cache.explicit_slots.len()` and slices target `slots` safely.
- `c4865a0` (2026-02-25): `regex-syntax/src/hir/translate.rs` — HIR negation fix for character classes (compile-only edge case; previously observed causing a +2.6% cross-crate LTO layout shift on `find_iter_userid` in Study 2).
- `2c7b172` (2026-06-06): doc comment only (`regex-automata/src/util/search.rs`).
- `a7f2ff6` (2026-06-06): doc comment only (`regex-lite/src/lib.rs`).
- `468fc64` (2026-06-11): `dense::DFA::from_bytes` rejects match start states (deserialization only).
- `c420333` (2026-07-09): doc-test miri attribute only (`meta/regex.rs`).
- `e358341` (2026-07-04): adds `regex!` lazy macro (`src/regex/{string,bytes}.rs`).
- `6c44a0f` (2026-06-10): internal `thompson::Config` helper cleanup (`meta/regex.rs`, `meta/strategy.rs`).
- `f9b0ab1` (2026-06-10): adds `PrefilterI::name()` + engine choice unit tests (`meta/strategy.rs`, `util/prefilter/*`).
- `e018953` (2026-06-10): whitespace/indentation fix only (`meta/*.rs`, `hir/mod.rs`).
- `30390ec` (2026-07-14): formatting tweaks only (`meta/strategy.rs`).
- `72d650c` (2026-08-10): replaces deprecated `usize::MAX` module constants (`pikevm.rs`, `primitives.rs`).
- `80b9d14` (2026-10-19): adds `Regex::is_match_with` convenience wrapper (`meta/regex.rs`).
