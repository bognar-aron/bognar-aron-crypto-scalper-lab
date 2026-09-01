# Open-source synthesis for CRYPTO SCALPER LAB

Source basis: user-supplied repository notes dated 2026-09-01. This document synthesizes the supplied material into an architecture decision for this project. Repository activity, licences, exchange support and API compatibility should still be re-checked before code-level integration.

## Executive decision

Do **not** adopt one external trading bot as the project core.

Build a modular research and execution stack and borrow the strongest pattern from each ecosystem:

- **CCXT** for unified REST exchange metadata, OHLCV and later simple execution adapters.
- **Cryptofeed** for live WebSocket trades, L1/L2/L3 order-book, funding, OI and liquidation feeds.
- **NautilusTrader-inspired event model** for deterministic event replay and research/live parity.
- **Jesse-inspired strategy API** for small, testable strategy modules.
- **Freqtrade-inspired research workflow** for systematic data -> backtest -> development optimization -> paper/dry-run progression.
- **Hummingbot-inspired market-microstructure and maker logic** for order-book, spread, inventory and arbitrage research.
- **OctoBot-inspired operator UX** only where useful: paper mode, control surface, alerts and external-signal adapters.
- **Passivbot** and **R2** are reference implementations / idea mines, not architectural dependencies.

The project's own strongest differentiator remains the **walk-forward + cost model + sealed holdout protocol**. External frameworks must fit this protocol, not replace it.

---

## 1. Target architecture

### Layer A — Market data acquisition

**Historical / REST:** CCXT

Use for:
- exchange metadata,
- symbol discovery,
- OHLCV,
- public trades where practical,
- fee / market metadata where exposed,
- later private account/execution adapters if needed.

Rules:
- prefer official exchange APIs over HTML scraping,
- rate-limit and retry centrally,
- timestamp every observation,
- preserve raw exchange fields alongside normalized fields where useful,
- cache aggressively.

**Live market microstructure:** Cryptofeed

Use for:
- trades,
- best bid/ask,
- L2/L3 order books where supported,
- funding,
- open interest,
- liquidations,
- index / derivative reference data.

Critical engineering requirements:
- snapshot + delta validation,
- sequence-number checks,
- reconnect recovery,
- clock synchronization,
- stale-feed detection,
- exchange timestamp vs receive timestamp,
- gap logging.

### Layer B — Storage

**Phase 1:** Parquet on Google Drive / local workspace.

Why:
- simple,
- cheap,
- columnar,
- ideal for pandas/Polars research,
- easy partitioning by exchange/symbol/date/feed type.

Suggested layout:

```text
data/
  ohlcv/exchange=binance/symbol=BTCUSDC/date=YYYY-MM-DD/
  trades/exchange=binance/symbol=BTCUSDC/date=YYYY-MM-DD/
  book_l2/exchange=binance/symbol=BTCUSDC/date=YYYY-MM-DD/
  derivatives/exchange=.../
```

**Phase 2, only when needed:** ClickHouse / QuestDB / TimescaleDB-class time-series store.

Do not add database infrastructure until Parquet becomes the bottleneck.

### Layer C — Canonical event model

Adopt a **NautilusTrader-style principle**, not necessarily its code:

Research and live trading should consume the same normalized event types.

Core events:
- `TradeEvent`
- `QuoteEvent`
- `BookSnapshotEvent`
- `BookDeltaEvent`
- `CandleEvent`
- `FundingEvent`
- `LiquidationEvent`
- `OrderSubmitted`
- `OrderAck`
- `OrderFill`
- `OrderCancel`
- `RiskEvent`

Every event should carry:
- exchange,
- symbol,
- event timestamp,
- receive timestamp where available,
- sequence / source identifier,
- normalized values,
- raw source payload reference where useful.

This is the bridge from candle backtesting to true microstructure research.

### Layer D — Strategy API

Use a **Jesse-like clean strategy interface**.

A strategy should not know how Binance authentication, storage or GitHub works.

Conceptually:

```python
class Strategy:
    def on_start(self, context): ...
    def on_event(self, event, state): ...
    def generate_intent(self, state): ...
    def on_fill(self, fill, state): ...
```

Separate:
- signal generation,
- portfolio sizing,
- execution choice,
- risk vetoes.

This allows the same alpha signal to be tested with taker execution, maker execution, different fees and different risk regimes.

### Layer E — Research engine

Keep our current protocol and strengthen it with **Freqtrade-style research ergonomics**, without allowing unrestricted parameter mining.

Required pipeline:

1. ingest / validate data,
2. precompute features,
3. train/development window,
4. walk-forward validation,
5. minimum trade-count gates,
6. realistic fee/spread/slippage/latency assumptions,
7. development cost sensitivity,
8. paper/shadow test,
9. only then sealed holdout,
10. only then tiny live capital.

Optimization rules:
- optimization is allowed only inside development data,
- parameter search spaces must be declared before the run,
- compare families, not hundreds of near-identical parameter mutations,
- record every attempted configuration,
- no deleting ugly runs from the research history.

### Layer F — Microstructure / maker engine

Borrow the strongest ideas from **Hummingbot**.

Research features:
- spread capture,
- queue-aware maker fills,
- order-book imbalance,
- microprice,
- depth-weighted pressure,
- inventory skew,
- maker/taker decision,
- cross-exchange price dislocation,
- adverse-selection measurement.

This should become a separate research family from candle-based directional strategies.

### Layer G — Execution

**First live implementation:** simple own execution adapter using CCXT or direct exchange connector.

Why not immediately adopt a whole bot framework:
- easier to audit,
- smaller attack surface,
- exact control over order semantics,
- research engine remains independent.

For market-making / multi-venue execution, Hummingbot connectors may later be evaluated as an execution component rather than as the entire research stack.

Execution must model and record:
- intended price,
- submitted price,
- exchange acknowledgement,
- fill price,
- fill latency,
- partial fills,
- cancellation latency,
- spread at decision time,
- realized slippage,
- fees / rebates.

### Layer H — Risk engine

Keep and extend the existing independent risk layer.

Mandatory controls:
- API key with trade permission only,
- withdrawal disabled,
- IP whitelist where supported,
- dedicated subaccount,
- max position size,
- max gross exposure,
- max concurrent positions,
- daily loss limit,
- rolling loss limit,
- drawdown kill switch,
- consecutive-loss cooldown,
- order-rate limit,
- stale-data kill switch,
- exchange-disconnect kill switch,
- price-deviation sanity check,
- manual emergency stop.

The strategy cannot override risk vetoes.

### Layer I — Operations / observability

Borrow the useful operator ideas from **Freqtrade / OctoBot**:

- paper mode,
- live status dashboard,
- alerts,
- trade log,
- current risk state,
- current positions,
- data-feed health,
- PnL decomposition,
- manual pause / kill.

A GUI is secondary. Reliable logs and reproducibility come first.

---

## 2. What each external project contributes

| Project | Adopt | Do not blindly adopt |
|---|---|---|
| Freqtrade | research workflow, dry-run progression, optimization ergonomics | unrestricted hyperopt as proof of edge |
| Hummingbot | connectors, maker/microstructure concepts, inventory/spread logic | assuming market making is profitable by default |
| Jesse | clean strategy-development API | framework-specific coupling |
| NautilusTrader | deterministic event-driven architecture, research/live parity | complexity before we actually need it |
| OctoBot | operator UX, paper mode, external-signal adapters | GUI-driven architecture as project core |
| Passivbot | limit/grid execution ideas for research | martingale/grid risk as default live strategy |
| CCXT | normalized exchange REST/execution access | pretending all exchanges behave identically |
| Cryptofeed | normalized live trade/order-book feed | trusting reconnect/order-book state without validation |
| R2 | understandable arbitrage architecture example | old connectors/API assumptions |

---

## 3. Licensing rule

Treat licence compatibility as an architecture constraint.

From the supplied notes:
- Freqtrade: GPL-3.0
- Hummingbot: Apache-2.0
- OctoBot: GPL-3.0-or-later
- NautilusTrader: LGPL-3.0
- CCXT: MIT
- other repositories: verify current `LICENSE` before integration.

Project policy:

1. We may **study architectural patterns** from any repository.
2. Do not copy GPL source code into this repository unless we intentionally accept the resulting licence obligations.
3. Prefer clean-room reimplementation of generic ideas where appropriate.
4. MIT / Apache-2.0 components are easier candidates for direct dependency use, subject to their notices and current licences.
5. Verify licence again at the exact commit/tag used.

---

## 4. Proposed roadmap

### v0.7 — Benchmark + data-layer upgrade

Goal: stop evaluating only our own candle logic.

Build:
- canonical strategy interface,
- external-style benchmark strategies,
- Parquet feature cache,
- CCXT metadata/data adapter,
- explicit run manifest including git commit, data range, fees and config,
- same sealed-OOS discipline.

Deliverable:
- our strategies vs benchmark families under identical assumptions.

### v0.8 — Market Microstructure Lab

Goal: test whether the edge exists below 5-minute OHLCV resolution.

Build:
- Cryptofeed collector,
- trades + L1/L2 capture,
- book reconstruction validation,
- spread / imbalance / microprice features,
- maker/taker execution simulator,
- latency and partial-fill model.

First strategy families:
- order-book imbalance momentum,
- short-horizon mean reversion,
- spread capture,
- liquidity-vacuum breakout,
- cross-symbol / cross-venue lead-lag.

### v0.9 — Paper / shadow execution

Goal: measure simulation-vs-reality error before risking capital.

Build:
- exchange testnet or dry-run where useful,
- live market data,
- shadow orders,
- intended-vs-realizable fill analysis,
- execution-quality dashboard,
- risk kill switches.

No live capital required.

### v1.0 — Small-capital production candidate

Only if a strategy survives:
- development,
- walk-forward validation,
- sealed holdout,
- live paper/shadow trading,
- execution-cost comparison,
- operational failure testing.

Then start with deliberately small capital and hard risk caps.

---

## 5. Best current stack for this project

```text
GitHub
  source + research log + manifests + CI

Google Drive
  historical datasets + Parquet cache + large run artifacts

Google Colab / later cloud compute
  interactive research compute

CCXT
  REST metadata / OHLCV / simple exchange adapter

Cryptofeed
  real-time trades / quotes / order books / derivatives feeds

Our canonical event model
  deterministic normalized research stream

Our Strategy API
  Jesse-inspired clean strategy modules

Our Research Engine
  walk-forward + realistic costs + sealed holdout

Our Microstructure Engine
  Hummingbot-inspired maker/order-book research

Our Risk Engine
  independent veto layer

Our Execution Layer
  auditable exchange-specific adapters
```

## Final principle

The project should not become a collection of bots. It should become a **research operating system for finding out whether a trading hypothesis survives contact with data, costs and execution reality**.

External open-source projects are components, benchmarks and teachers. The proof standard remains ours.
