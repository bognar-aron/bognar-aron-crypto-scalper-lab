# CRYPTO SCALPER LAB

Online-first crypto market research lab built to **reject weak strategies before money is exposed**. The project uses explicit execution costs, walk-forward validation, minimum sample gates and sealed holdouts.

## Current version: v0.8 Market Microstructure Lab

v0.7 tested three simple 5-minute OHLCV benchmarks on the same seven-USDC research universe. None passed the development gate:

- Donchian + volume breakout: 599 validation trades, 0/3 positive folds, median expectancy -0.157R.
- EMA trend: 612 validation trades, 0/3 positive folds, median expectancy -0.169R.
- VWAP mean reversion: 516 validation trades, 0/3 positive folds, median expectancy -0.194R.

That result motivated the move below candle level.

### v0.8 has two research lanes

**A. Historical taker-flow research**

Binance Spot monthly `aggTrades` are processed one month at a time into 1-second features:

- trade count and quote volume,
- taker buy/sell quote volume,
- signed quote flow,
- 1s / 5s / 30s taker imbalance,
- VWAP and short-horizon returns,
- fixed-bin 1s / 5s / 30s predictive diagnostics.

Historical v0.8 research refuses data at or after `2026-08-01`.

**B. Prospective live L2 capture**

Cryptofeed public Binance Spot `TRADES + L2_BOOK` feeds are normalized into the project's own event model and stored as raw trade logs plus microstructure snapshots. Features currently include spread, L1/L5 imbalance, top-5 quote depth, microprice, microprice edge, latency and rolling taker flow.

Live capture is data collection only. It is not eligible for parameter selection until the v0.8 strategy protocol is frozen.

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
- **v0.8: market microstructure / taker-flow research.**

## Colab

Open `notebooks/CRYPTO_SCALPER_LAB_v08_COLAB.ipynb` and run all cells for the historical trade-flow pilot. The live L2 cell is disabled by default and must be explicitly enabled.

## CLI

Historical trade-flow pilot:

```bash
python microstructure_lab_v08.py tradeflow \
  --symbols SOLUSDC,BTCUSDC,ETHUSDC \
  --start 2026-01-01 \
  --end 2026-04-01 \
  --data-dir data \
  --out runs/v08_tradeflow
```

Optional public live L2 capture:

```bash
pip install -r requirements-v08.txt
python microstructure_lab_v08.py capture \
  --symbols BTC-USDC,SOL-USDC,ETH-USDC \
  --seconds 300 \
  --depth 10 \
  --snapshot-interval-ms 100 \
  --out runs/v08_live_capture
```

No exchange API key is required for v0.8 phase 1.

## Research docs

- `docs/RESEARCH_LOG.md`
- `docs/OPEN_SOURCE_ARCHITECTURE.md`
- `docs/V07_IMPLEMENTATION.md`
- `docs/V08_IMPLEMENTATION.md`
