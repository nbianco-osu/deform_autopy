"""
Define and compare microstructure target distributions.

Targets can be scalar values, tolerances, or empirical distributions. This
supports the candidacy workflow where the desired result may be a distribution
of acceptable grain sizes or damage values rather than one exact number.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class MicrostructureTarget:
    """One scalar or distributional target for a measured/simulated metric."""

    metric: str
    target: float
    tolerance: float | None = None
    weight: float = 1.0
    distribution_csv: str | None = None
    distribution_column: str | None = None


def load_targets_csv(path: str | Path) -> list[MicrostructureTarget]:
    """Load target definitions from CSV.

    Required columns: metric, target.
    Optional columns: tolerance, weight, distribution_csv, distribution_column.
    """
    df = pd.read_csv(path)
    required = {"metric", "target"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Target CSV is missing columns: {missing}")

    targets = []
    for _, row in df.iterrows():
        targets.append(
            MicrostructureTarget(
                metric=str(row["metric"]),
                target=float(row["target"]),
                tolerance=_optional_float(row.get("tolerance")),
                weight=float(row.get("weight", 1.0)),
                distribution_csv=_optional_text(row.get("distribution_csv")),
                distribution_column=_optional_text(row.get("distribution_column")),
            )
        )
    return targets


def _optional_float(value) -> float | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return float(value)


def _optional_text(value) -> str | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return str(value)


def empirical_distribution_values(target: MicrostructureTarget, base_dir: str | Path | None = None) -> np.ndarray:
    """Load empirical values for a distribution target."""
    if not target.distribution_csv:
        return np.array([], dtype=float)
    path = Path(target.distribution_csv)
    if not path.is_absolute() and base_dir is not None:
        path = Path(base_dir) / path
    df = pd.read_csv(path)
    column = target.distribution_column or target.metric
    if column not in df.columns:
        raise ValueError(f"{path} does not contain distribution column {column!r}.")
    return pd.to_numeric(df[column], errors="coerce").dropna().to_numpy(dtype=float)


def scalar_target_errors(row: pd.Series, targets: list[MicrostructureTarget]) -> dict[str, float]:
    """Compute weighted scalar errors for one dataset row."""
    metrics = {}
    total_abs = 0.0
    total_sq = 0.0
    used = 0
    for target in targets:
        if target.metric not in row or pd.isna(row[target.metric]):
            continue
        value = float(row[target.metric])
        raw_error = value - target.target
        scale = target.tolerance if target.tolerance not in [None, 0] else max(abs(target.target), 1.0)
        normalized_error = raw_error / scale
        weighted_abs = target.weight * abs(normalized_error)
        weighted_sq = target.weight * normalized_error**2
        prefix = f"target_{target.metric}"
        metrics[f"{prefix}_value"] = value
        metrics[f"{prefix}_target"] = target.target
        metrics[f"{prefix}_raw_error"] = raw_error
        metrics[f"{prefix}_normalized_error"] = normalized_error
        metrics[f"{prefix}_weighted_abs_error"] = weighted_abs
        metrics[f"{prefix}_weighted_sq_error"] = weighted_sq
        total_abs += weighted_abs
        total_sq += weighted_sq
        used += 1
    metrics["target_total_abs_error"] = total_abs
    metrics["target_total_sq_error"] = total_sq
    metrics["target_num_metrics_used"] = used
    return metrics


def quantile_distance(values: np.ndarray, target_values: np.ndarray, n_quantiles: int = 51) -> float:
    """Approximate 1D distribution distance using quantile differences."""
    values = np.asarray(values, dtype=float)
    target_values = np.asarray(target_values, dtype=float)
    values = values[np.isfinite(values)]
    target_values = target_values[np.isfinite(target_values)]
    if len(values) == 0 or len(target_values) == 0:
        return float("nan")
    q = np.linspace(0.0, 1.0, n_quantiles)
    return float(np.mean(np.abs(np.quantile(values, q) - np.quantile(target_values, q))))


def summarize_microstructure_values(values: np.ndarray, prefix: str = "grain") -> dict[str, float]:
    """Summarize a measured or simulated microstructure distribution."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return {f"{prefix}_count": 0}
    return {
        f"{prefix}_count": int(len(values)),
        f"{prefix}_mean": float(np.mean(values)),
        f"{prefix}_std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        f"{prefix}_p10": float(np.percentile(values, 10)),
        f"{prefix}_p50": float(np.percentile(values, 50)),
        f"{prefix}_p90": float(np.percentile(values, 90)),
    }

