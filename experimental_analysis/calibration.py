"""
Transparent calibration workflows for AF/DEFORM comparisons.

The first calibration method is a grid search over scalar correction parameters.
It is intentionally simple: every candidate is written to a CSV with objective
terms, making it easy to inspect and defend before moving to Bayesian or
gradient-based calibration.
"""

from __future__ import annotations

from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd


def apply_parameter_corrections(
    dataset: pd.DataFrame,
    parameters: dict[str, float],
) -> pd.DataFrame:
    """Apply simple scalar corrections to common model columns."""
    output = dataset.copy()

    if "force_scale" in parameters:
        for column in ["max_force_kn", "peak_stress_mpa", "effective_stress_mpa"]:
            if column in output.columns:
                output[column] = pd.to_numeric(output[column], errors="coerce") * float(parameters["force_scale"])

    if "temperature_offset_c" in parameters:
        for column in ["contact_temperature_c", "temperature_mean_c", "forging_temp_c"]:
            if column in output.columns:
                output[column] = pd.to_numeric(output[column], errors="coerce") + float(parameters["temperature_offset_c"])

    if "grain_scale" in parameters:
        for column in ["grain_mean_um", "grain_size_um", "initial_grain_mean_um"]:
            if column in output.columns:
                output[column] = pd.to_numeric(output[column], errors="coerce") * float(parameters["grain_scale"])

    if "damage_scale" in parameters:
        for column in ["damage_max", "damage_observed"]:
            if column in output.columns:
                output[column] = pd.to_numeric(output[column], errors="coerce") * float(parameters["damage_scale"])

    return output


def metric_error(
    dataset: pd.DataFrame,
    metric: str,
    target: float,
    tolerance: float | None = None,
    weight: float = 1.0,
) -> float:
    """Compute weighted normalized error for a metric mean."""
    if metric not in dataset.columns:
        return float("nan")
    values = pd.to_numeric(dataset[metric], errors="coerce").dropna()
    if values.empty:
        return float("nan")
    estimate = float(values.mean())
    scale = tolerance if tolerance not in [None, 0] else max(abs(float(target)), 1.0)
    return float(weight * ((estimate - float(target)) / scale) ** 2)


def grid_search_calibration(
    dataset: pd.DataFrame,
    parameter_grid: dict[str, list[float]],
    targets: list[dict],
) -> pd.DataFrame:
    """Evaluate all parameter combinations against scalar targets."""
    if not parameter_grid:
        raise ValueError("parameter_grid is empty.")
    parameter_names = list(parameter_grid)
    rows = []
    for values in product(*[parameter_grid[name] for name in parameter_names]):
        parameters = dict(zip(parameter_names, values))
        corrected = apply_parameter_corrections(dataset, parameters)
        objective_terms = {}
        objective = 0.0
        used = 0
        for target in targets:
            error = metric_error(
                corrected,
                metric=str(target["metric"]),
                target=float(target["target"]),
                tolerance=target.get("tolerance"),
                weight=float(target.get("weight", 1.0)),
            )
            objective_terms[f"error_{target['metric']}"] = error
            if np.isfinite(error):
                objective += error
                used += 1
        rows.append(
            {
                **parameters,
                **objective_terms,
                "calibration_objective": objective,
                "calibration_targets_used": used,
            }
        )
    result = pd.DataFrame(rows).sort_values("calibration_objective", ascending=True).reset_index(drop=True)
    result["calibration_rank"] = np.arange(1, len(result) + 1)
    return result


def default_parameter_grid() -> dict[str, list[float]]:
    """Return conservative default calibration candidates."""
    return {
        "force_scale": [0.9, 1.0, 1.1],
        "temperature_offset_c": [-25.0, 0.0, 25.0],
        "grain_scale": [0.9, 1.0, 1.1],
        "damage_scale": [0.8, 1.0, 1.2],
    }


def load_calibration_targets(path: str | Path) -> list[dict]:
    """Load calibration targets from CSV columns metric,target,tolerance,weight."""
    df = pd.read_csv(path)
    required = {"metric", "target"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Calibration target CSV is missing columns: {missing}")
    targets = []
    for _, row in df.iterrows():
        targets.append(
            {
                "metric": str(row["metric"]),
                "target": float(row["target"]),
                "tolerance": None if "tolerance" not in row or pd.isna(row["tolerance"]) else float(row["tolerance"]),
                "weight": 1.0 if "weight" not in row or pd.isna(row["weight"]) else float(row["weight"]),
            }
        )
    return targets


def run_default_calibration(
    dataset_csv: str | Path,
    targets_csv: str | Path,
    output_dir: str | Path,
    parameter_grid: dict[str, list[float]] | None = None,
) -> dict[str, str]:
    """Run grid-search calibration from CSV files and write outputs."""
    dataset = pd.read_csv(dataset_csv)
    targets = load_calibration_targets(targets_csv)
    parameter_grid = parameter_grid or default_parameter_grid()
    result = grid_search_calibration(dataset, parameter_grid, targets)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_csv = output_dir / "calibration_grid_search.csv"
    best_csv = output_dir / "calibration_best_parameters.csv"
    result.to_csv(result_csv, index=False)
    result.head(1).to_csv(best_csv, index=False)
    return {
        "calibration_grid_search": str(result_csv),
        "calibration_best_parameters": str(best_csv),
        "calibration_rows": str(len(result)),
    }

