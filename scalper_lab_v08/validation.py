from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

DEFAULT_FEATURE = "taker_imbalance_5s"
DEFAULT_THRESHOLD = 0.60
HORIZONS = (1, 5, 30)

COST_SCENARIOS_BPS = {
    "conservative_taker": 24.0,
    "fee_only_taker": 20.0,
    "low_cost_taker": 12.0,
    "maker_like_research": 4.0,
    "frictionless_upper_bound": 0.0,
}


def add_forward_returns(df: pd.DataFrame, horizons: Iterable[int] = HORIZONS) -> pd.DataFrame:
    x = df.copy()
    price = x["last_price"].astype(float)
    for h in horizons:
        x[f"fwd_{int(h)}s_bps"] = 10_000.0 * (price.shift(-int(h)) / price - 1.0)
    return x


def nonoverlap_sample(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Deterministic non-overlapping horizon windows anchored to the frame's first second."""
    h = int(horizon)
    if h <= 0:
        raise ValueError("horizon must be positive")
    if df.empty:
        return df.copy()
    return df.iloc[::h].copy()


def block_bootstrap_mean_ci(values, block_size: int = 60, n_boot: int = 300, seed: int = 73, alpha: float = 0.05) -> tuple[float, float]:
    """Block-mean bootstrap confidence interval for the mean."""
    arr = np.asarray(pd.Series(values).dropna(), dtype=float)
    if arr.size == 0:
        return (np.nan, np.nan)
    bs = max(1, int(block_size))
    if arr.size < bs:
        m = float(arr.mean())
        return (m, m)
    n_blocks = arr.size // bs
    arr = arr[: n_blocks * bs].reshape(n_blocks, bs)
    block_means = arr.mean(axis=1)
    if n_blocks == 1 or n_boot <= 1:
        m = float(block_means.mean())
        return (m, m)
    rng = np.random.default_rng(int(seed))
    boots = np.empty(int(n_boot), dtype=float)
    for i in range(int(n_boot)):
        boots[i] = rng.choice(block_means, size=n_blocks, replace=True).mean()
    return float(np.quantile(boots, alpha / 2)), float(np.quantile(boots, 1 - alpha / 2))


def _quantile_rows(sample: pd.DataFrame, feature: str, return_col: str) -> tuple[list[dict], float, float]:
    z = sample[[feature, return_col]].dropna().copy()
    if len(z) < 25 or z[feature].nunique() < 2:
        return [], np.nan, np.nan
    pct = z[feature].rank(method="average", pct=True)
    z["quantile"] = pd.cut(
        pct,
        bins=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0000001],
        labels=[1, 2, 3, 4, 5],
        include_lowest=True,
    ).astype("Int64")
    rows, means = [], []
    for q in range(1, 6):
        mask = z["quantile"].eq(q)
        g = z.loc[mask, return_col]
        mean = float(g.mean()) if len(g) else np.nan
        means.append(mean)
        rows.append({
            "quantile": q,
            "seconds": int(len(g)),
            "mean_feature": float(z.loc[mask, feature].mean()) if len(g) else np.nan,
            "mean_fwd_bps": mean,
            "median_fwd_bps": float(g.median()) if len(g) else np.nan,
        })
    s = pd.Series(means, index=range(1, 6), dtype=float)
    qcorr = float(pd.Series(range(1, 6), index=s.index).corr(s.rank(method="average"))) if s.notna().sum() >= 3 else np.nan
    top_bottom = float(means[-1] - means[0]) if np.isfinite(means[-1]) and np.isfinite(means[0]) else np.nan
    return rows, qcorr, top_bottom


def validate_cell(
    df: pd.DataFrame,
    symbol: str,
    month: str,
    period: str,
    feature: str = DEFAULT_FEATURE,
    threshold: float = DEFAULT_THRESHOLD,
    horizons: Iterable[int] = HORIZONS,
    block_seconds: int = 300,
    n_boot: int = 300,
    seed: int = 73,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if feature not in df.columns:
        raise ValueError(f"missing frozen feature: {feature}")
    x = add_forward_returns(df, horizons=horizons)
    metrics, quantiles, economics = [], [], []

    for h in horizons:
        h = int(h)
        ret_col = f"fwd_{h}s_bps"
        sample = nonoverlap_sample(x, h)
        sample = sample[(sample["trade_count"] > 0) & sample[ret_col].notna()].copy()

        rank_corr = np.nan
        if len(sample) and sample[feature].nunique() > 1 and sample[ret_col].nunique() > 1:
            rank_corr = float(sample[feature].rank(pct=True).corr(sample[ret_col].rank(pct=True)))

        strong = sample[sample[feature].abs() >= float(threshold)].copy()
        aligned_s = pd.Series(
            np.sign(strong[feature].to_numpy(dtype=float)) * strong[ret_col].to_numpy(dtype=float),
            dtype=float,
        )
        block_observations = max(1, int(block_seconds) // h)
        ci_lo, ci_hi = block_bootstrap_mean_ci(aligned_s, block_size=block_observations, n_boot=n_boot, seed=int(seed) + h)

        qrows, qcorr, top_bottom = _quantile_rows(sample, feature, ret_col)
        for row in qrows:
            row.update({"period": period, "symbol": symbol, "month": month, "horizon_s": h})
            quantiles.append(row)

        mean_aligned = float(aligned_s.mean()) if len(aligned_s) else np.nan
        metrics.append({
            "period": period,
            "symbol": symbol,
            "month": month,
            "horizon_s": h,
            "active_nonoverlap_seconds": int(len(sample)),
            "strong_flow_seconds": int(len(strong)),
            "rank_corr": rank_corr,
            "strong_flow_mean_aligned_bps": mean_aligned,
            "strong_flow_median_aligned_bps": float(aligned_s.median()) if len(aligned_s) else np.nan,
            "strong_flow_hit_rate": float((aligned_s > 0).mean()) if len(aligned_s) else np.nan,
            "strong_flow_zero_rate": float((aligned_s == 0).mean()) if len(aligned_s) else np.nan,
            "bootstrap_mean_ci_low_bps": ci_lo,
            "bootstrap_mean_ci_high_bps": ci_hi,
            "aligned_p90_bps": float(aligned_s.quantile(0.90)) if len(aligned_s) else np.nan,
            "aligned_p95_bps": float(aligned_s.quantile(0.95)) if len(aligned_s) else np.nan,
            "aligned_p99_bps": float(aligned_s.quantile(0.99)) if len(aligned_s) else np.nan,
            "prob_aligned_gt_1bps": float((aligned_s > 1.0).mean()) if len(aligned_s) else np.nan,
            "prob_aligned_gt_2bps": float((aligned_s > 2.0).mean()) if len(aligned_s) else np.nan,
            "prob_aligned_gt_5bps": float((aligned_s > 5.0).mean()) if len(aligned_s) else np.nan,
            "quantile_monotonic_corr": qcorr,
            "quantile_top_minus_bottom_bps": top_bottom,
        })

        for scenario, cost_bps in COST_SCENARIOS_BPS.items():
            economics.append({
                "period": period,
                "symbol": symbol,
                "month": month,
                "horizon_s": h,
                "scenario": scenario,
                "roundtrip_cost_bps": float(cost_bps),
                "gross_mean_aligned_bps": mean_aligned,
                "net_mean_aligned_bps": mean_aligned - float(cost_bps) if np.isfinite(mean_aligned) else np.nan,
            })

    return pd.DataFrame(metrics), pd.DataFrame(quantiles), pd.DataFrame(economics)


def aggregate_validation_gate(cells: pd.DataFrame, economics: pd.DataFrame) -> dict:
    """Predeclared v0.8.1 gate. Primary proof horizons: 1s and 5s; 30s is diagnostic."""
    val = cells[cells["period"].eq("validation")].copy()
    result = {
        "protocol_version": "v0.8.1",
        "frozen_feature": DEFAULT_FEATURE,
        "frozen_strong_flow_threshold": DEFAULT_THRESHOLD,
        "primary_horizons_s": [1, 5],
        "secondary_horizon_s": 30,
        "validation_cells": int(val[["symbol", "month"]].drop_duplicates().shape[0]),
        "minimum_validation_cells": 10,
        "criteria": {
            "positive_rank_corr_fraction": 0.75,
            "positive_aligned_mean_fraction": 0.75,
            "positive_bootstrap_ci_fraction": 0.50,
            "positive_quantile_direction_fraction": 0.67,
        },
        "by_horizon": {},
    }

    horizon_pass = {}
    for h in HORIZONS:
        g = val[val["horizon_s"].eq(h)].copy()
        n = len(g)
        stats = {
            "cells": int(n),
            "median_rank_corr": float(g["rank_corr"].median()) if n else np.nan,
            "positive_rank_corr_fraction": float((g["rank_corr"] > 0).mean()) if n else np.nan,
            "median_aligned_mean_bps": float(g["strong_flow_mean_aligned_bps"].median()) if n else np.nan,
            "positive_aligned_mean_fraction": float((g["strong_flow_mean_aligned_bps"] > 0).mean()) if n else np.nan,
            "positive_bootstrap_ci_fraction": float((g["bootstrap_mean_ci_low_bps"] > 0).mean()) if n else np.nan,
            "median_hit_rate": float(g["strong_flow_hit_rate"].median()) if n else np.nan,
            "median_quantile_top_minus_bottom_bps": float(g["quantile_top_minus_bottom_bps"].median()) if n else np.nan,
            "positive_quantile_direction_fraction": float((g["quantile_top_minus_bottom_bps"] > 0).mean()) if n else np.nan,
        }
        passed = (
            n >= result["minimum_validation_cells"]
            and stats["median_rank_corr"] > 0
            and stats["positive_rank_corr_fraction"] >= 0.75
            and stats["median_aligned_mean_bps"] > 0
            and stats["positive_aligned_mean_fraction"] >= 0.75
            and stats["positive_bootstrap_ci_fraction"] >= 0.50
            and stats["positive_quantile_direction_fraction"] >= 0.67
        )
        stats["information_horizon_pass"] = bool(passed)
        result["by_horizon"][str(h)] = stats
        horizon_pass[h] = bool(passed)

    result["information_pass"] = bool(horizon_pass.get(1, False) and horizon_pass.get(5, False))

    ev = economics[
        economics["period"].eq("validation")
        & economics["scenario"].eq("maker_like_research")
        & economics["horizon_s"].isin([1, 5])
    ].copy()
    execution_stats = {
        "scenario": "maker_like_research",
        "roundtrip_cost_bps": 4.0,
        "median_net_mean_aligned_bps": float(ev["net_mean_aligned_bps"].median()) if len(ev) else np.nan,
        "positive_net_cell_fraction": float((ev["net_mean_aligned_bps"] > 0).mean()) if len(ev) else np.nan,
    }
    result["execution_economics"] = execution_stats
    result["execution_pass"] = bool(
        np.isfinite(execution_stats["median_net_mean_aligned_bps"])
        and execution_stats["median_net_mean_aligned_bps"] > 0
        and execution_stats["positive_net_cell_fraction"] >= 0.75
    )
    result["overall_live_candidate_pass"] = bool(result["information_pass"] and result["execution_pass"])
    return result
