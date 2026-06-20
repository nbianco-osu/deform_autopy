"""
Metric calculations for DEFORM optimization.

These functions turn raw post-processing outputs into numeric objectives.
Keep them independent of DEFORM API calls so they can run on saved CSV files.
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd


def _as_array(values):
    """Convert a list/Series to a finite float numpy array."""
    arr = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    return arr[np.isfinite(arr)]


def summarize_microstructure(microstructure_csv):
    """Summarize a JMAK microstructure CSV produced from a GRAIN block."""
    df = pd.read_csv(microstructure_csv)
    grain = _as_array(df["Average grain size (um)"])
    initial_grain = _as_array(df.get("Initial grain size (um)", []))
    rex = _as_array(df.get("Rex. vol. fraction", []))
    retained_strain = _as_array(df.get("Retained strain", []))

    return {
        "micro_num_elements": int(len(df)),
        "grain_mean_um": float(np.mean(grain)) if len(grain) else math.nan,
        "grain_std_um": float(np.std(grain, ddof=1)) if len(grain) > 1 else 0.0,
        "grain_p10_um": float(np.percentile(grain, 10)) if len(grain) else math.nan,
        "grain_p50_um": float(np.percentile(grain, 50)) if len(grain) else math.nan,
        "grain_p90_um": float(np.percentile(grain, 90)) if len(grain) else math.nan,
        "initial_grain_mean_um": float(np.mean(initial_grain)) if len(initial_grain) else math.nan,
        "rex_fraction_mean": float(np.mean(rex)) if len(rex) else math.nan,
        "retained_strain_mean": float(np.mean(retained_strain)) if len(retained_strain) else math.nan,
    }


def grain_size_error(metrics, target_grain_size_um, use_absolute=True):
    """Return grain-size error from a metrics dictionary."""
    error = float(metrics["grain_mean_um"]) - float(target_grain_size_um)
    return abs(error) if use_absolute else error


def summarize_load_stroke(load_stroke_csv):
    """Summarize common load-stroke outputs.

    The function is tolerant of column names and reports values only when
    matching columns exist.
    """
    df = pd.read_csv(load_stroke_csv)
    result = {"load_stroke_rows": int(len(df))}

    for column in df.columns:
        lower = column.lower()
        values = _as_array(df[column])
        if not len(values):
            continue
        if "load" in lower:
            result[f"{column}_max"] = float(np.max(values))
            result[f"{column}_min"] = float(np.min(values))
        if "stroke" in lower:
            result[f"{column}_final"] = float(values[-1])
        if "stress" in lower:
            result[f"{column}_max"] = float(np.max(values))
        if "strain" in lower:
            result[f"{column}_max"] = float(np.max(values))

    return result


def summarize_damage(damage_csv):
    """Summarize damage values exported by post-processing.

    The processor writes a small CSV with `damage_min` and `damage_max` when it
    can read DEFORM object info from a DB. This function is also tolerant of
    wider CSV exports and will use any numeric column containing "damage".
    """
    df = pd.read_csv(damage_csv)
    result = {"damage_rows": int(len(df))}
    damage_columns = [column for column in df.columns if "damage" in column.lower()]

    all_values = []
    for column in damage_columns:
        values = _as_array(df[column])
        if not len(values):
            continue
        safe_name = column.lower().replace(" ", "_")
        result[f"{safe_name}_min"] = float(np.min(values))
        result[f"{safe_name}_max"] = float(np.max(values))
        all_values.extend(values.tolist())

    if all_values:
        result["damage_min"] = float(np.min(all_values))
        result["damage_max"] = float(np.max(all_values))

    return result


def summarize_coordinates(coordinate_csv):
    """Compute centering errors from saved object coordinate CSV.

    Expects rows from `die_positioning.save_object_coordinates`.
    """
    df = pd.read_csv(coordinate_csv)
    centers = df[df["coord_type"] == "center"].copy()
    centers = centers.set_index("object")

    result = {}
    if "Workpiece" not in centers.index:
        return result

    wkp = centers.loc["Workpiece", ["x", "y", "z"]].astype(float)
    for obj in ["Top Die", "Bottom Die"]:
        if obj in centers.index:
            die = centers.loc[obj, ["x", "y", "z"]].astype(float)
            delta = die - wkp
            prefix = obj.lower().replace(" ", "_")
            result[f"{prefix}_center_dx"] = float(delta["x"])
            result[f"{prefix}_center_dy"] = float(delta["y"])
            result[f"{prefix}_center_dz"] = float(delta["z"])
            result[f"{prefix}_center_distance"] = float(np.linalg.norm(delta.to_numpy()))

    return result


def centerline_bending_metric(point_csv, x_col="x", y_col="y", z_col="z", axis_col="x"):
    """Estimate bending as max transverse deviation from a fitted centerline.

    This is intended for exported point-tracking or sampled centerline data.
    The metric fits transverse coordinates as functions of the main axis and
    reports the largest residual magnitude.
    """
    df = pd.read_csv(point_csv)
    axis = _as_array(df[axis_col])
    y = _as_array(df[y_col])
    z = _as_array(df[z_col])
    if len(axis) < 3 or len(y) != len(axis) or len(z) != len(axis):
        raise ValueError("Need at least three valid centerline points with x/y/z columns.")

    y_fit = np.polyval(np.polyfit(axis, y, 1), axis)
    z_fit = np.polyval(np.polyfit(axis, z, 1), axis)
    deviation = np.sqrt((y - y_fit) ** 2 + (z - z_fit) ** 2)
    return {
        "centerline_max_deviation": float(np.max(deviation)),
        "centerline_mean_deviation": float(np.mean(deviation)),
    }


def weighted_objective(metrics, weights, minimize=True):
    """Combine metrics into one scalar objective.

    Missing or NaN metrics are skipped. For minimization studies, lower values
    are better. For maximization, set `minimize=False` to flip the sign.
    """
    score = 0.0
    used = {}
    for name, weight in weights.items():
        value = metrics.get(name)
        if value is None or pd.isna(value):
            continue
        contribution = float(weight) * float(value)
        used[name] = contribution
        score += contribution
    return {"objective": score if minimize else -score, "objective_terms": used}


def collect_metrics_from_files(
    initial_microstructure_csv=None,
    microstructure_csv=None,
    load_stroke_csv=None,
    coordinate_csv=None,
    centerline_csv=None,
    damage_csv=None,
):
    """Collect all available metrics from optional post-processing files."""
    metrics = {}
    if initial_microstructure_csv and Path(initial_microstructure_csv).exists():
        initial_metrics = summarize_microstructure(initial_microstructure_csv)
        metrics.update({
            f"initial_state_{key}": value
            for key, value in initial_metrics.items()
        })
    if microstructure_csv and Path(microstructure_csv).exists():
        metrics.update(summarize_microstructure(microstructure_csv))
    if load_stroke_csv and Path(load_stroke_csv).exists():
        metrics.update(summarize_load_stroke(load_stroke_csv))
    if coordinate_csv and Path(coordinate_csv).exists():
        metrics.update(summarize_coordinates(coordinate_csv))
    if centerline_csv and Path(centerline_csv).exists():
        metrics.update(centerline_bending_metric(centerline_csv))
    if damage_csv and Path(damage_csv).exists():
        metrics.update(summarize_damage(damage_csv))
    return metrics
