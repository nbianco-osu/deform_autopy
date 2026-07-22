"""
Command-line action-file creator used by deform_config_gui.py.

This module mirrors the AF load-stroke workflow in create_action_file.py without
executing work at import time. It reads raw AF machine CSV files, detects contact
from force/position traces, calculates penetration depth, converts position and
depth to inches, and writes the DEFORM action CSV used by run_deform_hits_config.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


OUTPUT_COLUMNS = [
    "hit_number",
    "material",
    "x_mm",
    "angle_of_workpiece",
    "contact_position_mm",
    "min_position_mm",
    "depth_mm",
    "temperature_of_workpiece_C",
    "max_force_kN",
    "x_in",
    "x_rel_pos_in",
    "depth_in",
    "offset_in",
    "rotation",
]


def detect_material_from_filename(filename):
    """Infer the short material label from the AF filename convention."""
    parts = Path(filename).name.split("_")
    if len(parts) > 1 and parts[1] == "316L":
        return "316L"
    return "4140"


def process_af_hit_file(csv_path, position_start_threshold_mm=30.0, force_sigma_multiplier=1.5):
    """Extract one DEFORM action row from a raw AF load-stroke CSV."""
    hit_df = pd.read_csv(csv_path)
    hit_df["Time (s)"] = (
        hit_df["Time Unix (ms)"] - hit_df["Time Unix (ms)"].min()
    ) / 1000.0

    x_position_mm = hit_df["X"].value_counts().index.values[0]
    theta_deg = hit_df["A"].value_counts().index.values[0]
    max_force_kn = hit_df["Force (kN)"].max()

    time_s = hit_df["Time (s)"].to_numpy()
    temperature_c = hit_df["Thermal Cam Temp (c)"].to_numpy()
    position_mm = hit_df["Position (mm)"].to_numpy()
    force_kn = hit_df["Force (kN)"].to_numpy()

    sort_idx = np.argsort(time_s)
    time_s = time_s[sort_idx]
    temperature_c = temperature_c[sort_idx]
    force_kn = force_kn[sort_idx]
    position_mm = position_mm[sort_idx]

    start_candidates = np.where(position_mm <= position_start_threshold_mm)[0]
    if len(start_candidates) == 0:
        raise ValueError(
            f"{csv_path.name}: position never reached {position_start_threshold_mm} mm."
        )

    start_search_idx = int(start_candidates[0])
    baseline_force = force_kn[:start_search_idx]
    force_threshold = np.mean(baseline_force) + force_sigma_multiplier * np.std(baseline_force)
    force_threshold = max(force_threshold, 0.25)

    contact_idx = None
    for index in range(start_search_idx, len(time_s)):
        if force_kn[index] > force_threshold:
            contact_idx = max(index - 1, 0)
            break

    if contact_idx is None:
        raise ValueError(f"{csv_path.name}: no contact point detected.")

    min_idx = contact_idx + np.argmin(position_mm[contact_idx:])
    contact_position_mm = position_mm[contact_idx]
    min_position_mm = position_mm[min_idx]
    penetration_depth_mm = contact_position_mm - min_position_mm
    contact_temperature_c = temperature_c[contact_idx]

    return {
        "material": detect_material_from_filename(csv_path.name),
        "x_mm": x_position_mm,
        "angle_of_workpiece": theta_deg,
        "contact_position_mm": contact_position_mm,
        "min_position_mm": min_position_mm,
        "depth_mm": penetration_depth_mm,
        "temperature_of_workpiece_C": contact_temperature_c,
        "max_force_kN": max_force_kn,
    }


def create_action_file_from_af_load_stroke(
    base_path,
    hit_folders,
    output_dir,
    output_prefix="af",
    position_start_threshold_mm=30.0,
    force_sigma_multiplier=1.5,
):
    """Create one action CSV per AF hit folder."""
    base_path = Path(base_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_paths = []
    for hit_folder in hit_folders:
        hit_folder = str(hit_folder).strip()
        if not hit_folder:
            continue

        hit_path = base_path / hit_folder
        if not hit_path.exists():
            raise FileNotFoundError(f"AF hit folder was not found: {hit_path}")

        rows = []
        for hit_number, csv_path in enumerate(sorted(hit_path.glob("*.csv")), start=1):
            print(f"Processing hit {hit_number}: {csv_path}")
            row = process_af_hit_file(
                csv_path,
                position_start_threshold_mm=position_start_threshold_mm,
                force_sigma_multiplier=force_sigma_multiplier,
            )
            row["hit_number"] = hit_number
            rows.append(row)

        if not rows:
            raise ValueError(f"No raw AF CSV files were found in {hit_path}")

        df = pd.DataFrame(rows)
        df["x_in"] = df["x_mm"] / 25.4
        df["x_rel_pos_in"] = df["x_in"] - np.max(df["x_in"])
        df["depth_in"] = df["depth_mm"] / 25.4

        offset_vals = [0]
        rotation_vals = [0]
        x_positions = df["x_rel_pos_in"].values
        theta_values = df["angle_of_workpiece"].values
        for index, x_position in enumerate(x_positions[:-1]):
            offset_vals.append(x_positions[index + 1] - x_position)
            rotation_vals.append(theta_values[index + 1] - theta_values[index])

        df["offset_in"] = offset_vals
        df["rotation"] = rotation_vals

        output_path = output_dir / f"{output_prefix}_{hit_folder}_deform_actions.csv"
        df[OUTPUT_COLUMNS].to_csv(output_path, index=False)
        output_paths.append(output_path)
        print(f"Wrote action file: {output_path}")

    return output_paths


def parse_hit_folders(text):
    """Parse comma-separated hit folder names."""
    return [part.strip() for part in str(text).split(",") if part.strip()]


def main():
    parser = argparse.ArgumentParser(description="Create DEFORM action CSVs from AF load-stroke data.")
    parser.add_argument("--base-path", required=True, help="Folder containing AF hit subfolders.")
    parser.add_argument("--hit-folders", required=True, help="Comma-separated AF hit subfolders.")
    parser.add_argument("--output-dir", required=True, help="Folder where action CSVs will be written.")
    parser.add_argument("--output-prefix", default="af", help="Output filename prefix.")
    parser.add_argument("--position-threshold-mm", type=float, default=30.0)
    parser.add_argument("--force-sigma-multiplier", type=float, default=1.5)
    args = parser.parse_args()

    outputs = create_action_file_from_af_load_stroke(
        base_path=args.base_path,
        hit_folders=parse_hit_folders(args.hit_folders),
        output_dir=args.output_dir,
        output_prefix=args.output_prefix,
        position_start_threshold_mm=args.position_threshold_mm,
        force_sigma_multiplier=args.force_sigma_multiplier,
    )
    print("Created action files:")
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
