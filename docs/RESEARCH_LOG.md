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

The v0.8 signal definition is frozen before examining Apr-Jul 2026 validation data.

Validation protocol:

- feature stays `taker_imbalance_5s`,
- strong-flow threshold stays 0.60,
- symbols stay SOLUSDC/BTCUSDC/ETHUSDC,
- validation window is `[2026-04-01, 2026-08-01)`,
- 2026-08-01+ historical holdout remains locked,
- 1s and 5s are primary proof horizons; 30s is diagnostic,
- horizon windows are sampled non-overlapping,
- confidence intervals use 300-second block bootstrap,
- quantile direction, hit rate and tail behavior are reported,
- fixed round-trip execution hurdles are evaluated separately from information quality.

The information gate requires cross-cell consistency, not a single pooled p-value. The execution gate uses an intentionally optimistic 4 bps maker-like research hurdle and does not claim executable fills.

No validation result may be used to move the 0.60 threshold. If the signal fails, it fails. If information survives but execution does not, the next step is L2 state conditioning and realistic maker queue/fill modeling, not live trading.

See `docs/V081_VALIDATION_PROTOCOL.md`.
