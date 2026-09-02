import numpy as np
import pandas as pd

from microstructure_validation_v081 import _safe_loader_end
from scalper_lab_v08.aggtrades import SEALED_HOLDOUT_START
from scalper_lab_v08.validation import (
    aggregate_validation_gate,
    block_bootstrap_mean_ci,
    nonoverlap_sample,
    validate_cell,
)


def synthetic_frame(n=6000):
    idx = pd.date_range('2026-04-01', periods=n, freq='1s', tz='UTC')
    rng = np.random.default_rng(7)
    imbalance = np.tanh(rng.normal(size=n))
    step = np.zeros(n)
    step[1:] = 0.00001 * (0.35 * imbalance[:-1] + rng.normal(scale=0.25, size=n - 1))
    price = 100.0 * np.cumprod(1.0 + step)
    return pd.DataFrame({
        'last_price': price,
        'trade_count': np.ones(n, dtype='int32'),
        'taker_imbalance_5s': imbalance,
    }, index=idx)


def test_nonoverlap_sampling_is_deterministic():
    df = synthetic_frame(100)
    assert len(nonoverlap_sample(df, 1)) == 100
    assert len(nonoverlap_sample(df, 5)) == 20
    assert len(nonoverlap_sample(df, 30)) == 4


def test_block_bootstrap_constant_series():
    lo, hi = block_bootstrap_mean_ci(np.ones(1200), block_size=60, n_boot=30)
    assert lo == 1.0
    assert hi == 1.0


def test_validate_cell_produces_three_horizons_and_quantiles():
    cells, quantiles, economics = validate_cell(
        synthetic_frame(), 'BTCUSDC', '2026-04', 'validation', block_seconds=60, n_boot=30
    )
    assert set(cells['horizon_s']) == {1, 5, 30}
    assert len(quantiles) == 15
    assert set(economics['scenario']) >= {'conservative_taker', 'maker_like_research', 'frictionless_upper_bound'}
    row = cells[cells['horizon_s'].eq(1)].iloc[0]
    assert row['rank_corr'] > 0
    assert row['quantile_top_minus_bottom_bps'] > 0


def test_gate_runs_on_twelve_validation_cells():
    cells, _, economics = validate_cell(
        synthetic_frame(), 'BTCUSDC', '2026-04', 'validation', block_seconds=60, n_boot=20
    )
    cframes, eframes = [], []
    for i in range(12):
        c = cells.copy()
        e = economics.copy()
        c['symbol'] = f'S{i % 3}'
        e['symbol'] = f'S{i % 3}'
        c['month'] = f'2026-{4 + i // 3:02d}'
        e['month'] = f'2026-{4 + i // 3:02d}'
        cframes.append(c)
        eframes.append(e)
    gate = aggregate_validation_gate(pd.concat(cframes, ignore_index=True), pd.concat(eframes, ignore_index=True))
    assert gate['validation_cells'] == 12
    assert 'information_pass' in gate
    assert 'execution_pass' in gate


def test_holdout_boundary_is_exclusive_and_safe():
    safe = pd.Timestamp(_safe_loader_end('2026-08-01'))
    assert safe < SEALED_HOLDOUT_START
    assert safe.month == 7
    try:
        _safe_loader_end('2026-08-02')
    except ValueError:
        pass
    else:
        raise AssertionError('crossing the sealed holdout must fail')
