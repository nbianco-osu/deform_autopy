"""
Run pyJMAK on local thermal histories throughout a workpiece.

The existing pyJMAK adapter runs one bulk temperature history, usually from the
thermal camera or a representative hit curve. This module handles spatially
resolved histories such as DEFORM nodal/element exports:

    location_id,time_s,temperature_c,x_mm,y_mm,z_mm
    101,0.00,1050.0,0.0,0.0,0.0
    101,0.05,1048.2,0.0,0.0,0.0
    102,0.00,998.0,3.0,0.0,0.0

For each location, pyJMAK receives the local time-temperature path and returns
phase fractions at that location. With the stable 316L material file this should
stay Austenite = 1.0 unless the local temperature history reaches a calibrated
transformation or melting range.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from .pyjmak_adapter import run_pyjmak_phase_simulation


LOCATION_ALIASES = ["location_id", "node_id", "element_id", "point_id", "id"]
TIME_ALIASES = ["time_s", "time", "Time", "Time (s)"]
TEMPERATURE_ALIASES = ["temperature_c", "temp_c", "Temperature (C)", "Thermal Cam Temp (c)"]
COORDINATE_ALIASES = {
    "x_mm": ["x_mm", "x", "X", "X (mm)"],
    "y_mm": ["y_mm", "y", "Y", "Y (mm)"],
    "z_mm": ["z_mm", "z", "Z", "Z (mm)"],
}


def first_existing_column(columns: list[str], aliases: list[str]) -> str | None:
    """Return the first matching column from a list of aliases."""
    lower_lookup = {str(column).strip().lower(): column for column in columns}
    for alias in aliases:
        exact = str(alias).strip()
        if exact in columns:
            return exact
        lower = exact.lower()
        if lower in lower_lookup:
            return lower_lookup[lower]
    return None


def normalize_local_temperature_history(
    input_csv: str | Path,
    output_csv: str | Path | None = None,
) -> pd.DataFrame:
    """Read a local thermal-history CSV and normalize expected column names."""
    input_csv = Path(input_csv)
    df = pd.read_csv(input_csv)
    columns = list(df.columns)

    location_col = first_existing_column(columns, LOCATION_ALIASES)
    time_col = first_existing_column(columns, TIME_ALIASES)
    temp_col = first_existing_column(columns, TEMPERATURE_ALIASES)
    if location_col is None:
        raise ValueError(f"{input_csv} is missing a location column. Expected one of {LOCATION_ALIASES}.")
    if time_col is None:
        raise ValueError(f"{input_csv} is missing a time column. Expected one of {TIME_ALIASES}.")
    if temp_col is None:
        raise ValueError(f"{input_csv} is missing a temperature column. Expected one of {TEMPERATURE_ALIASES}.")

    normalized = pd.DataFrame(
        {
            "location_id": df[location_col].astype(str),
            "time_s": pd.to_numeric(df[time_col], errors="coerce"),
            "temperature_c": pd.to_numeric(df[temp_col], errors="coerce"),
        }
    )
    for target, aliases in COORDINATE_ALIASES.items():
        source = first_existing_column(columns, aliases)
        normalized[target] = pd.to_numeric(df[source], errors="coerce") if source else np.nan

    normalized = normalized.dropna(subset=["time_s", "temperature_c"])
    normalized = normalized.sort_values(["location_id", "time_s"]).reset_index(drop=True)
    if normalized.empty:
        raise ValueError(f"{input_csv} does not contain usable local temperature rows.")

    if output_csv:
        output_csv = Path(output_csv)
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        normalized.to_csv(output_csv, index=False)
    return normalized


def location_metadata(group: pd.DataFrame) -> dict[str, float | str]:
    """Capture one row of spatial metadata for a location."""
    row = {"location_id": str(group["location_id"].iloc[0])}
    for column in ["x_mm", "y_mm", "z_mm"]:
        values = pd.to_numeric(group[column], errors="coerce").dropna()
        row[column] = float(values.iloc[0]) if not values.empty else np.nan
    return row


def write_pyjmak_temperature_file(group: pd.DataFrame, output_file: str | Path) -> Path:
    """Write one location history in pyJMAK's two-column input format."""
    output_file = Path(output_file)
    history = group[["time_s", "temperature_c"]].copy()
    history["time_s"] = pd.to_numeric(history["time_s"], errors="coerce")
    history["temperature_c"] = pd.to_numeric(history["temperature_c"], errors="coerce")
    history = history.dropna().sort_values("time_s")
    if history.empty:
        raise ValueError("Cannot write pyJMAK temperature file for an empty local history.")
    history["time_s"] = history["time_s"] - float(history["time_s"].iloc[0])
    history.to_csv(output_file, index=False, header=False)
    return output_file


def run_pyjmak_for_local_histories(
    local_temperature_csv: str | Path,
    output_dir: str | Path,
    material_input_file: str | Path,
    source_path: str | Path | None = None,
    max_locations: int | None = None,
    verbose: bool = False,
) -> dict[str, str]:
    """Run pyJMAK independently for each local workpiece history.

    Parameters
    ----------
    local_temperature_csv:
        CSV with location, time, temperature, and optional x/y/z columns.
    output_dir:
        Folder where normalized histories and pyJMAK results are written.
    material_input_file:
        Abaqus-like pyJMAK material input. For 316L, start with
        `pyjmak_316L_stable_austenite_nist.inp`.
    max_locations:
        Optional throttle for testing large DEFORM exports. Leave blank/None for
        all locations.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_csv = output_dir / "local_temperature_histories_normalized.csv"
    normalized = normalize_local_temperature_history(local_temperature_csv, normalized_csv)

    local_results = []
    local_summaries = []
    temp_root = output_dir / "pyjmak_local_temperature_files"
    temp_root.mkdir(parents=True, exist_ok=True)

    grouped = list(normalized.groupby("location_id", sort=True))
    if max_locations is not None:
        grouped = grouped[: int(max_locations)]

    for location_id, group in grouped:
        safe_id = "".join(char if char.isalnum() or char in "-_." else "_" for char in str(location_id))
        temperature_file = temp_root / f"{safe_id}_temperature.csv"
        output_csv = output_dir / "local_phase_fraction_files" / f"{safe_id}_phase_fractions.csv"
        output_csv.parent.mkdir(parents=True, exist_ok=True)

        write_pyjmak_temperature_file(group, temperature_file)
        run_pyjmak_phase_simulation(
            temperature_file=temperature_file,
            material_input_file=material_input_file,
            output_csv=output_csv,
            source_path=source_path,
            verbose=verbose,
        )
        result = pd.read_csv(output_csv)
        metadata = location_metadata(group)
        for key, value in metadata.items():
            result[key] = value
        local_results.append(result)

        final = result.tail(1).iloc[0].to_dict()
        summary = dict(metadata)
        summary.update(
            {
                "temperature_min_c": float(pd.to_numeric(group["temperature_c"], errors="coerce").min()),
                "temperature_max_c": float(pd.to_numeric(group["temperature_c"], errors="coerce").max()),
                "time_max_s": float(pd.to_numeric(group["time_s"], errors="coerce").max()),
                "phase_fraction_csv": str(output_csv),
            }
        )
        for column in result.columns:
            if column.startswith("phase_fraction_"):
                summary[f"final_{column}"] = float(final[column])
        local_summaries.append(summary)

    combined_csv = output_dir / "local_pyjmak_phase_fractions.csv"
    summary_csv = output_dir / "local_pyjmak_phase_summary.csv"
    if local_results:
        pd.concat(local_results, ignore_index=True).to_csv(combined_csv, index=False)
    else:
        pd.DataFrame().to_csv(combined_csv, index=False)
    pd.DataFrame(local_summaries).to_csv(summary_csv, index=False)

    summary_json = output_dir / "local_pyjmak_outputs.json"
    outputs = {
        "local_temperature_histories_normalized": str(normalized_csv),
        "local_pyjmak_phase_fractions": str(combined_csv),
        "local_pyjmak_phase_summary": str(summary_csv),
        "local_pyjmak_location_count": str(len(local_summaries)),
        "local_pyjmak_material_input_file": str(material_input_file),
    }
    summary_json.write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    outputs["local_pyjmak_outputs_json"] = str(summary_json)
    return outputs
