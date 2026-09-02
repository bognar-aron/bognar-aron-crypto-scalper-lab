#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import pandas as pd

from scalper_lab_v08.aggtrades import iter_aggtrade_months, tradeflow_1s
from scalper_lab_v08.cryptofeed_adapter import CryptofeedMicrostructureRecorder
from scalper_lab_v08.diagnostics import diagnostic_summary, flow_predictive_diagnostics


def _norm_spot_symbol(raw: str) -> str:
    return raw.strip().upper().replace('/', '').replace('-', '')


def _norm_feed_symbol(raw: str) -> str:
    s = raw.strip().upper().replace('/', '-')
    if '-' in s:
        return s
    for quote in ('USDC','USDT','USD','EUR','BTC','ETH'):
        if s.endswith(quote) and len(s) > len(quote):
            return f'{s[:-len(quote)]}-{quote}'
    return s


def run_tradeflow(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    diagnostic_rows = []

    for raw_symbol in args.symbols.split(','):
        symbol = _norm_spot_symbol(raw_symbol)
        if not symbol:
            continue
        print(f'[AGGTRADES] {symbol} {args.start} -> {args.end}')
        symbol_root = out / 'tradeflow' / f'symbol={symbol}'
        symbol_root.mkdir(parents=True, exist_ok=True)
        symbol_summaries = []
        for ym, raw in iter_aggtrade_months(symbol, args.start, args.end, args.data_dir, download=not args.no_download):
            one = tradeflow_1s(raw)
            month_dir = symbol_root / f'month={ym}'
            month_dir.mkdir(parents=True, exist_ok=True)
            path = month_dir / 'part.parquet'
            try:
                one.to_parquet(path)
                output_path = str(path)
            except Exception:
                path = month_dir / 'part.csv.gz'
                one.to_csv(path, compression='gzip')
                output_path = str(path)

            active = one[one['trade_count'] > 0]
            diag = diagnostic_summary(one)
            diag.update({'symbol': symbol, 'month': ym})
            diagnostic_rows.append(diag)
            bins = flow_predictive_diagnostics(one)
            bins.insert(0, 'month', ym)
            bins.insert(0, 'symbol', symbol)
            bins.to_csv(month_dir / 'flow_bins.csv', index=False)

            row = {
                'symbol': symbol,
                'month': ym,
                'raw_aggtrades': int(len(raw)),
                'seconds': int(len(one)),
                'active_seconds': int(len(active)),
                'median_quote_volume_active_s': float(active['quote_volume'].median()) if len(active) else 0.0,
                'p95_abs_taker_imbalance_5s': float(active['taker_imbalance_5s'].abs().quantile(.95)) if len(active) else 0.0,
                'p95_abs_ret_1s_bps': float(active['ret_1s_bps'].abs().quantile(.95)) if len(active) else 0.0,
                'output': output_path,
            }
            manifest_rows.append(row)
            symbol_summaries.append(row)
            print(f"  {ym}: {len(raw):,} aggTrades -> {len(one):,} seconds")

        if symbol_summaries:
            pd.DataFrame(symbol_summaries).to_csv(symbol_root / 'manifest.csv', index=False)

    pd.DataFrame(manifest_rows).to_csv(out / 'tradeflow_manifest.csv', index=False)
    pd.DataFrame(diagnostic_rows).to_csv(out / 'predictive_diagnostics.csv', index=False)
    (out / 'research_guard.json').write_text(json.dumps({
        'sealed_holdout_start': '2026-08-01',
        'historical_microstructure_holdout_status': 'locked',
        'historical_research_rule': 'end date must be strictly before 2026-08-01',
        'live_capture_rule': 'prospective raw capture may continue, but is not used for parameter selection until a protocol is frozen',
    }, indent=2), encoding='utf-8')
    if manifest_rows:
        print('\n=== TRADEFLOW MANIFEST ===')
        print(pd.DataFrame(manifest_rows).to_string(index=False))
    return 0


def run_capture(args) -> int:
    symbols = [_norm_feed_symbol(s) for s in args.symbols.split(',') if s.strip()]
    recorder = CryptofeedMicrostructureRecorder(args.out, depth=args.depth, snapshot_interval_ms=args.snapshot_interval_ms)
    result = asyncio.run(recorder.capture(symbols=symbols, seconds=args.seconds))
    print(json.dumps(result, indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='CRYPTO SCALPER LAB v0.8 Market Microstructure Lab')
    sub = p.add_subparsers(dest='command', required=True)

    t = sub.add_parser('tradeflow', help='build historical 1-second taker-flow features from Binance spot aggTrades')
    t.add_argument('--symbols', default='SOLUSDC,BTCUSDC,ETHUSDC')
    t.add_argument('--start', default='2026-01-01')
    t.add_argument('--end', default='2026-04-01')
    t.add_argument('--data-dir', default='data')
    t.add_argument('--out', default='runs/v08_tradeflow')
    t.add_argument('--no-download', action='store_true')
    t.set_defaults(func=run_tradeflow)

    c = sub.add_parser('capture', help='capture public live Binance trades + L2 book via Cryptofeed')
    c.add_argument('--symbols', default='BTC-USDC,SOL-USDC,ETH-USDC')
    c.add_argument('--seconds', type=int, default=300)
    c.add_argument('--depth', type=int, default=10)
    c.add_argument('--snapshot-interval-ms', type=int, default=100)
    c.add_argument('--out', default='runs/v08_live_capture')
    c.set_defaults(func=run_capture)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
