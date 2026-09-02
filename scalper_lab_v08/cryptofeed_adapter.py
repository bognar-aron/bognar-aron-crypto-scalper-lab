from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import time
from typing import Iterable

import pandas as pd

from scalper_lab_v07.events import BookLevel, BookSnapshotEvent, TradeEvent
from .features import TradeFlowWindow, snapshot_features
from .orderbook import L2OrderBook


def _ts(value) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp.now(tz='UTC')
    if isinstance(value, (int, float)):
        return pd.to_datetime(float(value), unit='s', utc=True)
    x = pd.Timestamp(value)
    return x.tz_localize('UTC') if x.tzinfo is None else x.tz_convert('UTC')


class JsonlSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.count = 0

    def write(self, row: dict) -> None:
        clean = {}
        for k, v in row.items():
            clean[k] = v.isoformat() if isinstance(v, pd.Timestamp) else v
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(clean, ensure_ascii=False, default=str) + '\n')
        self.count += 1


class CryptofeedMicrostructureRecorder:
    """Public-data-only live recorder.

    Cryptofeed is imported lazily, so research/unit tests do not depend on it.
    Each L2 callback is normalized to our own BookSnapshotEvent contract and
    reduced to a feature snapshot. Trades are stored separately and also feed
    rolling taker-flow features.
    """

    def __init__(self, out_dir: str | Path, depth: int = 10, snapshot_interval_ms: int = 100):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.depth = int(depth)
        self.snapshot_interval_ms = int(snapshot_interval_ms)
        self.books: dict[tuple[str, str], L2OrderBook] = {}
        self.flows: dict[tuple[str, str], TradeFlowWindow] = {}
        self.last_snapshot_ns: dict[tuple[str, str], int] = {}
        self.trade_sink = JsonlSink(self.out_dir / 'trades.jsonl')
        self.feature_sink = JsonlSink(self.out_dir / 'microstructure.jsonl')

    def _key(self, exchange: str, symbol: str) -> tuple[str, str]:
        return exchange.lower(), symbol.upper()

    async def on_trade(self, t, receipt_timestamp):
        key = self._key(str(t.exchange), str(t.symbol))
        evt = TradeEvent(
            exchange=key[0], symbol=key[1],
            event_time=_ts(getattr(t, 'timestamp', None)),
            receive_time=_ts(receipt_timestamp),
            price=float(t.price), quantity=float(t.amount),
            side=str(t.side).lower() if getattr(t, 'side', None) else None,
            trade_id=str(getattr(t, 'id', '')) or None,
        )
        self.flows.setdefault(key, TradeFlowWindow(max_seconds=60)).add(evt)
        self.trade_sink.write({
            'exchange': evt.exchange, 'symbol': evt.symbol,
            'event_time': evt.event_time, 'receive_time': evt.receive_time,
            'price': evt.price, 'quantity': evt.quantity, 'side': evt.side,
            'trade_id': evt.trade_id,
        })

    async def on_book(self, b, receipt_timestamp):
        key = self._key(str(b.exchange), str(b.symbol))
        now_ns = time.monotonic_ns()
        min_ns = self.snapshot_interval_ms * 1_000_000
        prev = self.last_snapshot_ns.get(key)
        if prev is not None and now_ns - prev < min_ns:
            return
        self.last_snapshot_ns[key] = now_ns

        bids = []
        asks = []
        for i in range(self.depth):
            try:
                p, q = b.book.bids.index(i)
                bids.append(BookLevel(float(p), float(q)))
            except (IndexError, TypeError):
                break
        for i in range(self.depth):
            try:
                p, q = b.book.asks.index(i)
                asks.append(BookLevel(float(p), float(q)))
            except (IndexError, TypeError):
                break
        if not bids or not asks:
            return
        evt = BookSnapshotEvent(
            exchange=key[0], symbol=key[1],
            event_time=_ts(getattr(b, 'timestamp', None)),
            receive_time=_ts(receipt_timestamp),
            bids=tuple(bids), asks=tuple(asks),
        )
        book = self.books.setdefault(key, L2OrderBook(key[0], key[1], max_levels=self.depth))
        book.apply_snapshot(evt)
        snap = snapshot_features(book, self.flows.get(key))
        self.feature_sink.write(asdict(snap))

    async def capture(self, symbols: Iterable[str], seconds: int = 300, exchange: str = 'BINANCE') -> dict:
        try:
            from cryptofeed import FeedHandler
            from cryptofeed.defines import L2_BOOK, TRADES
            from cryptofeed.exchanges import Binance
        except ImportError as exc:
            raise RuntimeError('Install live dependency: pip install cryptofeed>=2.5,<3') from exc

        if exchange.upper() != 'BINANCE':
            raise ValueError('v0.8 phase-1 live recorder currently supports BINANCE only')
        fh = FeedHandler(on_feed_error='raise')
        fh.add_feed(Binance(
            symbols=list(symbols), channels=[TRADES, L2_BOOK],
            callbacks={TRADES: self.on_trade, L2_BOOK: self.on_book},
            max_depth=self.depth,
        ))
        task = asyncio.create_task(fh.run_async(install_signal_handlers=False))
        try:
            await asyncio.sleep(int(seconds))
        finally:
            fh.request_stop()
            await task
        result = {
            'capture_seconds': int(seconds),
            'symbols': list(symbols),
            'trades_written': self.trade_sink.count,
            'microstructure_snapshots_written': self.feature_sink.count,
            'output_dir': str(self.out_dir),
        }
        (self.out_dir / 'capture_manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
