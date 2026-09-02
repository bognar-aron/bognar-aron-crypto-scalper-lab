from __future__ import annotations

import numpy as np
import pandas as pd

BINS = [-1.000001, -0.6, -0.2, 0.2, 0.6, 1.000001]
LABELS = ['strong_sell', 'sell', 'neutral', 'buy', 'strong_buy']


def add_forward_returns(df: pd.DataFrame, horizons=(1,5,30)) -> pd.DataFrame:
    x = df.copy()
    price = x['last_price'].astype(float)
    for h in horizons:
        x[f'fwd_{h}s_bps'] = 10_000.0 * (price.shift(-h) / price - 1.0)
    return x


def flow_predictive_diagnostics(df: pd.DataFrame, feature: str = 'taker_imbalance_5s') -> pd.DataFrame:
    x = add_forward_returns(df)
    x = x[x['trade_count'] > 0].copy()
    x['flow_bin'] = pd.cut(x[feature].clip(-1,1), bins=BINS, labels=LABELS, include_lowest=True)
    rows = []
    for label in LABELS:
        g = x[x['flow_bin'] == label]
        row = {'flow_bin': label, 'seconds': int(len(g)), 'mean_imbalance': float(g[feature].mean()) if len(g) else np.nan}
        for h in (1,5,30):
            s = g[f'fwd_{h}s_bps'].dropna()
            row[f'mean_fwd_{h}s_bps'] = float(s.mean()) if len(s) else np.nan
            row[f'median_fwd_{h}s_bps'] = float(s.median()) if len(s) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def diagnostic_summary(df: pd.DataFrame, feature: str = 'taker_imbalance_5s') -> dict:
    x = add_forward_returns(df)
    x = x[x['trade_count'] > 0].copy()
    strong = x[x[feature].abs() >= 0.6].copy()
    sign = np.sign(strong[feature])
    result = {
        'active_seconds': int(len(x)),
        'strong_flow_seconds': int(len(strong)),
        'feature': feature,
    }
    ranked = x[feature].rank(pct=True)
    for h in (1,5,30):
        fwd = x[f'fwd_{h}s_bps']
        result[f'rank_corr_fwd_{h}s'] = float(ranked.corr(fwd.rank(pct=True)))
        aligned = sign * strong[f'fwd_{h}s_bps']
        result[f'strong_flow_mean_aligned_fwd_{h}s_bps'] = float(aligned.mean())
        result[f'strong_flow_median_aligned_fwd_{h}s_bps'] = float(aligned.median())
        buys = strong[strong[feature] >= 0.6][f'fwd_{h}s_bps']
        result[f'strong_buy_mean_fwd_{h}s_bps'] = float(buys.mean())
    return result
