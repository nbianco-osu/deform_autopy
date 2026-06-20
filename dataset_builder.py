"""
Build tabular optimization datasets from DEFORM manifests and metrics files.

The output dataset should have one row per run or per hit, with input features
and measured outputs/objectives in the same table.
"""

import json
from pathlib import Path

import pandas as pd

from metrics import collect_metrics_from_files, weighted_objective
from run_manifest import load_manifest


def flatten_dict(data, prefix=""):
    """Flatten nested dictionaries into feature columns."""
    flat = {}
    for key, value in (data or {}).items():
        name = f"{prefix}{key}" if not prefix else f"{prefix}_{key}"
        if isinstance(value, dict):
            flat.update(flatten_dict(value, name))
        else:
            flat[name] = value
    return flat


def parse_metadata_json(value):
    """Parse metadata JSON from a manifest row."""
    if value in ("", None) or pd.isna(value):
        return {}
    return json.loads(value)


def build_dataset_from_manifest(
    manifest_path,
    output_csv_path,
    metric_file_columns=None,
    objective_weights=None,
):
    """Build a dataset from manifest rows plus optional metric files.

    `metric_file_columns` maps metric source names to manifest columns:

    ```
    {
        "microstructure_csv": "microstructure_csv",
        "load_stroke_csv": "load_stroke_csv",
        "coordinate_csv": "coordinate_csv"
    }
    ```
    """
    if metric_file_columns is None:
        metric_file_columns = {
            "initial_microstructure_csv": "initial_microstructure_csv",
            "microstructure_csv": "microstructure_csv",
            "load_stroke_csv": "load_stroke_csv",
            "coordinate_csv": "coordinate_csv",
            "damage_csv": "damage_csv",
        }

    manifest = load_manifest(manifest_path)
    rows = []

    for _, manifest_row in manifest.iterrows():
        row = manifest_row.to_dict()
        metadata = flatten_dict(parse_metadata_json(row.get("metadata_json")))
        row.update({f"meta_{key}": value for key, value in metadata.items()})

        metric_inputs = {}
        for metric_key, column_name in metric_file_columns.items():
            path_value = row.get(column_name)
            if path_value not in ("", None) and not pd.isna(path_value):
                metric_inputs[metric_key] = path_value

        metrics = collect_metrics_from_files(**metric_inputs)
        row.update(metrics)

        if objective_weights:
            row.update(weighted_objective(metrics, objective_weights))

        rows.append(row)

    dataset = pd.DataFrame(rows)
    output_csv_path = Path(output_csv_path)
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(output_csv_path, index=False)
    return dataset


def append_candidate_inputs(dataset_csv_path, candidates_csv_path, output_csv_path):
    """Append proposed candidate runs to an existing dataset for planning."""
    dataset = pd.read_csv(dataset_csv_path) if Path(dataset_csv_path).exists() else pd.DataFrame()
    candidates = pd.read_csv(candidates_csv_path)
    combined = pd.concat([dataset, candidates], ignore_index=True, sort=False)
    output_csv_path = Path(output_csv_path)
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_csv_path, index=False)
    return combined
