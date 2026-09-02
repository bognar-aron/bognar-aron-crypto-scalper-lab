# CRYPTO SCALPER LAB

Online-first crypto market research lab built to **reject weak strategies before money is exposed**. The project uses explicit execution costs, walk-forward validation, minimum sample gates and sealed holdouts.

## Current version: v0.8.1 Microstructure Validation

v0.7 tested three simple 5-minute OHLCV benchmarks on the same seven-USDC research universe. None passed the development gate:

- Donchian + volume breakout: 599 validation trades, 0/3 positive folds, median expectancy -0.157R.
- EMA trend: 612 validation trades, 0/3 positive folds, median expectancy -0.169R.
- VWAP mean reversion: 516 validation trades, 0/3 positive folds, median expectancy -0.194R.

That result motivated the move below candle level.

## v0.8 result

The Jan-Mar 2026 historical trade-flow pilot processed about 67.1 million Binance Spot aggregate trades across SOLUSDC, BTCUSDC and ETHUSDC. The frozen 5-second taker-imbalance feature showed a small but consistently positive relationship with subsequent 1s/5s/30s returns across all nine symbol-month development cells.

The signal was far smaller than ordinary taker round-trip friction, so v0.8 did **not** produce a tradeable strategy. It produced an information hypothesis worth validating.

## v0.8.1 validation

The feature definition and threshold are frozen before the later temporal validation:

- feature: `taker_imbalance_5s`
- strong-flow threshold: `abs(feature) >= 0.60`
- symbols: SOLUSDC, BTCUSDC, ETHUSDC
- development reference: `[2026-01-01, 2026-04-01)`
- validation: `[2026-04-01, 2026-08-01)`
- sealed historical holdout: `2026-08-01+`, still locked

v0.8.1 adds deterministic non-overlapping horizon sampling, block-bootstrap confidence intervals, hit rates, tail-return diagnostics, rank-quantile monotonicity and fixed execution-cost hurdles.

The research output separates:

- `information_pass`: does the signal reproduce across later symbol-month cells?
- `execution_pass`: does any useful edge remain even under an optimistic fixed 4 bps round-trip maker-like research hurdle?
- `overall_live_candidate_pass`: requires both.

No validation result is allowed to move the frozen 0.60 threshold.

## v0.8 market-data architecture

**Historical taker-flow research**

Binance Spot monthly `aggTrades` are processed month-by-month into 1-second features: trade count, quote volume, taker buy/sell flow, signed quote flow, 1s/5s/30s taker imbalance, VWAP and short-horizon returns.

**Prospective live L2 capture**

Cryptofeed public Binance Spot `TRADES + L2_BOOK` feeds are normalized into the project's own event model. Features include spread, L1/L5 imbalance, top-5 quote depth, microprice, microprice edge, latency and rolling taker flow.

Live capture is data collection only until the feature/strategy protocol is frozen.

## Architecture

- **GitHub**: source code, notebooks, CI and research history.
- **Google Drive**: large Binance archives, Parquet datasets and run outputs.
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
- **v0.8.1: frozen temporal validation and execution-economics stress test.**

## Colab

- `notebooks/CRYPTO_SCALPER_LAB_v08_COLAB.ipynb`: original Jan-Mar trade-flow pilot and optional live L2 capture.
- `notebooks/CRYPTO_SCALPER_LAB_v081_COLAB.ipynb`: Apr-Jul frozen temporal validation.

## CLI

```bash
python microstructure_validation_v081.py \
  --symbols SOLUSDC,BTCUSDC,ETHUSDC \
  --validation-start 2026-04-01 \
  --validation-end 2026-08-01 \
  --data-dir data \
  --out runs/v081_validation \
  --block-seconds 300 \
  --n-boot 300
```

## Research docs

- `docs/RESEARCH_LOG.md`
- `docs/OPEN_SOURCE_ARCHITECTURE.md`
- `docs/V07_IMPLEMENTATION.md`
- `docs/V08_IMPLEMENTATION.md`
- `docs/V081_VALIDATION_PROTOCOL.md`
