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

Phase 1 is split into two lanes.

### Historical taker-flow lane

Binance Spot monthly `aggTrades` are processed month-by-month to keep memory bounded. The parser handles post-2025 microsecond timestamps and infers taker direction from `buyer_is_maker`.

Features are aggregated to 1 second:

- trade count,
- quote/base volume,
- buy and sell taker quote volume,
- signed quote flow,
- 1s / 5s / 30s taker imbalance,
- VWAP,
- short-horizon returns.

The first analysis is pre-strategy: fixed imbalance buckets and rank correlation versus 1s / 5s / 30s forward returns. This asks whether the information exists before building an execution rule around it.

Historical research is hard-blocked from loading data at or after 2026-08-01.

### Prospective live L2 lane

Cryptofeed public Binance Spot `TRADES` and `L2_BOOK` callbacks are normalized into the project's own event contract. The recorder captures raw trades and throttled L2 feature snapshots with:

- spread,
- L1/L5 order-book imbalance,
- top-5 quote depth,
- microprice and microprice edge,
- receive latency,
- rolling taker flow.

Live data collected after the historical holdout date is treated as prospective raw data only and cannot be used for parameter selection until the feature and strategy protocol is frozen.

Next intended milestone after proving the data layer: queue-position / maker-fill and latency-aware shadow execution, not immediate live trading.
