#!/usr/bin/env python3
"""
CRYPTO SCALPER v0.5-engine backtester

USDC spot backtest for BTCUSDC, ETHUSDC, SOLUSDC.
Strategy: 1h trend filter -> 15m volume breakout -> 5m VWAP/EMA20/breakout-level pullback -> 5m trigger.

Design goals:
- no lookahead: signals use completed bars only; entries occur at next 5m open
- conservative intrabar ordering
- fees + slippage modeled separately
- one global portfolio, at most one open position across all symbols
- rolling risk controls and kill switch
- Binance public monthly kline archive downloader, no API key required

This is research/backtesting software, not an execution bot.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

BINANCE_ARCHIVE = "https://data.binance.vision/data/spot/monthly/klines"
KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_base",
    "taker_buy_quote", "ignore",
]


@dataclass
class Config:
    symbols: Tuple[str, ...] = ("BTCUSDC", "ETHUSDC", "SOLUSDC")
    initial_equity_usdc: float = 2500.0
    risk_per_trade: float = 0.003
    max_position_fraction: float = 0.40
    max_open_positions: int = 1
    max_trades_24h: int = 4

    fee_bps_per_side: float = 10.0
    slippage_bps_per_side: float = 2.0

    ema_fast_1h: int = 50
    ema_slow_1h: int = 200
    ema_slope_lookback_1h: int = 3

    breakout_lookback_15m: int = 12
    breakout_volume_median_15m: int = 20
    breakout_volume_multiple: float = 1.5

    pullback_expiry_minutes: int = 30
    pullback_min_retrace: float = 0.25
    pullback_max_retrace: float = 0.60

    ema_pullback_5m: int = 20
    trigger_volume_median_5m: int = 20
    trigger_volume_multiple: float = 1.1
    atr_period_5m: int = 14
    atr_stop_buffer: float = 0.15
    min_stop_pct: float = 0.0025
    max_stop_pct: float = 0.0080

    tp1_r: float = 1.0
    tp2_r: float = 2.0
    tp1_fraction: float = 0.40
    tp2_fraction: float = 0.60
    time_stop_minutes: int = 90
    time_stop_mfe_r: float = 0.50

    consecutive_loss_count: int = 3
    consecutive_loss_cooldown_hours: int = 6
    loss_24h_pct: float = 0.01
    loss_24h_cooldown_hours: int = 12
    loss_7d_pct: float = 0.03
    loss_7d_cooldown_hours: int = 48
    kill_switch_drawdown_pct: float = 0.10

    # If multiple symbols signal for the same entry candle, the strongest score wins.
    # score = breakout volume ratio + small normalized EMA slope bonus
    score_slope_weight: float = 0.10


@dataclass
class Candidate:
    symbol: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    stop_raw: float
    breakout_level: float
    breakout_volume_ratio: float
    ema50_slope_pct: float
    score: float


@dataclass
class Trade:
    symbol: str
    signal_time: str
    entry_time: str
    exit_time: str
    entry_raw: float
    entry_exec: float
    initial_stop_raw: float
    final_stop_raw: float
    tp1_raw: float
    tp2_raw: float
    position_quote_usdc: float
    quantity: float
    risk_budget_usdc: float
    actual_initial_risk_usdc: float
    exit_reason: str
    tp1_hit: bool
    gross_pnl_usdc: float
    fees_usdc: float
    net_pnl_usdc: float
    pnl_r_budget: float
    pnl_pct_equity_before: float
    equity_before: float
    equity_after: float
    duration_minutes: float
    mfe_r: float
    mae_r: float
    breakout_volume_ratio: float
    ema50_slope_pct: float


def utc(ts) -> pd.Timestamp:
    x = pd.Timestamp(ts)
    if x.tzinfo is None:
        return x.tz_localize("UTC")
    return x.tz_convert("UTC")


def month_starts(start: str, end: str) -> List[pd.Timestamp]:
    s = utc(start).to_period("M").start_time.tz_localize("UTC")
    e = utc(end).to_period("M").start_time.tz_localize("UTC")
    return list(pd.date_range(s, e, freq="MS", tz="UTC"))


def _timestamp_unit(series: pd.Series) -> str:
    # Binance spot archive uses microseconds from 2025-01-01 onward.
    value = int(pd.to_numeric(series, errors="coerce").dropna().iloc[0])
    return "us" if value >= 100_000_000_000_000 else "ms"


def parse_kline_csv(raw: bytes, interval_minutes: int = 5) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), header=None)
    if df.shape[1] < 12:
        raise ValueError(f"Unexpected Binance kline format: {df.shape[1]} columns")
    df = df.iloc[:, :12]
    df.columns = KLINE_COLUMNS

    # Some archive variants can include a textual header. Remove it if present.
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    df = df.dropna(subset=["open_time"]).copy()
    unit = _timestamp_unit(df["open_time"])

    num_cols = ["open", "high", "low", "close", "volume", "quote_volume", "trades"]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "volume", "quote_volume"])

    open_dt = pd.to_datetime(df["open_time"].astype("int64"), unit=unit, utc=True)
    # Use exact bar end labels so 00:05, 00:10, 00:15 aggregate cleanly.
    df.index = open_dt + pd.Timedelta(minutes=interval_minutes)
    df.index.name = "bar_end"
    return df[["open", "high", "low", "close", "volume", "quote_volume", "trades"]].sort_index()


def download_month(symbol: str, month: pd.Timestamp, data_dir: Path, session: requests.Session) -> Optional[Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    ym = month.strftime("%Y-%m")
    cached = data_dir / f"{symbol}-5m-{ym}.zip"
    if cached.exists() and cached.stat().st_size > 100:
        return cached

    url = f"{BINANCE_ARCHIVE}/{symbol}/5m/{symbol}-5m-{ym}.zip"
    r = session.get(url, timeout=45)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    cached.write_bytes(r.content)
    return cached


def load_symbol(symbol: str, start: str, end: str, data_dir: Path, download: bool = True) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    months = month_starts(start, end)
    session = requests.Session()
    session.headers.update({"User-Agent": "crypto-scalper-v0.5-engine-research/1.0"})

    for month in months:
        ym = month.strftime("%Y-%m")
        zpath = data_dir / f"{symbol}-5m-{ym}.zip"
        if not zpath.exists() and download:
            try:
                downloaded = download_month(symbol, month, data_dir, session)
                if downloaded is None:
                    print(f"[WARN] {symbol} {ym}: archive not found; skipped", file=sys.stderr)
                    continue
                zpath = downloaded
            except Exception as exc:
                print(f"[WARN] {symbol} {ym}: download failed: {exc}", file=sys.stderr)
                continue

        if not zpath.exists():
            continue
        try:
            with zipfile.ZipFile(zpath) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not names:
                    raise ValueError("ZIP contains no CSV")
                frames.append(parse_kline_csv(zf.read(names[0]), interval_minutes=5))
        except Exception as exc:
            print(f"[WARN] {zpath.name}: parse failed: {exc}", file=sys.stderr)

    if not frames:
        raise FileNotFoundError(
            f"No 5m data loaded for {symbol}. Use --download with internet access, "
            f"or place Binance monthly ZIPs in {data_dir}."
        )

    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    start_ts, end_ts = utc(start), utc(end)
    return df[(df.index > start_ts) & (df.index <= end_ts + pd.Timedelta(days=1))].copy()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = df.resample(rule, label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "quote_volume": "sum", "trades": "sum",
    })
    return out.dropna(subset=["open", "high", "low", "close"])


def prepare_features(df5: pd.DataFrame, cfg: Config) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df5 = df5.copy()

    # True daily VWAP from Binance quote/base volume, anchored 00:00 UTC.
    day = df5.index.floor("D")
    cum_qv = df5["quote_volume"].groupby(day).cumsum()
    cum_vol = df5["volume"].groupby(day).cumsum().replace(0, np.nan)
    df5["vwap"] = cum_qv / cum_vol
    df5["ema20"] = df5["close"].ewm(span=cfg.ema_pullback_5m, adjust=False).mean()
    df5["vol_med20"] = df5["volume"].shift(1).rolling(cfg.trigger_volume_median_5m).median()
    df5["atr"] = true_range(df5).rolling(cfg.atr_period_5m).mean()

    df15 = resample_ohlcv(df5, "15min")
    # VWAP at 15m close equals the most recent 5m cumulative VWAP.
    df15["vwap"] = df5["vwap"].reindex(df15.index, method="ffill")
    df15["prior_high"] = df15["high"].shift(1).rolling(cfg.breakout_lookback_15m).max()
    df15["vol_median"] = df15["volume"].shift(1).rolling(cfg.breakout_volume_median_15m).median()
    df15["volume_ratio"] = df15["volume"] / df15["vol_median"]
    df15["breakout"] = (
        (df15["close"] > df15["prior_high"]) &
        (df15["volume_ratio"] >= cfg.breakout_volume_multiple) &
        (df15["close"] > df15["vwap"])
    )

    df1h = resample_ohlcv(df5, "1h")
    df1h["ema50"] = df1h["close"].ewm(span=cfg.ema_fast_1h, adjust=False).mean()
    df1h["ema200"] = df1h["close"].ewm(span=cfg.ema_slow_1h, adjust=False).mean()
    df1h["ema50_prev"] = df1h["ema50"].shift(cfg.ema_slope_lookback_1h)
    df1h["ema50_slope_pct"] = df1h["ema50"] / df1h["ema50_prev"] - 1.0
    df1h["trend_ok"] = (
        (df1h["close"] > df1h["ema50"]) &
        (df1h["ema50"] > df1h["ema200"]) &
        (df1h["ema50"] > df1h["ema50_prev"])
    )

    # Align only completed 1h bars to each completed 5m bar.
    df5["trend_ok"] = df1h["trend_ok"].reindex(df5.index, method="ffill").eq(True)
    df5["ema50_slope_pct"] = df1h["ema50_slope_pct"].reindex(df5.index, method="ffill")

    return df5, df15, df1h


def generate_candidates(symbol: str, df5: pd.DataFrame, df15: pd.DataFrame, cfg: Config) -> List[Candidate]:
    """State-machine signal generation. A breakout creates one active setup for <=30 minutes."""
    candidates: List[Candidate] = []
    breakout_rows = df15[df15["breakout"]].copy()
    if breakout_rows.empty:
        return candidates

    breakout_map = {t: row for t, row in breakout_rows.iterrows()}
    idx = df5.index
    active = None

    for i, t in enumerate(idx):
        # A completed 15m breakout can activate at its close.
        if t in breakout_map and active is None:
            br = breakout_map[t]
            impulse_low = float(br["low"])
            impulse_high = float(br["high"])
            impulse_range = impulse_high - impulse_low
            if impulse_range > 0 and np.isfinite(impulse_range):
                active = {
                    "breakout_time": t,
                    "expiry": t + pd.Timedelta(minutes=cfg.pullback_expiry_minutes),
                    "impulse_low": impulse_low,
                    "impulse_high": impulse_high,
                    "impulse_range": impulse_range,
                    "breakout_level": float(br["prior_high"]),
                    "volume_ratio": float(br["volume_ratio"]),
                    "pullback_touched": False,
                    "pullback_low": math.inf,
                }

        if active is None:
            continue
        if t <= active["breakout_time"]:
            continue
        if t > active["expiry"]:
            active = None
            continue

        row = df5.loc[t]
        if not np.isfinite(row.get("atr", np.nan)):
            continue

        active["pullback_low"] = min(active["pullback_low"], float(row["low"]))
        retrace = (active["impulse_high"] - active["pullback_low"]) / active["impulse_range"]

        # Once the setup retraces too deeply, it is invalid, even if it later bounces.
        if retrace > cfg.pullback_max_retrace:
            active = None
            continue

        if retrace >= cfg.pullback_min_retrace:
            levels = [float(row["ema20"]), float(row["vwap"]), active["breakout_level"]]
            touched = any(np.isfinite(level) and float(row["low"]) <= level <= float(row["high"]) for level in levels)
            active["pullback_touched"] = active["pullback_touched"] or touched

        if not active["pullback_touched"] or i == 0:
            continue

        prev = df5.iloc[i - 1]
        trigger = (
            bool(row["trend_ok"]) and
            float(row["close"]) > float(row["open"]) and
            float(row["close"]) > float(prev["high"]) and
            float(row["close"]) > float(row["vwap"]) and
            np.isfinite(row["vol_med20"]) and
            float(row["volume"]) >= cfg.trigger_volume_multiple * float(row["vol_med20"])
        )
        if not trigger:
            continue

        # Entry is strictly at the NEXT completed 5m candle's open.
        if i + 1 >= len(idx):
            active = None
            continue
        entry_time = idx[i + 1]
        stop_raw = active["pullback_low"] - cfg.atr_stop_buffer * float(row["atr"])
        slope = float(row["ema50_slope_pct"]) if np.isfinite(row["ema50_slope_pct"]) else 0.0
        score = active["volume_ratio"] + cfg.score_slope_weight * max(0.0, slope * 10_000.0)
        candidates.append(Candidate(
            symbol=symbol,
            signal_time=t,
            entry_time=entry_time,
            stop_raw=float(stop_raw),
            breakout_level=float(active["breakout_level"]),
            breakout_volume_ratio=float(active["volume_ratio"]),
            ema50_slope_pct=slope,
            score=float(score),
        ))
        active = None

    return candidates


def side_costs(cfg: Config) -> Tuple[float, float]:
    return cfg.fee_bps_per_side / 10_000.0, cfg.slippage_bps_per_side / 10_000.0


def simulate_trade(
    cand: Candidate,
    df5: pd.DataFrame,
    equity: float,
    cfg: Config,
) -> Optional[Trade]:
    if cand.entry_time not in df5.index:
        return None
    entry_i = df5.index.get_loc(cand.entry_time)
    if not isinstance(entry_i, (int, np.integer)):
        return None

    fee_rate, slip = side_costs(cfg)
    entry_raw = float(df5.iloc[entry_i]["open"])
    entry_exec = entry_raw * (1.0 + slip)
    if cand.stop_raw <= 0 or cand.stop_raw >= entry_raw:
        return None

    stop_pct = (entry_raw - cand.stop_raw) / entry_raw
    if not (cfg.min_stop_pct <= stop_pct <= cfg.max_stop_pct):
        return None

    risk_budget = equity * cfg.risk_per_trade
    position_quote = min(risk_budget / stop_pct, equity * cfg.max_position_fraction)
    if position_quote <= 0:
        return None
    quantity = position_quote / entry_exec
    initial_risk_usdc = quantity * (entry_exec - cand.stop_raw)

    R_raw = entry_raw - cand.stop_raw
    tp1_raw = entry_raw + cfg.tp1_r * R_raw
    tp2_raw = entry_raw + cfg.tp2_r * R_raw
    # Approximate raw price needed to recover entry + exit fee/slippage burden.
    roundtrip_cost = 2.0 * (fee_rate + slip)
    breakeven_raw = entry_raw * (1.0 + roundtrip_cost)

    remaining = quantity
    tp1_hit = False
    final_stop = cand.stop_raw
    gross_pnl = 0.0
    fees = quantity * entry_exec * fee_rate  # entry fee
    mfe = -math.inf
    mae = math.inf
    exit_time = cand.entry_time
    exit_reason = "DATA_END"

    def sell(qty: float, raw_price: float) -> Tuple[float, float]:
        exec_price = raw_price * (1.0 - slip)
        gross = qty * (exec_price - entry_exec)
        fee = qty * exec_price * fee_rate
        return gross, fee

    start_time = cand.entry_time
    max_end = start_time + pd.Timedelta(minutes=max(cfg.time_stop_minutes + 60, 180))
    window = df5.iloc[entry_i:]

    for t, row in window.iterrows():
        if t > max_end and not tp1_hit:
            # Safety only; normal time-stop below should have closed it.
            pass

        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        mfe = max(mfe, (high - entry_raw) / R_raw)
        mae = min(mae, (low - entry_raw) / R_raw)

        if not tp1_hit:
            # Conservative ambiguity rule: if stop and TP1 are both inside one candle,
            # assume stop happened first.
            if low <= final_stop:
                g, f = sell(remaining, final_stop)
                gross_pnl += g
                fees += f
                remaining = 0.0
                exit_time = t
                exit_reason = "STOP"
                break
            if high >= tp1_raw:
                qty1 = quantity * cfg.tp1_fraction
                g, f = sell(qty1, tp1_raw)
                gross_pnl += g
                fees += f
                remaining -= qty1
                tp1_hit = True
                final_stop = max(final_stop, breakeven_raw)

                # TP2 can also be reached in the same candle. Since stop could not have
                # occurred first (we checked the original stop), allow TP2 after TP1.
                if high >= tp2_raw:
                    g, f = sell(remaining, tp2_raw)
                    gross_pnl += g
                    fees += f
                    remaining = 0.0
                    exit_time = t
                    exit_reason = "TP2"
                    break
        else:
            # Conservative once TP1 was hit in a prior candle: if BE stop and TP2 are
            # both possible in this candle, assume the stop happened first.
            if low <= final_stop:
                g, f = sell(remaining, final_stop)
                gross_pnl += g
                fees += f
                remaining = 0.0
                exit_time = t
                exit_reason = "BE_STOP_AFTER_TP1"
                break
            if high >= tp2_raw:
                g, f = sell(remaining, tp2_raw)
                gross_pnl += g
                fees += f
                remaining = 0.0
                exit_time = t
                exit_reason = "TP2"
                break

        elapsed = (t - start_time).total_seconds() / 60.0
        if elapsed >= cfg.time_stop_minutes and mfe < cfg.time_stop_mfe_r:
            g, f = sell(remaining, close)
            gross_pnl += g
            fees += f
            remaining = 0.0
            exit_time = t
            exit_reason = "TIME_STOP"
            break

    if remaining > 0:
        # Dataset ended while position was still open: close at last available close.
        row = window.iloc[-1]
        exit_time = window.index[-1]
        g, f = sell(remaining, float(row["close"]))
        gross_pnl += g
        fees += f
        remaining = 0.0
        exit_reason = "DATA_END"

    net = gross_pnl - fees
    equity_after = equity + net
    duration = (exit_time - cand.entry_time).total_seconds() / 60.0

    return Trade(
        symbol=cand.symbol,
        signal_time=cand.signal_time.isoformat(),
        entry_time=cand.entry_time.isoformat(),
        exit_time=exit_time.isoformat(),
        entry_raw=entry_raw,
        entry_exec=entry_exec,
        initial_stop_raw=cand.stop_raw,
        final_stop_raw=final_stop,
        tp1_raw=tp1_raw,
        tp2_raw=tp2_raw,
        position_quote_usdc=position_quote,
        quantity=quantity,
        risk_budget_usdc=risk_budget,
        actual_initial_risk_usdc=initial_risk_usdc,
        exit_reason=exit_reason,
        tp1_hit=tp1_hit,
        gross_pnl_usdc=gross_pnl,
        fees_usdc=fees,
        net_pnl_usdc=net,
        pnl_r_budget=net / risk_budget if risk_budget else np.nan,
        pnl_pct_equity_before=net / equity if equity else np.nan,
        equity_before=equity,
        equity_after=equity_after,
        duration_minutes=duration,
        mfe_r=float(mfe),
        mae_r=float(mae),
        breakout_volume_ratio=cand.breakout_volume_ratio,
        ema50_slope_pct=cand.ema50_slope_pct,
    )


def trade_df(trades: List[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    return pd.DataFrame([asdict(t) for t in trades])


def risk_gate(now: pd.Timestamp, equity: float, peak_equity: float, trades: List[Trade], cfg: Config) -> Tuple[bool, str]:
    dd = 1.0 - equity / peak_equity if peak_equity > 0 else 0.0
    if dd >= cfg.kill_switch_drawdown_pct:
        return False, "KILL_SWITCH_DRAWDOWN"

    if not trades:
        return True, "OK"

    tdf = trade_df(trades)
    tdf["entry_time_dt"] = pd.to_datetime(tdf["entry_time"], utc=True)
    tdf["exit_time_dt"] = pd.to_datetime(tdf["exit_time"], utc=True)

    # Max 4 entries in any rolling 24h.
    recent_entries = tdf[tdf["entry_time_dt"] > now - pd.Timedelta(hours=24)]
    if len(recent_entries) >= cfg.max_trades_24h:
        return False, "MAX_TRADES_24H"

    if len(tdf) >= cfg.consecutive_loss_count:
        lastn = tdf.iloc[-cfg.consecutive_loss_count:]
        if (lastn["net_pnl_usdc"] < 0).all():
            cool_until = lastn["exit_time_dt"].iloc[-1] + pd.Timedelta(hours=cfg.consecutive_loss_cooldown_hours)
            if now < cool_until:
                return False, "CONSECUTIVE_LOSS_COOLDOWN"

    last24 = tdf[tdf["exit_time_dt"] > now - pd.Timedelta(hours=24)]
    if not last24.empty and last24["net_pnl_usdc"].sum() <= -cfg.loss_24h_pct * equity:
        cool_until = last24["exit_time_dt"].max() + pd.Timedelta(hours=cfg.loss_24h_cooldown_hours)
        if now < cool_until:
            return False, "LOSS_24H_COOLDOWN"

    last7d = tdf[tdf["exit_time_dt"] > now - pd.Timedelta(days=7)]
    if not last7d.empty and last7d["net_pnl_usdc"].sum() <= -cfg.loss_7d_pct * equity:
        cool_until = last7d["exit_time_dt"].max() + pd.Timedelta(hours=cfg.loss_7d_cooldown_hours)
        if now < cool_until:
            return False, "LOSS_7D_COOLDOWN"

    return True, "OK"


def run_portfolio(candidates: List[Candidate], data: Dict[str, pd.DataFrame], cfg: Config) -> Tuple[List[Trade], pd.DataFrame]:
    # Same entry timestamp: higher score wins. Globally one open position.
    candidates = sorted(candidates, key=lambda c: (c.entry_time, -c.score, c.symbol))
    equity = cfg.initial_equity_usdc
    peak_equity = equity
    occupied_until = pd.Timestamp.min.tz_localize("UTC")
    trades: List[Trade] = []
    skips = []
    accepted_entry_times = set()

    for cand in candidates:
        if cand.entry_time in accepted_entry_times:
            skips.append((cand.symbol, cand.entry_time, "LOWER_SCORE_SAME_TIME"))
            continue
        if cand.entry_time <= occupied_until:
            skips.append((cand.symbol, cand.entry_time, "POSITION_ALREADY_OPEN"))
            continue
        allowed, reason = risk_gate(cand.entry_time, equity, peak_equity, trades, cfg)
        if not allowed:
            skips.append((cand.symbol, cand.entry_time, reason))
            if reason == "KILL_SWITCH_DRAWDOWN":
                break
            continue

        trade = simulate_trade(cand, data[cand.symbol], equity, cfg)
        if trade is None:
            skips.append((cand.symbol, cand.entry_time, "INVALID_AT_ENTRY"))
            continue

        trades.append(trade)
        accepted_entry_times.add(cand.entry_time)
        equity = trade.equity_after
        peak_equity = max(peak_equity, equity)
        occupied_until = pd.Timestamp(trade.exit_time)

    skip_df = pd.DataFrame(skips, columns=["symbol", "entry_time", "reason"])
    return trades, skip_df


def summarize(trades: List[Trade], cfg: Config) -> Dict[str, float | int | str]:
    if not trades:
        return {
            "trades": 0,
            "start_equity_usdc": cfg.initial_equity_usdc,
            "end_equity_usdc": cfg.initial_equity_usdc,
            "net_pnl_usdc": 0.0,
        }
    df = trade_df(trades)
    wins = df[df["net_pnl_usdc"] > 0]
    losses = df[df["net_pnl_usdc"] < 0]
    gross_profit = wins["net_pnl_usdc"].sum()
    gross_loss_abs = -losses["net_pnl_usdc"].sum()
    profit_factor = gross_profit / gross_loss_abs if gross_loss_abs > 0 else np.inf

    equity = pd.Series([cfg.initial_equity_usdc] + df["equity_after"].tolist(), dtype=float)
    peak = equity.cummax()
    dd = 1.0 - equity / peak

    return {
        "trades": int(len(df)),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate_pct": float(100.0 * len(wins) / len(df)),
        "profit_factor": float(profit_factor),
        "expectancy_r_budget": float(df["pnl_r_budget"].mean()),
        "avg_win_r_budget": float(wins["pnl_r_budget"].mean()) if len(wins) else np.nan,
        "avg_loss_r_budget": float(losses["pnl_r_budget"].mean()) if len(losses) else np.nan,
        "max_drawdown_pct": float(100.0 * dd.max()),
        "start_equity_usdc": float(cfg.initial_equity_usdc),
        "end_equity_usdc": float(df["equity_after"].iloc[-1]),
        "net_pnl_usdc": float(df["net_pnl_usdc"].sum()),
        "return_pct": float(100.0 * (df["equity_after"].iloc[-1] / cfg.initial_equity_usdc - 1.0)),
        "fees_usdc": float(df["fees_usdc"].sum()),
        "avg_duration_minutes": float(df["duration_minutes"].mean()),
        "tp1_hit_rate_pct": float(100.0 * df["tp1_hit"].mean()),
        "pass_trade_count_150": bool(len(df) >= 150),
        "pass_profit_factor_1_30": bool(profit_factor > 1.30),
        "pass_expectancy_0_10r": bool(df["pnl_r_budget"].mean() > 0.10),
        "pass_max_dd_8pct": bool(100.0 * dd.max() < 8.0),
    }


def write_report(out_dir: Path, trades: List[Trade], skips: pd.DataFrame, summary: Dict, cfg: Config) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    tdf = trade_df(trades)
    tdf.to_csv(out_dir / "trades.csv", index=False)
    skips.to_csv(out_dir / "skipped_candidates.csv", index=False)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (out_dir / "config_used.json").write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")

    if not tdf.empty:
        eq = tdf[["exit_time", "equity_after", "symbol", "net_pnl_usdc"]].copy()
        eq.to_csv(out_dir / "equity_curve.csv", index=False)
        by_symbol = tdf.groupby("symbol").agg(
            trades=("symbol", "size"),
            net_pnl_usdc=("net_pnl_usdc", "sum"),
            avg_r=("pnl_r_budget", "mean"),
            win_rate=("net_pnl_usdc", lambda s: float((s > 0).mean())),
            fees_usdc=("fees_usdc", "sum"),
        )
        by_symbol.to_csv(out_dir / "by_symbol.csv")


def parse_symbols(s: str) -> Tuple[str, ...]:
    return tuple(x.strip().upper().replace("/", "") for x in s.split(",") if x.strip())


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="CRYPTO SCALPER v0.5-engine USDC spot backtester")
    p.add_argument("--start", default="2025-01-01", help="UTC start date")
    p.add_argument("--end", default="2026-07-31", help="UTC end date; completed archive months recommended")
    p.add_argument("--symbols", default="BTCUSDC,ETHUSDC,SOLUSDC")
    p.add_argument("--equity", type=float, default=2500.0, help="Starting equity in USDC")
    p.add_argument("--data-dir", default="data", help="Cache/input directory for Binance monthly ZIPs")
    p.add_argument("--out", default="results", help="Output directory")
    p.add_argument("--no-download", action="store_true", help="Do not download; use cached ZIP files only")
    args = p.parse_args(argv)

    cfg = Config(symbols=parse_symbols(args.symbols), initial_equity_usdc=args.equity)
    data_dir = Path(args.data_dir)
    out_dir = Path(args.out)

    all_data: Dict[str, pd.DataFrame] = {}
    all_candidates: List[Candidate] = []

    for symbol in cfg.symbols:
        print(f"[LOAD] {symbol} {args.start} -> {args.end}")
        raw = load_symbol(symbol, args.start, args.end, data_dir, download=not args.no_download)
        df5, df15, _ = prepare_features(raw, cfg)
        candidates = generate_candidates(symbol, df5, df15, cfg)
        print(f"[SIGNALS] {symbol}: {len(candidates)} candidates")
        all_data[symbol] = df5
        all_candidates.extend(candidates)

    print(f"[PORTFOLIO] candidates: {len(all_candidates)}")
    trades, skips = run_portfolio(all_candidates, all_data, cfg)
    summary = summarize(trades, cfg)
    write_report(out_dir, trades, skips, summary, cfg)

    print("\n=== CRYPTO SCALPER v0.5-engine SUMMARY ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"\nResults written to: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
