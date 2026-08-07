"""
Experimental/DEFORM data fusion strategies.

The fusion layer is intentionally conservative because the final Agility Forge
data-fusion strategy is still a research decision. The implemented strategies
are scientifically defensible starting points:

1. hit_level_join: align rows by run/hit identifiers when both sources share
   those labels.
2. nearest_spatial_join: align experimental characterization points to nearest
   DEFORM coordinates when physical positions are available.
3. target_error_join: compare DEFORM rows to experimental scalar targets without
   claiming pointwise spatial correspondence.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .microstructure_targets import MicrostructureTarget, scalar_target_errors


def hit_level_join(
    experimental_df: pd.DataFrame,
    deform_df: pd.DataFrame,
    keys: list[str] | None = None,
    suffixes: tuple[str, str] = ("_exp", "_deform"),
) -> pd.DataFrame:
    """Join experimental and DEFORM rows by run/hit metadata."""
    keys = keys or [key for key in ["run_name", "hit", "global_hit_number"] if key in experimental_df.columns and key in deform_df.columns]
    if not keys:
        raise ValueError("No shared hit-level keys were found.")
    return experimental_df.merge(deform_df, on=keys, how="inner", suffixes=suffixes)


def nearest_spatial_join(
    experimental_df: pd.DataFrame,
    deform_df: pd.DataFrame,
    exp_coord_cols: tuple[str, str, str] = ("x_mm", "y_mm", "z_mm"),
    deform_coord_cols: tuple[str, str, str] = ("x_mm", "y_mm", "z_mm"),
    max_distance_mm: float | None = None,
) -> pd.DataFrame:
    """Assign each experimental point to the nearest DEFORM point/element."""
    for column in exp_coord_cols:
        if column not in experimental_df.columns:
            raise ValueError(f"Experimental table is missing coordinate column {column!r}.")
    for column in deform_coord_cols:
        if column not in deform_df.columns:
            raise ValueError(f"DEFORM table is missing coordinate column {column!r}.")

    exp_xyz = experimental_df.loc[:, exp_coord_cols].to_numpy(dtype=float)
    deform_xyz = deform_df.loc[:, deform_coord_cols].to_numpy(dtype=float)
    rows = []
    for exp_index, exp_point in enumerate(exp_xyz):
        distances = np.linalg.norm(deform_xyz - exp_point[None, :], axis=1)
        nearest_index = int(np.argmin(distances))
        distance = float(distances[nearest_index])
        if max_distance_mm is not None and distance > max_distance_mm:
            continue
        row = {}
        row.update({f"exp_{key}": value for key, value in experimental_df.iloc[exp_index].items()})
        row.update({f"deform_{key}": value for key, value in deform_df.iloc[nearest_index].items()})
        row["nearest_distance_mm"] = distance
        rows.append(row)
    return pd.DataFrame(rows)


def add_target_errors(dataset: pd.DataFrame, targets: list[MicrostructureTarget]) -> pd.DataFrame:
    """Append scalar target error columns to each row of a dataset."""
    if not targets:
        return dataset.copy()
    rows = []
    for _, row in dataset.iterrows():
        row_dict = row.to_dict()
        row_dict.update(scalar_target_errors(row, targets))
        rows.append(row_dict)
    return pd.DataFrame(rows)


def load_table(path: str | Path | None) -> pd.DataFrame:
    """Read a CSV path or return an empty table."""
    if path is None or str(path).strip() == "":
        return pd.DataFrame()
    path = Path(path)
    return pd.read_csv(path) if path.exists() else pd.DataFrame()

