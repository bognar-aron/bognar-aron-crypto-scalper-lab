# v0.8.2 — L2 Conditioning + Maker Fill Lab

## Purpose

v0.8.1 validated that the frozen 5-second taker-flow signal contains reproducible information, but it failed execution economics. v0.8.2 therefore does **not** retune the flow signal. It asks two narrower questions on new, prospective public Binance data:

1. Does L2 state condition the already-validated flow signal into larger short-horizon moves?
2. Can a conservative passive maker-entry model obtain realistic fills without assuming free queue priority?

## Frozen conditioning protocol

Before capture, the following constants are fixed:

- flow feature: `trade_flow_imbalance_5s`
- strong flow: `abs(flow) >= 0.60`
- signed L5 book confirmation: `>= 0.25`
- signed microprice edge confirmation: `>= 0.05 bps`
- opposing/same L5 quote-depth ratio: `<= 0.80`
- tight spread: `<= 1.50 bps`
- signal cooldown: 5 seconds
- markout horizons: 1s, 5s, 30s

The thresholds may not be retuned from the same prospective capture.

## Conditions reported

The analyzer reports:

- flow only,
- flow + book confirmation,
- flow + microprice confirmation,
- flow + thin opposing depth,
- full confirmation.

The goal is diagnostic conditioning, not parameter search.

## Conservative shadow maker model

At each non-overlapping strong-flow signal:

- buy signals post at current best bid; sell signals post at current best ask,
- research order size is 100 quote units,
- TTL is 5 seconds,
- **100% of displayed L1 size is treated as queue ahead**,
- only actual opposing aggressive trades at-or-through the entry price consume queue,
- cancellations do not improve queue position,
- fill occurs only after queue ahead plus our own order quantity is consumed.

This deliberately understates fills relative to an optimistic cancellation-aware model.

After fill, the lab measures 1s/5s/30s mid-price markout versus the passive entry price. This is **one-sided maker-entry research**, not a complete round-trip PnL backtest and not a live-trading approval.

## Data sufficiency gate

A single capture is called sufficient for preliminary analysis only if it produces at least:

- 100 strong-flow signals,
- 25 full-confirm signals,
- 25 conservative shadow fills.

Failure means collect more prospective data, not relax thresholds.

## Data path

Colab writes:

`CRYPTO_SCALPER_LAB_v04/runs/v082_L2_<timestamp>/`

with:

- `v082_protocol_PRECAPTURE.json`
- `capture/trades.jsonl`
- `capture/microstructure.jsonl`
- `capture/capture_manifest.json`
- `v082_protocol.json`
- `l2_condition_diagnostics.csv`
- `maker_shadow_fills.csv`
- `maker_fill_summary.csv`
- `v082_gate.json`

## Safety / research discipline

- Public market data only.
- No API key.
- No order placement.
- No withdrawal capability.
- No strategy profitability pass in v0.8.2.
- No live candidate can be declared from this phase.
