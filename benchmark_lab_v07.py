#!/usr/bin/env python3
"""CRYPTO SCALPER LAB v0.7 — fixed benchmark strategies under walk-forward validation.

The benchmark layer deliberately uses the existing v0.6 cost/risk engine so strategy
comparisons do not get a different execution model. The 2026-08-01+ sealed holdout
is never loaded by this script.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from backtester import Candidate, Config, load_symbol, run_portfolio, summarize
from scalper_lab_v07.benchmarks import BENCHMARK_FACTORIES
from scalper_lab_v07.data import dataframe_to_bars

FOLDS = [
    ("2024-10-01", "2025-03-01"),
    ("2025-03-01", "2025-09-01"),
    ("2025-09-01", "2026-04-01"),
]
SEALED_HOLDOUT_START = "2026-08-01"


def utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def slice_window(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    return df[(df.index > utc(start)) & (df.index <= utc(end))].copy()


def signals_to_candidates(symbol: str, df5: pd.DataFrame, strategy_name: str) -> List[Candidate]:
    strategy = BENCHMARK_FACTORIES[strategy_name]()
    idx = df5.index
    pos = {t: i for i, t in enumerate(idx)}
    out: List[Candidate] = []
    for bar in dataframe_to_bars(df5, exchange="binance", symbol=symbol, interval="5m"):
        sig = strategy.on_bar(bar)
        if sig is None or sig.side != "long":
            continue
        i = pos[bar.event_time]
        if i + 1 >= len(idx):
            continue
        entry_time = idx[i + 1]
        entry_open = float(df5.iloc[i + 1]["open"])
        stop_raw = entry_open * (1.0 - sig.stop_pct)
        out.append(Candidate(
            symbol=symbol,
            signal_time=bar.event_time,
            entry_time=entry_time,
            stop_raw=stop_raw,
            breakout_level=float(bar.close),
            breakout_volume_ratio=float(sig.strength),
            ema50_slope_pct=0.0,
            score=float(sig.strength),
        ))
    return out


def run_fold(strategy_name: str, data: Dict[str, pd.DataFrame], start: str, end: str, cfg: Config) -> dict:
    fold_data: Dict[str, pd.DataFrame] = {}
    candidates: List[Candidate] = []
    for symbol, full in data.items():
        df5 = slice_window(full, start, end)
        if df5.empty:
            continue
        fold_data[symbol] = df5
        candidates.extend(signals_to_candidates(symbol, df5, strategy_name))
    trades, skips = run_portfolio(candidates, fold_data, cfg)
    summary = summarize(trades, cfg)
    summary.update({
        "strategy": strategy_name,
        "validation_start": start,
        "validation_end": end,
        "candidates": len(candidates),
        "skipped_candidates": int(len(skips)),
    })
    return summary


def aggregate(strategy_name: str, rows: list[dict]) -> dict:
    exp = [float(r.get("expectancy_r_budget", np.nan)) for r in rows]
    dds = [float(r.get("max_drawdown_pct", 0.0)) for r in rows]
    trades = [int(r.get("trades", 0)) for r in rows]
    positive = sum(np.isfinite(x) and x > 0 for x in exp)
    median_exp = float(np.nanmedian(exp)) if any(np.isfinite(x) for x in exp) else np.nan
    worst_exp = float(np.nanmin(exp)) if any(np.isfinite(x) for x in exp) else np.nan
    worst_dd = max(dds) if dds else 0.0
    total_trades = sum(trades)
    min_fold_trades = min(trades) if trades else 0
    eligible = bool(
        positive >= 2 and
        min_fold_trades >= 10 and
        total_trades >= 50 and
        np.isfinite(median_exp) and median_exp > 0 and
        np.isfinite(worst_exp) and worst_exp >= -0.20 and
        worst_dd < 8.0
    )
    return {
        "strategy": strategy_name,
        "eligible": eligible,
        "positive_validation_folds": positive,
        "total_validation_trades": total_trades,
        "min_validation_trades_per_fold": min_fold_trades,
        "median_expectancy_r": median_exp,
        "worst_fold_expectancy_r": worst_exp,
        "worst_validation_drawdown_pct": worst_dd,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="v0.7 fixed benchmark walk-forward lab")
    p.add_argument("--symbols", default="SOLUSDC,BTCUSDC,ETHUSDC,BNBUSDC,XRPUSDC,ADAUSDC,DOGEUSDC")
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2026-07-31", help="must remain before sealed holdout start")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out", default="runs/v07_benchmarks")
    p.add_argument("--fee-bps", type=float, default=10.0)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    args = p.parse_args(argv)

    if utc(args.end) >= utc(SEALED_HOLDOUT_START):
        raise SystemExit(f"Refusing to load sealed holdout. --end must be before {SEALED_HOLDOUT_START}")

    symbols = tuple(x.strip().upper().replace("/", "") for x in args.symbols.split(",") if x.strip())
    cfg = Config(
        symbols=symbols,
        fee_bps_per_side=args.fee_bps,
        slippage_bps_per_side=args.slippage_bps,
        min_stop_pct=0.004,
        max_stop_pct=0.018,
        tp1_r=1.25,
        tp2_r=2.5,
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    data: Dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        print(f"[LOAD] {symbol}")
        data[symbol] = load_symbol(symbol, args.start, args.end, Path(args.data_dir), download=True)

    fold_rows: list[dict] = []
    leaderboard: list[dict] = []
    for name in BENCHMARK_FACTORIES:
        rows = []
        for fold_no, (start, end) in enumerate(FOLDS, 1):
            row = run_fold(name, data, start, end, cfg)
            row["fold"] = fold_no
            rows.append(row)
            fold_rows.append(row)
            print(f"[{name}] fold {fold_no}: trades={row.get('trades', 0)} exp={row.get('expectancy_r_budget', np.nan)}")
        leaderboard.append(aggregate(name, rows))

    folds_df = pd.DataFrame(fold_rows)
    board = pd.DataFrame(leaderboard).sort_values(
        ["eligible", "median_expectancy_r", "positive_validation_folds", "total_validation_trades"],
        ascending=[False, False, False, False], na_position="last",
    )
    folds_df.to_csv(out / "benchmark_walk_forward.csv", index=False)
    board.to_csv(out / "benchmark_leaderboard.csv", index=False)

    eligible = board[board["eligible"] == True]
    gate = {
        "benchmark_pass": bool(len(eligible)),
        "eligible_benchmarks": eligible["strategy"].tolist(),
        "required_positive_validation_folds": 2,
        "required_min_validation_trades_per_fold": 10,
        "required_total_validation_trades": 50,
        "required_median_expectancy_r_gt": 0.0,
        "required_worst_fold_expectancy_r_gte": -0.20,
        "required_worst_validation_drawdown_pct_lt": 8.0,
        "sealed_holdout_status": "locked",
        "sealed_holdout_start": SEALED_HOLDOUT_START,
    }
    (out / "benchmark_gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")

    print("\n=== v0.7 BENCHMARK WALK-FORWARD LEADERBOARD ===")
    print(board.to_string(index=False))
    print("\n", json.dumps(gate, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
