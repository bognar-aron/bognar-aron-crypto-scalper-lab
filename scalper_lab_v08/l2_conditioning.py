from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Iterable

import numpy as np
import pandas as pd

FROZEN_FLOW_FEATURE = "trade_flow_imbalance_5s"
FROZEN_FLOW_THRESHOLD = 0.60
BOOK_IMBALANCE_CONFIRM = 0.25
MICROPRICE_EDGE_CONFIRM_BPS = 0.05
OPPOSING_DEPTH_RATIO_MAX = 0.80
TIGHT_SPREAD_MAX_BPS = 1.50
SIGNAL_COOLDOWN_SECONDS = 5
FORWARD_HORIZONS = (1, 5, 30)


def load_jsonl(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for c in ("event_time", "receive_time"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df.sort_values(["symbol", "event_time"]).reset_index(drop=True)


def add_condition_columns(df: pd.DataFrame) -> pd.DataFrame:
    required = {
        FROZEN_FLOW_FEATURE, "imbalance_l5", "microprice_edge_bps", "spread_bps",
        "bid_quote_depth_l5", "ask_quote_depth_l5",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing L2 feature columns: {sorted(missing)}")
    x = df.copy()
    flow = pd.to_numeric(x[FROZEN_FLOW_FEATURE], errors="coerce").fillna(0.0)
    sign = np.sign(flow)
    x["signal_sign"] = sign.astype("int8")
    x["strong_flow"] = flow.abs().ge(FROZEN_FLOW_THRESHOLD)
    x["book_confirm"] = (sign * pd.to_numeric(x["imbalance_l5"], errors="coerce").fillna(0.0)).ge(BOOK_IMBALANCE_CONFIRM)
    x["microprice_confirm"] = (sign * pd.to_numeric(x["microprice_edge_bps"], errors="coerce").fillna(0.0)).ge(MICROPRICE_EDGE_CONFIRM_BPS)

    bid_depth = pd.to_numeric(x["bid_quote_depth_l5"], errors="coerce")
    ask_depth = pd.to_numeric(x["ask_quote_depth_l5"], errors="coerce")
    same = np.where(sign >= 0, bid_depth, ask_depth)
    opp = np.where(sign >= 0, ask_depth, bid_depth)
    ratio = np.divide(opp, same, out=np.full(len(x), np.nan, dtype=float), where=np.asarray(same) > 0)
    x["opposing_to_same_depth_ratio_l5"] = ratio
    x["thin_opposing"] = pd.Series(ratio, index=x.index).le(OPPOSING_DEPTH_RATIO_MAX)
    x["tight_spread"] = pd.to_numeric(x["spread_bps"], errors="coerce").le(TIGHT_SPREAD_MAX_BPS)
    x["full_confirm"] = (
        x["strong_flow"] & x["book_confirm"] & x["microprice_confirm"]
        & x["thin_opposing"] & x["tight_spread"]
    )
    return x


def select_nonoverlap_signals(df: pd.DataFrame, cooldown_seconds: int = SIGNAL_COOLDOWN_SECONDS) -> pd.DataFrame:
    x = add_condition_columns(df)
    x = x[x["strong_flow"] & x["event_time"].notna()].copy()
    if x.empty:
        return x
    picked = []
    delta = pd.Timedelta(seconds=int(cooldown_seconds))
    for _, g in x.groupby("symbol", sort=False):
        last = None
        for idx, row in g.sort_values("event_time").iterrows():
            t = row["event_time"]
            if last is None or t >= last + delta:
                picked.append(idx)
                last = t
    return x.loc[picked].sort_values(["symbol", "event_time"]).reset_index(drop=True)


def _future_mid(snaps: pd.DataFrame, symbol: str, target: pd.Timestamp, tolerance_ms: int = 500) -> float:
    g = snaps[snaps["symbol"].eq(symbol)]
    if g.empty:
        return np.nan
    times = g["event_time"].to_numpy(dtype="datetime64[ns]")
    target64 = np.datetime64(target.tz_convert("UTC").tz_localize(None))
    pos = np.searchsorted(times, target64, side="left")
    if pos >= len(g):
        return np.nan
    row = g.iloc[int(pos)]
    if row["event_time"] > target + pd.Timedelta(milliseconds=tolerance_ms):
        return np.nan
    return float(row["mid"])


def condition_diagnostics(snapshots: pd.DataFrame, horizons: Iterable[int] = FORWARD_HORIZONS) -> pd.DataFrame:
    snaps = add_condition_columns(snapshots)
    signals = select_nonoverlap_signals(snaps)
    rows = []
    labels = {
        "flow_only": pd.Series(True, index=signals.index),
        "book_confirm": signals["book_confirm"],
        "microprice_confirm": signals["microprice_confirm"],
        "thin_opposing": signals["thin_opposing"],
        "full_confirm": signals["full_confirm"],
    }
    for label, mask in labels.items():
        sub = signals[mask].copy()
        for h in horizons:
            aligned = []
            for _, r in sub.iterrows():
                future = _future_mid(snaps, r["symbol"], r["event_time"] + pd.Timedelta(seconds=int(h)))
                if np.isfinite(future) and float(r["mid"]) > 0:
                    aligned.append(float(r["signal_sign"]) * 10000.0 * (future / float(r["mid"]) - 1.0))
            s = pd.Series(aligned, dtype=float)
            rows.append({
                "condition": label,
                "horizon_s": int(h),
                "signals": int(len(sub)),
                "observations": int(len(s)),
                "mean_aligned_fwd_bps": float(s.mean()) if len(s) else np.nan,
                "median_aligned_fwd_bps": float(s.median()) if len(s) else np.nan,
                "hit_rate": float((s > 0).mean()) if len(s) else np.nan,
                "p90_bps": float(s.quantile(.90)) if len(s) else np.nan,
                "p95_bps": float(s.quantile(.95)) if len(s) else np.nan,
            })
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class MakerFillConfig:
    order_notional_quote: float = 100.0
    ttl_seconds: float = 5.0
    queue_ahead_fraction: float = 1.0
    min_signal_cooldown_seconds: int = SIGNAL_COOLDOWN_SECONDS


def _eligible_trade_volume(trades: pd.DataFrame, sign: int, entry_price: float, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    g = trades[(trades["event_time"] > start) & (trades["event_time"] <= end)].copy()
    if sign > 0:
        return g[g["side"].eq("sell") & (pd.to_numeric(g["price"], errors="coerce") <= entry_price)]
    return g[g["side"].eq("buy") & (pd.to_numeric(g["price"], errors="coerce") >= entry_price)]


def simulate_maker_fills(
    snapshots: pd.DataFrame,
    trades: pd.DataFrame,
    config: MakerFillConfig = MakerFillConfig(),
) -> pd.DataFrame:
    snaps = add_condition_columns(snapshots)
    signals = select_nonoverlap_signals(snaps, cooldown_seconds=config.min_signal_cooldown_seconds)
    trades = trades.copy()
    trades["event_time"] = pd.to_datetime(trades["event_time"], utc=True, errors="coerce")
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["quantity"] = pd.to_numeric(trades["quantity"], errors="coerce")
    rows = []
    for _, sig in signals.iterrows():
        sign = int(sig["signal_sign"])
        if sign == 0:
            continue
        entry_price = float(sig["best_bid"] if sign > 0 else sig["best_ask"])
        displayed = float(sig["bid_size_l1"] if sign > 0 else sig["ask_size_l1"])
        qty = float(config.order_notional_quote) / entry_price
        queue_ahead = max(0.0, displayed * float(config.queue_ahead_fraction))
        required = queue_ahead + qty
        expiry = sig["event_time"] + pd.Timedelta(seconds=float(config.ttl_seconds))
        eligible = _eligible_trade_volume(
            trades[trades["symbol"].eq(sig["symbol"])],
            sign, entry_price, sig["event_time"], expiry
        ).sort_values("event_time")
        cum = 0.0
        fill_time = pd.NaT
        for _, tr in eligible.iterrows():
            cum += float(tr["quantity"])
            if cum >= required:
                fill_time = tr["event_time"]
                break
        filled = pd.notna(fill_time)
        row = {
            "symbol": sig["symbol"],
            "signal_time": sig["event_time"],
            "signal_sign": sign,
            "entry_price": entry_price,
            "order_quantity": qty,
            "visible_queue_ahead_qty": queue_ahead,
            "required_trade_through_qty": required,
            "ttl_seconds": float(config.ttl_seconds),
            "filled": bool(filled),
            "fill_time": fill_time if filled else None,
            "fill_latency_ms": (fill_time - sig["event_time"]).total_seconds() * 1000.0 if filled else np.nan,
            "strong_flow": bool(sig["strong_flow"]),
            "book_confirm": bool(sig["book_confirm"]),
            "microprice_confirm": bool(sig["microprice_confirm"]),
            "thin_opposing": bool(sig["thin_opposing"]),
            "tight_spread": bool(sig["tight_spread"]),
            "full_confirm": bool(sig["full_confirm"]),
            "spread_bps_at_signal": float(sig["spread_bps"]),
            "flow_imbalance_5s": float(sig[FROZEN_FLOW_FEATURE]),
            "book_imbalance_l5": float(sig["imbalance_l5"]),
            "microprice_edge_bps": float(sig["microprice_edge_bps"]),
        }
        if filled:
            for h in FORWARD_HORIZONS:
                future = _future_mid(snaps, sig["symbol"], fill_time + pd.Timedelta(seconds=h))
                row[f"maker_entry_markout_{h}s_bps"] = (
                    sign * 10000.0 * (future / entry_price - 1.0)
                    if np.isfinite(future) and entry_price > 0 else np.nan
                )
        else:
            for h in FORWARD_HORIZONS:
                row[f"maker_entry_markout_{h}s_bps"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def maker_fill_summary(fills: pd.DataFrame) -> pd.DataFrame:
    if fills.empty:
        return pd.DataFrame()
    groups = {
        "flow_only": pd.Series(True, index=fills.index),
        "book_confirm": fills["book_confirm"].astype(bool),
        "microprice_confirm": fills["microprice_confirm"].astype(bool),
        "thin_opposing": fills["thin_opposing"].astype(bool),
        "full_confirm": fills["full_confirm"].astype(bool),
    }
    rows = []
    for label, mask in groups.items():
        g = fills[mask].copy()
        filled = g[g["filled"]].copy()
        row = {
            "condition": label,
            "signals": int(len(g)),
            "fills": int(len(filled)),
            "fill_rate": float(len(filled) / len(g)) if len(g) else np.nan,
            "median_fill_latency_ms": float(filled["fill_latency_ms"].median()) if len(filled) else np.nan,
        }
        for h in FORWARD_HORIZONS:
            c = f"maker_entry_markout_{h}s_bps"
            row[f"mean_markout_{h}s_bps"] = float(filled[c].mean()) if len(filled) else np.nan
            row[f"median_markout_{h}s_bps"] = float(filled[c].median()) if len(filled) else np.nan
            row[f"positive_markout_{h}s_fraction"] = float((filled[c] > 0).mean()) if len(filled) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)
