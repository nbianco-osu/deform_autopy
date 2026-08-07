"""
Uncertainty utilities for experimental/simulation fusion.

These functions avoid heavy dependencies so they can run in the same Spyder
environment as the DEFORM scripts. Gaussian KDE, bootstrap confidence intervals,
and weighted statistics provide a practical first layer for uncertainty-aware
surrogate and DCI workflows.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def clean_array(values) -> np.ndarray:
    """Return finite float values from any array-like input."""
    array = np.asarray(values, dtype=float)
    return array[np.isfinite(array)]


def bootstrap_ci(values, statistic=np.mean, n_bootstrap: int = 2000, confidence: float = 0.95, seed: int = 17) -> dict[str, float]:
    """Estimate a nonparametric bootstrap confidence interval."""
    values = clean_array(values)
    if len(values) == 0:
        return {"estimate": math.nan, "ci_low": math.nan, "ci_high": math.nan, "n": 0}
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(int(n_bootstrap)):
        sample = rng.choice(values, size=len(values), replace=True)
        stats.append(float(statistic(sample)))
    alpha = (1.0 - confidence) / 2.0
    return {
        "estimate": float(statistic(values)),
        "ci_low": float(np.quantile(stats, alpha)),
        "ci_high": float(np.quantile(stats, 1.0 - alpha)),
        "n": int(len(values)),
    }


def silverman_bandwidth(values) -> float:
    """Silverman's rule-of-thumb bandwidth for 1D Gaussian KDE."""
    values = clean_array(values)
    if len(values) < 2:
        return 1.0
    std = np.std(values, ddof=1)
    iqr = np.subtract(*np.percentile(values, [75, 25]))
    sigma = min(std, iqr / 1.349) if iqr > 0 else std
    bandwidth = 0.9 * sigma * len(values) ** (-1.0 / 5.0)
    return float(max(bandwidth, 1e-9))


def gaussian_kde_pdf(query, samples, bandwidth: float | None = None, weights=None) -> np.ndarray:
    """Evaluate a simple 1D Gaussian KDE at query points."""
    query = np.asarray(query, dtype=float)
    samples = clean_array(samples)
    if len(samples) == 0:
        return np.full_like(query, np.nan, dtype=float)
    bandwidth = bandwidth or silverman_bandwidth(samples)
    if weights is None:
        weights = np.ones(len(samples), dtype=float) / len(samples)
    else:
        weights = np.asarray(weights, dtype=float)
        weights = weights / max(np.sum(weights), 1e-300)
    z = (query[:, None] - samples[None, :]) / bandwidth
    density = np.exp(-0.5 * z**2) / (math.sqrt(2.0 * math.pi) * bandwidth)
    return density @ weights


def weighted_mean(values, weights) -> float:
    """Return weighted mean with normalized weights."""
    values = clean_array(values)
    weights = np.asarray(weights, dtype=float)
    weights = weights[: len(values)]
    total = np.sum(weights)
    if len(values) == 0 or total <= 0:
        return math.nan
    return float(np.sum(values * weights) / total)


def weighted_quantile(values, quantiles, weights=None) -> np.ndarray:
    """Compute weighted quantiles for 1D values."""
    values = clean_array(values)
    quantiles = np.asarray(quantiles, dtype=float)
    if len(values) == 0:
        return np.full_like(quantiles, np.nan)
    if weights is None:
        return np.quantile(values, quantiles)
    weights = np.asarray(weights, dtype=float)[: len(values)]
    sorter = np.argsort(values)
    values = values[sorter]
    weights = weights[sorter]
    cumulative = np.cumsum(weights) - 0.5 * weights
    cumulative = cumulative / max(np.sum(weights), 1e-300)
    return np.interp(quantiles, cumulative, values)


def summarize_uncertainty_table(df: pd.DataFrame, columns: list[str], confidence: float = 0.95) -> pd.DataFrame:
    """Create bootstrap uncertainty summaries for selected numeric columns."""
    rows = []
    for column in columns:
        if column not in df.columns:
            continue
        values = pd.to_numeric(df[column], errors="coerce").dropna().to_numpy(dtype=float)
        row = {"metric": column, **bootstrap_ci(values, confidence=confidence)}
        rows.append(row)
    return pd.DataFrame(rows)

