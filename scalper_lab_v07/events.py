from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence
import pandas as pd


def utc_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


@dataclass(frozen=True)
class MarketEvent:
    exchange: str
    symbol: str
    event_time: pd.Timestamp
    receive_time: pd.Timestamp | None = None
    sequence: int | None = None
    raw: Mapping[str, object] = field(default_factory=dict, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "event_time", utc_timestamp(self.event_time))
        if self.receive_time is not None:
            object.__setattr__(self, "receive_time", utc_timestamp(self.receive_time))
        if not self.exchange:
            raise ValueError("exchange is required")
        if not self.symbol:
            raise ValueError("symbol is required")


@dataclass(frozen=True)
class BarEvent(MarketEvent):
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    quote_volume: float | None = None
    trades: int | None = None
    interval: str = "5m"

    def __post_init__(self):
        super().__post_init__()
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC geometry")
        if self.volume < 0:
            raise ValueError("volume cannot be negative")


@dataclass(frozen=True)
class TradeEvent(MarketEvent):
    price: float = 0.0
    quantity: float = 0.0
    side: str | None = None
    trade_id: str | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("trade price and quantity must be positive")
        if self.side not in (None, "buy", "sell"):
            raise ValueError("side must be buy, sell or None")


@dataclass(frozen=True)
class QuoteEvent(MarketEvent):
    bid: float = 0.0
    ask: float = 0.0
    bid_size: float | None = None
    ask_size: float | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.bid <= 0 or self.ask <= 0 or self.ask < self.bid:
            raise ValueError("invalid bid/ask")

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        return 10_000.0 * (self.ask - self.bid) / self.mid


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float

    def __post_init__(self):
        if self.price <= 0 or self.size < 0:
            raise ValueError("invalid order-book level")


@dataclass(frozen=True)
class BookSnapshotEvent(MarketEvent):
    bids: Sequence[BookLevel] = field(default_factory=tuple)
    asks: Sequence[BookLevel] = field(default_factory=tuple)

    def __post_init__(self):
        super().__post_init__()
        if self.bids and self.asks and self.bids[0].price > self.asks[0].price:
            raise ValueError("crossed book snapshot")


@dataclass(frozen=True)
class BookDeltaEvent(MarketEvent):
    side: str = "bid"
    price: float = 0.0
    size: float = 0.0

    def __post_init__(self):
        super().__post_init__()
        if self.side not in ("bid", "ask"):
            raise ValueError("side must be bid or ask")
        if self.price <= 0 or self.size < 0:
            raise ValueError("invalid book delta")
