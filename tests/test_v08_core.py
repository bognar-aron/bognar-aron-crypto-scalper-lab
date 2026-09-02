import pandas as pd
import pytest

from scalper_lab_v07.events import BookDeltaEvent, BookLevel, BookSnapshotEvent, TradeEvent
from scalper_lab_v08.aggtrades import parse_aggtrades_csv, tradeflow_1s
from scalper_lab_v08.features import TradeFlowWindow, snapshot_features
from scalper_lab_v08.orderbook import L2OrderBook, OrderBookStateError


def ts(s='2026-01-01T00:00:00Z'):
    return pd.Timestamp(s)


def test_l2_snapshot_and_microprice():
    b = L2OrderBook('binance', 'BTC-USDC')
    evt = BookSnapshotEvent(exchange='binance', symbol='BTC-USDC', event_time=ts(), receive_time=ts('2026-01-01T00:00:00.010Z'),
        bids=(BookLevel(100, 3), BookLevel(99, 2)), asks=(BookLevel(101, 1), BookLevel(102, 2)))
    b.apply_snapshot(evt)
    assert b.best_bid == 100
    assert b.best_ask == 101
    assert b.imbalance(1) == pytest.approx(0.5)
    assert b.microprice == pytest.approx((101*3 + 100*1)/4)
    snap = snapshot_features(b)
    assert snap.microprice_edge_bps > 0
    assert snap.latency_ms == pytest.approx(10.0)


def test_sequence_gap_rejected():
    b = L2OrderBook('binance', 'BTC-USDC')
    b.apply_snapshot(BookSnapshotEvent(exchange='binance', symbol='BTC-USDC', event_time=ts(), sequence=10,
        bids=(BookLevel(100,1),), asks=(BookLevel(101,1),)))
    with pytest.raises(OrderBookStateError):
        b.apply_delta(BookDeltaEvent(exchange='binance', symbol='BTC-USDC', event_time=ts('2026-01-01T00:00:01Z'), sequence=12, side='bid', price=100, size=2))


def test_tradeflow_window():
    f = TradeFlowWindow(60)
    f.add(TradeEvent(exchange='binance',symbol='BTC-USDC',event_time=ts(),price=100,quantity=2,side='buy'))
    f.add(TradeEvent(exchange='binance',symbol='BTC-USDC',event_time=ts('2026-01-01T00:00:00.5Z'),price=100,quantity=1,side='sell'))
    s = f.stats(ts('2026-01-01T00:00:00.5Z'), 1)
    assert s['signed_quote'] == pytest.approx(100)
    assert s['gross_quote'] == pytest.approx(300)
    assert s['imbalance'] == pytest.approx(1/3)


def test_parse_aggtrades_microseconds_and_side():
    raw = b'1,100.0,2.0,1,2,1767225600000000,False,True\n2,101.0,1.0,3,3,1767225600100000,True,True\n'
    df = parse_aggtrades_csv(raw)
    assert str(df.index.tz) == 'UTC'
    assert df.iloc[0]['taker_side'] == 'buy'
    assert df.iloc[1]['taker_side'] == 'sell'
    assert df.iloc[0]['signed_quote'] == pytest.approx(200)
    assert df.iloc[1]['signed_quote'] == pytest.approx(-101)


def test_tradeflow_1s_aggregation():
    idx = pd.to_datetime(['2026-01-01T00:00:00.1Z','2026-01-01T00:00:00.2Z','2026-01-01T00:00:01.1Z'])
    df = pd.DataFrame({
        'price':[100,100,101], 'quantity':[1,2,1], 'taker_side':['buy','sell','buy'],
        'quote_notional':[100,200,101], 'signed_quote':[100,-200,101], 'agg_trade_id':[1,2,3]
    }, index=idx)
    out = tradeflow_1s(df)
    assert out.iloc[0]['trade_count'] == 2
    assert out.iloc[0]['signed_quote'] == pytest.approx(-100)
    assert out.iloc[0]['taker_imbalance'] == pytest.approx(-1/3)
    assert out.iloc[1]['signed_quote_5s'] == pytest.approx(1)
