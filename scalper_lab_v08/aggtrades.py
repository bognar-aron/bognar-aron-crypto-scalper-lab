from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

BINANCE_AGG_ARCHIVE = 'https://data.binance.vision/data/spot/monthly/aggTrades'
AGG_COLUMNS = [
    'agg_trade_id', 'price', 'quantity', 'first_trade_id', 'last_trade_id',
    'timestamp', 'buyer_is_maker', 'best_price_match',
]
SEALED_HOLDOUT_START = pd.Timestamp('2026-08-01', tz='UTC')


def _timestamp_unit(value: int) -> str:
    return 'us' if int(value) >= 100_000_000_000_000 else 'ms'


def parse_aggtrades_csv(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), header=None)
    if df.shape[1] < 8:
        raise ValueError(f'unexpected aggTrades format: {df.shape[1]} columns')
    df = df.iloc[:, :8]
    df.columns = AGG_COLUMNS
    df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce')
    df = df.dropna(subset=['timestamp', 'price', 'quantity']).copy()
    if df.empty:
        return df
    unit = _timestamp_unit(int(df['timestamp'].iloc[0]))
    df.index = pd.to_datetime(df['timestamp'].astype('int64'), unit=unit, utc=True)
    df.index.name = 'event_time'
    maker = df['buyer_is_maker'].astype(str).str.lower().isin(['true', '1'])
    df['taker_side'] = np.where(maker, 'sell', 'buy')
    df['quote_notional'] = df['price'] * df['quantity']
    df['signed_quote'] = np.where(df['taker_side'].eq('buy'), df['quote_notional'], -df['quote_notional'])
    return df[['price','quantity','taker_side','quote_notional','signed_quote','agg_trade_id']].sort_index()


def _month_starts(start: str, end: str) -> list[pd.Timestamp]:
    s = pd.Timestamp(start, tz='UTC') if pd.Timestamp(start).tzinfo is None else pd.Timestamp(start).tz_convert('UTC')
    e = pd.Timestamp(end, tz='UTC') if pd.Timestamp(end).tzinfo is None else pd.Timestamp(end).tz_convert('UTC')
    s = s.to_period('M').start_time.tz_localize('UTC')
    e = e.to_period('M').start_time.tz_localize('UTC')
    return list(pd.date_range(s, e, freq='MS', tz='UTC'))


def _guard_sealed(end: str) -> None:
    e = pd.Timestamp(end)
    if e.tzinfo is None:
        e = e.tz_localize('UTC')
    else:
        e = e.tz_convert('UTC')
    if e >= SEALED_HOLDOUT_START:
        raise ValueError('v0.8 historical research refuses data at/after 2026-08-01 sealed holdout')


def download_month(symbol: str, month: pd.Timestamp, data_dir: Path, session: requests.Session) -> Optional[Path]:
    folder = data_dir / 'aggTrades'
    folder.mkdir(parents=True, exist_ok=True)
    ym = month.strftime('%Y-%m')
    cached = folder / f'{symbol}-aggTrades-{ym}.zip'
    if cached.exists() and cached.stat().st_size > 100:
        return cached
    url = f'{BINANCE_AGG_ARCHIVE}/{symbol}/{symbol}-aggTrades-{ym}.zip'
    r = session.get(url, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    cached.write_bytes(r.content)
    return cached


def load_aggtrades(symbol: str, start: str, end: str, data_dir: str | Path, download: bool = True) -> pd.DataFrame:
    _guard_sealed(end)
    data_dir = Path(data_dir)
    session = requests.Session()
    session.headers.update({'User-Agent': 'crypto-scalper-lab-v08/1.0'})
    frames = []
    for month in _month_starts(start, end):
        ym = month.strftime('%Y-%m')
        zpath = data_dir / 'aggTrades' / f'{symbol}-aggTrades-{ym}.zip'
        if not zpath.exists() and download:
            try:
                got = download_month(symbol, month, data_dir, session)
                if got is None:
                    print(f'[WARN] {symbol} {ym}: aggTrades archive not found', file=sys.stderr)
                    continue
                zpath = got
            except Exception as exc:
                print(f'[WARN] {symbol} {ym}: aggTrades download failed: {exc}', file=sys.stderr)
                continue
        if not zpath.exists():
            continue
        try:
            with zipfile.ZipFile(zpath) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith('.csv')]
                if names:
                    frames.append(parse_aggtrades_csv(zf.read(names[0])))
        except Exception as exc:
            print(f'[WARN] {zpath.name}: aggTrades parse failed: {exc}', file=sys.stderr)
    if not frames:
        raise FileNotFoundError(f'no aggTrades loaded for {symbol}')
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep='last')]
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    s = s.tz_localize('UTC') if s.tzinfo is None else s.tz_convert('UTC')
    e = e.tz_localize('UTC') if e.tzinfo is None else e.tz_convert('UTC')
    return df[(df.index >= s) & (df.index < e)].copy()


def tradeflow_1s(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate raw aggregate trades into deterministic 1-second research features."""
    if df.empty:
        return pd.DataFrame()
    x = df.copy()
    x['buy_quote'] = np.where(x['taker_side'].eq('buy'), x['quote_notional'], 0.0)
    x['sell_quote'] = np.where(x['taker_side'].eq('sell'), x['quote_notional'], 0.0)
    x['px_qty'] = x['price'] * x['quantity']
    out = x.resample('1s').agg(
        trade_count=('price','size'),
        base_volume=('quantity','sum'),
        quote_volume=('quote_notional','sum'),
        buy_quote=('buy_quote','sum'),
        sell_quote=('sell_quote','sum'),
        signed_quote=('signed_quote','sum'),
        last_price=('price','last'),
        high_price=('price','max'),
        low_price=('price','min'),
        px_qty=('px_qty','sum'),
    )
    out['vwap'] = out['px_qty'] / out['base_volume'].replace(0, np.nan)
    out['taker_imbalance'] = out['signed_quote'] / out['quote_volume'].replace(0, np.nan)
    out['trade_count'] = out['trade_count'].fillna(0).astype('int32')
    for c in ['base_volume','quote_volume','buy_quote','sell_quote','signed_quote']:
        out[c] = out[c].fillna(0.0)
    out['taker_imbalance'] = out['taker_imbalance'].fillna(0.0)
    out['last_price'] = out['last_price'].ffill()
    out['vwap'] = out['vwap'].fillna(out['last_price'])
    out['ret_1s_bps'] = 10_000.0 * out['last_price'].pct_change(fill_method=None)
    out['signed_quote_5s'] = out['signed_quote'].rolling(5, min_periods=1).sum()
    out['quote_volume_5s'] = out['quote_volume'].rolling(5, min_periods=1).sum()
    out['taker_imbalance_5s'] = out['signed_quote_5s'] / out['quote_volume_5s'].replace(0, np.nan)
    out['taker_imbalance_5s'] = out['taker_imbalance_5s'].fillna(0.0)
    out['signed_quote_30s'] = out['signed_quote'].rolling(30, min_periods=1).sum()
    out['quote_volume_30s'] = out['quote_volume'].rolling(30, min_periods=1).sum()
    out['taker_imbalance_30s'] = out['signed_quote_30s'] / out['quote_volume_30s'].replace(0, np.nan)
    out['taker_imbalance_30s'] = out['taker_imbalance_30s'].fillna(0.0)
    return out.drop(columns=['px_qty'])


def iter_aggtrade_months(symbol: str, start: str, end: str, data_dir: str | Path, download: bool = True):
    """Yield one filtered month at a time to keep tick-scale research memory bounded."""
    _guard_sealed(end)
    data_dir = Path(data_dir)
    session = requests.Session()
    session.headers.update({'User-Agent': 'crypto-scalper-lab-v08/1.0'})
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    s = s.tz_localize('UTC') if s.tzinfo is None else s.tz_convert('UTC')
    e = e.tz_localize('UTC') if e.tzinfo is None else e.tz_convert('UTC')
    for month in _month_starts(start, end):
        ym = month.strftime('%Y-%m')
        zpath = data_dir / 'aggTrades' / f'{symbol}-aggTrades-{ym}.zip'
        if not zpath.exists() and download:
            try:
                got = download_month(symbol, month, data_dir, session)
                if got is None:
                    print(f'[WARN] {symbol} {ym}: aggTrades archive not found', file=sys.stderr)
                    continue
                zpath = got
            except Exception as exc:
                print(f'[WARN] {symbol} {ym}: aggTrades download failed: {exc}', file=sys.stderr)
                continue
        if not zpath.exists():
            continue
        with zipfile.ZipFile(zpath) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith('.csv')]
            if not names:
                continue
            df = parse_aggtrades_csv(zf.read(names[0]))
        df = df[(df.index >= s) & (df.index < e)].copy()
        if not df.empty:
            yield ym, df
