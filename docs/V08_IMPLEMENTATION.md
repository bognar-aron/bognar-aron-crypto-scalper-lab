# v0.8 Market Microstructure Lab

## Objective

v0.7 showed that three simple 5-minute OHLCV benchmark families all failed the same walk-forward gate. v0.8 therefore moves below candle level and tests whether short-horizon market microstructure contains measurable information before building another trading strategy.

## Phase 1 implemented

### Historical trade-flow lane

Source: Binance Spot monthly `aggTrades` archives.

The loader:
- understands Binance millisecond and post-2025 microsecond timestamps,
- derives taker side from `buyer_is_maker`,
- preserves raw quote notional and signed quote flow,
- refuses historical research data at or after `2026-08-01`,
- processes one month at a time to bound memory usage.

Each month is aggregated to deterministic 1-second features:
- trade count,
- base and quote volume,
- taker buy / sell quote volume,
- signed quote flow,
- 1s taker imbalance,
- rolling 5s / 30s taker imbalance,
- last price, VWAP and 1-second return.

The first diagnostic is intentionally pre-strategy. It asks whether 5-second taker imbalance has monotonic relationship with 1s / 5s / 30s forward returns, using fixed imbalance buckets and rank correlation. No parameter search is performed.

### Prospective live L2 lane

Source: Cryptofeed public Binance Spot WebSocket feeds.

The recorder subscribes to:
- `TRADES`
- `L2_BOOK`

and normalizes the feed into the project's own event contract. It writes:
- `trades.jsonl`
- `microstructure.jsonl`
- `capture_manifest.json`

The current snapshot feature set includes:
- best bid / ask,
- spread in bps,
- L1 and L5 imbalance,
- top-5 bid / ask quote depth,
- microprice,
- microprice edge versus mid,
- event-to-receive latency,
- rolling 1s / 5s taker-flow imbalance.

Book snapshots are sampled at a configurable interval, default 100 ms, to avoid unbounded storage growth during the first collection phase.

## Important research guard

Historical research still refuses the existing `2026-08-01+` sealed holdout.

Live order-book capture after that date is allowed only as **prospective raw data collection**. It must not be used for parameter selection until the v0.8 strategy protocol and feature definitions are frozen. Collection is not equivalent to inspecting or optimizing on the future dataset.

## Order-book integrity

`L2OrderBook` supports:
- snapshot replacement,
- delta application,
- size-zero level deletion,
- identity checks,
- optional strict sequence continuity,
- crossed / locked book rejection,
- deterministic top-N depth and imbalance calculations.

Cryptofeed's normalized L2 callback currently enters the lab as snapshots. Raw exchange-specific sequence/delta replay is deliberately deferred until the normalized feature contract has been validated.

## Not implemented yet

- historical spot L2 reconstruction,
- exchange-specific raw depth-delta replay,
- queue-position / maker fill model,
- partial fills,
- latency-aware execution simulator,
- liquidation/funding/OI fusion,
- strategy selection on microstructure features,
- paper/live order submission.

The system remains research-only and uses public market data. No exchange credentials are required by v0.8 phase 1.
