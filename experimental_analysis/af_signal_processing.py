"""
Process Agility Forge force-position-temperature hit files.

The methods here follow the same basic contact logic used by the action-file
creator: contact is detected when force rises above a baseline threshold after
the tool is near the workpiece. Stress-strain output is labelled "effective"
because AF open-die indentation is not a uniform uniaxial compression test. The
conversion is still useful for comparing hits when the contact-area assumption is
kept consistent and documented.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .schema import AFColumnMap, ContactDetectionConfig, StressStrainConfig


COMMON_COLUMN_ALIASES = {
    "Time (s)": ["Time (s)", "Time", "time", "t", "Seconds"],
    "Position (mm)": ["Position (mm)", "Position", "position", "Ram Position (mm)"],
    "Force (kN)": ["Force (kN)", "Force", "force", "Load (kN)", "Load"],
    "Thermal Cam Temp (c)": [
        "Thermal Cam Temp (c)",
        "Thermal Cam Temp (C)",
        "Temperature (C)",
        "Temp (C)",
        "temperature",
    ],
}


def resolve_column(df: pd.DataFrame, requested: str | None, logical_name: str) -> str:
    """Resolve a requested column using common aliases if needed."""
    if requested and requested in df.columns:
        return requested
    for alias in COMMON_COLUMN_ALIASES.get(logical_name, []):
        if alias in df.columns:
            return alias
    lowered = {str(column).strip().lower(): column for column in df.columns}
    if requested and requested.strip().lower() in lowered:
        return lowered[requested.strip().lower()]
    for alias in COMMON_COLUMN_ALIASES.get(logical_name, []):
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    raise KeyError(f"Could not find {logical_name!r}. Available columns: {list(df.columns)}")


def read_af_hit_csv(csv_path: str | Path, column_map: AFColumnMap | None = None) -> pd.DataFrame:
    """Read one AF hit CSV and normalize core columns."""
    column_map = column_map or AFColumnMap()
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path)

    columns = {
        "time_s": resolve_column(df, column_map.time_s, "Time (s)"),
        "position_mm": resolve_column(df, column_map.position_mm, "Position (mm)"),
        "force_kn": resolve_column(df, column_map.force_kn, "Force (kN)"),
        "temperature_c": resolve_column(df, column_map.temperature_c, "Thermal Cam Temp (c)"),
    }

    normalized = pd.DataFrame(
        {
            name: pd.to_numeric(df[source], errors="coerce")
            for name, source in columns.items()
        }
    ).dropna(subset=["time_s", "position_mm", "force_kn"])
    normalized = normalized.sort_values("time_s").reset_index(drop=True)
    normalized["source_file"] = csv_path.name
    normalized["hit"] = infer_hit_number(csv_path.name)
    return normalized


def infer_hit_number(filename: str) -> int | None:
    """Infer hit number from a filename, returning None when no number is found."""
    matches = re.findall(r"(?:hit|h)[ _-]*(\d+)|(?:^|[_-])(\d+)(?:[_-]|$)", filename, flags=re.I)
    numbers = [int(item) for match in matches for item in match if item != ""]
    return numbers[-1] if numbers else None


def detect_contact(
    hit_df: pd.DataFrame,
    config: ContactDetectionConfig | None = None,
) -> dict[str, float | int]:
    """Detect first contact and deepest penetration in one AF hit."""
    config = config or ContactDetectionConfig()
    position = hit_df["position_mm"].to_numpy(dtype=float)
    force = hit_df["force_kn"].to_numpy(dtype=float)
    time = hit_df["time_s"].to_numpy(dtype=float)
    temp = hit_df["temperature_c"].to_numpy(dtype=float)

    start_candidates = np.where(position < config.position_start_threshold_mm)[0]
    start_idx = int(start_candidates[0]) if len(start_candidates) else 0
    baseline = force[: max(start_idx, 3)]
    if len(baseline) < 3:
        baseline = force[: min(len(force), 10)]
    threshold = float(np.nanmean(baseline) + config.force_sigma_multiplier * np.nanstd(baseline))
    threshold = max(threshold, config.minimum_force_threshold_kn)

    contact_idx = None
    for index in range(start_idx, len(force)):
        if force[index] > threshold:
            contact_idx = max(index - config.contact_index_correction, 0)
            break
    if contact_idx is None:
        raise ValueError("No contact point detected from force threshold.")

    min_idx = int(contact_idx + np.nanargmin(position[contact_idx:]))
    depth_mm = float(position[contact_idx] - position[min_idx])
    return {
        "contact_idx": int(contact_idx),
        "min_idx": int(min_idx),
        "contact_time_s": float(time[contact_idx]),
        "min_time_s": float(time[min_idx]),
        "contact_position_mm": float(position[contact_idx]),
        "min_position_mm": float(position[min_idx]),
        "depth_mm": depth_mm,
        "contact_force_kn": float(force[contact_idx]),
        "max_force_kn": float(np.nanmax(force[contact_idx:])),
        "contact_temperature_c": float(temp[contact_idx]) if len(temp) else np.nan,
        "force_threshold_kn": threshold,
    }


def contact_area_mm2(depth_mm: np.ndarray, config: StressStrainConfig) -> np.ndarray:
    """Estimate projected contact area for effective stress calculations."""
    if config.contact_area_mm2 is not None:
        return np.full_like(depth_mm, max(float(config.contact_area_mm2), config.min_contact_area_mm2))

    if config.contact_area_mode == "flat_punch":
        diameter = config.flat_punch_diameter_mm or config.stock_diameter_mm
        area = np.pi * (float(diameter) / 2.0) ** 2
        return np.full_like(depth_mm, max(area, config.min_contact_area_mm2))

    if config.contact_area_mode == "growing_flat":
        diameter = np.clip(2.0 * np.sqrt(np.maximum(depth_mm, 0.0) * config.stock_diameter_mm), 0.0, config.stock_diameter_mm)
        area = np.pi * (diameter / 2.0) ** 2
        return np.maximum(area, config.min_contact_area_mm2)

    raise ValueError("contact_area_mode must be flat_punch or growing_flat.")


def effective_stress_strain_curve(
    hit_df: pd.DataFrame,
    contact: dict[str, float | int],
    config: StressStrainConfig | None = None,
) -> pd.DataFrame:
    """Convert post-contact AF force-position data to effective stress-strain."""
    config = config or StressStrainConfig()
    contact_idx = int(contact["contact_idx"])
    curve = hit_df.iloc[contact_idx:].copy().reset_index(drop=True)
    depth = float(contact["contact_position_mm"]) - curve["position_mm"].to_numpy(dtype=float)
    depth = np.maximum(depth, 0.0)
    force_n = curve["force_kn"].to_numpy(dtype=float) * 1000.0
    area = contact_area_mm2(depth, config)
    stress_mpa = force_n / area

    reference_height = config.initial_height_mm or config.stock_diameter_mm
    engineering_strain = depth / max(reference_height, 1e-9)
    true_strain = -np.log(np.clip(1.0 - engineering_strain, 1e-9, None))

    curve["depth_mm"] = depth
    curve["contact_area_mm2"] = area
    curve["effective_stress_mpa"] = stress_mpa
    curve["engineering_strain"] = engineering_strain
    curve["true_strain"] = true_strain
    return curve


def process_af_hit_file(
    csv_path: str | Path,
    output_dir: str | Path | None = None,
    column_map: AFColumnMap | None = None,
    contact_config: ContactDetectionConfig | None = None,
    stress_config: StressStrainConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, float | int | str]]:
    """Process one raw AF hit file into a stress-strain curve and summary."""
    hit_df = read_af_hit_csv(csv_path, column_map=column_map)
    contact = detect_contact(hit_df, config=contact_config)
    curve = effective_stress_strain_curve(hit_df, contact, config=stress_config)
    summary = {
        **contact,
        "source_file": Path(csv_path).name,
        "hit": hit_df["hit"].iloc[0],
        "curve_rows": int(len(curve)),
        "temperature_mean_c": float(np.nanmean(curve["temperature_c"])),
    }

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(csv_path).stem
        curve.to_csv(output_dir / f"{stem}_stress_strain.csv", index=False)
    return curve, summary


def process_af_folder(
    raw_dir: str | Path,
    output_dir: str | Path,
    hit_glob: str = "*.csv",
    column_map: AFColumnMap | None = None,
    contact_config: ContactDetectionConfig | None = None,
    stress_config: StressStrainConfig | None = None,
) -> tuple[pd.DataFrame, list[Path]]:
    """Process every AF hit CSV in a folder."""
    raw_dir = Path(raw_dir)
    output_dir = Path(output_dir)
    curve_dir = output_dir / "stress_strain_curves"
    summaries = []
    curve_paths = []
    for csv_path in sorted(raw_dir.glob(hit_glob), key=lambda path: (infer_hit_number(path.name) or 10**9, path.name)):
        curve, summary = process_af_hit_file(
            csv_path,
            output_dir=curve_dir,
            column_map=column_map,
            contact_config=contact_config,
            stress_config=stress_config,
        )
        summaries.append(summary)
        curve_paths.append(curve_dir / f"{csv_path.stem}_stress_strain.csv")

    summary_df = pd.DataFrame(summaries)
    if not summary_df.empty:
        summary_df.to_csv(output_dir / "af_hit_signal_summary.csv", index=False)
    return summary_df, curve_paths

