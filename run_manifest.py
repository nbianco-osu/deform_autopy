"""
Run manifest utilities for DEFORM optimization studies.

The manifest is a durable CSV log where each row describes one simulation,
hit, or aggregate run. It is intentionally simple: run scripts and
post-processing scripts can append dictionaries without needing a database.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


DEFAULT_MANIFEST_COLUMNS = [
    "record_id",
    "timestamp",
    "study_name",
    "run_name",
    "run_dir",
    "hit",
    "status",
    "config_path",
    "action_file",
    "material",
    "die",
    "die_motion_mode",
    "grain_init_mode",
    "notes",
]


def _json_default(value):
    """Convert non-JSON scalar types to strings for metadata storage."""
    try:
        return value.item()
    except AttributeError:
        return str(value)


def serialize_metadata(metadata):
    """Serialize nested metadata to a compact JSON string."""
    if metadata in (None, ""):
        return ""
    return json.dumps(metadata, sort_keys=True, default=_json_default)


def ensure_manifest(manifest_path, columns=None):
    """Create an empty manifest CSV if it does not already exist."""
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        columns = DEFAULT_MANIFEST_COLUMNS + ["metadata_json"]
    if not manifest_path.exists():
        pd.DataFrame(columns=columns).to_csv(manifest_path, index=False)
    return manifest_path


def load_manifest(manifest_path):
    """Load a manifest CSV, returning an empty default manifest if missing."""
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        ensure_manifest(manifest_path)
    return pd.read_csv(manifest_path)


def next_record_id(df):
    """Return a simple monotonically increasing record id."""
    if df.empty or "record_id" not in df.columns:
        return 1
    return int(pd.to_numeric(df["record_id"], errors="coerce").max()) + 1


def append_manifest_record(manifest_path, record, metadata=None):
    """Append one run/hit record to the manifest CSV.

    Parameters
    ----------
    manifest_path : str or Path
        Destination CSV.
    record : dict
        Flat columns such as run name, material, die, status, hit, etc.
    metadata : dict or None
        Optional nested data stored in `metadata_json`.
    """
    manifest_path = ensure_manifest(manifest_path)
    df = load_manifest(manifest_path)

    row = {column: "" for column in df.columns}
    row.update(record)
    row["record_id"] = row.get("record_id") or next_record_id(df)
    row["timestamp"] = row.get("timestamp") or datetime.now().isoformat(timespec="seconds")
    row["metadata_json"] = serialize_metadata(metadata)

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(manifest_path, index=False)
    return row


def update_manifest_status(manifest_path, record_id, status, notes=None):
    """Update status and optional notes for an existing manifest record."""
    manifest_path = Path(manifest_path)
    df = load_manifest(manifest_path)
    mask = pd.to_numeric(df["record_id"], errors="coerce") == int(record_id)
    if not mask.any():
        raise ValueError(f"record_id {record_id} not found in {manifest_path}")

    df.loc[mask, "status"] = status
    if notes is not None:
        df.loc[mask, "notes"] = notes
    df.to_csv(manifest_path, index=False)
    return df.loc[mask].iloc[0].to_dict()
