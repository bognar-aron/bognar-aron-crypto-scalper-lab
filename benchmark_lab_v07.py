#!/usr/bin/env python3
"""CRYPTO SCALPER LAB v0.7 — benchmark runner using the existing cost/risk engine."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

from backtester import Candidate, Config, load_symbol, run_portfolio, summarize, trade_df
from scalper_lab_v07.benchmarks import BENCHMARK_FACTORIES
from scalper_lab_v07.data import dataframe_to_bars


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


def run_one(strategy_name: str, symbols: tuple[str, ...], start: str, end: str, data_dir: Path, cfg: Config):
    data: Dict[str, pd.DataFrame] = {}
    candidates: List[Candidate] = []
    for symbol in symbols:
        df5 = load_symbol(symbol, start, end, data_dir, download=True)
        data[symbol] = df5
        candidates.extend(signals_to_candidates(symbol, df5, strategy_name))
    trades, skips = run_portfolio(candidates, data, cfg)
    summary = summarize(trades, cfg)
    summary["strategy"] = strategy_name
    summary["candidates"] = len(candidates)
    return summary, trades, skips


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", default="SOLUSDC,BTCUSDC,ETHUSDC,BNBUSDC,XRPUSDC,ADAUSDC,DOGEUSDC")
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2026-07-31")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out", default="runs/v07_benchmarks")
    p.add_argument("--fee-bps", type=float, default=10.0)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    args = p.parse_args(argv)

    symbols = tuple(x.strip().upper().replace("/", "") for x in args.symbols.split(",") if x.strip())
    base_cfg = Config(symbols=symbols, fee_bps_per_side=args.fee_bps, slippage_bps_per_side=args.slippage_bps,
                      min_stop_pct=0.004, max_stop_pct=0.018, tp1_r=1.25, tp2_r=2.5)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    leaderboard = []
    for name in BENCHMARK_FACTORIES:
        summary, trades, skips = run_one(name, symbols, args.start, args.end, Path(args.data_dir), base_cfg)
        leaderboard.append(summary)
        sub = out / name
        sub.mkdir(exist_ok=True)
        trade_df(trades).to_csv(sub / "trades.csv", index=False)
        skips.to_csv(sub / "skips.csv", index=False)
        (sub / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        print(name, summary)

    board = pd.DataFrame(leaderboard).sort_values(["expectancy_r_budget", "profit_factor"], ascending=False, na_position="last")
    board.to_csv(out / "benchmark_leaderboard.csv", index=False)
    print("\n=== v0.7 BENCHMARK LEADERBOARD ===")
    print(board.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
