"""
Process completed DEFORM DOE runs into metrics and a training dataset.

This file is the bridge between `run_initial_doe.py` / `doe_runner.py` and the
optimization loop:

1. Read the DOE manifest.
2. For each completed run, find the generated config and run folder.
3. Save the initial pre-run GRAIN state from the starting key file.
4. Parse post-hit/final GRAIN key files into microstructure CSVs.
5. Track maximum damage using DEFORM object info when the API is available.
6. Discover coordinate/load CSVs when they already exist.
7. Update the manifest with result-file paths.
8. Build `dataset.csv` for surrogate modeling and Bayesian optimization.

The file is designed to run in Spyder on the lab computer. It can also run on a
non-DEFORM computer for file-only processing, but DB-to-damage extraction needs
the DEFORM Python API on the path.
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from dataset_builder import build_dataset_from_manifest
from metrics import summarize_damage
from microstructure_post_processing import save_microstructure_csv_from_key
from run_manifest import load_manifest


RESULT_COLUMNS = [
    "processed_status",
    "processing_notes",
    "initial_microstructure_csv",
    "microstructure_csv",
    "hit_microstructure_csvs",
    "damage_csv",
    "coordinate_csv",
    "load_stroke_csv",
]


def is_blank(value):
    """Return True for missing manifest/config values."""
    return value is None or value == "" or pd.isna(value)


def load_json(path):
    """Load a JSON file."""
    with open(path, "r") as file:
        return json.load(file)


def parse_json_or_file(value, default=None):
    """Parse a JSON string or a path to a JSON file."""
    if is_blank(value):
        return default
    if isinstance(value, dict):
        return value

    text = str(value)
    if text.lstrip().startswith(("{", "[")):
        return json.loads(text)

    path = Path(text)
    if path.exists():
        return load_json(path)
    return json.loads(text)


def ensure_columns(df, columns):
    """Ensure a DataFrame contains all requested columns."""
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    return df


def format_config_value(value, config):
    """Apply the same simple config placeholders used by the DEFORM runner."""
    if not isinstance(value, str):
        return value
    return value.format(
        tp_type=config.get("tp_type", ""),
        material=config.get("material", ""),
        run_number=config.get("run_number", ""),
        num_hits=config.get("num_hits", ""),
        height=config.get("height", ""),
        die=config.get("die", ""),
        mesh_type=config.get("mesh_type", ""),
        stock_diameter=config.get("stock_diameter", ""),
    )


def resolve_path(path_value, config, config_dir):
    """Resolve absolute paths and config-relative paths."""
    if is_blank(path_value):
        return None

    path_value = format_config_value(str(path_value), config)
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (Path(config_dir) / path).resolve()


def get_action_path(config, config_dir):
    """Resolve the action CSV referenced by a generated run config."""
    action_file = format_config_value(config.get("action_file", ""), config)
    if is_blank(action_file):
        return None

    action_path = Path(action_file)
    if action_path.is_absolute():
        return action_path

    action_parent = config.get("action_path", config.get("base_path", ""))
    action_parent = resolve_path(action_parent, config, config_dir)
    return action_parent / action_path if action_parent else None


def infer_die(config, action_path):
    """Infer die number from config first, then from the action CSV."""
    if not is_blank(config.get("die")):
        return int(config["die"])

    if action_path and action_path.exists():
        action_df = pd.read_csv(action_path)
        die_column = config.get("die_column", "die")
        if die_column in action_df.columns:
            return int(action_df[die_column].iloc[0])

    return None


def infer_num_hits(config, action_path):
    """Infer the number of hits from config or the action CSV."""
    num_hits = config.get("num_hits", "all")
    if isinstance(num_hits, str) and num_hits.lower() == "all":
        if action_path and action_path.exists():
            return int(len(pd.read_csv(action_path)))
        return None
    return int(num_hits)


def resolve_initial_key(config, config_path):
    """Resolve the starting key file used before hit 1.

    Capturing this file's GRAIN block preserves the supplier/initial grain
    state before the first DEFORM solve changes the microstructure.
    """
    config_dir = Path(config_path).resolve().parent
    if not is_blank(config.get("init_key")):
        return resolve_path(config["init_key"], config, config_dir)

    action_path = get_action_path(config, config_dir)
    die = infer_die(config, action_path)
    if die is None:
        return None

    key_files = config.get("key_files", {})
    key_template = key_files.get(str(die))
    if is_blank(key_template):
        return None

    key_path = resolve_path(config.get("key_path", ""), config, config_dir)
    if key_path is None:
        return None
    return key_path / format_config_value(key_template, config)


def latest_file(paths):
    """Return the newest file from a list of candidate paths."""
    paths = [Path(path) for path in paths if Path(path).exists()]
    if not paths:
        return None
    return max(paths, key=lambda path: path.stat().st_mtime)


def find_first_file(root, patterns):
    """Find the newest matching file under a run folder."""
    root = Path(root)
    if not root.exists():
        return None

    matches = []
    for pattern in patterns:
        matches.extend(root.rglob(pattern))
    return latest_file(matches)


def find_hit_key(run_dir, run_name, hit):
    """Find the post-hit key file for one multihit run."""
    run_dir = Path(run_dir)
    hit_dir = run_dir / f"{run_name}-hit{hit}"
    explicit = [
        hit_dir / f"af-hit-{hit}_final.KEY",
        hit_dir / f"af-hit-{hit}_final.key",
        hit_dir / f"af-hit-{hit}_post.KEY",
        hit_dir / f"af-hit-{hit}_post.key",
    ]
    found = latest_file(explicit)
    if found:
        return found

    patterns = [
        f"*hit*{hit}*final*.KEY",
        f"*hit*{hit}*final*.key",
        f"*hit*{hit}*post*.KEY",
        f"*hit*{hit}*post*.key",
        f"*{hit}*final*.KEY",
        f"*{hit}*final*.key",
        f"*{hit}*post*.KEY",
        f"*{hit}*post*.key",
    ]
    search_root = hit_dir if hit_dir.exists() else run_dir
    return find_first_file(search_root, patterns)


def save_initial_microstructure(config, config_path, output_dir, notes):
    """Save the pre-run GRAIN block from the starting key file."""
    initial_key = resolve_initial_key(config, config_path)
    if initial_key is None:
        notes.append("Could not resolve initial key file for initial grain capture.")
        return ""
    if not initial_key.exists():
        notes.append(f"Initial key file was not found: {initial_key}")
        return ""

    output_path = output_dir / "initial_microstructure.csv"
    try:
        save_microstructure_csv_from_key(initial_key, output_path)
        return str(output_path)
    except Exception as exc:
        notes.append(f"Initial microstructure was not saved: {exc}")
        return ""


def save_hit_microstructures(run_dir, run_name, num_hits, output_dir, notes):
    """Save post-hit microstructure CSVs and return all paths plus the final path."""
    if num_hits is None:
        notes.append("Could not infer num_hits; final microstructure search skipped.")
        return [], ""

    hit_csvs = []
    final_csv = ""

    for hit in range(1, num_hits + 1):
        key_path = find_hit_key(run_dir, run_name, hit)
        if key_path is None:
            notes.append(f"No post-hit key file found for hit {hit}.")
            continue

        output_path = output_dir / f"microstructure_hit{hit}.csv"
        try:
            save_microstructure_csv_from_key(key_path, output_path)
            hit_csvs.append(str(output_path))
            final_csv = str(output_path)
        except Exception as exc:
            notes.append(f"Microstructure parse failed for hit {hit}: {exc}")

    return hit_csvs, final_csv


def find_related_csvs(run_dir):
    """Discover common post-processing CSVs that may already exist."""
    return {
        "coordinate_csv": find_first_file(run_dir, ["*coord*.csv", "*coordinate*.csv"]),
        "load_stroke_csv": find_first_file(run_dir, ["*load*stroke*.csv", "*load_stroke*.csv"]),
    }


def find_final_db(run_dir):
    """Find a likely final DB file for DEFORM API object-info extraction."""
    return find_first_file(run_dir, ["*.DB", "*.db"])


def extract_damage_with_deform_api(run_dir, object_name="Workpiece", step_no=0):
    """Extract workpiece damage min/max using DEFORM object info.

    The DEFORM API reference manual lists `damageMin` and `damageMax` as
    members of `StructObjInfo`; its object-info use case reads a DB step, gets
    the workpiece object, then calls `getObjInfo()`.
    """
    db_path = find_final_db(run_dir)
    if db_path is None:
        raise FileNotFoundError(f"No DB file found under {run_dir}")

    from deformModel import defModel

    defModel.setCurrentDir(str(db_path.parent))
    defModel.readDb(str(db_path), step_no)

    try:
        obj = defModel.getObj(object_name)
    except Exception:
        obj = defModel.getObjByNo(1)

    obj_info = obj.getObjInfo()
    return {
        "source": "deform_api_getObjInfo",
        "source_file": str(db_path),
        "object": object_name,
        "step_no": step_no,
        "damage_min": float(obj_info.damageMin),
        "damage_max": float(obj_info.damageMax),
    }


def extract_damage_from_existing_csv(run_dir):
    """Fallback: summarize an existing damage CSV if one was exported."""
    damage_file = find_first_file(run_dir, ["*damage*.csv", "*Damage*.csv"])
    if damage_file is None:
        return None

    summary = summarize_damage(damage_file)
    if "damage_max" not in summary:
        return None
    return {
        "source": "existing_damage_csv",
        "source_file": str(damage_file),
        "object": "",
        "step_no": "",
        "damage_min": summary.get("damage_min", ""),
        "damage_max": summary.get("damage_max", ""),
    }


def save_damage_summary(run_dir, output_dir, notes, object_name="Workpiece", step_no=0):
    """Save normalized damage min/max to a small CSV."""
    damage_row = None
    try:
        damage_row = extract_damage_with_deform_api(
            run_dir=run_dir,
            object_name=object_name,
            step_no=step_no,
        )
    except Exception as exc:
        notes.append(f"DEFORM API damage extraction skipped/failed: {exc}")
        damage_row = extract_damage_from_existing_csv(run_dir)

    if damage_row is None:
        notes.append("No max-damage source found.")
        return ""

    output_path = output_dir / "damage_summary.csv"
    pd.DataFrame([damage_row]).to_csv(output_path, index=False)
    return str(output_path)


def process_manifest_row(row, output_subdir="processed", damage_object="Workpiece", damage_step_no=0):
    """Process one manifest row and return manifest-column updates."""
    notes = []
    updates = {column: "" for column in RESULT_COLUMNS}

    run_name = str(row.get("run_name", ""))
    run_dir = Path(str(row.get("run_dir", "")))
    config_path = Path(str(row.get("config_path", "")))

    if is_blank(run_name):
        updates["processed_status"] = "skipped"
        updates["processing_notes"] = "Missing run_name."
        return updates
    if is_blank(str(run_dir)) or not run_dir.exists():
        updates["processed_status"] = "skipped"
        updates["processing_notes"] = f"Run directory not found: {run_dir}"
        return updates
    if is_blank(str(config_path)) or not config_path.exists():
        updates["processed_status"] = "skipped"
        updates["processing_notes"] = f"Config file not found: {config_path}"
        return updates

    output_dir = run_dir / output_subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_json(config_path)
    action_path = get_action_path(config, config_path.parent)
    num_hits = infer_num_hits(config, action_path)

    updates["initial_microstructure_csv"] = save_initial_microstructure(
        config=config,
        config_path=config_path,
        output_dir=output_dir,
        notes=notes,
    )

    hit_csvs, final_csv = save_hit_microstructures(
        run_dir=run_dir,
        run_name=run_name,
        num_hits=num_hits,
        output_dir=output_dir,
        notes=notes,
    )
    updates["hit_microstructure_csvs"] = ";".join(hit_csvs)
    updates["microstructure_csv"] = final_csv

    related_csvs = find_related_csvs(run_dir)
    for key, path_value in related_csvs.items():
        updates[key] = str(path_value) if path_value else ""

    updates["damage_csv"] = save_damage_summary(
        run_dir=run_dir,
        output_dir=output_dir,
        notes=notes,
        object_name=damage_object,
        step_no=damage_step_no,
    )

    updates["processed_status"] = "processed"
    updates["processing_notes"] = " | ".join(notes)
    return updates


def process_doe_results(
    manifest_path,
    dataset_path=None,
    objective_weights=None,
    statuses=("completed",),
    output_subdir="processed",
    damage_object="Workpiece",
    damage_step_no=0,
):
    """Process DOE results, update manifest, and build a dataset."""
    manifest_path = Path(manifest_path)
    manifest = ensure_columns(load_manifest(manifest_path), RESULT_COLUMNS)

    status_set = {status.lower() for status in statuses}
    processed_count = 0

    for idx, row in manifest.iterrows():
        row_status = str(row.get("status", "")).lower()
        if status_set and row_status not in status_set:
            continue

        updates = process_manifest_row(
            row=row,
            output_subdir=output_subdir,
            damage_object=damage_object,
            damage_step_no=damage_step_no,
        )
        for column, value in updates.items():
            manifest.at[idx, column] = value
        processed_count += 1

    manifest.to_csv(manifest_path, index=False)

    if dataset_path is None:
        dataset_path = manifest_path.with_name("dataset.csv")

    dataset = build_dataset_from_manifest(
        manifest_path=manifest_path,
        output_csv_path=dataset_path,
        objective_weights=objective_weights,
    )

    return {
        "manifest_path": str(manifest_path),
        "dataset_path": str(dataset_path),
        "processed_count": processed_count,
        "dataset_rows": int(len(dataset)),
    }


def train_and_propose_next(
    dataset_path,
    bounds,
    next_candidates_path,
    target_column="objective",
    model_type="random_forest",
    n_random_candidates=2000,
    n_select=5,
    random_seed=1,
):
    """Optionally train a surrogate and write next Bayesian candidates."""
    from optimizers.bayesian import propose_bayesian_candidates
    from surrogate_model import save_training_report, train_surrogate

    model, report = train_surrogate(
        dataset_csv_path=dataset_path,
        target_column=target_column,
        model_type=model_type,
        random_state=random_seed,
    )
    report_path = Path(next_candidates_path).with_name("surrogate_report.json")
    save_training_report(report, report_path)

    next_candidates = propose_bayesian_candidates(
        model=model,
        completed_dataset=dataset_path,
        bounds=bounds,
        target_column=target_column,
        n_random_candidates=n_random_candidates,
        n_select=n_select,
        random_seed=random_seed,
        minimize=True,
    )
    next_candidates_path = Path(next_candidates_path)
    next_candidates_path.parent.mkdir(parents=True, exist_ok=True)
    next_candidates.to_csv(next_candidates_path, index=False)

    return {
        "surrogate_report": str(report_path),
        "next_candidates": str(next_candidates_path),
        "n_next_candidates": int(len(next_candidates)),
    }


def main():
    parser = argparse.ArgumentParser(description="Process completed DEFORM DOE runs.")
    parser.add_argument("--manifest", required=True, help="DOE manifest CSV.")
    parser.add_argument("--dataset", default=None, help="Output dataset CSV. Defaults beside manifest.")
    parser.add_argument(
        "--objective-weights",
        default=None,
        help="JSON string or JSON file mapping metric names to objective weights.",
    )
    parser.add_argument(
        "--statuses",
        default="completed",
        help="Comma-separated manifest statuses to process. Use empty string to process all rows.",
    )
    parser.add_argument("--output-subdir", default="processed", help="Per-run result subfolder name.")
    parser.add_argument("--damage-object", default="Workpiece", help="Object used for max damage extraction.")
    parser.add_argument("--damage-step-no", type=int, default=0, help="DB step number for damage extraction.")
    parser.add_argument("--propose-next", action="store_true", help="Train surrogate and write next candidates.")
    parser.add_argument("--bounds", default=None, help="JSON string or JSON file with optimizer bounds.")
    parser.add_argument("--next-candidates", default=None, help="Output CSV for proposed candidates.")
    parser.add_argument("--model-type", default="random_forest", help="random_forest, extra_trees, or gaussian_process.")
    parser.add_argument("--n-random-candidates", type=int, default=2000)
    parser.add_argument("--n-select", type=int, default=5)
    parser.add_argument("--random-seed", type=int, default=1)
    args = parser.parse_args()

    statuses = tuple(status.strip() for status in args.statuses.split(",") if status.strip())
    objective_weights = parse_json_or_file(args.objective_weights, default=None)

    result = process_doe_results(
        manifest_path=args.manifest,
        dataset_path=args.dataset,
        objective_weights=objective_weights,
        statuses=statuses,
        output_subdir=args.output_subdir,
        damage_object=args.damage_object,
        damage_step_no=args.damage_step_no,
    )
    print(json.dumps(result, indent=2))

    if args.propose_next:
        if objective_weights is None:
            raise ValueError("--propose-next requires --objective-weights so the dataset has an objective.")
        if args.bounds is None:
            raise ValueError("--propose-next requires --bounds.")
        if args.next_candidates is None:
            raise ValueError("--propose-next requires --next-candidates.")

        proposal = train_and_propose_next(
            dataset_path=result["dataset_path"],
            bounds=parse_json_or_file(args.bounds),
            next_candidates_path=args.next_candidates,
            model_type=args.model_type,
            n_random_candidates=args.n_random_candidates,
            n_select=args.n_select,
            random_seed=args.random_seed,
        )
        print(json.dumps(proposal, indent=2))


if __name__ == "__main__":
    main()
