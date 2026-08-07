"""
Import experimental microstructure and property measurements.

This module normalizes characterization CSV files into a shared format that can
later be joined with AF process signals and DEFORM outputs. It keeps all source
columns for traceability while adding standardized columns where possible.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


STANDARD_COLUMNS = {
    "run_name": ["run_name", "run", "experiment", "sample_id", "specimen_id"],
    "hit": ["hit", "hit_number", "global_hit_number"],
    "region": ["region", "location", "section", "roi", "site"],
    "x_mm": ["x_mm", "x", "x position mm", "x_pos_mm"],
    "y_mm": ["y_mm", "y", "y position mm", "y_pos_mm"],
    "z_mm": ["z_mm", "z", "z position mm", "z_pos_mm"],
    "grain_size_um": ["grain_size_um", "grain size um", "average grain size (um)", "grain_diameter_um"],
    "hardness_hv": ["hardness_hv", "hardness hv", "hv", "vickers_hardness"],
    "porosity_fraction": ["porosity_fraction", "porosity", "void_fraction"],
    "damage_observed": ["damage_observed", "damage", "crack", "cracking"],
    "yield_strength_mpa": ["yield_strength_mpa", "yield strength mpa", "ys_mpa"],
    "ultimate_strength_mpa": ["ultimate_strength_mpa", "uts_mpa", "ultimate tensile strength mpa"],
    "elongation_percent": ["elongation_percent", "elongation", "percent_elongation"],
}


def _normalize_name(name: str) -> str:
    """Normalize a column name for robust matching."""
    return str(name).strip().lower().replace("_", " ")


def find_source_column(df: pd.DataFrame, standard_name: str) -> str | None:
    """Find a source column for one standardized output column."""
    normalized = {_normalize_name(column): column for column in df.columns}
    for alias in STANDARD_COLUMNS.get(standard_name, []):
        key = _normalize_name(alias)
        if key in normalized:
            return normalized[key]
    return None


def normalize_microstructure_table(
    df: pd.DataFrame,
    source_file: str = "",
    keep_source_columns: bool = True,
) -> pd.DataFrame:
    """Normalize one characterization table to standard columns."""
    output = pd.DataFrame(index=df.index)
    for standard_name in STANDARD_COLUMNS:
        source = find_source_column(df, standard_name)
        if source is None:
            output[standard_name] = np.nan
            continue
        if standard_name in {"run_name", "region", "damage_observed"}:
            output[standard_name] = df[source].astype(str)
        else:
            output[standard_name] = pd.to_numeric(df[source], errors="coerce")

    output["source_file"] = source_file
    if keep_source_columns:
        for column in df.columns:
            output[f"source_{column}"] = df[column]
    return output


def load_microstructure_file(path: str | Path, keep_source_columns: bool = True) -> pd.DataFrame:
    """Load and normalize one characterization CSV file."""
    path = Path(path)
    df = pd.read_csv(path)
    normalized = normalize_microstructure_table(
        df,
        source_file=path.name,
        keep_source_columns=keep_source_columns,
    )
    return normalized


def load_microstructure_folder(
    folder: str | Path,
    glob_pattern: str = "*.csv",
    keep_source_columns: bool = True,
) -> pd.DataFrame:
    """Load all characterization CSVs in a folder into one normalized table."""
    folder = Path(folder)
    tables = [
        load_microstructure_file(path, keep_source_columns=keep_source_columns)
        for path in sorted(folder.glob(glob_pattern))
    ]
    if not tables:
        return pd.DataFrame()
    return pd.concat(tables, ignore_index=True)


def summarize_microstructure_by_group(
    df: pd.DataFrame,
    group_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Summarize normalized microstructure/property values by run/hit/region."""
    if df.empty:
        return pd.DataFrame()
    group_columns = group_columns or [column for column in ["run_name", "hit", "region"] if column in df.columns]
    numeric_columns = [
        column
        for column in [
            "grain_size_um",
            "hardness_hv",
            "porosity_fraction",
            "yield_strength_mpa",
            "ultimate_strength_mpa",
            "elongation_percent",
        ]
        if column in df.columns
    ]
    if not group_columns or not numeric_columns:
        return pd.DataFrame()

    grouped = df.groupby(group_columns, dropna=False)[numeric_columns]
    summary = grouped.agg(["count", "mean", "std", "min", "median", "max"])
    summary.columns = ["_".join(parts).strip("_") for parts in summary.columns]
    return summary.reset_index()


def write_microstructure_import_outputs(
    input_path: str | Path,
    output_dir: str | Path,
    glob_pattern: str = "*.csv",
) -> dict[str, str]:
    """Import characterization data from a file/folder and write normalized CSVs."""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if input_path.is_dir():
        normalized = load_microstructure_folder(input_path, glob_pattern=glob_pattern)
    else:
        normalized = load_microstructure_file(input_path)

    normalized_csv = output_dir / "experimental_microstructure_normalized.csv"
    summary_csv = output_dir / "experimental_microstructure_summary.csv"
    normalized.to_csv(normalized_csv, index=False)
    summarize_microstructure_by_group(normalized).to_csv(summary_csv, index=False)
    return {
        "experimental_microstructure_normalized": str(normalized_csv),
        "experimental_microstructure_summary": str(summary_csv),
        "experimental_microstructure_rows": str(len(normalized)),
    }

