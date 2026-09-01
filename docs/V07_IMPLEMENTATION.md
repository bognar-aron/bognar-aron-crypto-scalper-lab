# v0.7 Benchmark + Data Layer

## What is implemented now

v0.7 is the first step from a single-purpose candle backtester toward a modular research system.

### Event model

`scalper_lab_v07/events.py` defines normalized research events:

- `BarEvent`
- `TradeEvent`
- `QuoteEvent`
- `BookSnapshotEvent`
- `BookDeltaEvent`

Every event carries exchange, symbol and UTC event time. The model already separates exchange event time from optional receive time and supports optional sequence numbers so later WebSocket/order-book feeds can be checked for gaps.

### Strategy API

`scalper_lab_v07/strategy.py` provides a deliberately small strategy interface inspired by the clean research workflow of frameworks such as Jesse, without taking code from them.

Strategies emit normalized `Signal` objects. They do not know about Binance, CCXT, Colab, order placement or account credentials.

### Data layer

`scalper_lab_v07/data.py` currently provides:

- pandas OHLCV -> normalized `BarEvent` conversion,
- monotonic timestamp / sequence validation,
- partitioned Parquet event storage,
- a thin optional CCXT REST adapter for OHLCV.

The Parquet partition scheme is intended for the Drive-backed research phase. A database should only be introduced once Parquet becomes an actual bottleneck.

### Fixed benchmark strategies

The first controls are intentionally simple and interpretable:

1. EMA trend crossover
2. Donchian + volume breakout
3. VWAP mean reversion

These are **benchmarks, not promoted trading strategies**. Their job is to answer whether a custom strategy is adding value over simple, well-understood rules.

### Walk-forward benchmark gate

`benchmark_lab_v07.py` does not use one full-period backtest to pick a winner. Each fixed benchmark is evaluated on the same three validation windows used by the research protocol.

A benchmark is only marked eligible if it simultaneously has:

- positive expectancy in >= 2/3 validation folds,
- >= 10 trades in every validation fold,
- >= 50 validation trades total,
- median validation expectancy > 0 R,
- worst-fold expectancy >= -0.20 R,
- worst validation drawdown < 8%.

The script refuses an `--end` date at or beyond `2026-08-01`. The sealed holdout therefore cannot be loaded accidentally by the v0.7 benchmark runner.

## Reuse of the existing execution engine

v0.7 deliberately calls the existing `backtester.py` portfolio/risk/cost engine. This makes the first benchmark comparison apples-to-apples with v0.6:

- same fee model,
- same slippage model,
- same position sizing,
- same one-position portfolio restriction,
- same rolling risk limits,
- same conservative intrabar handling.

A later event-driven execution simulator can replace this adapter only after it is regression-tested against the current engine.

## What is intentionally not implemented yet

The following belong to the next microstructure phase, not this PR:

- live Cryptofeed connection,
- L2/L3 book reconstruction,
- snapshot/delta recovery,
- exchange WebSocket reconnect logic,
- maker queue position,
- partial fills,
- order latency,
- live/paper account execution,
- API key handling.

This separation is deliberate. First establish a tested normalized event contract and benchmark discipline, then attach live feeds.

## Local test status

Before publishing this branch the v0.7 core test suite passed locally:

`5 passed`

GitHub CI is included at `.github/workflows/v07-ci.yml`.

## Colab

Use:

`notebooks/CRYPTO_SCALPER_LAB_v07_COLAB.ipynb`

The notebook clones the `v0.7-benchmark-data-layer` branch, reuses the existing Drive `data/` cache and writes a timestamped `v07_BENCHMARK_*` folder into Drive `runs/`.

Expected outputs:

- `benchmark_walk_forward.csv`
- `benchmark_leaderboard.csv`
- `benchmark_gate.json`
