import pandas as pd
import pytest

from scalper_lab_v07.events import BarEvent, QuoteEvent, BookDeltaEvent
from scalper_lab_v07.data import DataGapError, validate_monotonic_events
from scalper_lab_v07.benchmarks import EMATrendBenchmark, DonchianBreakoutBenchmark
from benchmark_lab_v07 import aggregate


def test_quote_spread_bps():
    q = QuoteEvent(exchange="x", symbol="BTCUSDC", event_time="2026-01-01", bid=100, ask=101)
    assert q.mid == 100.5
    assert 99 < q.spread_bps < 100


def test_sequence_gap_detection():
    ev = [
        BookDeltaEvent(exchange="x", symbol="BTCUSDC", event_time="2026-01-01T00:00:00Z", sequence=1, side="bid", price=100, size=1),
        BookDeltaEvent(exchange="x", symbol="BTCUSDC", event_time="2026-01-01T00:00:01Z", sequence=3, side="bid", price=100, size=2),
    ]
    with pytest.raises(DataGapError):
        validate_monotonic_events(ev, require_sequence=True)


def test_ema_strategy_emits_after_cross():
    s = EMATrendBenchmark(fast=2, slow=4)
    closes = [4, 3, 2, 2, 3, 5, 7]
    got = []
    for i, c in enumerate(closes):
        b = BarEvent(exchange="x", symbol="AUSDC", event_time=pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=5*i),
                     open=c, high=c+0.2, low=c-0.2, close=c, volume=10)
        got.append(s.on_bar(b))
    assert any(x is not None for x in got)


def test_donchian_requires_history():
    s = DonchianBreakoutBenchmark(lookback=3, volume_lookback=3, volume_mult=1.0)
    out = []
    for i, c in enumerate([1, 1.1, 1.2]):
        out.append(s.on_bar(BarEvent(exchange="x", symbol="AUSDC", event_time=f"2026-01-01T00:{i:02d}:00Z",
                                          open=c, high=c, low=c, close=c, volume=10)))
    assert out == [None, None, None]


def test_walk_forward_gate_requires_robustness():
    rows = [
        {"expectancy_r_budget": 0.15, "max_drawdown_pct": 2.0, "trades": 20},
        {"expectancy_r_budget": 0.08, "max_drawdown_pct": 3.0, "trades": 20},
        {"expectancy_r_budget": -0.10, "max_drawdown_pct": 4.0, "trades": 20},
    ]
    result = aggregate("x", rows)
    assert result["eligible"] is True
    rows[2]["expectancy_r_budget"] = -0.30
    assert aggregate("x", rows)["eligible"] is False
