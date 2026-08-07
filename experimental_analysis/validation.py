"""
Validation checks for real Agility Forge data processing.

The goal is to identify questionable AF hits before they enter calibration,
surrogate training, or DCI. The checks are intentionally transparent and
threshold-based so a researcher can defend, tune, and document every flag.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def validate_hit_summary(
    summary_df: pd.DataFrame,
    min_depth_mm: float = 0.01,
    max_depth_mm: float = 20.0,
    min_max_force_kn: float = 0.25,
    min_temperature_c: float = 20.0,
    max_temperature_c: float = 1400.0,
) -> pd.DataFrame:
    """Validate per-hit contact/depth/temperature summaries."""
    rows = []
    for _, row in summary_df.iterrows():
        flags = []
        depth = _float(row.get("depth_mm"))
        max_force = _float(row.get("max_force_kn"))
        temp = _float(row.get("contact_temperature_c"))
        contact_idx = _float(row.get("contact_idx"))
        min_idx = _float(row.get("min_idx"))

        if not np.isfinite(depth) or depth <= 0:
            flags.append("nonpositive_depth")
        elif depth < min_depth_mm:
            flags.append("very_small_depth")
        elif depth > max_depth_mm:
            flags.append("large_depth")

        if not np.isfinite(max_force) or max_force < min_max_force_kn:
            flags.append("low_force_signal")
        if np.isfinite(temp) and (temp < min_temperature_c or temp > max_temperature_c):
            flags.append("temperature_out_of_expected_range")
        if np.isfinite(contact_idx) and np.isfinite(min_idx) and min_idx <= contact_idx:
            flags.append("minimum_position_not_after_contact")

        rows.append(
            {
                "source_file": row.get("source_file", ""),
                "hit": row.get("hit", ""),
                "validation_status": "pass" if not flags else "review",
                "validation_flags": ";".join(flags),
                "num_validation_flags": len(flags),
            }
        )
    return pd.DataFrame(rows)


def validate_stress_strain_curve(
    curve: pd.DataFrame,
    min_rows: int = 20,
    min_strain_range: float = 1e-4,
    max_negative_stress_fraction: float = 0.01,
) -> dict[str, float | str]:
    """Validate one effective stress-strain curve."""
    flags = []
    stress = pd.to_numeric(curve.get("effective_stress_mpa", []), errors="coerce").to_numpy(dtype=float)
    strain = pd.to_numeric(curve.get("true_strain", []), errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(stress) & np.isfinite(strain)
    stress = stress[finite]
    strain = strain[finite]

    if len(stress) < min_rows:
        flags.append("few_curve_points")
    strain_range = float(np.nanmax(strain) - np.nanmin(strain)) if len(strain) else 0.0
    if strain_range < min_strain_range:
        flags.append("low_strain_range")
    if len(stress):
        negative_fraction = float(np.mean(stress < 0))
        if negative_fraction > max_negative_stress_fraction:
            flags.append("negative_stress_values")
    else:
        negative_fraction = float("nan")
        flags.append("no_valid_stress_values")

    return {
        "curve_rows": int(len(stress)),
        "strain_range": strain_range,
        "negative_stress_fraction": negative_fraction,
        "curve_validation_status": "pass" if not flags else "review",
        "curve_validation_flags": ";".join(flags),
        "curve_num_validation_flags": len(flags),
    }


def validate_curve_folder(curve_dir: str | Path, output_csv: str | Path | None = None) -> pd.DataFrame:
    """Validate every stress-strain curve CSV in a folder."""
    curve_dir = Path(curve_dir)
    rows = []
    for path in sorted(curve_dir.glob("*_stress_strain.csv")):
        curve = pd.read_csv(path)
        result = validate_stress_strain_curve(curve)
        result["curve_file"] = path.name
        if "hit" in curve.columns and not curve.empty:
            result["hit"] = curve["hit"].iloc[0]
        rows.append(result)
    output = pd.DataFrame(rows)
    if output_csv is not None:
        Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(output_csv, index=False)
    return output


def combine_validation(hit_validation: pd.DataFrame, curve_validation: pd.DataFrame) -> pd.DataFrame:
    """Combine hit-summary and curve validation outputs."""
    if hit_validation.empty:
        return curve_validation.copy()
    if curve_validation.empty:
        return hit_validation.copy()
    if "hit" in hit_validation.columns and "hit" in curve_validation.columns:
        return hit_validation.merge(curve_validation, on="hit", how="outer")
    return pd.concat([hit_validation.reset_index(drop=True), curve_validation.reset_index(drop=True)], axis=1)


def _float(value) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")

