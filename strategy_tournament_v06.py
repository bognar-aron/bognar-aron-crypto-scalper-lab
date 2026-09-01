#!/usr/bin/env python3
"""
CRYPTO SCALPER LAB v0.6 — Strategy Tournament

Five distinct long-only USDC spot strategy families compete on the same data,
fees/slippage, risk engine and walk-forward folds. This is research software,
not a live execution bot.

Families:
1) momentum_breakout
2) volatility_expansion
3) vwap_mean_reversion
4) trend_pullback_v2
5) relative_strength_rotation

Research protocol:
- development only: 2024-01-01 .. 2026-04-01 via 3 expanding walk-forward folds
- observed diagnostic: 2026-04-01 .. 2026-08-01, only if development has an eligible winner
- sealed holdout starts 2026-08-01 and is NEVER loaded by default
- holdout requires explicit --unlock-holdout and a development winner
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

from backtester import (
    Config, Candidate, Trade, load_symbol, prepare_features,
    run_portfolio, summarize, trade_df, utc, resample_ohlcv, true_range,
)

FOLDS = [
    ("2024-01-01", "2024-10-01", "2024-10-01", "2025-03-01"),
    ("2024-01-01", "2025-03-01", "2025-03-01", "2025-09-01"),
    ("2024-01-01", "2025-09-01", "2025-09-01", "2026-04-01"),
]
OBSERVED_START = "2026-04-01"
OBSERVED_END_EXCLUSIVE = "2026-08-01"
SEALED_HOLDOUT_START = "2026-08-01"
DEFAULT_SYMBOLS = (
    "SOLUSDC", "BTCUSDC", "ETHUSDC", "BNBUSDC", "XRPUSDC", "ADAUSDC", "DOGEUSDC"
)

@dataclass(frozen=True)
class StrategySpec:
    family: str
    variant: str
    params: Dict[str, float | int | bool]
    min_stop_pct: float
    max_stop_pct: float
    tp1_r: float
    tp2_r: float

    @property
    def strategy_id(self) -> str:
        payload = asdict(self)
        h = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]
        return f"{self.family}__{self.variant}__{h}"


def build_specs(mode: str = "fast") -> List[StrategySpec]:
    core = [
        StrategySpec("momentum_breakout", "vol15", {"volume_mult": 1.5}, 0.004, 0.015, 1.25, 2.5),
        StrategySpec("volatility_expansion", "compress85", {"compression": 0.85, "volume_mult": 1.1}, 0.004, 0.015, 1.25, 2.5),
        StrategySpec("vwap_mean_reversion", "dev15", {"deviation_atr": 1.5, "arm_bars": 8}, 0.004, 0.015, 1.0, 2.0),
        StrategySpec("trend_pullback_v2", "vol09", {"trigger_volume_mult": 0.9, "cooldown_min": 30}, 0.004, 0.015, 1.25, 2.5),
        StrategySpec("relative_strength_rotation", "6h15", {"lookback_h": 6, "min_return": 0.015, "volume_mult": 1.0}, 0.004, 0.015, 1.25, 2.5),
    ]
    if mode == "core":
        return core
    fast_extra = [
        StrategySpec("momentum_breakout", "vol20", {"volume_mult": 2.0}, 0.004, 0.015, 1.25, 2.5),
        StrategySpec("volatility_expansion", "compress80", {"compression": 0.80, "volume_mult": 1.1}, 0.004, 0.015, 1.25, 2.5),
        StrategySpec("vwap_mean_reversion", "dev20", {"deviation_atr": 2.0, "arm_bars": 8}, 0.004, 0.015, 1.0, 2.0),
        StrategySpec("trend_pullback_v2", "vol11", {"trigger_volume_mult": 1.1, "cooldown_min": 30}, 0.004, 0.015, 1.25, 2.5),
        StrategySpec("relative_strength_rotation", "12h25", {"lookback_h": 12, "min_return": 0.025, "volume_mult": 1.0}, 0.004, 0.015, 1.25, 2.5),
    ]
    if mode == "fast":
        return core + fast_extra
    full_extra = [
        StrategySpec("momentum_breakout", "vol125", {"volume_mult": 1.25}, 0.004, 0.015, 1.5, 3.0),
        StrategySpec("volatility_expansion", "compress70", {"compression": 0.70, "volume_mult": 1.1}, 0.004, 0.015, 1.5, 3.0),
        StrategySpec("vwap_mean_reversion", "dev125", {"deviation_atr": 1.25, "arm_bars": 10}, 0.004, 0.015, 1.0, 2.0),
        StrategySpec("trend_pullback_v2", "vol10wide", {"trigger_volume_mult": 1.0, "cooldown_min": 45}, 0.004, 0.018, 1.5, 3.0),
        StrategySpec("relative_strength_rotation", "6h10", {"lookback_h": 6, "min_return": 0.010, "volume_mult": 1.1}, 0.004, 0.015, 1.5, 3.0),
    ]
    if mode == "full":
        return core + fast_extra + full_extra
    raise ValueError(mode)


def next_5m_index(df5: pd.DataFrame, t: pd.Timestamp) -> pd.Timestamp | None:
    pos = df5.index.searchsorted(t, side="right")
    if pos >= len(df5.index):
        return None
    return df5.index[pos]


def slope_bonus(row) -> float:
    s = float(row.get("ema50_slope_pct", 0.0)) if np.isfinite(row.get("ema50_slope_pct", np.nan)) else 0.0
    return max(0.0, s * 10_000.0) * 0.10


def candidate(symbol: str, signal_time: pd.Timestamp, entry_time: pd.Timestamp, stop_raw: float,
              level: float, strength: float, slope: float = 0.0) -> Candidate:
    return Candidate(
        symbol=symbol, signal_time=signal_time, entry_time=entry_time,
        stop_raw=float(stop_raw), breakout_level=float(level),
        breakout_volume_ratio=float(strength), ema50_slope_pct=float(slope),
        score=float(strength + max(0.0, slope * 10_000.0) * 0.10),
    )


def gen_momentum(symbol: str, df5: pd.DataFrame, df15: pd.DataFrame, spec: StrategySpec) -> List[Candidate]:
    vol_mult = float(spec.params["volume_mult"])
    out = []
    cond = (
        (df15["close"] > df15["prior_high"]) &
        (df15["volume_ratio"] >= vol_mult) &
        (df15["close"] > df15["vwap"])
    )
    for t, br in df15[cond].iterrows():
        if t not in df5.index or not bool(df5.loc[t, "trend_ok"]):
            continue
        entry = next_5m_index(df5, t)
        if entry is None:
            continue
        atr = float(df5.loc[t, "atr"])
        if not np.isfinite(atr):
            continue
        stop = float(br["low"]) - 0.10 * atr
        slope = float(df5.loc[t, "ema50_slope_pct"]) if np.isfinite(df5.loc[t, "ema50_slope_pct"]) else 0.0
        out.append(candidate(symbol, t, entry, stop, float(br["prior_high"]), float(br["volume_ratio"]), slope))
    return out


def gen_volatility_expansion(symbol: str, df5: pd.DataFrame, df15: pd.DataFrame, spec: StrategySpec) -> List[Candidate]:
    compression_max = float(spec.params["compression"])
    volume_mult = float(spec.params["volume_mult"])
    x = df15.copy()
    tr = true_range(x)
    x["tr_med12"] = tr.shift(1).rolling(12).median()
    x["tr_med96"] = tr.shift(1).rolling(96).median()
    x["compression"] = x["tr_med12"] / x["tr_med96"]
    prior_high = x["high"].shift(1).rolling(8).max()
    cond = (
        (x["compression"] <= compression_max) &
        (x["close"] > prior_high) &
        (x["volume_ratio"] >= volume_mult) &
        (x["close"] > x["vwap"])
    )
    out = []
    for t, br in x[cond].iterrows():
        if t not in df5.index or not bool(df5.loc[t, "trend_ok"]):
            continue
        entry = next_5m_index(df5, t)
        if entry is None:
            continue
        atr = float(df5.loc[t, "atr"])
        if not np.isfinite(atr):
            continue
        stop = float(br["low"]) - 0.10 * atr
        comp = float(br["compression"])
        strength = float(br["volume_ratio"]) + max(0.0, compression_max - comp) * 3.0
        slope = float(df5.loc[t, "ema50_slope_pct"]) if np.isfinite(df5.loc[t, "ema50_slope_pct"]) else 0.0
        out.append(candidate(symbol, t, entry, stop, float(prior_high.loc[t]), strength, slope))
    return out


def add_broad_regime(df5: pd.DataFrame) -> pd.DataFrame:
    x = df5.copy()
    h = resample_ohlcv(x, "1h")
    h["ema200"] = h["close"].ewm(span=200, adjust=False).mean()
    h["ema200_prev"] = h["ema200"].shift(12)
    h["broad_bull"] = (h["close"] > h["ema200"]) & (h["ema200"] > h["ema200_prev"])
    x["broad_bull"] = h["broad_bull"].reindex(x.index, method="ffill").eq(True)
    return x


def gen_vwap_mean_reversion(symbol: str, df5: pd.DataFrame, df15: pd.DataFrame, spec: StrategySpec) -> List[Candidate]:
    del df15
    x = add_broad_regime(df5)
    dev = float(spec.params["deviation_atr"])
    arm_bars = int(spec.params["arm_bars"])
    out: List[Candidate] = []
    armed_until = None
    armed_low = math.inf
    idx = x.index
    for i, t in enumerate(idx):
        row = x.iloc[i]
        atr = float(row["atr"]) if np.isfinite(row["atr"]) else np.nan
        if not np.isfinite(atr) or not bool(row["broad_bull"]):
            continue
        extreme = float(row["low"]) <= float(row["vwap"]) - dev * atr
        if extreme:
            armed_until = t + pd.Timedelta(minutes=5 * arm_bars)
            armed_low = float(row["low"])
            continue
        if armed_until is None:
            continue
        if t > armed_until:
            armed_until = None
            armed_low = math.inf
            continue
        armed_low = min(armed_low, float(row["low"]))
        if i == 0:
            continue
        prev = x.iloc[i - 1]
        trigger = (
            float(row["close"]) > float(row["open"]) and
            float(row["close"]) > float(prev["high"]) and
            float(row["close"]) > float(row["ema20"]) and
            float(row["close"]) < float(row["vwap"]) * 1.003
        )
        if not trigger:
            continue
        entry = next_5m_index(x, t)
        if entry is None:
            break
        stop = armed_low - 0.10 * atr
        distance = max(0.0, (float(row["vwap"]) - float(row["close"])) / atr)
        out.append(candidate(symbol, t, entry, stop, float(row["vwap"]), dev + distance, 0.0))
        armed_until = None
        armed_low = math.inf
    return out


def gen_trend_pullback(symbol: str, df5: pd.DataFrame, df15: pd.DataFrame, spec: StrategySpec) -> List[Candidate]:
    del df15
    mult = float(spec.params["trigger_volume_mult"])
    cooldown = pd.Timedelta(minutes=int(spec.params["cooldown_min"]))
    x = df5.copy()
    out: List[Candidate] = []
    last_signal = pd.Timestamp("1970-01-01", tz="UTC")
    recent_low = x["low"].rolling(6).min()
    for i in range(1, len(x)):
        t = x.index[i]
        if t - last_signal < cooldown:
            continue
        row, prev = x.iloc[i], x.iloc[i - 1]
        if not bool(row["trend_ok"]) or not np.isfinite(row["atr"]) or not np.isfinite(row["vol_med20"]):
            continue
        # A pullback occurred in the last three bars if price touched EMA20 or VWAP.
        recent = x.iloc[max(0, i-2):i+1]
        touched = False
        for _, r in recent.iterrows():
            for lev in (r["ema20"], r["vwap"]):
                if np.isfinite(lev) and float(r["low"]) <= float(lev) <= float(r["high"]):
                    touched = True
                    break
            if touched:
                break
        trigger = (
            touched and float(row["close"]) > float(row["open"]) and
            float(row["close"]) > float(prev["high"]) and
            float(row["close"]) > float(row["vwap"]) and
            float(row["volume"]) >= mult * float(row["vol_med20"])
        )
        if not trigger:
            continue
        entry = next_5m_index(x, t)
        if entry is None:
            continue
        stop = float(recent_low.iloc[i]) - 0.10 * float(row["atr"])
        slope = float(row["ema50_slope_pct"]) if np.isfinite(row["ema50_slope_pct"]) else 0.0
        strength = float(row["volume"] / row["vol_med20"])
        out.append(candidate(symbol, t, entry, stop, float(row["vwap"]), strength, slope))
        last_signal = t
    return out


def gen_relative_strength(prepared: Dict[str, pd.DataFrame], spec: StrategySpec) -> List[Candidate]:
    lookback_h = int(spec.params["lookback_h"])
    min_return = float(spec.params["min_return"])
    vol_mult = float(spec.params["volume_mult"])
    hourly: Dict[str, pd.DataFrame] = {}
    all_times = set()
    for symbol, df5 in prepared.items():
        h = resample_ohlcv(df5, "1h")
        h["ret"] = h["close"] / h["close"].shift(lookback_h) - 1.0
        h["vol_med"] = h["volume"].shift(1).rolling(24).median()
        h["vol_ratio"] = h["volume"] / h["vol_med"]
        h["trend_ok"] = df5["trend_ok"].reindex(h.index, method="ffill").eq(True)
        h["slope"] = df5["ema50_slope_pct"].reindex(h.index, method="ffill")
        hourly[symbol] = h
        all_times.update(h.index)
    out: List[Candidate] = []
    for t in sorted(all_times):
        choices = []
        for symbol, h in hourly.items():
            if t not in h.index:
                continue
            r = h.loc[t]
            if not np.isfinite(r["ret"]) or not np.isfinite(r["vol_ratio"]):
                continue
            if bool(r["trend_ok"]) and float(r["ret"]) >= min_return and float(r["vol_ratio"]) >= vol_mult:
                choices.append((float(r["ret"]), float(r["vol_ratio"]), symbol, r))
        if not choices:
            continue
        ret, vr, symbol, r = max(choices, key=lambda z: (z[0], z[1]))
        df5 = prepared[symbol]
        if t not in df5.index:
            continue
        entry = next_5m_index(df5, t)
        if entry is None:
            continue
        pos = df5.index.get_loc(t)
        if not isinstance(pos, (int, np.integer)):
            continue
        row = df5.iloc[pos]
        if not np.isfinite(row["atr"]):
            continue
        lo = float(df5.iloc[max(0, pos-11):pos+1]["low"].min())
        stop = lo - 0.10 * float(row["atr"])
        slope = float(r["slope"]) if np.isfinite(r["slope"]) else 0.0
        strength = ret * 100.0 + vr * 0.1
        out.append(candidate(symbol, t, entry, stop, float(r["close"]), strength, slope))
    return out


def generate_for_spec(spec: StrategySpec, prepared: Dict[str, pd.DataFrame], dfs15: Dict[str, pd.DataFrame]) -> List[Candidate]:
    out: List[Candidate] = []
    if spec.family == "relative_strength_rotation":
        return gen_relative_strength(prepared, spec)
    for symbol, df5 in prepared.items():
        if spec.family == "momentum_breakout":
            out.extend(gen_momentum(symbol, df5, dfs15[symbol], spec))
        elif spec.family == "volatility_expansion":
            out.extend(gen_volatility_expansion(symbol, df5, dfs15[symbol], spec))
        elif spec.family == "vwap_mean_reversion":
            out.extend(gen_vwap_mean_reversion(symbol, df5, dfs15[symbol], spec))
        elif spec.family == "trend_pullback_v2":
            out.extend(gen_trend_pullback(symbol, df5, dfs15[symbol], spec))
        else:
            raise ValueError(spec.family)
    return sorted(out, key=lambda c: (c.entry_time, -c.score, c.symbol))


def filter_candidates(candidates: Iterable[Candidate], start: str, end_exclusive: str) -> List[Candidate]:
    s, e = utc(start), utc(end_exclusive)
    return [c for c in candidates if s <= c.entry_time < e]


def eval_period(cands: List[Candidate], prepared: Dict[str, pd.DataFrame], cfg: Config,
                start: str, end_exclusive: str) -> Tuple[Dict, List[Trade]]:
    trades, _ = run_portfolio(filter_candidates(cands, start, end_exclusive), prepared, cfg)
    return summarize(trades, cfg), trades


def finite_pf(v) -> float:
    if pd.isna(v): return -1.0
    if np.isinf(v): return 99.0
    return float(v)


def row_metrics(s: Dict) -> Dict:
    return {
        "trades": int(s.get("trades", 0)),
        "profit_factor": float(s.get("profit_factor", np.nan)),
        "expectancy_r": float(s.get("expectancy_r_budget", np.nan)),
        "max_drawdown_pct": float(s.get("max_drawdown_pct", 0.0)),
        "return_pct": float(s.get("return_pct", 0.0)),
        "net_pnl_usdc": float(s.get("net_pnl_usdc", 0.0)),
        "fees_usdc": float(s.get("fees_usdc", 0.0)),
        "win_rate_pct": float(s.get("win_rate_pct", np.nan)),
    }


def make_cfg(base: Config, spec: StrategySpec, fee=None, slip=None) -> Config:
    return replace(
        base,
        min_stop_pct=spec.min_stop_pct,
        max_stop_pct=spec.max_stop_pct,
        tp1_r=spec.tp1_r,
        tp2_r=spec.tp2_r,
        fee_bps_per_side=base.fee_bps_per_side if fee is None else fee,
        slippage_bps_per_side=base.slippage_bps_per_side if slip is None else slip,
    )


def aggregate_validation(cands, prepared, cfg) -> Tuple[Dict, List[Trade]]:
    all_trades: List[Trade] = []
    for _, _, vs, ve in FOLDS:
        _, tr = eval_period(cands, prepared, cfg, vs, ve)
        all_trades.extend(tr)
    if not all_trades:
        return {"trades": 0, "net_pnl_usdc": 0.0, "profit_factor": np.nan, "expectancy_r_budget": np.nan, "fees_usdc": 0.0}, []
    df = trade_df(all_trades)
    wins = df[df.net_pnl_usdc > 0].net_pnl_usdc.sum()
    losses = -df[df.net_pnl_usdc < 0].net_pnl_usdc.sum()
    return {
        "trades": int(len(df)),
        "net_pnl_usdc": float(df.net_pnl_usdc.sum()),
        "profit_factor": float(wins/losses) if losses > 0 else float("inf"),
        "expectancy_r_budget": float(df.pnl_r_budget.mean()),
        "fees_usdc": float(df.fees_usdc.sum()),
    }, all_trades


def save_trades(path: Path, trades: List[Trade]) -> None:
    df = trade_df(trades)
    df.to_csv(path, index=False)


def save_by_symbol(path: Path, trades: List[Trade]) -> None:
    df = trade_df(trades)
    if df.empty:
        pd.DataFrame().to_csv(path, index=False); return
    df.groupby("symbol").agg(
        trades=("symbol", "size"), net_pnl_usdc=("net_pnl_usdc", "sum"),
        expectancy_r=("pnl_r_budget", "mean"), win_rate=("net_pnl_usdc", lambda x: float((x>0).mean())),
        fees_usdc=("fees_usdc", "sum"),
    ).reset_index().to_csv(path, index=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CRYPTO SCALPER LAB v0.6 Strategy Tournament")
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--equity", type=float, default=2500.0)
    ap.add_argument("--mode", choices=["core", "fast", "full"], default="fast")
    ap.add_argument("--fee-bps", type=float, default=10.0)
    ap.add_argument("--slippage-bps", type=float, default=2.0)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="lab_results_v06")
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--min-val-trades-per-fold", type=int, default=10)
    ap.add_argument("--min-total-val-trades", type=int, default=50)
    ap.add_argument("--min-positive-folds", type=int, default=2)
    ap.add_argument("--min-median-expectancy-r", type=float, default=0.0)
    ap.add_argument("--min-worst-expectancy-r", type=float, default=-0.20)
    ap.add_argument("--max-validation-dd-pct", type=float, default=8.0)
    ap.add_argument("--unlock-holdout", action="store_true")
    ap.add_argument("--holdout-end-exclusive", default="2026-09-01")
    args = ap.parse_args(argv)

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    data_dir = Path(args.data_dir)
    requested = tuple(x.strip().upper().replace("/", "") for x in args.symbols.split(",") if x.strip())

    raw: Dict[str, pd.DataFrame] = {}
    cov = []
    for sym in requested:
        try:
            df = load_symbol(sym, args.start, args.end, data_dir, download=not args.no_download)
            raw[sym] = df
            cov.append({"symbol": sym, "loaded": True, "bars": len(df), "first_bar": str(df.index.min()), "last_bar": str(df.index.max())})
            print(f"[DATA] {sym}: {len(df):,} bars")
        except Exception as exc:
            cov.append({"symbol": sym, "loaded": False, "bars": 0, "error": str(exc)})
            print(f"[SKIP] {sym}: {exc}")
    pd.DataFrame(cov).to_csv(out / "symbol_coverage.csv", index=False)
    if not raw:
        raise RuntimeError("No symbol data loaded")

    symbols = tuple(raw)
    base = Config(
        symbols=symbols, initial_equity_usdc=args.equity,
        fee_bps_per_side=args.fee_bps, slippage_bps_per_side=args.slippage_bps,
        max_trades_24h=4, risk_per_trade=0.003, max_position_fraction=0.4,
    )

    # Feature preparation is shared across strategies and uses only completed bars.
    prepared: Dict[str, pd.DataFrame] = {}
    dfs15: Dict[str, pd.DataFrame] = {}
    for sym, df in raw.items():
        d5, d15, _ = prepare_features(df, base)
        prepared[sym], dfs15[sym] = d5, d15

    specs = build_specs(args.mode)
    print(f"[TOURNAMENT] {len(specs)} strategy variants, {len(symbols)} symbols")

    rows, fold_rows = [], []
    cache: Dict[str, List[Candidate]] = {}
    spec_by_id = {s.strategy_id: s for s in specs}

    for spec in specs:
        sid = spec.strategy_id
        cfg = make_cfg(base, spec)
        cands = generate_for_spec(spec, prepared, dfs15)
        cache[sid] = cands
        fold_metrics = []
        for fold_i, (_, _, vs, ve) in enumerate(FOLDS, start=1):
            s, _tr = eval_period(cands, prepared, cfg, vs, ve)
            m = row_metrics(s)
            fold_metrics.append(m)
            fold_rows.append({"strategy_id": sid, "family": spec.family, "variant": spec.variant, "fold": fold_i, "val_start": vs, "val_end": ve, **m})
        trades = [m["trades"] for m in fold_metrics]
        exps = [m["expectancy_r"] for m in fold_metrics]
        pfs = [finite_pf(m["profit_factor"]) for m in fold_metrics]
        dds = [m["max_drawdown_pct"] for m in fold_metrics]
        positive = sum(1 for x in exps if np.isfinite(x) and x > 0)
        total = int(sum(trades))
        min_tr = int(min(trades)) if trades else 0
        med_exp = float(np.nanmedian(exps)) if exps else np.nan
        worst_exp = float(np.nanmin(exps)) if exps else np.nan
        med_pf = float(np.nanmedian(pfs)) if pfs else np.nan
        worst_dd = float(np.nanmax(dds)) if dds else 0.0
        eligible = bool(
            positive >= args.min_positive_folds and
            min_tr >= args.min_val_trades_per_fold and
            total >= args.min_total_val_trades and
            np.isfinite(med_exp) and med_exp > args.min_median_expectancy_r and
            np.isfinite(worst_exp) and worst_exp >= args.min_worst_expectancy_r and
            worst_dd < args.max_validation_dd_pct
        )
        rows.append({
            "strategy_id": sid, "family": spec.family, "variant": spec.variant,
            "candidate_count": len(cands), "eligible": eligible,
            "positive_val_folds": positive, "total_val_trades": total, "min_val_trades": min_tr,
            "median_val_expectancy_r": med_exp, "worst_val_expectancy_r": worst_exp,
            "median_val_profit_factor": med_pf, "worst_val_drawdown_pct": worst_dd,
            "params": json.dumps(spec.params, sort_keys=True),
            "min_stop_pct": spec.min_stop_pct, "max_stop_pct": spec.max_stop_pct,
            "tp1_r": spec.tp1_r, "tp2_r": spec.tp2_r,
        })
        print(f"[{spec.family}/{spec.variant}] cands={len(cands)} val={trades} pos={positive}/3 medE={med_exp:.3f} eligible={eligible}")

    wf = pd.DataFrame(fold_rows)
    wf.to_csv(out / "walk_forward_all_folds.csv", index=False)
    lb = pd.DataFrame(rows).sort_values(
        ["eligible", "positive_val_folds", "worst_val_expectancy_r", "median_val_expectancy_r", "median_val_profit_factor", "total_val_trades"],
        ascending=[False, False, False, False, False, False], kind="mergesort"
    ).reset_index(drop=True)
    lb.insert(0, "rank", np.arange(1, len(lb)+1))
    lb.to_csv(out / "tournament_leaderboard.csv", index=False)

    # One best variant per family for transparency.
    family_rows = []
    for fam, g in lb.groupby("family", sort=False):
        r = g.iloc[0].to_dict(); family_rows.append(r)
    pd.DataFrame(family_rows).sort_values("rank").to_csv(out / "family_champions.csv", index=False)

    winner_row = lb.iloc[0].to_dict() if not lb.empty else None
    dev_pass = bool(winner_row and winner_row["eligible"])
    selected_id = winner_row["strategy_id"] if winner_row else None
    selected_spec = spec_by_id[selected_id] if selected_id else None

    gate = {
        "development_pass": dev_pass,
        "selected_strategy_id": selected_id,
        "selected_family": selected_spec.family if selected_spec else None,
        "selected_variant": selected_spec.variant if selected_spec else None,
        "required_positive_validation_folds": args.min_positive_folds,
        "required_min_validation_trades_per_fold": args.min_val_trades_per_fold,
        "required_total_validation_trades": args.min_total_val_trades,
        "required_min_median_expectancy_r": args.min_median_expectancy_r,
        "required_min_worst_expectancy_r": args.min_worst_expectancy_r,
        "required_max_validation_dd_pct": args.max_validation_dd_pct,
        "observed_test_status": "pending" if dev_pass else "skipped_due_to_development_fail",
        "sealed_holdout_status": "locked",
        "sealed_holdout_start": SEALED_HOLDOUT_START,
    }
    (out / "development_gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    (out / "SEALED_HOLDOUT_LOCKED.txt").write_text("LOCKED: sealed holdout starts 2026-08-01 and was not evaluated.\n", encoding="utf-8")
    if selected_spec:
        (out / "selected_strategy.json").write_text(json.dumps(asdict(selected_spec), indent=2), encoding="utf-8")

    # Development cost sensitivity for the selected diagnostic/winner.
    if selected_spec:
        sens = []
        for fee, slip, label in [(10,2,"conservative"),(5,1,"lower_cost"),(2,1,"maker_like"),(0,0,"zero_cost")]:
            cfg = make_cfg(base, selected_spec, fee=fee, slip=slip)
            s, _ = aggregate_validation(cache[selected_id], prepared, cfg)
            sens.append({"scenario": label, "fee_bps_per_side": fee, "slippage_bps_per_side": slip,
                         "trades": s.get("trades",0), "net_pnl_usdc": s.get("net_pnl_usdc",0.0),
                         "profit_factor": s.get("profit_factor",np.nan), "expectancy_r": s.get("expectancy_r_budget",np.nan),
                         "fees_usdc": s.get("fees_usdc",0.0)})
        pd.DataFrame(sens).to_csv(out / "development_cost_sensitivity.csv", index=False)

    if not dev_pass:
        print("[GATE] DEVELOPMENT FAIL — observed test skipped; sealed holdout remains locked")
        return 0

    # Observed period is diagnostic only because it has been viewed in prior research.
    cfgw = make_cfg(base, selected_spec)
    obs_s, obs_tr = eval_period(cache[selected_id], prepared, cfgw, OBSERVED_START, OBSERVED_END_EXCLUSIVE)
    (out / "observed_test_summary.json").write_text(json.dumps(obs_s, indent=2), encoding="utf-8")
    save_trades(out / "observed_test_trades.csv", obs_tr)
    save_by_symbol(out / "observed_test_by_symbol.csv", obs_tr)
    gate["observed_test_status"] = "completed_nonsealed_diagnostic"

    if args.unlock_holdout:
        # The default load end is before the holdout, so explicitly reload only now.
        hold_raw: Dict[str, pd.DataFrame] = {}
        for sym in symbols:
            hold_raw[sym] = load_symbol(sym, SEALED_HOLDOUT_START, pd.Timestamp(args.holdout_end_exclusive)-pd.Timedelta(days=1), data_dir, download=not args.no_download)
        hold_prepared, hold15 = {}, {}
        for sym, df in hold_raw.items():
            d5, d15, _ = prepare_features(df, base); hold_prepared[sym]=d5; hold15[sym]=d15
        hc = generate_for_spec(selected_spec, hold_prepared, hold15)
        hs, ht = eval_period(hc, hold_prepared, cfgw, SEALED_HOLDOUT_START, args.holdout_end_exclusive)
        (out / "SEALED_HOLDOUT_summary.json").write_text(json.dumps(hs, indent=2), encoding="utf-8")
        save_trades(out / "SEALED_HOLDOUT_trades.csv", ht)
        gate["sealed_holdout_status"] = "UNLOCKED_AND_EVALUATED"
    (out / "development_gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    print("[GATE] DEVELOPMENT PASS — observed diagnostic completed; holdout", gate["sealed_holdout_status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
