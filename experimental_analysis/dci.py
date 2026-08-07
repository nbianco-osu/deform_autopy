"""
Data-consistent inversion utilities.

DCI updates a prior distribution over candidate inputs by comparing the density
of model-predicted quantities of interest to the observed density. This module
implements the practical 1D and independent-multi-QoI case needed for early AF
experiments. It is meant to be fed by a surrogate/model prediction table.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .uncertainty import gaussian_kde_pdf, weighted_quantile


@dataclass
class DCIResult:
    """Container for DCI weights and diagnostics."""

    updated_table: pd.DataFrame
    diagnostics: dict[str, float | int | str]


def normalized_weights_from_density_ratio(
    predicted_qoi,
    observed_qoi,
    epsilon: float = 1e-12,
) -> np.ndarray:
    """Compute DCI weights from observed/predicted KDE density ratios."""
    predicted = np.asarray(predicted_qoi, dtype=float)
    observed = np.asarray(observed_qoi, dtype=float)
    prior_pdf = gaussian_kde_pdf(predicted, predicted)
    observed_pdf = gaussian_kde_pdf(predicted, observed)
    ratio = observed_pdf / np.maximum(prior_pdf, epsilon)
    ratio[~np.isfinite(ratio)] = 0.0
    total = np.sum(ratio)
    if total <= 0:
        return np.ones(len(predicted), dtype=float) / max(len(predicted), 1)
    return ratio / total


def run_dci_update(
    prior_table: pd.DataFrame,
    predicted_qoi_columns: list[str],
    observed_qoi: dict[str, np.ndarray],
    input_columns: list[str] | None = None,
    epsilon: float = 1e-12,
) -> DCIResult:
    """Run an independent-QoI DCI update on a prior/prediction table.

    Parameters
    ----------
    prior_table:
        Table containing sampled input parameters and surrogate-predicted QoIs.
    predicted_qoi_columns:
        Columns in `prior_table` that represent model-predicted outputs.
    observed_qoi:
        Mapping from predicted column name to experimental observed samples.
    input_columns:
        Optional columns to summarize after reweighting.
    """
    if prior_table.empty:
        raise ValueError("prior_table is empty.")
    weights = np.ones(len(prior_table), dtype=float) / len(prior_table)
    used = 0
    for column in predicted_qoi_columns:
        if column not in prior_table.columns or column not in observed_qoi:
            continue
        column_values = pd.to_numeric(prior_table[column], errors="coerce").to_numpy(dtype=float)
        column_weights = normalized_weights_from_density_ratio(column_values, observed_qoi[column], epsilon=epsilon)
        weights *= column_weights
        used += 1

    total = np.sum(weights)
    if total <= 0:
        weights = np.ones(len(prior_table), dtype=float) / len(prior_table)
    else:
        weights = weights / total

    updated = prior_table.copy()
    updated["dci_weight"] = weights
    updated["dci_rank"] = updated["dci_weight"].rank(ascending=False, method="first").astype(int)
    effective_sample_size = 1.0 / max(float(np.sum(weights**2)), 1e-300)

    diagnostics: dict[str, float | int | str] = {
        "rows": int(len(updated)),
        "qoi_used": int(used),
        "effective_sample_size": float(effective_sample_size),
        "max_weight": float(np.max(weights)),
        "min_weight": float(np.min(weights)),
    }

    for column in input_columns or []:
        if column not in updated.columns:
            continue
        values = pd.to_numeric(updated[column], errors="coerce").to_numpy(dtype=float)
        q10, q50, q90 = weighted_quantile(values, [0.10, 0.50, 0.90], weights=weights)
        diagnostics[f"{column}_weighted_p10"] = float(q10)
        diagnostics[f"{column}_weighted_p50"] = float(q50)
        diagnostics[f"{column}_weighted_p90"] = float(q90)

    return DCIResult(updated_table=updated, diagnostics=diagnostics)


def resample_updated_distribution(
    updated_table: pd.DataFrame,
    n_samples: int,
    seed: int = 17,
) -> pd.DataFrame:
    """Sample rows from the DCI-updated table according to dci_weight."""
    if "dci_weight" not in updated_table.columns:
        raise ValueError("updated_table must contain dci_weight.")
    weights = pd.to_numeric(updated_table["dci_weight"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    weights = weights / max(np.sum(weights), 1e-300)
    rng = np.random.default_rng(seed)
    indices = rng.choice(np.arange(len(updated_table)), size=int(n_samples), replace=True, p=weights)
    return updated_table.iloc[indices].reset_index(drop=True)

