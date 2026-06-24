"""
Bayesian optimization utilities for expensive DEFORM runs.

The intended loop is:
1. Train a surrogate on completed DEFORM runs.
2. Generate many candidate parameter sets.
3. Score candidates with expected improvement.
4. Run the best few candidates in DEFORM.
"""

from pathlib import Path
import math
import numpy as np
import pandas as pd
from optimizers.doe import latin_hypercube


def _normal_pdf(x):
    return np.exp(-0.5 * x**2) / np.sqrt(2 * np.pi)


def _normal_cdf(x):
    return 0.5 * (1.0 + np.vectorize(math.erf)(x / np.sqrt(2.0)))


def expected_improvement(mean, std, best_y, xi=0.01, minimize=True):
    """Compute expected improvement from prediction mean/std arrays."""
    mean = np.asarray(mean, dtype=float)
    std = np.maximum(np.asarray(std, dtype=float), 1e-12)

    if minimize:
        improvement = best_y - mean - xi
    else:
        improvement = mean - best_y - xi

    z = improvement / std
    return improvement * _normal_cdf(z) + std * _normal_pdf(z)


def predict_with_uncertainty(model, candidates):
    """Return surrogate mean/std predictions.

    GaussianProcessRegressor supports direct standard deviation. For ensemble
    models inside a sklearn Pipeline, this estimates uncertainty from tree
    disagreement when available.
    """
    try:
        mean, std = model.predict(candidates, return_std=True)
        return mean, std
    except TypeError:
        pass

    mean = model.predict(candidates)
    try:
        preprocess = model.named_steps["preprocess"]
        regressor = model.named_steps["regressor"]
        transformed = preprocess.transform(candidates)
        tree_preds = np.vstack([tree.predict(transformed) for tree in regressor.estimators_])
        std = np.std(tree_preds, axis=0)
    except Exception:
        std = np.ones_like(mean, dtype=float)
    return mean, std


def propose_bayesian_candidates(
    model,
    completed_dataset,
    bounds,
    target_column="objective",
    n_random_candidates=1000,
    n_select=5,
    random_seed=1,
    minimize=True,
    xi=0.01,
    constant_columns=None,
):
    """Propose next DEFORM candidates using expected improvement."""
    completed = pd.read_csv(completed_dataset) if isinstance(completed_dataset, (str, Path)) else completed_dataset
    completed = completed.dropna(subset=[target_column])
    if completed.empty:
        raise ValueError("Need at least one completed objective value for Bayesian optimization.")

    best_y = completed[target_column].min() if minimize else completed[target_column].max()
    candidates = latin_hypercube(bounds, n_random_candidates, random_seed=random_seed)
    for key, value in (constant_columns or {}).items():
        candidates[key] = value

    mean, std = predict_with_uncertainty(model, candidates)
    candidates = candidates.copy()
    candidates["predicted_mean"] = mean
    candidates["predicted_std"] = std
    candidates["expected_improvement"] = expected_improvement(
        mean,
        std,
        best_y=best_y,
        xi=xi,
        minimize=minimize,
    )
    candidates = candidates.sort_values("expected_improvement", ascending=False)
    return candidates.head(n_select).reset_index(drop=True)
