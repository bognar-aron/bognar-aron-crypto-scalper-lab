# v0.8.1 Microstructure Validation Protocol

## Why this exists

The v0.8 Jan-Mar 2026 pilot found a small but consistent relationship between the frozen 5-second taker imbalance feature and subsequent 1s/5s/30s returns across SOLUSDC, BTCUSDC and ETHUSDC.

v0.8.1 is **not** a strategy-optimization release. Its purpose is to attempt to falsify that signal on a later, fixed temporal validation window.

## Frozen before validation

- Feature: `taker_imbalance_5s`
- Strong-flow threshold: `abs(feature) >= 0.60`
- Symbols: SOLUSDC, BTCUSDC, ETHUSDC
- Development reference: `[2026-01-01, 2026-04-01)`
- Validation: `[2026-04-01, 2026-08-01)`
- Sealed historical holdout: `2026-08-01+`, still locked
- Horizons: 1s, 5s, 30s
- Primary proof horizons: 1s and 5s
- 30s is diagnostic because v0.8 already showed rapid signal decay

The validation results may not be used to move the 0.60 threshold or replace the feature definition.

## Dependency control

Forward-return windows overlap strongly at second-level frequency. v0.8.1 therefore evaluates each horizon on deterministic non-overlapping samples before filtering active seconds.

Confidence intervals use block-level bootstrap resampling. The default block duration is 300 seconds and the default bootstrap count is 300.

## Per symbol-month cell diagnostics

For each of the 12 validation cells (3 symbols x 4 months), v0.8.1 records:

- rank correlation between frozen taker imbalance and forward return
- aligned mean and median forward return after strong flow
- strict-positive hit rate and zero-return rate
- 95% block-bootstrap CI for aligned mean
- p90 / p95 / p99 aligned return
- probability of aligned move above 1 / 2 / 5 bps
- five rank-quantile return buckets
- top-minus-bottom quantile spread
- quantile monotonicity diagnostic

## Predeclared information gate

At least 10 validation symbol-month cells must exist.

For each primary horizon, all of the following must hold:

- median rank correlation > 0
- positive rank correlation in at least 75% of cells
- median aligned mean > 0 bps
- positive aligned mean in at least 75% of cells
- bootstrap lower confidence bound > 0 in at least 50% of cells
- positive top-minus-bottom quantile spread in at least 67% of cells

`information_pass = PASS` only if both the 1-second and 5-second horizons pass.

## Execution economics

The same gross signal is evaluated under fixed round-trip hurdles:

- conservative taker: 24 bps
- fee-only taker: 20 bps
- low-cost taker: 12 bps
- maker-like research hurdle: 4 bps
- frictionless upper bound: 0 bps

The 4 bps maker-like hurdle is deliberately optimistic and **does not represent a promised executable fee/fill model**.

`execution_pass = PASS` only if the maker-like 4 bps scenario has positive median net aligned return and at least 75% of the 1s/5s validation cells are net positive.

`overall_live_candidate_pass` requires both information and execution PASS.

## Outputs

- `validation_protocol.json` is written before loading validation data
- `validation_manifest.csv`
- `validation_cells.csv`
- `validation_quantiles.csv`
- `validation_summary.csv`
- `execution_economics.csv`
- `validation_gate.json`

No result from this stage authorizes live trading. A surviving information signal still needs prospective L2 data, a realistic fill/queue/latency model, and paper/shadow execution.
