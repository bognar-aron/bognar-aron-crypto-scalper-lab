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

Expanded to:

- SOLUSDC
- BTCUSDC
- ETHUSDC
- BNBUSDC
- XRPUSDC
- ADAUSDC
- DOGEUSDC

The larger sample solved the trade-count problem but removed the apparent edge. No tested configuration passed the stricter development gate. The 2026-08-01+ holdout remained locked.

Conclusion: do not continue parameter-mining the same breakout/pullback architecture.

## v0.6 — Strategy Tournament

Instead of tuning one strategy family more aggressively, v0.6 compares five distinct hypotheses under the same execution and validation framework:

1. Momentum breakout
2. Volatility expansion
3. VWAP mean reversion
4. Trend pullback v2
5. Relative-strength rotation

The key rule remains unchanged: if nobody passes, nobody wins.
