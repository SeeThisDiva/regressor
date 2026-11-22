# Study 3 Flagged Comparisons (`batch regex --fdr by`, alpha=0.05)

- Commits: **51** (`4733e28..3d79fe9`, 1 year)
- Benchmarks: **25**
- Total pairwise comparisons: **1250**
- Flagged pre-FDR / post-BH-FDR / post-BY-FDR: **371 / 371 / 371**

| Transition | Benchmark | Shift % | p-value | Baseline CV % | Noise Floor % | Null Control | Session Break | Canary (within / vs-prev) | Subject |
|---|---|---:|---:|---:|---:|---|---|---|---|
| `4733e28->6a81006` | `rebar_curated_01_literal_sherlock_casei_en` | +0.41% | 3.03e-06 | 0.12% | 0.38% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: exclude development scripts and fuzzing data |
| `4733e28->6a81006` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | -5.45% | 3.33e-06 | 0.72% | 2.17% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: exclude development scripts and fuzzing data |
| `4733e28->6a81006` | `rebar_curated_02_literal_alternate_sherlock_en` | +0.21% | 2.44e-05 | 0.05% | 0.16% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: exclude development scripts and fuzzing data |
| `4733e28->6a81006` | `rebar_curated_04_ruff_noqa_tweaked_lite` | -1.28% | 6.70e-05 | 0.41% | 1.25% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: exclude development scripts and fuzzing data |
| `4733e28->6a81006` | `rebar_curated_08_words_all_russian` | -0.56% | 1.44e-05 | 0.18% | 0.53% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: exclude development scripts and fuzzing data |
| `4733e28->6a81006` | `rebar_opt_onepass_first_three_words_en` | -3.36% | 3.23e-06 | 0.42% | 1.26% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: exclude development scripts and fuzzing data |
| `6a81006->0c07fae` | `find_iter_userid` | +2.73% | 3.27e-06 | 0.31% | 0.92% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_curated_01_literal_sherlock_casei_en` | -0.40% | 2.06e-03 | 0.12% | 0.36% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_curated_01_literal_sherlock_en` | +15.97% | 1.22e-06 | 0.36% | 1.09% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +6.06% | 3.32e-06 | 0.97% | 2.90% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_curated_03_date_unicode` | -2.18% | 3.36e-06 | 0.26% | 0.78% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_curated_04_ruff_noqa_real` | -4.32% | 3.52e-04 | 0.70% | 2.10% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_curated_04_ruff_noqa_tweaked_lite` | +4.61% | 4.06e-06 | 0.67% | 2.02% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_curated_09_aws_keys_quick` | +2.75% | 4.81e-06 | 0.73% | 2.18% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_curated_10_bounded_repeat_context` | -1.01% | 3.37e-06 | 0.17% | 0.51% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_opt_backtrack_words_en` | -1.48% | 1.68e-04 | 0.27% | 0.80% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_opt_onepass_first_three_words_en` | +5.25% | 3.28e-06 | 0.33% | 0.99% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_opt_reverse_inner_email` | +9.85% | 3.11e-07 | 0.00% | 0.00% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_opt_reverse_suffix_holmes` | +6.00% | 2.78e-06 | 0.36% | 1.08% | yes | no | OK / OK | regex-lite-0.1.9 |
| `6a81006->0c07fae` | `rebar_wild_rustsec_cargo_audit_bytes` | +3.44% | 2.09e-06 | 0.12% | 0.37% | yes | no | OK / OK | regex-lite-0.1.9 |
| `0c07fae->a3433f6` | `find_iter_userid` | -1.29% | 3.27e-06 | 0.35% | 1.05% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `is_match_status` | +27.13% | 2.85e-06 | 2.99% | 8.98% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `rebar_curated_01_literal_sherlock_en` | -12.56% | 1.32e-06 | 0.11% | 0.33% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | -12.16% | 3.33e-06 | 1.27% | 3.80% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `rebar_curated_02_literal_alternate_sherlock_en` | +0.63% | 2.28e-06 | 0.12% | 0.37% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `rebar_curated_03_date_unicode` | +2.10% | 3.37e-06 | 0.27% | 0.81% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `rebar_curated_04_ruff_noqa_tweaked_lite` | -4.50% | 3.32e-06 | 1.20% | 3.60% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `rebar_curated_10_bounded_repeat_context` | +0.95% | 3.36e-06 | 0.13% | 0.40% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `rebar_opt_backtrack_words_en` | +3.42% | 3.33e-06 | 0.70% | 2.10% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `rebar_opt_onepass_first_three_words_en` | -4.11% | 3.17e-06 | 0.33% | 0.99% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `rebar_opt_reverse_inner_email` | -9.51% | 3.11e-07 | 0.12% | 0.37% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `rebar_opt_reverse_suffix_holmes` | -5.99% | 2.17e-06 | 0.44% | 1.33% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `0c07fae->a3433f6` | `rebar_wild_rustsec_cargo_audit_bytes` | -3.32% | 2.06e-06 | 0.59% | 1.77% | yes | no | OK / OK | regex-syntax-0.8.9 |
| `a3433f6->5e195de` | `is_match_status` | -22.87% | 2.47e-06 | 0.36% | 1.09% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.14 |
| `a3433f6->5e195de` | `rebar_curated_01_literal_sherlock_en` | +1.93% | 2.59e-06 | 0.33% | 1.00% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.14 |
| `a3433f6->5e195de` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +14.29% | 3.32e-06 | 0.65% | 1.94% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.14 |
| `a3433f6->5e195de` | `rebar_curated_04_ruff_noqa_tweaked_lite` | +2.60% | 3.29e-06 | 0.38% | 1.13% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.14 |
| `a3433f6->5e195de` | `rebar_curated_08_words_all_russian` | +0.52% | 7.32e-06 | 0.14% | 0.42% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.14 |
| `a3433f6->5e195de` | `rebar_curated_09_aws_keys_quick` | -0.73% | 7.11e-05 | 0.24% | 0.73% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.14 |
| `a3433f6->5e195de` | `rebar_curated_10_bounded_repeat_letters_ru` | -1.99% | 4.20e-04 | 0.54% | 1.62% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.14 |
| `a3433f6->5e195de` | `rebar_opt_onepass_first_three_words_en` | +5.91% | 3.16e-06 | 0.43% | 1.30% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.14 |
| `a3433f6->5e195de` | `rebar_opt_reverse_suffix_holmes` | +0.67% | 1.12e-05 | 0.20% | 0.60% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.14 |
| `5e195de->b028e4f` | `rebar_curated_01_literal_sherlock_casei_en` | -0.40% | 1.45e-06 | 0.11% | 0.34% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.12.3 |
| `5e195de->b028e4f` | `rebar_curated_01_literal_sherlock_en` | -4.61% | 2.82e-06 | 0.27% | 0.82% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.12.3 |
| `5e195de->b028e4f` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | -8.59% | 3.31e-06 | 0.83% | 2.50% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.12.3 |
| `5e195de->b028e4f` | `rebar_curated_03_date_unicode` | -1.90% | 3.38e-06 | 0.24% | 0.71% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.12.3 |
| `5e195de->b028e4f` | `rebar_curated_04_ruff_noqa_real` | -7.18% | 1.92e-04 | 1.03% | 3.09% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.12.3 |
| `5e195de->b028e4f` | `rebar_curated_05_lexer_veryl_regexset` | -5.79% | 3.38e-06 | 0.32% | 0.96% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.12.3 |
| `5e195de->b028e4f` | `rebar_curated_09_aws_keys_quick` | +11.89% | 3.16e-06 | 0.46% | 1.38% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.12.3 |
| `5e195de->b028e4f` | `rebar_opt_onepass_first_three_words_en` | -5.59% | 3.31e-06 | 0.35% | 1.06% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.12.3 |
| `5e195de->b028e4f` | `rebar_opt_reverse_inner_email` | +0.60% | 1.29e-07 | 0.08% | 0.23% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.12.3 |
| `5e195de->b028e4f` | `rebar_opt_reverse_suffix_holmes` | +3.33% | 2.05e-06 | 0.32% | 0.96% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.12.3 |
| `b028e4f->2aaa18d` | `rebar_curated_01_literal_sherlock_casei_en` | +0.41% | 1.24e-06 | 0.10% | 0.32% | yes | no | OK / ENVIRONMENT_SUSPECT | rure-0.2.5 |
| `b028e4f->2aaa18d` | `rebar_curated_01_literal_sherlock_en` | +2.84% | 2.93e-06 | 0.46% | 1.38% | yes | no | OK / ENVIRONMENT_SUSPECT | rure-0.2.5 |
| `b028e4f->2aaa18d` | `rebar_curated_02_literal_alternate_sherlock_en` | +0.84% | 1.01e-06 | 0.16% | 0.49% | yes | no | OK / ENVIRONMENT_SUSPECT | rure-0.2.5 |
| `b028e4f->2aaa18d` | `rebar_curated_05_lexer_veryl_regexset` | +7.03% | 3.38e-06 | 0.55% | 1.65% | yes | no | OK / ENVIRONMENT_SUSPECT | rure-0.2.5 |
| `b028e4f->2aaa18d` | `rebar_curated_05_lexer_veryl_single` | -4.57% | 3.38e-06 | 0.41% | 1.22% | yes | no | OK / ENVIRONMENT_SUSPECT | rure-0.2.5 |
| `b028e4f->2aaa18d` | `rebar_curated_09_aws_keys_quick` | -10.06% | 3.16e-06 | 1.44% | 4.32% | yes | no | OK / ENVIRONMENT_SUSPECT | rure-0.2.5 |
| `b028e4f->2aaa18d` | `rebar_opt_reverse_inner_email` | -0.60% | 8.27e-08 | 0.00% | 0.00% | yes | no | OK / ENVIRONMENT_SUSPECT | rure-0.2.5 |
| `b028e4f->2aaa18d` | `rebar_opt_reverse_suffix_holmes` | -1.61% | 2.26e-06 | 0.23% | 0.68% | yes | no | OK / ENVIRONMENT_SUSPECT | rure-0.2.5 |
| `b028e4f->2aaa18d` | `rebar_wild_rustsec_cargo_audit_bytes` | +0.57% | 2.97e-06 | 0.17% | 0.52% | yes | no | OK / ENVIRONMENT_SUSPECT | rure-0.2.5 |
| `2aaa18d->d8761c0` | `rebar_curated_01_literal_sherlock_casei_en` | -0.40% | 1.08e-06 | 0.09% | 0.28% | yes | no | OK / OK | cargo: also include `benches` |
| `2aaa18d->d8761c0` | `rebar_curated_01_literal_sherlock_en` | +1.66% | 3.11e-06 | 0.45% | 1.35% | yes | no | OK / OK | cargo: also include `benches` |
| `2aaa18d->d8761c0` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | -8.16% | 3.32e-06 | 0.67% | 2.00% | yes | no | OK / OK | cargo: also include `benches` |
| `2aaa18d->d8761c0` | `rebar_curated_02_literal_alternate_sherlock_en` | -1.04% | 9.37e-07 | 0.12% | 0.35% | yes | no | OK / OK | cargo: also include `benches` |
| `2aaa18d->d8761c0` | `rebar_curated_03_date_unicode` | +1.27% | 3.31e-06 | 0.16% | 0.49% | yes | no | OK / OK | cargo: also include `benches` |
| `2aaa18d->d8761c0` | `rebar_curated_04_ruff_noqa_real` | -8.77% | 3.25e-06 | 1.35% | 4.05% | yes | no | OK / OK | cargo: also include `benches` |
| `2aaa18d->d8761c0` | `rebar_curated_09_aws_keys_quick` | +14.61% | 3.20e-06 | 0.77% | 2.32% | yes | no | OK / OK | cargo: also include `benches` |
| `2aaa18d->d8761c0` | `rebar_curated_10_bounded_repeat_letters_ru` | -1.22% | 6.59e-04 | 0.34% | 1.03% | yes | no | OK / OK | cargo: also include `benches` |
| `2aaa18d->d8761c0` | `rebar_opt_reverse_inner_email` | +0.30% | 2.26e-05 | 0.00% | 0.00% | yes | no | OK / OK | cargo: also include `benches` |
| `d8761c0->c4865a0` | `find_iter_userid` | +1.16% | 3.27e-06 | 0.20% | 0.61% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | syntax: fix negation handling in HIR translation |
| `d8761c0->c4865a0` | `rebar_curated_01_literal_sherlock_casei_en` | +0.61% | 1.12e-06 | 0.10% | 0.30% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | syntax: fix negation handling in HIR translation |
| `d8761c0->c4865a0` | `rebar_curated_02_literal_alternate_sherlock_en` | +0.84% | 2.15e-06 | 0.18% | 0.56% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | syntax: fix negation handling in HIR translation |
| `d8761c0->c4865a0` | `rebar_curated_09_aws_keys_quick` | -5.27% | 3.21e-06 | 0.24% | 0.73% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | syntax: fix negation handling in HIR translation |
| `d8761c0->c4865a0` | `rebar_wild_rustsec_cargo_audit_bytes` | -0.38% | 9.06e-03 | 0.12% | 0.35% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | syntax: fix negation handling in HIR translation |
| `c4865a0->839d16b` | `rebar_curated_01_literal_sherlock_en` | -2.17% | 2.56e-06 | 0.25% | 0.74% | yes | no | OK / OK | regex-syntax-0.8.10 |
| `c4865a0->839d16b` | `rebar_curated_03_date_unicode` | -1.13% | 4.98e-06 | 0.34% | 1.03% | yes | no | OK / OK | regex-syntax-0.8.10 |
| `c4865a0->839d16b` | `rebar_curated_04_ruff_noqa_real` | +5.95% | 3.28e-06 | 0.30% | 0.89% | yes | no | OK / OK | regex-syntax-0.8.10 |
| `c4865a0->839d16b` | `rebar_curated_05_lexer_veryl_regexset` | -6.34% | 3.39e-06 | 0.47% | 1.43% | yes | no | OK / OK | regex-syntax-0.8.10 |
| `c4865a0->839d16b` | `rebar_curated_05_lexer_veryl_single` | +1.55% | 4.09e-06 | 0.42% | 1.25% | yes | no | OK / OK | regex-syntax-0.8.10 |
| `c4865a0->839d16b` | `rebar_curated_08_words_all_russian` | +1.03% | 3.95e-05 | 0.13% | 0.40% | yes | no | OK / OK | regex-syntax-0.8.10 |
| `c4865a0->839d16b` | `rebar_curated_09_aws_keys_quick` | -7.44% | 2.98e-06 | 0.42% | 1.25% | yes | no | OK / OK | regex-syntax-0.8.10 |
| `c4865a0->839d16b` | `rebar_curated_10_bounded_repeat_letters_ru` | -2.96% | 3.34e-06 | 0.59% | 1.78% | yes | no | OK / OK | regex-syntax-0.8.10 |
| `839d16b->2c7b172` | `find_iter_userid` | -2.20% | 3.28e-06 | 0.27% | 0.80% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_curated_01_literal_sherlock_en` | +15.51% | 8.45e-07 | 0.32% | 0.95% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +7.60% | 3.31e-06 | 0.85% | 2.55% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_curated_03_date_unicode` | +1.54% | 3.32e-06 | 0.17% | 0.51% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_curated_04_ruff_noqa_real` | -7.34% | 3.29e-06 | 2.15% | 6.46% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_curated_04_ruff_noqa_tweaked_lite` | +2.05% | 2.75e-05 | 0.36% | 1.09% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_curated_05_lexer_veryl_regexset` | +5.40% | 3.39e-06 | 0.44% | 1.32% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_curated_05_lexer_veryl_single` | -1.29% | 1.39e-03 | 0.40% | 1.19% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_curated_09_aws_keys_quick` | +13.40% | 3.07e-06 | 0.35% | 1.05% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_opt_backtrack_words_en` | +1.26% | 4.01e-06 | 0.33% | 1.00% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_opt_reverse_inner_email` | +10.51% | 5.00e-07 | 0.12% | 0.37% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_opt_reverse_suffix_holmes` | +3.97% | 2.28e-06 | 0.28% | 0.83% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `839d16b->2c7b172` | `rebar_wild_rustsec_cargo_audit_bytes` | +3.04% | 2.37e-06 | 0.21% | 0.62% | yes | no | ENVIRONMENT_SUSPECT / OK | docs: clarify unsupported Anchored::Pattern searches |
| `2c7b172->a7f2ff6` | `find_iter_userid` | +1.37% | 5.94e-06 | 0.40% | 1.20% | yes | no | OK / OK | docs: clarify regex-lite word boundaries |
| `2c7b172->a7f2ff6` | `rebar_curated_01_literal_sherlock_en` | -12.71% | 7.09e-07 | 0.06% | 0.19% | yes | no | OK / OK | docs: clarify regex-lite word boundaries |
| `2c7b172->a7f2ff6` | `rebar_curated_05_lexer_veryl_regexset` | -6.44% | 3.38e-06 | 0.33% | 1.00% | yes | no | OK / OK | docs: clarify regex-lite word boundaries |
| `2c7b172->a7f2ff6` | `rebar_opt_onepass_first_three_words_en` | -2.49% | 3.25e-06 | 0.44% | 1.32% | yes | no | OK / OK | docs: clarify regex-lite word boundaries |
| `2c7b172->a7f2ff6` | `rebar_opt_reverse_inner_email` | -9.51% | 2.78e-07 | 0.10% | 0.29% | yes | no | OK / OK | docs: clarify regex-lite word boundaries |
| `2c7b172->a7f2ff6` | `rebar_opt_reverse_suffix_holmes` | -4.46% | 2.47e-06 | 0.32% | 0.97% | yes | no | OK / OK | docs: clarify regex-lite word boundaries |
| `2c7b172->a7f2ff6` | `rebar_wild_rustsec_cargo_audit_bytes` | -2.77% | 1.86e-06 | 0.13% | 0.39% | yes | no | OK / OK | docs: clarify regex-lite word boundaries |
| `a7f2ff6->9825c74` | `rebar_curated_08_words_all_russian` | +0.51% | 8.99e-06 | 0.16% | 0.47% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | syntax: avoid re-canonicalizing the entire IntervalSet on push (#1308) |
| `a7f2ff6->9825c74` | `rebar_wild_rustsec_cargo_audit_bytes` | +0.76% | 2.61e-06 | 0.14% | 0.41% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | syntax: avoid re-canonicalizing the entire IntervalSet on push (#1308) |
| `9825c74->d709000` | `rebar_curated_01_literal_sherlock_en` | +1.65% | 2.10e-06 | 0.24% | 0.73% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.12.4 |
| `9825c74->d709000` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +1.63% | 7.22e-06 | 0.49% | 1.49% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.12.4 |
| `9825c74->d709000` | `rebar_curated_05_lexer_veryl_regexset` | +9.14% | 3.38e-06 | 1.44% | 4.33% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.12.4 |
| `9825c74->d709000` | `rebar_curated_10_bounded_repeat_context` | +1.24% | 2.11e-05 | 0.40% | 1.21% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.12.4 |
| `9825c74->d709000` | `rebar_opt_onepass_first_three_words_en` | +2.29% | 3.17e-06 | 0.21% | 0.64% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.12.4 |
| `9825c74->d709000` | `rebar_opt_reverse_suffix_holmes` | +1.67% | 2.32e-06 | 0.29% | 0.86% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.12.4 |
| `d709000->1401679` | `rebar_curated_01_literal_sherlock_en` | -1.90% | 2.67e-06 | 0.33% | 0.99% | yes | no | OK / OK | regex-syntax-0.8.11 |
| `d709000->1401679` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +5.56% | 3.29e-06 | 0.77% | 2.30% | yes | no | OK / OK | regex-syntax-0.8.11 |
| `d709000->1401679` | `rebar_curated_09_aws_keys_quick` | -7.65% | 3.25e-06 | 0.20% | 0.62% | yes | no | OK / OK | regex-syntax-0.8.11 |
| `d709000->1401679` | `rebar_opt_backtrack_words_en` | +2.27% | 3.27e-06 | 0.28% | 0.83% | yes | no | OK / OK | regex-syntax-0.8.11 |
| `d709000->1401679` | `rebar_opt_reverse_suffix_holmes` | -1.31% | 5.10e-05 | 0.27% | 0.80% | yes | no | OK / OK | regex-syntax-0.8.11 |
| `d709000->1401679` | `rebar_wild_rustsec_cargo_audit_bytes` | -0.75% | 1.13e-04 | 0.20% | 0.60% | yes | no | OK / OK | regex-syntax-0.8.11 |
| `1401679->7b89cf0` | `rebar_curated_01_literal_sherlock_casei_en` | +0.41% | 1.65e-05 | 0.12% | 0.36% | yes | no | OK / ENVIRONMENT_SUSPECT | deps: update to regex-syntax 0.8.11 |
| `1401679->7b89cf0` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | -7.49% | 3.28e-06 | 0.84% | 2.52% | yes | no | OK / ENVIRONMENT_SUSPECT | deps: update to regex-syntax 0.8.11 |
| `1401679->7b89cf0` | `rebar_curated_02_literal_alternate_sherlock_en` | +0.63% | 2.01e-06 | 0.19% | 0.58% | yes | no | OK / ENVIRONMENT_SUSPECT | deps: update to regex-syntax 0.8.11 |
| `7b89cf0->7b96fdc` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +2.52% | 6.64e-06 | 0.81% | 2.45% | yes | no | OK / OK | 1.12.4 |
| `7b89cf0->7b96fdc` | `rebar_curated_04_ruff_noqa_real` | -6.50% | 6.64e-04 | 1.33% | 4.00% | yes | no | OK / OK | 1.12.4 |
| `7b89cf0->7b96fdc` | `rebar_curated_05_lexer_veryl_regexset` | -6.05% | 3.37e-06 | 0.58% | 1.74% | yes | no | OK / OK | 1.12.4 |
| `7b89cf0->7b96fdc` | `rebar_curated_09_aws_keys_quick` | +11.85% | 3.23e-06 | 0.29% | 0.87% | yes | no | OK / OK | 1.12.4 |
| `7b89cf0->7b96fdc` | `rebar_opt_backtrack_words_en` | -2.50% | 3.15e-06 | 0.20% | 0.60% | yes | no | OK / OK | 1.12.4 |
| `7b96fdc->468fc64` | `compile_moderate` | -4.76% | 4.14e-06 | 0.89% | 2.66% | no | no | OK / OK | automata: reject dense DFA start states that are match states |
| `7b96fdc->468fc64` | `rebar_curated_01_literal_sherlock_casei_en` | -0.60% | 3.52e-05 | 0.12% | 0.36% | no | no | OK / OK | automata: reject dense DFA start states that are match states |
| `7b96fdc->468fc64` | `rebar_curated_01_literal_sherlock_en` | -1.65% | 2.36e-06 | 0.27% | 0.82% | no | no | OK / OK | automata: reject dense DFA start states that are match states |
| `7b96fdc->468fc64` | `rebar_curated_02_literal_alternate_sherlock_en` | -0.83% | 1.74e-06 | 0.17% | 0.51% | no | no | OK / OK | automata: reject dense DFA start states that are match states |
| `7b96fdc->468fc64` | `rebar_curated_03_date_unicode` | -2.54% | 3.36e-06 | 0.50% | 1.50% | no | no | OK / OK | automata: reject dense DFA start states that are match states |
| `7b96fdc->468fc64` | `rebar_curated_05_lexer_veryl_regexset` | +7.15% | 3.38e-06 | 1.46% | 4.39% | no | no | OK / OK | automata: reject dense DFA start states that are match states |
| `7b96fdc->468fc64` | `rebar_curated_09_aws_keys_quick` | -11.17% | 3.28e-06 | 0.30% | 0.90% | no | no | OK / OK | automata: reject dense DFA start states that are match states |
| `7b96fdc->468fc64` | `rebar_curated_10_bounded_repeat_context` | -0.93% | 2.25e-05 | 0.15% | 0.46% | no | no | OK / OK | automata: reject dense DFA start states that are match states |
| `7b96fdc->468fc64` | `rebar_opt_backtrack_words_en` | +3.40% | 3.27e-06 | 0.28% | 0.84% | no | no | OK / OK | automata: reject dense DFA start states that are match states |
| `7b96fdc->468fc64` | `rebar_opt_reverse_inner_email` | +0.60% | 1.03e-06 | 0.17% | 0.51% | no | no | OK / OK | automata: reject dense DFA start states that are match states |
| `7b96fdc->468fc64` | `rebar_wild_rustsec_cargo_audit_bytes` | -0.75% | 2.34e-06 | 0.21% | 0.65% | no | no | OK / OK | automata: reject dense DFA start states that are match states |
| `468fc64->0858006` | `rebar_curated_01_literal_sherlock_en` | +1.40% | 2.46e-06 | 0.24% | 0.73% | yes | no | OK / OK | docs: add AI policy for contributors |
| `468fc64->0858006` | `rebar_opt_backtrack_words_en` | -0.95% | 5.31e-06 | 0.26% | 0.77% | yes | no | OK / OK | docs: add AI policy for contributors |
| `468fc64->0858006` | `rebar_opt_reverse_inner_email` | -0.60% | 3.69e-07 | 0.08% | 0.23% | yes | no | OK / OK | docs: add AI policy for contributors |
| `0858006->b9d2cf7` | `rebar_curated_01_literal_sherlock_casei_en` | +0.61% | 1.48e-06 | 0.12% | 0.36% | yes | no | ENVIRONMENT_SUSPECT / OK | github: add FUNDING link |
| `0858006->b9d2cf7` | `rebar_curated_01_literal_sherlock_en` | -1.94% | 2.47e-06 | 0.54% | 1.61% | yes | no | ENVIRONMENT_SUSPECT / OK | github: add FUNDING link |
| `0858006->b9d2cf7` | `rebar_curated_02_literal_alternate_sherlock_en` | +0.63% | 1.93e-06 | 0.16% | 0.49% | yes | no | ENVIRONMENT_SUSPECT / OK | github: add FUNDING link |
| `0858006->b9d2cf7` | `rebar_curated_03_date_unicode` | +0.77% | 3.33e-06 | 0.15% | 0.44% | yes | no | ENVIRONMENT_SUSPECT / OK | github: add FUNDING link |
| `0858006->b9d2cf7` | `rebar_curated_09_aws_keys_quick` | -1.73% | 3.27e-06 | 0.42% | 1.25% | yes | no | ENVIRONMENT_SUSPECT / OK | github: add FUNDING link |
| `0858006->b9d2cf7` | `rebar_opt_onepass_first_three_words_en` | +4.86% | 3.32e-06 | 0.21% | 0.64% | yes | no | ENVIRONMENT_SUSPECT / OK | github: add FUNDING link |
| `0858006->b9d2cf7` | `rebar_opt_reverse_inner_email` | +0.60% | 4.64e-07 | 0.14% | 0.41% | yes | no | ENVIRONMENT_SUSPECT / OK | github: add FUNDING link |
| `b9d2cf7->c420333` | `compile_moderate` | +7.91% | 4.14e-06 | 1.76% | 5.28% | yes | no | OK / OK | automata: disable miri on a couple doc tests |
| `b9d2cf7->c420333` | `rebar_curated_01_literal_sherlock_en` | +3.96% | 2.28e-06 | 0.34% | 1.00% | yes | no | OK / OK | automata: disable miri on a couple doc tests |
| `b9d2cf7->c420333` | `rebar_curated_04_ruff_noqa_real` | -9.10% | 4.73e-05 | 2.73% | 8.20% | yes | no | OK / OK | automata: disable miri on a couple doc tests |
| `b9d2cf7->c420333` | `rebar_curated_04_ruff_noqa_tweaked_lite` | -1.32% | 3.33e-06 | 0.41% | 1.23% | yes | no | OK / OK | automata: disable miri on a couple doc tests |
| `b9d2cf7->c420333` | `rebar_curated_05_lexer_veryl_regexset` | +10.06% | 3.35e-06 | 0.62% | 1.85% | yes | no | OK / OK | automata: disable miri on a couple doc tests |
| `b9d2cf7->c420333` | `rebar_curated_09_aws_keys_quick` | +12.66% | 3.26e-06 | 0.25% | 0.74% | yes | no | OK / OK | automata: disable miri on a couple doc tests |
| `b9d2cf7->c420333` | `rebar_opt_backtrack_words_en` | -2.43% | 3.14e-06 | 0.30% | 0.89% | yes | no | OK / OK | automata: disable miri on a couple doc tests |
| `b9d2cf7->c420333` | `rebar_opt_onepass_first_three_words_en` | -2.44% | 3.32e-06 | 0.41% | 1.23% | yes | no | OK / OK | automata: disable miri on a couple doc tests |
| `b9d2cf7->c420333` | `rebar_opt_reverse_inner_email` | -0.60% | 1.97e-07 | 0.08% | 0.23% | yes | no | OK / OK | automata: disable miri on a couple doc tests |
| `c420333->e358341` | `compile_moderate` | -6.78% | 6.15e-06 | 1.43% | 4.29% | no | no | OK / ENVIRONMENT_SUSPECT | api: add `regex!` macro for lazy compilation |
| `c420333->e358341` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +6.07% | 3.36e-06 | 0.57% | 1.71% | no | no | OK / ENVIRONMENT_SUSPECT | api: add `regex!` macro for lazy compilation |
| `c420333->e358341` | `rebar_curated_05_lexer_veryl_regexset` | -2.90% | 4.77e-05 | 0.65% | 1.95% | no | no | OK / ENVIRONMENT_SUSPECT | api: add `regex!` macro for lazy compilation |
| `c420333->e358341` | `rebar_curated_08_words_all_russian` | +0.68% | 3.68e-06 | 0.22% | 0.66% | no | no | OK / ENVIRONMENT_SUSPECT | api: add `regex!` macro for lazy compilation |
| `c420333->e358341` | `rebar_curated_09_aws_keys_quick` | +1.63% | 3.24e-06 | 0.20% | 0.62% | no | no | OK / ENVIRONMENT_SUSPECT | api: add `regex!` macro for lazy compilation |
| `e358341->7d941a9` | `rebar_curated_01_literal_sherlock_casei_en` | -0.60% | 1.99e-06 | 0.13% | 0.40% | yes | no | OK / OK | regex-automata-0.4.15 |
| `e358341->7d941a9` | `rebar_curated_01_literal_sherlock_en` | -5.96% | 2.65e-06 | 0.29% | 0.86% | yes | no | OK / OK | regex-automata-0.4.15 |
| `e358341->7d941a9` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | -12.84% | 4.11e-06 | 1.23% | 3.68% | yes | no | OK / OK | regex-automata-0.4.15 |
| `e358341->7d941a9` | `rebar_curated_02_literal_alternate_sherlock_en` | -1.04% | 9.08e-07 | 0.10% | 0.28% | yes | no | OK / OK | regex-automata-0.4.15 |
| `e358341->7d941a9` | `rebar_curated_05_lexer_veryl_regexset` | -6.42% | 3.39e-06 | 1.11% | 3.34% | yes | no | OK / OK | regex-automata-0.4.15 |
| `e358341->7d941a9` | `rebar_curated_09_aws_keys_quick` | +0.80% | 3.27e-06 | 0.19% | 0.56% | yes | no | OK / OK | regex-automata-0.4.15 |
| `e358341->7d941a9` | `rebar_opt_backtrack_words_en` | +0.90% | 3.27e-06 | 0.20% | 0.59% | yes | no | OK / OK | regex-automata-0.4.15 |
| `7d941a9->926af2e` | `find_iter_userid` | +9.52% | 3.02e-06 | 0.17% | 0.50% | yes | no | OK / OK | 1.13.0 |
| `7d941a9->926af2e` | `rebar_curated_01_literal_sherlock_en` | +6.32% | 2.83e-06 | 0.51% | 1.53% | yes | no | OK / OK | 1.13.0 |
| `7d941a9->926af2e` | `rebar_curated_05_lexer_veryl_regexset` | +7.69% | 3.39e-06 | 0.79% | 2.37% | yes | no | OK / OK | 1.13.0 |
| `7d941a9->926af2e` | `rebar_opt_reverse_inner_email` | -0.30% | 1.10e-03 | 0.08% | 0.23% | yes | no | OK / OK | 1.13.0 |
| `926af2e->677e075` | `find_iter_userid` | -8.03% | 3.25e-06 | 0.58% | 1.76% | yes | no | OK / OK | ignore: whitelist .github directory |
| `926af2e->677e075` | `rebar_curated_02_literal_alternate_sherlock_en` | +0.63% | 4.49e-06 | 0.15% | 0.46% | yes | no | OK / OK | ignore: whitelist .github directory |
| `926af2e->677e075` | `rebar_curated_09_aws_keys_quick` | -0.62% | 4.37e-06 | 0.19% | 0.56% | yes | no | OK / OK | ignore: whitelist .github directory |
| `926af2e->677e075` | `rebar_opt_backtrack_words_en` | -1.12% | 3.95e-06 | 0.32% | 0.96% | yes | no | OK / OK | ignore: whitelist .github directory |
| `926af2e->677e075` | `rebar_opt_onepass_first_three_words_en` | +1.50% | 1.90e-05 | 0.48% | 1.44% | yes | no | OK / OK | ignore: whitelist .github directory |
| `926af2e->677e075` | `rebar_wild_rustsec_cargo_audit_bytes` | -0.75% | 3.43e-05 | 0.17% | 0.50% | yes | no | OK / OK | ignore: whitelist .github directory |
| `677e075->6c44a0f` | `rebar_curated_01_literal_sherlock_en` | -4.34% | 2.43e-06 | 0.29% | 0.86% | no | no | OK / OK | automata: DRY up Thompson configuration |
| `677e075->6c44a0f` | `rebar_curated_04_ruff_noqa_real` | +12.50% | 3.26e-06 | 0.60% | 1.81% | no | no | OK / OK | automata: DRY up Thompson configuration |
| `677e075->6c44a0f` | `rebar_curated_09_aws_keys_quick` | -12.64% | 3.18e-06 | 0.21% | 0.65% | no | no | OK / OK | automata: DRY up Thompson configuration |
| `677e075->6c44a0f` | `rebar_opt_backtrack_words_en` | +2.26% | 3.31e-06 | 0.33% | 0.98% | no | no | OK / OK | automata: DRY up Thompson configuration |
| `677e075->6c44a0f` | `rebar_opt_onepass_first_three_words_en` | +1.93% | 3.17e-06 | 0.39% | 1.17% | no | no | OK / OK | automata: DRY up Thompson configuration |
| `677e075->6c44a0f` | `rebar_opt_reverse_inner_email` | +0.60% | 1.29e-07 | 0.00% | 0.00% | no | no | OK / OK | automata: DRY up Thompson configuration |
| `6c44a0f->f9b0ab1` | `rebar_curated_01_literal_sherlock_casei_en` | -0.60% | 1.34e-06 | 0.14% | 0.43% | no | no | OK / OK | automata: add tests for confirming the regex engine choice |
| `6c44a0f->f9b0ab1` | `rebar_curated_01_literal_sherlock_en` | +2.27% | 2.39e-06 | 0.41% | 1.24% | no | no | OK / OK | automata: add tests for confirming the regex engine choice |
| `6c44a0f->f9b0ab1` | `rebar_curated_02_literal_alternate_sherlock_en` | -0.83% | 1.15e-06 | 0.11% | 0.32% | no | no | OK / OK | automata: add tests for confirming the regex engine choice |
| `6c44a0f->f9b0ab1` | `rebar_curated_04_ruff_noqa_real` | -4.09% | 3.94e-05 | 0.29% | 0.86% | no | no | OK / OK | automata: add tests for confirming the regex engine choice |
| `6c44a0f->f9b0ab1` | `rebar_curated_05_lexer_veryl_regexset` | -1.70% | 3.37e-06 | 0.35% | 1.04% | no | no | OK / OK | automata: add tests for confirming the regex engine choice |
| `6c44a0f->f9b0ab1` | `rebar_curated_09_aws_keys_quick` | +3.01% | 3.07e-06 | 0.33% | 0.98% | no | no | OK / OK | automata: add tests for confirming the regex engine choice |
| `6c44a0f->f9b0ab1` | `rebar_opt_backtrack_words_en` | -1.75% | 4.87e-06 | 0.56% | 1.67% | no | no | OK / OK | automata: add tests for confirming the regex engine choice |
| `6c44a0f->f9b0ab1` | `rebar_opt_reverse_inner_email` | -0.60% | 1.97e-07 | 0.08% | 0.23% | no | no | OK / OK | automata: add tests for confirming the regex engine choice |
| `6c44a0f->f9b0ab1` | `rebar_opt_reverse_suffix_holmes` | -1.00% | 2.33e-06 | 0.30% | 0.91% | no | no | OK / OK | automata: add tests for confirming the regex engine choice |
| `f9b0ab1->e018953` | `rebar_curated_01_literal_sherlock_casei_en` | +0.41% | 1.95e-06 | 0.12% | 0.38% | no | no | OK / OK | automata: fix indentation |
| `f9b0ab1->e018953` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | -7.02% | 3.32e-06 | 0.84% | 2.51% | no | no | OK / OK | automata: fix indentation |
| `f9b0ab1->e018953` | `rebar_curated_02_literal_alternate_sherlock_en` | +0.84% | 1.48e-06 | 0.12% | 0.37% | no | no | OK / OK | automata: fix indentation |
| `f9b0ab1->e018953` | `rebar_curated_10_bounded_repeat_letters_ru` | +3.43% | 1.09e-05 | 0.89% | 2.68% | no | no | OK / OK | automata: fix indentation |
| `f9b0ab1->e018953` | `rebar_opt_backtrack_words_en` | +1.90% | 3.26e-06 | 0.37% | 1.12% | no | no | OK / OK | automata: fix indentation |
| `f9b0ab1->e018953` | `rebar_opt_onepass_first_three_words_en` | -4.08% | 3.31e-06 | 0.47% | 1.39% | no | no | OK / OK | automata: fix indentation |
| `f9b0ab1->e018953` | `rebar_opt_reverse_inner_email` | +0.60% | 4.51e-07 | 0.08% | 0.23% | no | no | OK / OK | automata: fix indentation |
| `f9b0ab1->e018953` | `rebar_opt_reverse_suffix_holmes` | +1.01% | 2.75e-06 | 0.25% | 0.75% | no | no | OK / OK | automata: fix indentation |
| `f9b0ab1->e018953` | `rebar_reported_i988_sql_injection_compile` | +2.95% | 3.39e-06 | 0.67% | 2.00% | no | no | OK / OK | automata: fix indentation |
| `e018953->5524f02` | `find_iter_userid` | -0.56% | 1.59e-04 | 0.11% | 0.34% | yes | no | OK / OK | test: add regression tests for failed reverse suffix/inner optimizations |
| `e018953->5524f02` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +8.11% | 3.32e-06 | 0.99% | 2.96% | yes | no | OK / OK | test: add regression tests for failed reverse suffix/inner optimizations |
| `e018953->5524f02` | `rebar_curated_02_literal_alternate_sherlock_en` | -0.62% | 1.78e-06 | 0.11% | 0.32% | yes | no | OK / OK | test: add regression tests for failed reverse suffix/inner optimizations |
| `e018953->5524f02` | `rebar_curated_03_date_unicode` | -0.97% | 3.33e-06 | 0.24% | 0.71% | yes | no | OK / OK | test: add regression tests for failed reverse suffix/inner optimizations |
| `e018953->5524f02` | `rebar_curated_10_bounded_repeat_letters_ru` | -1.69% | 4.79e-05 | 0.50% | 1.50% | yes | no | OK / OK | test: add regression tests for failed reverse suffix/inner optimizations |
| `e018953->5524f02` | `rebar_opt_reverse_inner_email` | -0.60% | 1.41e-06 | 0.14% | 0.41% | yes | no | OK / OK | test: add regression tests for failed reverse suffix/inner optimizations |
| `5524f02->8c34f41` | `find_iter_userid` | +3.25% | 3.29e-06 | 0.31% | 0.93% | no | no | OK / OK | automata: avoid reverse suffix optimization for non-leftmost-first |
| `5524f02->8c34f41` | `rebar_curated_01_literal_sherlock_en` | +1.94% | 2.87e-06 | 0.36% | 1.07% | no | no | OK / OK | automata: avoid reverse suffix optimization for non-leftmost-first |
| `5524f02->8c34f41` | `rebar_curated_03_date_unicode` | +1.93% | 3.36e-06 | 0.16% | 0.48% | no | no | OK / OK | automata: avoid reverse suffix optimization for non-leftmost-first |
| `5524f02->8c34f41` | `rebar_curated_04_ruff_noqa_real` | -4.88% | 5.61e-05 | 0.37% | 1.10% | no | no | OK / OK | automata: avoid reverse suffix optimization for non-leftmost-first |
| `5524f02->8c34f41` | `rebar_curated_05_lexer_veryl_regexset` | -7.56% | 3.37e-06 | 0.51% | 1.52% | no | no | OK / OK | automata: avoid reverse suffix optimization for non-leftmost-first |
| `5524f02->8c34f41` | `rebar_curated_09_aws_keys_quick` | +10.60% | 2.80e-06 | 0.24% | 0.71% | no | no | OK / OK | automata: avoid reverse suffix optimization for non-leftmost-first |
| `5524f02->8c34f41` | `rebar_opt_backtrack_words_en` | -2.79% | 3.25e-06 | 0.33% | 0.99% | no | no | OK / OK | automata: avoid reverse suffix optimization for non-leftmost-first |
| `5524f02->8c34f41` | `rebar_opt_onepass_first_three_words_en` | +6.76% | 3.32e-06 | 0.37% | 1.12% | no | no | OK / OK | automata: avoid reverse suffix optimization for non-leftmost-first |
| `5524f02->8c34f41` | `rebar_wild_rustsec_cargo_audit_bytes` | +0.76% | 2.17e-06 | 0.17% | 0.53% | no | no | OK / OK | automata: avoid reverse suffix optimization for non-leftmost-first |
| `8c34f41->10afd70` | `find_iter_userid` | -2.18% | 3.25e-06 | 0.62% | 1.85% | no | no | OK / OK | automata: expose the extracted literals for inner literal extraction |
| `8c34f41->10afd70` | `rebar_curated_01_literal_sherlock_en` | -4.63% | 2.82e-06 | 0.24% | 0.72% | no | no | OK / OK | automata: expose the extracted literals for inner literal extraction |
| `8c34f41->10afd70` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +9.05% | 3.28e-06 | 0.90% | 2.71% | no | no | OK / OK | automata: expose the extracted literals for inner literal extraction |
| `8c34f41->10afd70` | `rebar_curated_04_ruff_noqa_real` | +8.70% | 3.23e-06 | 1.74% | 5.21% | no | no | OK / OK | automata: expose the extracted literals for inner literal extraction |
| `8c34f41->10afd70` | `rebar_curated_05_lexer_veryl_regexset` | +8.53% | 3.37e-06 | 0.25% | 0.74% | no | no | OK / OK | automata: expose the extracted literals for inner literal extraction |
| `8c34f41->10afd70` | `rebar_curated_05_lexer_veryl_single` | +0.65% | 5.16e-05 | 0.17% | 0.52% | no | no | OK / OK | automata: expose the extracted literals for inner literal extraction |
| `8c34f41->10afd70` | `rebar_curated_09_aws_keys_quick` | -11.05% | 3.21e-06 | 0.29% | 0.86% | no | no | OK / OK | automata: expose the extracted literals for inner literal extraction |
| `8c34f41->10afd70` | `rebar_opt_backtrack_words_en` | +1.67% | 3.31e-06 | 0.32% | 0.95% | no | no | OK / OK | automata: expose the extracted literals for inner literal extraction |
| `8c34f41->10afd70` | `rebar_opt_onepass_first_three_words_en` | -5.53% | 3.27e-06 | 0.32% | 0.96% | no | no | OK / OK | automata: expose the extracted literals for inner literal extraction |
| `8c34f41->10afd70` | `rebar_opt_reverse_suffix_holmes` | +1.33% | 2.07e-06 | 0.21% | 0.64% | no | no | OK / OK | automata: expose the extracted literals for inner literal extraction |
| `8c34f41->10afd70` | `rebar_wild_rustsec_cargo_audit_bytes` | -0.94% | 8.86e-06 | 0.18% | 0.53% | no | no | OK / OK | automata: expose the extracted literals for inner literal extraction |
| `10afd70->821a8eb` | `find_iter_userid` | -1.27% | 3.14e-06 | 0.20% | 0.61% | no | no | ENVIRONMENT_SUSPECT / OK | automata: refactor reverse suffix/inner search slightly |
| `10afd70->821a8eb` | `rebar_curated_01_literal_sherlock_en` | +4.01% | 2.85e-06 | 0.35% | 1.06% | no | no | ENVIRONMENT_SUSPECT / OK | automata: refactor reverse suffix/inner search slightly |
| `10afd70->821a8eb` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | -12.85% | 3.32e-06 | 0.47% | 1.40% | no | no | ENVIRONMENT_SUSPECT / OK | automata: refactor reverse suffix/inner search slightly |
| `10afd70->821a8eb` | `rebar_curated_04_ruff_noqa_real` | -9.64% | 3.22e-06 | 0.59% | 1.78% | no | no | ENVIRONMENT_SUSPECT / OK | automata: refactor reverse suffix/inner search slightly |
| `10afd70->821a8eb` | `rebar_curated_09_aws_keys_quick` | +15.56% | 3.18e-06 | 0.30% | 0.91% | no | no | ENVIRONMENT_SUSPECT / OK | automata: refactor reverse suffix/inner search slightly |
| `10afd70->821a8eb` | `rebar_curated_10_bounded_repeat_letters_ru` | -2.83% | 1.09e-05 | 0.82% | 2.46% | no | no | ENVIRONMENT_SUSPECT / OK | automata: refactor reverse suffix/inner search slightly |
| `10afd70->821a8eb` | `rebar_opt_reverse_suffix_holmes` | -0.99% | 6.45e-06 | 0.23% | 0.70% | no | no | ENVIRONMENT_SUSPECT / OK | automata: refactor reverse suffix/inner search slightly |
| `821a8eb->30390ec` | `compile_moderate` | +11.51% | 2.33e-05 | 3.06% | 9.18% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `find_iter_userid` | +2.01% | 3.26e-06 | 0.29% | 0.87% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_01_literal_sherlock_en` | -1.93% | 5.31e-05 | 0.39% | 1.16% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +17.76% | 3.37e-06 | 0.77% | 2.30% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_04_ruff_noqa_real` | +20.39% | 3.33e-06 | 3.20% | 9.59% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_04_ruff_noqa_tweaked_lite` | +12.20% | 5.52e-06 | 0.31% | 0.92% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_05_lexer_veryl_regexset` | +5.09% | 1.76e-05 | 0.47% | 1.40% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_05_lexer_veryl_single` | +9.85% | 3.38e-06 | 0.48% | 1.45% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_06_cloudflare_redos_long` | +0.16% | 7.88e-06 | 0.00% | 0.00% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_08_words_all_russian` | +0.56% | 5.42e-03 | 0.16% | 0.49% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_09_aws_keys_quick` | -11.18% | 5.49e-05 | 0.16% | 0.47% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_10_bounded_repeat_context` | +9.48% | 2.12e-05 | 1.28% | 3.83% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_10_bounded_repeat_letters_ru` | +13.43% | 3.38e-06 | 1.09% | 3.27% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_curated_12_dictionary_single` | +1.74% | 5.60e-06 | 0.08% | 0.24% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_opt_onepass_first_three_words_en` | +4.72% | 3.96e-05 | 1.53% | 4.59% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_opt_reverse_inner_email` | +10.00% | 2.44e-03 | 0.29% | 0.88% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_opt_reverse_suffix_holmes` | +1.33% | 1.75e-06 | 0.31% | 0.94% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_reported_i988_sql_injection_compile` | +15.61% | 7.48e-06 | 1.43% | 4.29% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_unicode_compile_one_letter` | +21.35% | 3.39e-06 | 4.19% | 12.56% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `821a8eb->30390ec` | `rebar_wild_rustsec_cargo_audit_bytes` | +12.71% | 7.54e-06 | 0.20% | 0.59% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: formatting tweaks |
| `30390ec->fa91c31` | `rebar_opt_reverse_suffix_holmes` | -0.98% | 2.81e-04 | 0.21% | 0.63% | no | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: fix a bug caught by Codex review |
| `fa91c31->64ad0b6` | `rebar_curated_01_literal_sherlock_casei_en` | +0.61% | 1.26e-06 | 0.12% | 0.36% | no | no | OK / ENVIRONMENT_SUSPECT | automata: fix bug in reverse suffix/inner optimization |
| `fa91c31->64ad0b6` | `rebar_curated_02_literal_alternate_sherlock_en` | +0.53% | 5.06e-06 | 0.13% | 0.39% | no | no | OK / ENVIRONMENT_SUSPECT | automata: fix bug in reverse suffix/inner optimization |
| `fa91c31->64ad0b6` | `rebar_curated_05_lexer_veryl_regexset` | -11.36% | 3.39e-06 | 2.23% | 6.70% | no | no | OK / ENVIRONMENT_SUSPECT | automata: fix bug in reverse suffix/inner optimization |
| `fa91c31->64ad0b6` | `rebar_curated_06_cloudflare_redos_long` | +94.38% | 1.86e-07 | 0.06% | 0.17% | no | no | OK / ENVIRONMENT_SUSPECT | automata: fix bug in reverse suffix/inner optimization |
| `fa91c31->64ad0b6` | `rebar_curated_10_bounded_repeat_context` | -4.50% | 3.22e-06 | 1.45% | 4.35% | no | no | OK / ENVIRONMENT_SUSPECT | automata: fix bug in reverse suffix/inner optimization |
| `fa91c31->64ad0b6` | `rebar_unicode_compile_one_letter` | -12.32% | 3.39e-06 | 3.75% | 11.24% | no | no | OK / ENVIRONMENT_SUSPECT | automata: fix bug in reverse suffix/inner optimization |
| `64ad0b6->75fcb96` | `find_iter_userid` | -0.88% | 6.98e-05 | 0.25% | 0.74% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.13.1 |
| `64ad0b6->75fcb96` | `rebar_curated_04_ruff_noqa_real` | +6.54% | 3.35e-06 | 1.20% | 3.59% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.13.1 |
| `64ad0b6->75fcb96` | `rebar_curated_05_lexer_veryl_regexset` | +8.62% | 3.39e-06 | 0.46% | 1.39% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.13.1 |
| `64ad0b6->75fcb96` | `rebar_curated_09_aws_keys_quick` | -9.11% | 5.52e-05 | 0.26% | 0.78% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.13.1 |
| `64ad0b6->75fcb96` | `rebar_curated_10_bounded_repeat_context` | +0.34% | 5.43e-05 | 0.10% | 0.30% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.13.1 |
| `64ad0b6->75fcb96` | `rebar_curated_10_bounded_repeat_letters_ru` | -1.98% | 8.33e-04 | 0.39% | 1.17% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.13.1 |
| `64ad0b6->75fcb96` | `rebar_opt_backtrack_words_en` | +4.24% | 2.77e-03 | 0.32% | 0.96% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.13.1 |
| `64ad0b6->75fcb96` | `rebar_opt_reverse_inner_email` | +0.30% | 2.24e-03 | 0.08% | 0.23% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.13.1 |
| `64ad0b6->75fcb96` | `rebar_opt_reverse_suffix_holmes` | -1.63% | 6.42e-05 | 0.31% | 0.94% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.13.1 |
| `64ad0b6->75fcb96` | `rebar_reported_i988_sql_injection_compile` | +5.49% | 7.46e-06 | 0.61% | 1.83% | yes | no | ENVIRONMENT_SUSPECT / OK | changelog: 1.13.1 |
| `75fcb96->40e9823` | `compile_moderate` | +10.33% | 1.10e-05 | 2.97% | 8.91% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | 1.13.1 |
| `75fcb96->40e9823` | `find_iter_userid` | +69.61% | 3.20e-06 | 0.78% | 2.34% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | 1.13.1 |
| `75fcb96->40e9823` | `rebar_curated_01_literal_sherlock_casei_en` | +13.91% | 2.17e-04 | 1.20% | 3.61% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | 1.13.1 |
| `75fcb96->40e9823` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +25.75% | 7.42e-06 | 0.88% | 2.65% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | 1.13.1 |
| `75fcb96->40e9823` | `rebar_curated_02_literal_alternate_sherlock_en` | +11.71% | 2.07e-05 | 0.21% | 0.62% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | 1.13.1 |
| `75fcb96->40e9823` | `rebar_curated_03_date_unicode` | +1.35% | 1.04e-04 | 0.20% | 0.58% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | 1.13.1 |
| `75fcb96->40e9823` | `rebar_curated_04_ruff_noqa_tweaked_lite` | +3.62% | 1.32e-05 | 1.00% | 3.00% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | 1.13.1 |
| `75fcb96->40e9823` | `rebar_curated_05_lexer_veryl_regexset` | -5.75% | 3.39e-06 | 0.46% | 1.38% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | 1.13.1 |
| `40e9823->2b52759` | `find_iter_userid` | -41.27% | 3.27e-06 | 11.91% | 35.73% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.13.1, redux |
| `40e9823->2b52759` | `rebar_curated_05_lexer_veryl_regexset` | -2.02% | 3.38e-06 | 0.60% | 1.79% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.13.1, redux |
| `40e9823->2b52759` | `rebar_opt_onepass_first_three_words_en` | -4.42% | 3.32e-06 | 0.28% | 0.83% | yes | no | OK / ENVIRONMENT_SUSPECT | 1.13.1, redux |
| `2b52759->c21ed55` | `rebar_curated_01_literal_sherlock_casei_en` | -0.60% | 1.01e-06 | 0.10% | 0.28% | no | no | OK / ENVIRONMENT_SUSPECT | automata: make MAX_POOL_STACKS user configurable |
| `2b52759->c21ed55` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +8.73% | 1.43e-05 | 2.83% | 8.48% | no | no | OK / ENVIRONMENT_SUSPECT | automata: make MAX_POOL_STACKS user configurable |
| `2b52759->c21ed55` | `rebar_curated_02_literal_alternate_sherlock_en` | -0.83% | 2.02e-06 | 0.16% | 0.47% | no | no | OK / ENVIRONMENT_SUSPECT | automata: make MAX_POOL_STACKS user configurable |
| `2b52759->c21ed55` | `rebar_curated_04_ruff_noqa_tweaked_lite` | +2.21% | 4.11e-06 | 0.64% | 1.91% | no | no | OK / ENVIRONMENT_SUSPECT | automata: make MAX_POOL_STACKS user configurable |
| `2b52759->c21ed55` | `rebar_curated_05_lexer_veryl_regexset` | +7.15% | 3.38e-06 | 0.52% | 1.57% | no | no | OK / ENVIRONMENT_SUSPECT | automata: make MAX_POOL_STACKS user configurable |
| `2b52759->c21ed55` | `rebar_curated_09_aws_keys_quick` | +2.10% | 3.20e-06 | 0.22% | 0.67% | no | no | OK / ENVIRONMENT_SUSPECT | automata: make MAX_POOL_STACKS user configurable |
| `2b52759->c21ed55` | `rebar_opt_backtrack_words_en` | -3.14% | 5.68e-05 | 0.53% | 1.59% | no | no | OK / ENVIRONMENT_SUSPECT | automata: make MAX_POOL_STACKS user configurable |
| `c21ed55->3af3e27` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +7.43% | 3.33e-06 | 0.53% | 1.59% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | regex-automata-0.4.17 |
| `c21ed55->3af3e27` | `rebar_curated_09_aws_keys_quick` | +3.23% | 3.20e-06 | 0.21% | 0.62% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | regex-automata-0.4.17 |
| `c21ed55->3af3e27` | `rebar_curated_10_bounded_repeat_context` | +0.46% | 9.38e-03 | 0.13% | 0.39% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | regex-automata-0.4.17 |
| `c21ed55->3af3e27` | `rebar_curated_10_bounded_repeat_letters_ru` | +3.68% | 3.30e-06 | 0.85% | 2.54% | yes | no | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | regex-automata-0.4.17 |
| `3af3e27->92e0f22` | `rebar_curated_01_literal_sherlock_en` | -3.59% | 2.45e-06 | 0.27% | 0.82% | no | no | OK / OK | automata: avoid re-computing `available_parallelism` |
| `3af3e27->92e0f22` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | -12.54% | 3.34e-06 | 0.48% | 1.45% | no | no | OK / OK | automata: avoid re-computing `available_parallelism` |
| `3af3e27->92e0f22` | `rebar_curated_04_ruff_noqa_real` | +9.14% | 3.32e-06 | 0.41% | 1.23% | no | no | OK / OK | automata: avoid re-computing `available_parallelism` |
| `3af3e27->92e0f22` | `rebar_curated_05_lexer_veryl_regexset` | -3.28% | 3.38e-06 | 0.58% | 1.74% | no | no | OK / OK | automata: avoid re-computing `available_parallelism` |
| `3af3e27->92e0f22` | `rebar_curated_09_aws_keys_quick` | -13.09% | 3.09e-06 | 0.21% | 0.62% | no | no | OK / OK | automata: avoid re-computing `available_parallelism` |
| `3af3e27->92e0f22` | `rebar_curated_10_bounded_repeat_letters_ru` | -2.40% | 6.64e-04 | 0.28% | 0.84% | no | no | OK / OK | automata: avoid re-computing `available_parallelism` |
| `3af3e27->92e0f22` | `rebar_opt_backtrack_words_en` | +1.45% | 3.32e-06 | 0.28% | 0.83% | no | no | OK / OK | automata: avoid re-computing `available_parallelism` |
| `3af3e27->92e0f22` | `rebar_opt_onepass_first_three_words_en` | +5.14% | 3.27e-06 | 0.87% | 2.61% | no | no | OK / OK | automata: avoid re-computing `available_parallelism` |
| `3af3e27->92e0f22` | `rebar_opt_reverse_inner_email` | +0.60% | 1.86e-07 | 0.11% | 0.32% | no | no | OK / OK | automata: avoid re-computing `available_parallelism` |
| `3af3e27->92e0f22` | `rebar_wild_rustsec_cargo_audit_bytes` | -0.76% | 6.17e-06 | 0.24% | 0.73% | no | no | OK / OK | automata: avoid re-computing `available_parallelism` |
| `92e0f22->e6ad938` | `rebar_curated_01_literal_sherlock_casei_en` | +0.81% | 1.71e-06 | 0.10% | 0.31% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.18 |
| `92e0f22->e6ad938` | `rebar_curated_01_literal_sherlock_en` | +2.01% | 2.59e-06 | 0.30% | 0.89% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.18 |
| `92e0f22->e6ad938` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +5.04% | 3.35e-06 | 1.04% | 3.11% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.18 |
| `92e0f22->e6ad938` | `rebar_curated_02_literal_alternate_sherlock_en` | +0.84% | 2.10e-06 | 0.17% | 0.53% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.18 |
| `92e0f22->e6ad938` | `rebar_curated_08_words_all_russian` | -0.72% | 3.34e-06 | 0.22% | 0.66% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.18 |
| `92e0f22->e6ad938` | `rebar_curated_09_aws_keys_quick` | -0.82% | 6.95e-04 | 0.27% | 0.80% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.18 |
| `92e0f22->e6ad938` | `rebar_opt_backtrack_words_en` | +1.58% | 1.19e-05 | 0.45% | 1.35% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.18 |
| `92e0f22->e6ad938` | `rebar_opt_reverse_inner_email` | -0.60% | 8.27e-08 | 0.00% | 0.00% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.18 |
| `92e0f22->e6ad938` | `rebar_opt_reverse_suffix_holmes` | +1.67% | 1.78e-06 | 0.16% | 0.49% | yes | no | ENVIRONMENT_SUSPECT / OK | regex-automata-0.4.18 |
| `e6ad938->782152f` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +8.41% | 3.33e-06 | 1.18% | 3.55% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: fix glob typo in `workspace.package.include` setting |
| `e6ad938->782152f` | `rebar_curated_03_date_unicode` | +59.10% | 4.94e-04 | 12.38% | 37.15% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: fix glob typo in `workspace.package.include` setting |
| `e6ad938->782152f` | `rebar_curated_05_lexer_veryl_regexset` | +6.38% | 3.37e-06 | 0.54% | 1.62% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: fix glob typo in `workspace.package.include` setting |
| `e6ad938->782152f` | `rebar_curated_06_cloudflare_redos_long` | +1.04% | 8.78e-07 | 0.04% | 0.14% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: fix glob typo in `workspace.package.include` setting |
| `e6ad938->782152f` | `rebar_curated_09_aws_keys_quick` | +9.90% | 3.28e-06 | 2.30% | 6.91% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: fix glob typo in `workspace.package.include` setting |
| `e6ad938->782152f` | `rebar_opt_reverse_inner_email` | +0.60% | 2.52e-07 | 0.00% | 0.00% | yes | no | OK / ENVIRONMENT_SUSPECT | cargo: fix glob typo in `workspace.package.include` setting |
| `782152f->ada2a5a` | `rebar_curated_05_lexer_veryl_regexset` | -7.81% | 3.37e-06 | 0.69% | 2.06% | yes | no | OK / OK | changelog: update to include #1333 |
| `782152f->ada2a5a` | `rebar_curated_06_cloudflare_redos_long` | -1.03% | 4.73e-04 | 0.05% | 0.15% | yes | no | OK / OK | changelog: update to include #1333 |
| `782152f->ada2a5a` | `rebar_curated_09_aws_keys_quick` | +2.63% | 3.33e-06 | 0.47% | 1.41% | yes | no | OK / OK | changelog: update to include #1333 |
| `782152f->ada2a5a` | `rebar_wild_rustsec_cargo_audit_bytes` | +1.53% | 2.43e-06 | 0.14% | 0.42% | yes | no | OK / OK | changelog: update to include #1333 |
| `ada2a5a->72d650c` | `rebar_curated_05_lexer_veryl_regexset` | +7.81% | 3.38e-06 | 0.55% | 1.64% | no | yes | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: replace uses of deprecated module integer constants |
| `ada2a5a->72d650c` | `rebar_reported_i988_sql_injection_compile` | +3.79% | 3.08e-04 | 1.09% | 3.26% | no | yes | ENVIRONMENT_SUSPECT / ENVIRONMENT_SUSPECT | automata: replace uses of deprecated module integer constants |
| `72d650c->d1d557d` | `find_iter_userid` | -0.72% | 6.44e-05 | 0.21% | 0.64% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_curated_01_literal_sherlock_casei_en` | +0.61% | 1.88e-06 | 0.11% | 0.33% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_curated_01_literal_sherlock_en` | +14.37% | 1.18e-06 | 0.71% | 2.12% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | -8.23% | 3.31e-06 | 0.62% | 1.85% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_curated_02_literal_alternate_sherlock_en` | +0.42% | 2.10e-05 | 0.12% | 0.35% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_curated_04_ruff_noqa_real` | +10.83% | 3.30e-06 | 0.53% | 1.59% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_curated_05_lexer_veryl_regexset` | +3.20% | 3.36e-06 | 0.37% | 1.11% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_curated_06_cloudflare_redos_long` | -0.48% | 1.33e-05 | 0.06% | 0.18% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_curated_09_aws_keys_quick` | -10.16% | 3.23e-06 | 0.19% | 0.58% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_curated_10_bounded_repeat_letters_ru` | +3.52% | 3.35e-06 | 0.54% | 1.61% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_opt_onepass_first_three_words_en` | +5.08% | 3.64e-06 | 1.53% | 4.59% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_opt_reverse_inner_email` | +10.21% | 2.79e-07 | 0.11% | 0.34% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_opt_reverse_suffix_holmes` | +6.02% | 1.93e-06 | 0.33% | 0.98% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `72d650c->d1d557d` | `rebar_wild_rustsec_cargo_audit_bytes` | +4.19% | 2.51e-06 | 0.32% | 0.95% | yes | no | OK / ENVIRONMENT_SUSPECT | tests: s/std::usize::MAX/usize::MAX |
| `d1d557d->a1e367b` | `rebar_curated_01_literal_sherlock_en` | -13.29% | 1.17e-06 | 0.09% | 0.27% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +8.36% | 3.31e-06 | 1.09% | 3.28% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_curated_04_ruff_noqa_real` | -9.63% | 3.28e-06 | 0.24% | 0.72% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_curated_05_lexer_veryl_regexset` | -3.83% | 3.32e-06 | 0.48% | 1.44% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_curated_09_aws_keys_quick` | +14.66% | 3.32e-06 | 0.28% | 0.84% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_curated_10_bounded_repeat_letters_ru` | -2.39% | 7.75e-04 | 0.22% | 0.67% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_curated_12_dictionary_single` | +0.20% | 5.88e-06 | 0.06% | 0.19% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_opt_backtrack_words_en` | -1.17% | 5.60e-05 | 0.38% | 1.14% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_opt_onepass_first_three_words_en` | -4.81% | 3.21e-06 | 0.23% | 0.69% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_opt_reverse_inner_email` | -9.26% | 4.67e-07 | 0.21% | 0.63% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_opt_reverse_suffix_holmes` | -4.73% | 1.68e-06 | 0.28% | 0.85% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_reported_i988_sql_injection_compile` | +5.47% | 1.33e-05 | 1.34% | 4.02% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_unicode_compile_one_letter` | +8.52% | 8.13e-05 | 2.65% | 7.95% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `d1d557d->a1e367b` | `rebar_wild_rustsec_cargo_audit_bytes` | -3.66% | 3.00e-06 | 0.59% | 1.78% | no | no | ENVIRONMENT_SUSPECT / OK | automata/dfa/onepass: fix a bug when `WhichCaptures::None` is used |
| `80b9d14->ad23cc2` | `rebar_curated_06_cloudflare_redos_long` | -0.95% | 5.07e-07 | 0.06% | 0.19% | no | no | OK / ENVIRONMENT_SUSPECT | meta: fix off-by-one error |
| `80b9d14->ad23cc2` | `rebar_curated_08_words_all_russian` | -1.06% | 3.29e-06 | 0.16% | 0.47% | no | no | OK / ENVIRONMENT_SUSPECT | meta: fix off-by-one error |
| `80b9d14->ad23cc2` | `rebar_curated_10_bounded_repeat_letters_ru` | +3.19% | 3.30e-06 | 0.34% | 1.03% | no | no | OK / ENVIRONMENT_SUSPECT | meta: fix off-by-one error |
| `ad23cc2->94ac45b` | `find_iter_userid` | +2.83% | 3.19e-06 | 0.23% | 0.69% | no | no | OK / ENVIRONMENT_SUSPECT | automata: revert default pool capacity change |
| `ad23cc2->94ac45b` | `rebar_curated_01_literal_sherlock_en` | -1.68% | 4.95e-06 | 0.50% | 1.51% | no | no | OK / ENVIRONMENT_SUSPECT | automata: revert default pool capacity change |
| `ad23cc2->94ac45b` | `rebar_curated_04_ruff_noqa_real` | +8.64% | 3.29e-06 | 0.45% | 1.34% | no | no | OK / ENVIRONMENT_SUSPECT | automata: revert default pool capacity change |
| `ad23cc2->94ac45b` | `rebar_curated_05_lexer_veryl_regexset` | +2.54% | 3.37e-06 | 0.51% | 1.53% | no | no | OK / ENVIRONMENT_SUSPECT | automata: revert default pool capacity change |
| `ad23cc2->94ac45b` | `rebar_curated_09_aws_keys_quick` | -12.31% | 3.30e-06 | 0.33% | 0.99% | no | no | OK / ENVIRONMENT_SUSPECT | automata: revert default pool capacity change |
| `ad23cc2->94ac45b` | `rebar_curated_10_bounded_repeat_context` | -0.86% | 3.29e-06 | 0.16% | 0.49% | no | no | OK / ENVIRONMENT_SUSPECT | automata: revert default pool capacity change |
| `ad23cc2->94ac45b` | `rebar_curated_10_bounded_repeat_letters_ru` | -3.57% | 3.27e-06 | 0.23% | 0.69% | no | no | OK / ENVIRONMENT_SUSPECT | automata: revert default pool capacity change |
| `94ac45b->3d79fe9` | `rebar_curated_01_literal_sherlock_en` | +4.00% | 3.09e-06 | 0.69% | 2.07% | no | no | OK / ENVIRONMENT_SUSPECT | syntax: don't lift alternation prefixes that can match more than one way |
| `94ac45b->3d79fe9` | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | +8.73% | 3.30e-06 | 0.90% | 2.71% | no | no | OK / ENVIRONMENT_SUSPECT | syntax: don't lift alternation prefixes that can match more than one way |
| `94ac45b->3d79fe9` | `rebar_curated_04_ruff_noqa_real` | -8.16% | 3.31e-06 | 0.68% | 2.04% | no | no | OK / ENVIRONMENT_SUSPECT | syntax: don't lift alternation prefixes that can match more than one way |
| `94ac45b->3d79fe9` | `rebar_curated_05_lexer_veryl_regexset` | -9.28% | 3.38e-06 | 0.40% | 1.21% | no | no | OK / ENVIRONMENT_SUSPECT | syntax: don't lift alternation prefixes that can match more than one way |
| `94ac45b->3d79fe9` | `rebar_curated_06_cloudflare_redos_long` | +1.36% | 2.19e-06 | 0.04% | 0.12% | no | no | OK / ENVIRONMENT_SUSPECT | syntax: don't lift alternation prefixes that can match more than one way |
| `94ac45b->3d79fe9` | `rebar_curated_09_aws_keys_quick` | +10.98% | 3.32e-06 | 0.38% | 1.14% | no | no | OK / ENVIRONMENT_SUSPECT | syntax: don't lift alternation prefixes that can match more than one way |
| `94ac45b->3d79fe9` | `rebar_curated_10_bounded_repeat_context` | +1.08% | 3.27e-06 | 0.08% | 0.25% | no | no | OK / ENVIRONMENT_SUSPECT | syntax: don't lift alternation prefixes that can match more than one way |
| `94ac45b->3d79fe9` | `rebar_curated_10_bounded_repeat_letters_ru` | +0.96% | 6.08e-06 | 0.26% | 0.78% | no | no | OK / ENVIRONMENT_SUSPECT | syntax: don't lift alternation prefixes that can match more than one way |
| `94ac45b->3d79fe9` | `rebar_opt_onepass_first_three_words_en` | -2.50% | 3.26e-06 | 0.23% | 0.68% | no | no | OK / ENVIRONMENT_SUSPECT | syntax: don't lift alternation prefixes that can match more than one way |
