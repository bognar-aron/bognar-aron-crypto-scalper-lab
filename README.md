# CRYPTO SCALPER LAB

Online-first crypto market research lab built to **reject weak strategies before money is exposed**. The project uses explicit execution costs, walk-forward validation, minimum sample gates and sealed holdouts.

## Current version: v0.8.2 L2 Conditioning + Maker Fill Lab

v0.7 tested three simple 5-minute OHLCV benchmarks on the same seven-USDC research universe. None passed the development gate:

- Donchian + volume breakout: 599 validation trades, 0/3 positive folds, median expectancy -0.157R.
- EMA trend: 612 validation trades, 0/3 positive folds, median expectancy -0.169R.
- VWAP mean reversion: 516 validation trades, 0/3 positive folds, median expectancy -0.194R.

That result motivated the move below candle level.

## v0.8 result

The Jan-Mar 2026 historical trade-flow pilot processed about 67.1 million Binance Spot aggregate trades across SOLUSDC, BTCUSDC and ETHUSDC. The frozen 5-second taker-imbalance feature showed a small but consistently positive relationship with subsequent 1s/5s/30s returns across all nine symbol-month development cells.

The signal was far smaller than ordinary taker round-trip friction, so v0.8 did **not** produce a tradeable strategy. It produced an information hypothesis worth validating.

## v0.8.1 validation result

The feature definition and threshold were frozen before the later temporal validation:

- feature: `taker_imbalance_5s`
- strong-flow threshold: `abs(feature) >= 0.60`
- symbols: SOLUSDC, BTCUSDC, ETHUSDC
- development reference: `[2026-01-01, 2026-04-01)`
- validation: `[2026-04-01, 2026-08-01)`
- sealed historical holdout: `2026-08-01+`, still locked

Real Apr-Jul result:

- `information_pass = true`
- `execution_pass = false`
- `overall_live_candidate_pass = false`
- 12 validation symbol-month cells
- positive rank correlation: 12/12 cells at 1s, 5s and 30s
- positive aligned mean: 12/12 cells at all three horizons
- positive bootstrap lower bound: 12/12 cells at all three horizons
- median rank correlation: 0.153 at 1s, 0.147 at 5s, 0.079 at 30s
- median aligned mean: +0.118 bps at 1s, +0.233 bps at 5s, +0.288 bps at 30s
- optimistic 4 bps maker-like round-trip hurdle: median net aligned edge -3.847 bps, 0% positive cells

Conclusion: the information signal reproduced, but ordinary round-trip execution economics did not.

## v0.8.2 prospective L2 conditioning

v0.8.2 does **not** retune the validated flow signal. It freezes a small set of L2 confirmation rules before collecting new public Binance data:

- signed L5 book imbalance >= 0.25
- signed microprice edge >= 0.05 bps
- opposing/same L5 depth ratio <= 0.80
- spread <= 1.50 bps
- 5-second signal cooldown

It compares flow-only observations with book-confirmed, microprice-confirmed, thin-opposing-depth and full-confirm states at 1s/5s/30s forward horizons.

### Conservative shadow maker fill model

At each strong-flow signal:

- buy posts at current best bid; sell posts at current best ask,
- 100 quote-unit research order,
- 5-second TTL,
- 100% of displayed L1 size is considered queue ahead,
- only actual opposing aggressive trades at-or-through the entry price consume queue,
- cancellations receive no queue credit,
- fills are followed by 1s/5s/30s entry-price-to-mid markouts.

This is intentionally conservative and is **not** a full round-trip PnL backtest. v0.8.2 cannot declare a live candidate.

## v0.8 market-data architecture

**Historical taker-flow research**

Binance Spot monthly `aggTrades` are processed month-by-month into 1-second features: trade count, quote volume, taker buy/sell flow, signed quote flow, 1s/5s/30s taker imbalance, VWAP and short-horizon returns.

**Prospective live L2 capture**

Cryptofeed public Binance Spot `TRADES + L2_BOOK` feeds are normalized into the project's own event model. Features include spread, L1/L5 imbalance, top-5 quote depth, microprice, microprice edge, latency and rolling taker flow.

## Architecture

- **GitHub**: source code, notebooks, CI and research history.
- **Google Drive**: large Binance archives, prospective JSONL captures, Parquet datasets and run outputs.
- **Google Colab**: interactive compute from browser/iPhone.
- **GitHub Actions**: reproducibility and unit/compile checks.
- **CCXT**: optional REST adapter layer.
- **Cryptofeed**: optional live WebSocket feed layer.
- **Own event contract**: keeps research independent of any single external framework.

## Research lineage

- v0.3: original tight-stop pullback scalp failed after costs.
- v0.4: encouraging 4-trade OOS result, rejected for tiny sample and weak development stability.
- v0.5: seven-USDC robustness test removed the apparent edge.
- v0.6: five-family Strategy Tournament.
- v0.7: independent OHLCV benchmark lab, all three controls failed.
- v0.8: first second-level taker-flow signal discovery.
- v0.8.1: frozen temporal validation passed information, failed execution economics.
- **v0.8.2: prospective L2 conditioning + conservative maker-fill research.**

## Colab

- `notebooks/CRYPTO_SCALPER_LAB_v08_COLAB.ipynb`: original Jan-Mar trade-flow pilot and optional live L2 capture.
- `notebooks/CRYPTO_SCALPER_LAB_v081_COLAB.ipynb`: Apr-Jul frozen temporal validation.
- `notebooks/CRYPTO_SCALPER_LAB_v082_COLAB.ipynb`: prospective 30-minute L2/trade capture and maker-fill analysis.

## Research docs

- `docs/RESEARCH_LOG.md`
- `docs/OPEN_SOURCE_ARCHITECTURE.md`
- `docs/V07_IMPLEMENTATION.md`
- `docs/V08_IMPLEMENTATION.md`
- `docs/V081_VALIDATION_PROTOCOL.md`
- `docs/V082_IMPLEMENTATION.md`
