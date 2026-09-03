import pandas as pd

from scalper_lab_v08.l2_conditioning import (
    MakerFillConfig,
    add_condition_columns,
    condition_diagnostics,
    maker_fill_summary,
    select_nonoverlap_signals,
    simulate_maker_fills,
)


def snapshots():
    idx = pd.date_range("2026-09-03T00:00:00Z", periods=80, freq="100ms")
    rows = []
    for t in idx:
        rows.append({
            "exchange": "binance", "symbol": "BTC-USDC", "event_time": t, "receive_time": t,
            "best_bid": 100.0, "best_ask": 100.02, "mid": 100.01, "spread_bps": 1.9998,
            "bid_size_l1": 1.0, "ask_size_l1": 0.5,
            "imbalance_l1": 1/3, "imbalance_l5": 0.5,
            "bid_quote_depth_l5": 1000.0, "ask_quote_depth_l5": 500.0,
            "microprice": 100.015, "microprice_edge_bps": 0.5,
            "latency_ms": 1.0, "trade_flow_imbalance_1s": 0.7,
            "trade_flow_imbalance_5s": 0.7, "signed_quote_1s": 100, "signed_quote_5s": 500,
        })
    return pd.DataFrame(rows)


def test_condition_columns_and_signal_cooldown():
    s = snapshots()
    x = add_condition_columns(s)
    assert x["book_confirm"].all()
    assert x["microprice_confirm"].all()
    assert x["thin_opposing"].all()
    assert not x["tight_spread"].any()
    sig = select_nonoverlap_signals(s, cooldown_seconds=5)
    assert len(sig) == 2


def test_condition_diagnostics_has_rows():
    s = snapshots()
    s["mid"] = 100.0 + (pd.Series(range(len(s))) * 0.001)
    s["best_bid"] = s["mid"] - .01
    s["best_ask"] = s["mid"] + .01
    d = condition_diagnostics(s, horizons=(1,5))
    assert set(d["condition"]) >= {"flow_only", "book_confirm", "full_confirm"}
    assert set(d["horizon_s"]) == {1,5}


def test_conservative_maker_fill_requires_queue_plus_order():
    s = snapshots()
    s["spread_bps"] = 1.0
    t0 = s.iloc[0]["event_time"]
    trades = pd.DataFrame([
        {"symbol":"BTC-USDC","event_time":t0+pd.Timedelta(seconds=1),"price":100.0,"quantity":0.6,"side":"sell"},
        {"symbol":"BTC-USDC","event_time":t0+pd.Timedelta(seconds=2),"price":100.0,"quantity":1.5,"side":"sell"},
    ])
    fills = simulate_maker_fills(s, trades, MakerFillConfig(order_notional_quote=10, ttl_seconds=5, queue_ahead_fraction=1.0))
    first = fills.iloc[0]
    assert first["filled"]
    assert first["fill_time"] == t0 + pd.Timedelta(seconds=2)
    assert first["full_confirm"]


def test_maker_fill_summary():
    s = snapshots()
    s["spread_bps"] = 1.0
    t0 = s.iloc[0]["event_time"]
    trades = pd.DataFrame([
        {"symbol":"BTC-USDC","event_time":t0+pd.Timedelta(seconds=1),"price":100.0,"quantity":3.0,"side":"sell"},
    ])
    fills = simulate_maker_fills(s, trades, MakerFillConfig(order_notional_quote=10, ttl_seconds=5))
    summary = maker_fill_summary(fills)
    assert "fill_rate" in summary.columns
