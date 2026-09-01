# CRYPTO SCALPER LAB

Online-first research lab for testing crypto trading hypotheses with walk-forward validation, explicit execution costs, and a sealed holdout.

## Current version: v0.6 Strategy Tournament

Five strategy families compete on the same seven USDC markets with the same fee, slippage and risk engine:

1. Momentum breakout
2. Volatility expansion
3. VWAP mean reversion
4. Trend pullback v2
5. Relative-strength rotation

FAST mode runs two predeclared variants per family. The research protocol does **not** promote a "least bad" strategy: if no candidate clears the development gate, there is no winner.

### Development gate

A candidate must satisfy all of the following:

- positive expectancy in at least 2 of 3 validation folds,
- at least 10 validation trades in every fold,
- at least 50 validation trades in total,
- median validation expectancy > 0 R,
- worst-fold expectancy >= -0.20 R,
- worst validation drawdown < 8%.

The 2026-08-01+ sealed holdout stays locked unless explicitly unlocked after a genuine development PASS.

## Architecture

- **GitHub**: source code, notebook, workflow, version history.
- **Google Drive**: Binance historical-data cache and large run outputs.
- **Google Colab**: interactive execution from browser/iPhone. The notebook clones the latest repo code, then reads/writes data on Drive.
- **GitHub Actions**: optional manual cloud run without Colab. Results are uploaded as workflow artifacts.

## Colab

Open `notebooks/CRYPTO_SCALPER_LAB_v06_COLAB.ipynb` in Colab and run all cells.

The notebook clones this repository fresh on every session but keeps the heavy `data/` cache and `runs/` history on Google Drive.

## CLI

```bash
pip install -r requirements.txt
python strategy_tournament_v06.py \
  --symbols SOLUSDC,BTCUSDC,ETHUSDC,BNBUSDC,XRPUSDC,ADAUSDC,DOGEUSDC \
  --mode fast \
  --fee-bps 10 \
  --slippage-bps 2 \
  --start 2024-01-01 \
  --end 2026-07-31 \
  --data-dir data \
  --out runs/v06
```

Do not unlock the sealed holdout merely to inspect it. The point of the holdout is that model selection cannot see it.

See `docs/RESEARCH_LOG.md` for the path from v0.3 to the current tournament.
