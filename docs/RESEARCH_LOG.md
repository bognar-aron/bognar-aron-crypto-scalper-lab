# Research log

## v0.3 — original SOL/BTC/ETH pullback scalp

First real Colab backtest on approximately 2025-01-02 to 2026-07-21, starting from 2,500 USDC:

- 100 trades
- 46% win rate
- Profit Factor 0.33
- expectancy -0.322 R/trade
- max drawdown -10.09%
- final equity 2,268.90 USDC
- return -9.24%

Main diagnosis: very tight stops plus conservative execution friction made the setup structurally weak. SOL was the only symbol with a remotely interesting gross signal.

## v0.4 — SOL-first wider-stop experiment

The winning development configuration used a wider stop envelope and stronger breakout-volume filter. Its sealed OOS result looked excellent at first glance:

- 4 trades
- 3 winners
- PF 6.73
- expectancy +0.504 R/trade
- return +0.605%

But the sample was far too small. Only 4 OOS trades meant the trade-count gate failed. Stability analysis also showed no broad profitable parameter island.

## v0.5 — multi-USDC robustness test

Expanded to SOLUSDC, BTCUSDC, ETHUSDC, BNBUSDC, XRPUSDC, ADAUSDC and DOGEUSDC.

The larger sample solved the trade-count problem but removed the apparent edge. No tested configuration passed the stricter development gate. The 2026-08-01+ holdout remained locked.

Conclusion: do not continue parameter-mining the same breakout/pullback architecture.

## v0.6 — Strategy Tournament

Instead of tuning one strategy family more aggressively, v0.6 compared five distinct hypotheses under the same execution and validation framework:

1. Momentum breakout
2. Volatility expansion
3. VWAP mean reversion
4. Trend pullback v2
5. Relative-strength rotation

The governing rule remained: if nobody passes, nobody wins.

## Open-source synthesis — architecture decision for v0.7+

User-supplied research on Freqtrade, Hummingbot, OctoBot, NautilusTrader, Passivbot, Jesse, CCXT, Cryptofeed and R2 was synthesized into a modular architecture rather than selecting a single external bot.

Decision:

- CCXT for unified REST exchange access and simple adapters.
- Cryptofeed for live trades/order-book/derivatives feeds.
- NautilusTrader-inspired deterministic event model.
- Jesse-inspired clean strategy API.
- Freqtrade-inspired research ergonomics and dry-run progression.
- Hummingbot-inspired order-book, maker and microstructure research.
- OctoBot operator UX ideas where useful.
- Passivbot and R2 as reference/idea sources only.

The project's own walk-forward validation, realistic execution-cost model and sealed holdout remain the governing proof standard.

## v0.7 — Benchmark + Data Layer

Implemented a normalized event contract, small strategy API, Parquet store, optional CCXT adapter and three fixed independent OHLCV control strategies. The controls were evaluated with the same three-fold robustness gate rather than a single full-period backtest.

Real benchmark result:

- Donchian + volume breakout: 599 validation trades, 0/3 positive folds, median expectancy -0.157R, worst validation DD about 10.32%.
- EMA trend: 612 validation trades, 0/3 positive folds, median expectancy -0.169R, worst validation DD about 10.22%.
- VWAP mean reversion: 516 validation trades, 0/3 positive folds, median expectancy -0.194R, worst validation DD about 10.27%.

No benchmark passed. This substantially strengthened the case that the next research step should move below 5-minute OHLCV rather than tune another candle strategy.

## v0.8 — Market Microstructure Lab

Phase 1 split into historical taker-flow research and prospective live L2 capture.

The Jan-Mar 2026 historical pilot processed approximately 67.1 million Binance Spot aggregate trades across SOLUSDC, BTCUSDC and ETHUSDC. It produced more than 10 million active one-second observations.

Frozen development feature:

- `taker_imbalance_5s`
- strong flow: `abs(imbalance) >= 0.60`
- forward horizons: 1s, 5s, 30s

Observed development result:

- rank correlation was positive in all nine symbol-month cells at the tested horizons,
- average signal strength was largest at 1 second and decayed quickly,
- strong-flow aligned forward returns were positive on average,
- the gross effect size was only around tenths of a basis point and therefore far below normal taker round-trip friction.

Conclusion: v0.8 discovered a consistent information hypothesis, not a tradeable strategy.

Prospective public Binance Spot `TRADES` and `L2_BOOK` capture remains available for later spread, depth, microprice, queue and fill research. Data collected after the historical holdout date is prospective raw data only.

## v0.8.1 — frozen microstructure validation

The v0.8 signal definition was frozen before examining Apr-Jul 2026 validation data.

Validation protocol:

- feature stayed `taker_imbalance_5s`,
- strong-flow threshold stayed 0.60,
- symbols stayed SOLUSDC/BTCUSDC/ETHUSDC,
- validation window was `[2026-04-01, 2026-08-01)`,
- 2026-08-01+ historical holdout remained locked,
- 1s and 5s were primary proof horizons; 30s diagnostic,
- horizon windows were sampled non-overlapping,
- confidence intervals used 300-second block bootstrap,
- quantile direction, hit rate and tail behavior were reported,
- fixed round-trip execution hurdles were evaluated separately from information quality.

Real validation result:

- `information_pass = true`
- `execution_pass = false`
- `overall_live_candidate_pass = false`
- 12/12 cells positive rank correlation at 1s, 5s and 30s
- 12/12 cells positive aligned mean at all three horizons
- 12/12 cells positive bootstrap lower bound at all three horizons
- median rank correlation: 0.153 / 0.147 / 0.079 for 1s / 5s / 30s
- median aligned mean: +0.118 / +0.233 / +0.288 bps
- optimistic 4 bps maker-like hurdle still produced median net -3.847 bps and 0% positive cells

Conclusion: the information survived later temporal validation, but the execution hurdle did not. This directly triggers L2 state conditioning and realistic maker queue/fill research rather than live trading.

See `docs/V081_VALIDATION_PROTOCOL.md`.

## v0.8.2 — prospective L2 conditioning + shadow maker fills

v0.8.2 freezes a small set of L2 conditioning rules before collecting new public Binance Spot `TRADES + L2_BOOK` data.

Frozen state definitions:

- strong 5s flow remains `abs(flow) >= 0.60`,
- signed L5 imbalance confirmation >= 0.25,
- signed microprice edge >= 0.05 bps,
- opposing/same L5 quote-depth ratio <= 0.80,
- spread <= 1.50 bps,
- 5-second signal cooldown,
- markouts at 1s, 5s and 30s.

The prospective analyzer compares flow-only observations with increasingly restrictive L2-confirmed states. No thresholds may be retuned from the same capture.

Shadow maker model:

- buy at best bid / sell at best ask,
- 100 quote-unit research order,
- 5-second TTL,
- all visible L1 quantity treated as queue ahead,
- only actual opposing aggressive trades at-or-through the order price consume queue,
- cancellation credit is zero,
- filled orders are evaluated by post-fill mid-price markout.

This phase measures data sufficiency, L2 conditioning and conservative passive-entry fill behavior. It is not a full round-trip strategy PnL test and cannot generate a live-trading approval.

See `docs/V082_IMPLEMENTATION.md`.
