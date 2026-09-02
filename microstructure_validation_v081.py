#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from scalper_lab_v08.aggtrades import SEALED_HOLDOUT_START, iter_aggtrade_months, tradeflow_1s
from scalper_lab_v08.validation import (
    COST_SCENARIOS_BPS,
    DEFAULT_FEATURE,
    DEFAULT_THRESHOLD,
    HORIZONS,
    aggregate_validation_gate,
    validate_cell,
)


def _norm_spot_symbol(raw: str) -> str:
    return raw.strip().upper().replace('/', '').replace('-', '')


def _utc(value: str) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize('UTC') if t.tzinfo is None else t.tz_convert('UTC')


def _safe_loader_end(exclusive_end: str) -> str:
    """Allow [start, 2026-08-01) without letting the v0.8 loader touch August data."""
    end = _utc(exclusive_end)
    if end > SEALED_HOLDOUT_START:
        raise ValueError('validation cannot cross the 2026-08-01 sealed holdout')
    if end == SEALED_HOLDOUT_START:
        end = end - pd.Timedelta(nanoseconds=1)
    return end.isoformat()


def protocol_payload(args) -> dict:
    return {
        'protocol_version': 'v0.8.1',
        'purpose': 'validate the already-observed v0.8 taker-flow information signal without parameter retuning',
        'development_reference_window': '[2026-01-01, 2026-04-01)',
        'validation_window': f'[{args.validation_start}, {args.validation_end})',
        'validation_end_is_exclusive': True,
        'sealed_holdout_start': '2026-08-01',
        'sealed_holdout_status': 'locked',
        'frozen_feature': DEFAULT_FEATURE,
        'frozen_strong_flow_threshold': DEFAULT_THRESHOLD,
        'horizons_s': list(HORIZONS),
        'primary_proof_horizons_s': [1, 5],
        'secondary_diagnostic_horizon_s': 30,
        'nonoverlap_sampling': 'every horizon-th second before active-second filtering',
        'block_bootstrap': {
            'block_seconds': int(args.block_seconds),
            'replicates': int(args.n_boot),
            'confidence_level': 0.95,
        },
        'information_gate': {
            'minimum_symbol_month_cells': 10,
            'positive_rank_corr_fraction': 0.75,
            'positive_aligned_mean_fraction': 0.75,
            'positive_bootstrap_ci_fraction': 0.50,
            'positive_quantile_direction_fraction': 0.67,
            'must_pass_primary_horizons': [1, 5],
        },
        'execution_cost_scenarios_bps_roundtrip': COST_SCENARIOS_BPS,
        'execution_gate_note': 'maker_like_research=4 bps is a research hurdle, not a promised executable fee/fill model',
        'parameter_selection_rule': 'validation results cannot be used to retune the frozen feature or 0.60 threshold',
    }


def run(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    protocol = protocol_payload(args)
    (out / 'validation_protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')

    loader_end = _safe_loader_end(args.validation_end)
    cell_frames, quantile_frames, econ_frames = [], [], []
    manifest_rows = []

    for raw_symbol in args.symbols.split(','):
        symbol = _norm_spot_symbol(raw_symbol)
        if not symbol:
            continue
        print(f'[VALIDATION] {symbol} {args.validation_start} -> {args.validation_end} exclusive')
        for ym, raw in iter_aggtrade_months(
            symbol,
            args.validation_start,
            loader_end,
            args.data_dir,
            download=not args.no_download,
        ):
            one = tradeflow_1s(raw)
            cells, quantiles, economics = validate_cell(
                one,
                symbol=symbol,
                month=ym,
                period='validation',
                block_seconds=args.block_seconds,
                n_boot=args.n_boot,
                seed=args.seed,
            )
            cell_frames.append(cells)
            quantile_frames.append(quantiles)
            econ_frames.append(economics)
            manifest_rows.append({
                'symbol': symbol,
                'month': ym,
                'raw_aggtrades': int(len(raw)),
                'one_second_rows': int(len(one)),
                'active_seconds': int((one['trade_count'] > 0).sum()),
            })
            print(f'  {ym}: {len(raw):,} aggTrades -> {len(one):,} seconds')

    if not cell_frames:
        raise RuntimeError('no validation cells were produced')

    cells = pd.concat(cell_frames, ignore_index=True)
    quantiles = pd.concat(quantile_frames, ignore_index=True) if quantile_frames else pd.DataFrame()
    economics = pd.concat(econ_frames, ignore_index=True) if econ_frames else pd.DataFrame()
    manifest = pd.DataFrame(manifest_rows)

    cells.to_csv(out / 'validation_cells.csv', index=False)
    quantiles.to_csv(out / 'validation_quantiles.csv', index=False)
    economics.to_csv(out / 'execution_economics.csv', index=False)
    manifest.to_csv(out / 'validation_manifest.csv', index=False)

    gate = aggregate_validation_gate(cells, economics)
    gate.update({
        'validation_window': f'[{args.validation_start}, {args.validation_end})',
        'sealed_holdout_start': '2026-08-01',
        'sealed_holdout_status': 'locked',
    })
    (out / 'validation_gate.json').write_text(json.dumps(gate, indent=2), encoding='utf-8')

    summary_rows = []
    for h in HORIZONS:
        g = cells[cells['horizon_s'].eq(h)]
        summary_rows.append({
            'horizon_s': h,
            'cells': len(g),
            'median_rank_corr': g['rank_corr'].median(),
            'positive_rank_corr_fraction': (g['rank_corr'] > 0).mean(),
            'median_aligned_mean_bps': g['strong_flow_mean_aligned_bps'].median(),
            'positive_aligned_mean_fraction': (g['strong_flow_mean_aligned_bps'] > 0).mean(),
            'positive_bootstrap_ci_fraction': (g['bootstrap_mean_ci_low_bps'] > 0).mean(),
            'median_hit_rate': g['strong_flow_hit_rate'].median(),
            'median_quantile_top_minus_bottom_bps': g['quantile_top_minus_bottom_bps'].median(),
            'information_horizon_pass': gate['by_horizon'][str(h)]['information_horizon_pass'],
        })
    pd.DataFrame(summary_rows).to_csv(out / 'validation_summary.csv', index=False)

    print('\n=== v0.8.1 VALIDATION GATE ===')
    print(json.dumps(gate, indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='CRYPTO SCALPER LAB v0.8.1 microstructure validation')
    p.add_argument('--symbols', default='SOLUSDC,BTCUSDC,ETHUSDC')
    p.add_argument('--validation-start', default='2026-04-01')
    p.add_argument('--validation-end', default='2026-08-01')
    p.add_argument('--data-dir', default='data')
    p.add_argument('--out', default='runs/v081_validation')
    p.add_argument('--block-seconds', type=int, default=300)
    p.add_argument('--n-boot', type=int, default=300)
    p.add_argument('--seed', type=int, default=73)
    p.add_argument('--no-download', action='store_true')
    args = p.parse_args(argv)
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
