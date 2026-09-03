#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scalper_lab_v08.l2_conditioning import (
    BOOK_IMBALANCE_CONFIRM,
    FROZEN_FLOW_FEATURE,
    FROZEN_FLOW_THRESHOLD,
    MICROPRICE_EDGE_CONFIRM_BPS,
    OPPOSING_DEPTH_RATIO_MAX,
    TIGHT_SPREAD_MAX_BPS,
    MakerFillConfig,
    condition_diagnostics,
    load_jsonl,
    maker_fill_summary,
    simulate_maker_fills,
)

PROTOCOL = {
    "version": "v0.8.2",
    "research_type": "prospective_l2_conditioning_and_shadow_maker_fill",
    "flow_feature": FROZEN_FLOW_FEATURE,
    "flow_threshold_abs": FROZEN_FLOW_THRESHOLD,
    "conditioning_thresholds": {
        "book_imbalance_l5_signed_min": BOOK_IMBALANCE_CONFIRM,
        "microprice_edge_signed_min_bps": MICROPRICE_EDGE_CONFIRM_BPS,
        "opposing_to_same_l5_depth_ratio_max": OPPOSING_DEPTH_RATIO_MAX,
        "tight_spread_max_bps": TIGHT_SPREAD_MAX_BPS,
    },
    "signal_cooldown_seconds": 5,
    "forward_horizons_seconds": [1, 5, 30],
    "maker_model": {
        "order_notional_quote": 100.0,
        "ttl_seconds": 5.0,
        "queue_ahead_fraction": 1.0,
        "fill_rule": "only actual opposing aggressive trades at-or-through entry consume visible queue plus our order quantity",
        "cancellation_credit": "none",
        "scope": "one-sided passive entry fill and post-fill markout; not a full round-trip PnL model",
    },
    "selection_rule": "thresholds are frozen before prospective capture and must not be retuned from this dataset",
    "live_trading_status": "disabled",
}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="CRYPTO SCALPER LAB v0.8.2 L2 Conditioning + Maker Fill Lab")
    p.add_argument("--capture-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    capture = Path(args.capture_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "v082_protocol.json").write_text(json.dumps(PROTOCOL, indent=2), encoding="utf-8")

    snaps = load_jsonl(capture / "microstructure.jsonl")
    trades = load_jsonl(capture / "trades.jsonl")
    if snaps.empty or trades.empty:
        raise RuntimeError("capture has no usable microstructure/trade rows")

    cond = condition_diagnostics(snaps)
    fills = simulate_maker_fills(snaps, trades, MakerFillConfig())
    fill_summary = maker_fill_summary(fills)
    cond.to_csv(out / "l2_condition_diagnostics.csv", index=False)
    fills.to_csv(out / "maker_shadow_fills.csv", index=False)
    fill_summary.to_csv(out / "maker_fill_summary.csv", index=False)

    gate = {
        "protocol_version": "v0.8.2",
        "capture_snapshots": int(len(snaps)),
        "capture_trades": int(len(trades)),
        "signals": int(len(fills)),
        "full_confirm_signals": int(fills["full_confirm"].sum()) if len(fills) else 0,
        "maker_fills": int(fills["filled"].sum()) if len(fills) else 0,
        "data_sufficiency_pass": bool(
            len(fills) >= 100 and
            (int(fills["full_confirm"].sum()) if len(fills) else 0) >= 25 and
            (int(fills["filled"].sum()) if len(fills) else 0) >= 25
        ),
        "strategy_profitability_pass": False,
        "live_candidate_pass": False,
        "reason": "v0.8.2 is a prospective conditioning/fill-model research phase, not a round-trip strategy backtest",
    }
    (out / "v082_gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    print(json.dumps(gate, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
