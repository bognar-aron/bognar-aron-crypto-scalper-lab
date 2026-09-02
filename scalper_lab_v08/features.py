from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import pandas as pd

from scalper_lab_v07.events import TradeEvent
from .orderbook import L2OrderBook


@dataclass(frozen=True)
class MicrostructureSnapshot:
    exchange: str
    symbol: str
    event_time: pd.Timestamp
    receive_time: pd.Timestamp | None
    best_bid: float
    best_ask: float
    mid: float
    spread_bps: float
    bid_size_l1: float
    ask_size_l1: float
    imbalance_l1: float
    imbalance_l5: float
    bid_quote_depth_l5: float
    ask_quote_depth_l5: float
    microprice: float
    microprice_edge_bps: float
    latency_ms: float | None
    trade_flow_imbalance_1s: float | None = None
    trade_flow_imbalance_5s: float | None = None
    signed_quote_1s: float | None = None
    signed_quote_5s: float | None = None


class TradeFlowWindow:
    """Rolling taker-flow state. Buy is positive, sell is negative."""

    def __init__(self, max_seconds: float = 60.0):
        self.max_seconds = float(max_seconds)
        self._events: deque[tuple[pd.Timestamp, float, float]] = deque()

    def add(self, trade: TradeEvent) -> None:
        sign = 1.0 if trade.side == 'buy' else -1.0 if trade.side == 'sell' else 0.0
        quote = float(trade.price) * float(trade.quantity)
        self._events.append((trade.event_time, sign * quote, quote))
        self._purge(trade.event_time)

    def _purge(self, now: pd.Timestamp) -> None:
        cutoff = now - pd.Timedelta(seconds=self.max_seconds)
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def stats(self, now: pd.Timestamp, seconds: float) -> dict[str, float]:
        self._purge(now)
        cutoff = now - pd.Timedelta(seconds=float(seconds))
        signed = 0.0
        gross = 0.0
        count = 0
        for ts, signed_quote, quote in reversed(self._events):
            if ts < cutoff:
                break
            signed += signed_quote
            gross += quote
            count += 1
        return {
            'signed_quote': signed,
            'gross_quote': gross,
            'imbalance': signed / gross if gross > 0 else 0.0,
            'trade_count': float(count),
        }


def snapshot_features(book: L2OrderBook, flow: TradeFlowWindow | None = None) -> MicrostructureSnapshot:
    mid = book.mid
    micro = book.microprice
    latency_ms = None
    if book.receive_time is not None and book.event_time is not None:
        latency_ms = (book.receive_time - book.event_time).total_seconds() * 1000.0
        if not math.isfinite(latency_ms):
            latency_ms = None

    flow1 = flow.stats(book.event_time, 1.0) if flow is not None and book.event_time is not None else None
    flow5 = flow.stats(book.event_time, 5.0) if flow is not None and book.event_time is not None else None
    return MicrostructureSnapshot(
        exchange=book.exchange,
        symbol=book.symbol,
        event_time=book.event_time,
        receive_time=book.receive_time,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        mid=mid,
        spread_bps=book.spread_bps,
        bid_size_l1=book.best_bid_size,
        ask_size_l1=book.best_ask_size,
        imbalance_l1=book.imbalance(1),
        imbalance_l5=book.imbalance(5),
        bid_quote_depth_l5=book.depth('bid', 5, quote_notional=True),
        ask_quote_depth_l5=book.depth('ask', 5, quote_notional=True),
        microprice=micro,
        microprice_edge_bps=10_000.0 * (micro - mid) / mid,
        latency_ms=latency_ms,
        trade_flow_imbalance_1s=flow1['imbalance'] if flow1 else None,
        trade_flow_imbalance_5s=flow5['imbalance'] if flow5 else None,
        signed_quote_1s=flow1['signed_quote'] if flow1 else None,
        signed_quote_5s=flow5['signed_quote'] if flow5 else None,
    )
