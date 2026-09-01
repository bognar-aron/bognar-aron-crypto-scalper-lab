from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from .events import BarEvent, MarketEvent


class DataGapError(RuntimeError):
    pass


def dataframe_to_bars(df: pd.DataFrame, exchange: str, symbol: str, interval: str = "5m") -> Iterator[BarEvent]:
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"missing OHLCV columns: {sorted(missing)}")
    for ts, row in df.sort_index().iterrows():
        yield BarEvent(
            exchange=exchange,
            symbol=symbol,
            event_time=ts,
            open=float(row["open"]), high=float(row["high"]), low=float(row["low"]), close=float(row["close"]),
            volume=float(row["volume"]),
            quote_volume=float(row["quote_volume"]) if "quote_volume" in row and pd.notna(row["quote_volume"]) else None,
            trades=int(row["trades"]) if "trades" in row and pd.notna(row["trades"]) else None,
            interval=interval,
        )


def validate_monotonic_events(events: Iterable[MarketEvent], require_sequence: bool = False) -> list[MarketEvent]:
    out = list(events)
    prev_time = None
    prev_seq = None
    for e in out:
        if prev_time is not None and e.event_time < prev_time:
            raise DataGapError("event_time moved backwards")
        if require_sequence:
            if e.sequence is None:
                raise DataGapError("sequence required but missing")
            if prev_seq is not None and e.sequence != prev_seq + 1:
                raise DataGapError(f"sequence gap: expected {prev_seq + 1}, got {e.sequence}")
            prev_seq = e.sequence
        prev_time = e.event_time
    return out


class ParquetEventStore:
    """Simple phase-1 columnar store. PyArrow is intentionally an optional dependency."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _partition(self, event: MarketEvent, feed_type: str) -> Path:
        date = event.event_time.strftime("%Y-%m-%d")
        return self.root / f"exchange={event.exchange}" / f"symbol={event.symbol}" / f"feed={feed_type}" / f"date={date}"

    def append(self, events: Iterable[MarketEvent], feed_type: str) -> list[Path]:
        grouped: dict[Path, list[dict]] = {}
        for e in events:
            grouped.setdefault(self._partition(e, feed_type), []).append(asdict(e))
        written = []
        for folder, rows in grouped.items():
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "part.parquet"
            new = pd.DataFrame(rows)
            if path.exists():
                old = pd.read_parquet(path)
                new = pd.concat([old, new], ignore_index=True)
            new.to_parquet(path, index=False)
            written.append(path)
        return written


class CCXTRestAdapter:
    """Thin optional adapter. Importing this module does not require CCXT."""

    def __init__(self, exchange_id: str, params: dict | None = None):
        try:
            import ccxt  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install ccxt") from exc
        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"unknown CCXT exchange: {exchange_id}")
        self.exchange_id = exchange_id
        self.client = getattr(ccxt, exchange_id)(params or {"enableRateLimit": True})

    def fetch_ohlcv(self, symbol: str, timeframe: str = "5m", since_ms: int | None = None, limit: int = 1000) -> pd.DataFrame:
        rows = self.client.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        if df.empty:
            return df
        df.index = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True)
        df.index.name = "bar_end"
        return df.astype(float)
