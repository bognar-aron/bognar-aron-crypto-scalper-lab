from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from scalper_lab_v07.events import BookDeltaEvent, BookLevel, BookSnapshotEvent


class OrderBookStateError(RuntimeError):
    pass


@dataclass
class L2OrderBook:
    """Small deterministic L2 book for research/replay.

    Size==0 deltas delete a level. Sequence checks are enforced only when
    sequence values are present, because not every normalized feed exposes them.
    """

    exchange: str
    symbol: str
    max_levels: int | None = None

    def __post_init__(self):
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.last_sequence: int | None = None
        self.event_time = None
        self.receive_time = None

    def _check_identity(self, exchange: str, symbol: str) -> None:
        if exchange != self.exchange or symbol != self.symbol:
            raise OrderBookStateError(f'event identity mismatch: {exchange} {symbol}')

    def _check_sequence(self, sequence: int | None, snapshot: bool = False) -> None:
        if sequence is None:
            return
        if snapshot or self.last_sequence is None:
            self.last_sequence = sequence
            return
        if sequence <= self.last_sequence:
            raise OrderBookStateError(f'non-increasing sequence: {sequence} <= {self.last_sequence}')
        if sequence != self.last_sequence + 1:
            raise OrderBookStateError(f'sequence gap: expected {self.last_sequence + 1}, got {sequence}')
        self.last_sequence = sequence

    @staticmethod
    def _normalize(levels: Iterable[BookLevel]) -> dict[float, float]:
        out: dict[float, float] = {}
        for level in levels:
            if level.size > 0:
                out[float(level.price)] = float(level.size)
        return out

    def apply_snapshot(self, event: BookSnapshotEvent) -> None:
        self._check_identity(event.exchange, event.symbol)
        self._check_sequence(event.sequence, snapshot=True)
        self.bids = self._normalize(event.bids)
        self.asks = self._normalize(event.asks)
        self.event_time = event.event_time
        self.receive_time = event.receive_time
        self._trim()
        self._validate()

    def apply_delta(self, event: BookDeltaEvent) -> None:
        self._check_identity(event.exchange, event.symbol)
        self._check_sequence(event.sequence)
        side = self.bids if event.side == 'bid' else self.asks
        price = float(event.price)
        if event.size == 0:
            side.pop(price, None)
        else:
            side[price] = float(event.size)
        self.event_time = event.event_time
        self.receive_time = event.receive_time
        self._trim()
        self._validate()

    def _trim(self) -> None:
        if not self.max_levels or self.max_levels <= 0:
            return
        keep_bids = sorted(self.bids, reverse=True)[: self.max_levels]
        keep_asks = sorted(self.asks)[: self.max_levels]
        self.bids = {p: self.bids[p] for p in keep_bids}
        self.asks = {p: self.asks[p] for p in keep_asks}

    def _validate(self) -> None:
        if self.bids and self.asks and self.best_bid >= self.best_ask:
            raise OrderBookStateError(f'crossed/locked book: {self.best_bid} >= {self.best_ask}')

    @property
    def best_bid(self) -> float:
        if not self.bids:
            raise OrderBookStateError('bid book empty')
        return max(self.bids)

    @property
    def best_ask(self) -> float:
        if not self.asks:
            raise OrderBookStateError('ask book empty')
        return min(self.asks)

    @property
    def best_bid_size(self) -> float:
        return self.bids[self.best_bid]

    @property
    def best_ask_size(self) -> float:
        return self.asks[self.best_ask]

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_bps(self) -> float:
        return 10_000.0 * (self.best_ask - self.best_bid) / self.mid

    @property
    def microprice(self) -> float:
        bq = self.best_bid_size
        aq = self.best_ask_size
        total = bq + aq
        if total <= 0:
            return self.mid
        return (self.best_ask * bq + self.best_bid * aq) / total

    def levels(self, side: str, n: int = 5) -> list[tuple[float, float]]:
        if side == 'bid':
            prices = sorted(self.bids, reverse=True)[:n]
            return [(p, self.bids[p]) for p in prices]
        if side == 'ask':
            prices = sorted(self.asks)[:n]
            return [(p, self.asks[p]) for p in prices]
        raise ValueError("side must be 'bid' or 'ask'")

    def depth(self, side: str, n: int = 5, quote_notional: bool = False) -> float:
        lvls = self.levels(side, n)
        if quote_notional:
            return sum(p * q for p, q in lvls)
        return sum(q for _, q in lvls)

    def imbalance(self, n: int = 5, quote_notional: bool = False) -> float:
        bid = self.depth('bid', n, quote_notional)
        ask = self.depth('ask', n, quote_notional)
        total = bid + ask
        return (bid - ask) / total if total > 0 else 0.0
