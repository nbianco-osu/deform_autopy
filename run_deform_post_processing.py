"""
Post-process one completed run from run_deform_hits_config.py.

This script is intentionally separate from the DOE processing workflow. Use it
after a normal Spyder run of `run_deform_hits_config.py` when you want a clean
set of analysis files for one multihit sequence.

Typical use in Spyder:

    CONFIG_PATH = r"C:\\path\\to\\run_config.json"
    process_run(config_path=CONFIG_PATH)

If `run_deform_hits_config.py` was run with its built-in DEFAULT_CONFIG and no
JSON config file, call:

    process_run()

Typical command line use:

    python run_deform_post_processing.py --config C:\\path\\to\\run_config.json

or, for the runner's built-in DEFAULT_CONFIG:

    python run_deform_post_processing.py

Outputs are written under:

    <data_path>/<run_name>/post_processed/

The processor creates:

- initial_microstructure.csv
- microstructure_hit<N>.csv for each available hit key
- hit_summary.csv
- run_metrics.csv
- run_summary.json
- coordinates_all_hits.csv when coordinate logs are present
- load_stroke_all_hits.csv when load-stroke CSVs are present
- damage_summary.csv when DEFORM API damage extraction or an existing damage CSV
  is available
"""

import argparse
import ast
import json
import math
from pathlib import Path
import pandas as pd
from metrics import collect_metrics_from_files, summarize_microstructure
from microstructure_post_processing import save_microstructure_csv_from_key
from process_doe_results import (
    extract_damage_from_existing_csv,
    extract_damage_with_deform_api,
    format_config_value,
    get_action_path,
    infer_die,
    infer_num_hits,
    is_blank,
    load_json,
    resolve_path,
)


POST_OUTPUT_COLUMNS = [
    "hit",
    "hit_dir",
    "key_file",
    "microstructure_csv",
    "coordinate_csv",
    "load_stroke_csv",
    "grain_mean_um",
    "grain_std_um",
    "rex_fraction_mean",
    "retained_strain_mean",
    "time_final",
    "stroke_final",
    "fx_abs_max",
    "fy_abs_max",
    "fz_abs_max",
    "notes",
]

ROOT = Path(__file__).resolve().parent
RUNNER_PATH = ROOT / "run_deform_hits_config.py"


def _safe_float(value):
    """Convert a value to float, returning NaN for blanks or parse failures."""
    try:
        if is_blank(value):
            return math.nan
        return float(value)
    except Exception:
        return math.nan


def _as_numeric(series):
    """Return finite numeric values from a pandas Series."""
    values = pd.to_numeric(series, errors="coerce")
    return values[pd.notna(values)]


def load_default_config_from_runner(runner_path=RUNNER_PATH):
    """Read DEFAULT_CONFIG from run_deform_hits_config.py without importing it.

    Importing the runner can require DEFORM API modules. Parsing the assignment
    from source keeps this post-processor usable for file-only processing too.
    """
    runner_path = Path(runner_path)
    tree = ast.parse(runner_path.read_text())
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "DEFAULT_CONFIG":
                return ast.literal_eval(node.value)
    raise ValueError(f"DEFAULT_CONFIG was not found in {runner_path}")


def load_effective_config(config_path=None):
    """Load a JSON config or the runner's built-in DEFAULT_CONFIG.

    Returns
    -------
    tuple
        `(config, config_dir, config_source, config_path_for_resolution)`.
    """
    if config_path:
        config_path = Path(config_path).resolve()
        return load_json(config_path), config_path.parent, str(config_path), config_path

    config = load_default_config_from_runner()
    return config, RUNNER_PATH.parent, f"DEFAULT_CONFIG from {RUNNER_PATH}", RUNNER_PATH


def infer_run_name(config, num_hits=None):
    """Return the formatted run name stored in the config.

    `run_deform_hits_config.py` normally fills this name before execution. If a
    hand-written config leaves it blank, this function mirrors the runner's
    action-file rule so the post-processor can still find the output folder.
    """
    run_name = format_config_value(config.get("run_name", ""), config)
    if not is_blank(run_name):
        return run_name

    action_file = Path(str(config.get("action_file", ""))).name
    action_parts = action_file.split("_")
    tp_type = config.get("tp_type") or (action_parts[2] if len(action_parts) > 2 else "tp")
    die_motion = config.get("die_motion_mode")
    if is_blank(die_motion):
        die_motion = "symmetric" if "bdm" in action_file.lower() else "single_top_die"

    material = config.get("material", "material")
    action_version = config.get("action_version", "v")
    run_number = config.get("run_number", "run")
    hit_count = num_hits if num_hits is not None else config.get("num_hits", "hits")

    run_name = (
        f"af_{tp_type}_{material}_rev_{action_version}_run{run_number}_"
        f"{hit_count}hits_{die_motion}"
    )
    if config.get("use_jmak", False):
        run_name += "_jmak"
    return run_name


def resolve_run_dir(config, config_path, run_dir=None, run_name=None):
    """Resolve the completed run folder.

    The default folder layout is the one created by `run_deform_hits_config.py`:

        <data_path>/<run_name>/<run_name>-hit<N>/
    """
    if run_dir:
        return Path(run_dir).resolve()

    config_dir = Path(config_path).resolve().parent
    data_path = resolve_path(config.get("data_path", ""), config, config_dir)
    if data_path is None:
        raise ValueError("Could not resolve data_path from the config.")
    if run_name is None:
        run_name = infer_run_name(config)
    return data_path / run_name


def resolve_initial_key_from_runner_config(config, config_path):
    """Resolve the same initial key that run_deform_hits_config.py reads.

    This mirrors the runner's JMAK behavior: when `use_jmak` is true and the
    selected key file ends in `.key`, the runner uses the `_jmak.key` variant.
    """
    config_dir = Path(config_path).resolve().parent
    if not is_blank(config.get("init_key")):
        return resolve_path(config["init_key"], config, config_dir)

    action_path = get_action_path(config, config_dir)
    die = infer_die(config, action_path)
    if die is None:
        return None

    key_template = config.get("key_files", {}).get(str(die))
    if is_blank(key_template):
        return None

    key_path = resolve_path(config.get("key_path", ""), config, config_dir)
    if key_path is None:
        return None

    key_file = format_config_value(key_template, config)
    if config.get("use_jmak", False) and key_file.lower().endswith(".key"):
        key_file = key_file[:-4] + "_jmak.key"
    return key_path / key_file


def find_latest_file(root, patterns):
    """Return the newest file under root that matches any pattern."""
    root = Path(root)
    matches = []
    for pattern in patterns:
        matches.extend(root.rglob(pattern))
    matches = [path for path in matches if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def find_hit_dir(run_dir, run_name, hit):
    """Return the expected hit folder, falling back to a pattern search."""
    expected = Path(run_dir) / f"{run_name}-hit{hit}"
    if expected.exists():
        return expected

    matches = [
        path for path in Path(run_dir).glob(f"*hit{hit}*")
        if path.is_dir()
    ]
    if not matches:
        return expected
    return max(matches, key=lambda path: path.stat().st_mtime)


def find_initial_key(run_dir, run_name):
    """Prefer the hit-0 initialized key, which captures supplier grain setup."""
    hit0_dir = find_hit_dir(run_dir, run_name, 0)
    candidates = [
        hit0_dir / "af-hit-0_initial.KEY",
        hit0_dir / "af-hit-0_initial.key",
        hit0_dir / "af-hit-0.KEY",
        hit0_dir / "af-hit-0.key",
    ]
    existing = [path for path in candidates if path.exists()]
    if existing:
        return max(existing, key=lambda path: path.stat().st_mtime)
    return find_latest_file(hit0_dir, ["*initial*.KEY", "*initial*.key", "*.KEY", "*.key"])


def find_hit_key(run_dir, run_name, hit):
    """Find the best post-solve key file for one hit."""
    hit_dir = find_hit_dir(run_dir, run_name, hit)
    preferred = [
        hit_dir / f"af-hit-{hit}_post.KEY",
        hit_dir / f"af-hit-{hit}_post.key",
        hit_dir / f"af-hit-{hit}_final.KEY",
        hit_dir / f"af-hit-{hit}_final.key",
    ]
    existing = [path for path in preferred if path.exists()]
    if existing:
        return max(existing, key=lambda path: path.stat().st_mtime)
    return find_latest_file(
        hit_dir,
        [
            f"*hit*{hit}*post*.KEY",
            f"*hit*{hit}*post*.key",
            f"*hit*{hit}*final*.KEY",
            f"*hit*{hit}*final*.key",
            "*.KEY",
            "*.key",
        ],
    )


def find_hit_coordinate_csv(run_dir, run_name, hit):
    """Find the newest coordinate CSV for a hit."""
    hit_dir = find_hit_dir(run_dir, run_name, hit)
    return find_latest_file(
        hit_dir,
        [
            f"*coordinates*hit{hit}*.csv",
            f"*coordinate*hit{hit}*.csv",
            "*coordinates*.csv",
            "*coordinate*.csv",
            "*coord*.csv",
        ],
    )


def find_hit_load_stroke_csv(run_dir, run_name, hit):
    """Find the load-stroke CSV exported by the runner for a hit."""
    hit_dir = find_hit_dir(run_dir, run_name, hit)
    return find_latest_file(
        hit_dir,
        [
            f"load_stroke_hit{hit}.csv",
            f"*load*stroke*hit{hit}*.csv",
            "*load_stroke*.csv",
            "*load*stroke*.csv",
        ],
    )


def save_initial_microstructure(run_dir, run_name, config, config_path, output_dir, notes):
    """Save initial grain data before the first forming solve."""
    initial_key = find_initial_key(run_dir, run_name)
    if initial_key is None:
        initial_key = resolve_initial_key_from_runner_config(config, config_path)
        if initial_key is not None:
            notes.append("Hit-0 initialized key was not found; used configured starting key.")

    if initial_key is None or not Path(initial_key).exists():
        notes.append("Initial microstructure was not saved because no initial key was found.")
        return ""

    output_path = Path(output_dir) / "initial_microstructure.csv"
    try:
        save_microstructure_csv_from_key(initial_key, output_path)
        return str(output_path)
    except Exception as exc:
        notes.append(f"Initial microstructure parse failed: {exc}")
        return ""


def summarize_labeled_load_stroke(load_stroke_csv):
    """Summarize the runner's load-stroke columns: Step, Time, S, V, Fx, Fy, Fz."""
    if is_blank(load_stroke_csv) or not Path(load_stroke_csv).exists():
        return {}

    df = pd.read_csv(load_stroke_csv)
    result = {"load_stroke_rows": int(len(df))}

    if "Time" in df.columns:
        values = _as_numeric(df["Time"])
        if len(values):
            result["time_final"] = float(values.iloc[-1])

    if "S" in df.columns:
        values = _as_numeric(df["S"])
        if len(values):
            result["stroke_final"] = float(values.iloc[-1])

    for force_col in ["Fx", "Fy", "Fz"]:
        if force_col not in df.columns:
            continue
        values = _as_numeric(df[force_col])
        if not len(values):
            continue
        lower = force_col.lower()
        result[f"{lower}_min"] = float(values.min())
        result[f"{lower}_max"] = float(values.max())
        result[f"{lower}_abs_max"] = float(values.abs().max())

    return result


def combine_csvs(paths, output_path, source_column="source_file"):
    """Combine compatible CSV files and add a source-file column."""
    frames = []
    for path in paths:
        if is_blank(path) or not Path(path).exists():
            continue
        df = pd.read_csv(path)
        df[source_column] = str(path)
        frames.append(df)

    if not frames:
        return ""

    combined = pd.concat(frames, ignore_index=True, sort=False)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)
    return str(output_path)


def save_damage_summary(run_dir, output_dir, notes, object_name="Workpiece", step_no=0):
    """Save damage min/max from DEFORM API or from an existing damage CSV."""
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
        notes.append("No damage source was found.")
        return ""

    output_path = Path(output_dir) / "damage_summary.csv"
    pd.DataFrame([damage_row]).to_csv(output_path, index=False)
    return str(output_path)


def process_hit(run_dir, run_name, hit, output_dir):
    """Parse one hit and return a normalized summary row."""
    notes = []
    hit_dir = find_hit_dir(run_dir, run_name, hit)
    key_file = find_hit_key(run_dir, run_name, hit)
    coordinate_csv = find_hit_coordinate_csv(run_dir, run_name, hit)
    load_stroke_csv = find_hit_load_stroke_csv(run_dir, run_name, hit)

    row = {
        "hit": hit,
        "hit_dir": str(hit_dir),
        "key_file": str(key_file) if key_file else "",
        "microstructure_csv": "",
        "coordinate_csv": str(coordinate_csv) if coordinate_csv else "",
        "load_stroke_csv": str(load_stroke_csv) if load_stroke_csv else "",
        "notes": "",
    }

    if key_file and Path(key_file).exists():
        micro_csv = Path(output_dir) / f"microstructure_hit{hit}.csv"
        try:
            save_microstructure_csv_from_key(key_file, micro_csv)
            row["microstructure_csv"] = str(micro_csv)
            row.update(summarize_microstructure(micro_csv))
        except Exception as exc:
            notes.append(f"Microstructure parse failed: {exc}")
    else:
        notes.append("No final/post key file was found.")

    if load_stroke_csv:
        try:
            row.update(summarize_labeled_load_stroke(load_stroke_csv))
        except Exception as exc:
            notes.append(f"Load-stroke summary failed: {exc}")

    row["notes"] = " | ".join(notes)
    return row


def process_run(
    config_path=None,
    run_dir=None,
    output_subdir="post_processed",
    damage_object="Workpiece",
    damage_step_no=0,
    objective_weights=None,
):
    """Post-process one completed `run_deform_hits_config.py` run.

    Parameters
    ----------
    config_path : str or Path, optional
        JSON config used by the run. If omitted, DEFAULT_CONFIG is read from
        run_deform_hits_config.py.
    run_dir : str or Path, optional
        Completed run folder. If omitted, the folder is inferred from
        `data_path` and `run_name` in the config.
    output_subdir : str
        Name of the post-processing folder created under the run folder.
    damage_object : str
        DEFORM object used for damage extraction.
    damage_step_no : int
        DB step number. DEFORM commonly uses 0 for the final state.
    objective_weights : dict, optional
        Optional metric weights used to add an objective column.
    """
    config, config_dir, config_source, config_path_for_resolution = load_effective_config(
        config_path
    )
    action_path = get_action_path(config, config_dir)
    num_hits = infer_num_hits(config, action_path)
    run_name = infer_run_name(config, num_hits=num_hits)
    run_dir = resolve_run_dir(
        config,
        config_path_for_resolution,
        run_dir=run_dir,
        run_name=run_name,
    )

    if num_hits is None:
        raise ValueError("Could not infer num_hits from config or action CSV.")
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory was not found: {run_dir}")

    output_dir = run_dir / output_subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    notes = []
    initial_micro_csv = save_initial_microstructure(
        run_dir=run_dir,
        run_name=run_name,
        config=config,
        config_path=config_path_for_resolution,
        output_dir=output_dir,
        notes=notes,
    )

    hit_rows = [
        process_hit(run_dir=run_dir, run_name=run_name, hit=hit, output_dir=output_dir)
        for hit in range(1, num_hits + 1)
    ]
    hit_summary = pd.DataFrame(hit_rows)
    for column in POST_OUTPUT_COLUMNS:
        if column not in hit_summary.columns:
            hit_summary[column] = ""
    hit_summary = hit_summary[POST_OUTPUT_COLUMNS + [
        column for column in hit_summary.columns if column not in POST_OUTPUT_COLUMNS
    ]]

    hit_summary_csv = output_dir / "hit_summary.csv"
    hit_summary.to_csv(hit_summary_csv, index=False)

    coordinate_paths = [row.get("coordinate_csv", "") for row in hit_rows]
    load_stroke_paths = [row.get("load_stroke_csv", "") for row in hit_rows]
    coordinates_all_csv = combine_csvs(coordinate_paths, output_dir / "coordinates_all_hits.csv")
    load_stroke_all_csv = combine_csvs(load_stroke_paths, output_dir / "load_stroke_all_hits.csv")

    damage_csv = save_damage_summary(
        run_dir=run_dir,
        output_dir=output_dir,
        notes=notes,
        object_name=damage_object,
        step_no=damage_step_no,
    )

    final_micro_csv = ""
    final_coordinate_csv = ""
    final_load_stroke_csv = ""
    if hit_rows:
        final_micro_csv = hit_rows[-1].get("microstructure_csv", "")
        final_coordinate_csv = hit_rows[-1].get("coordinate_csv", "")
        final_load_stroke_csv = hit_rows[-1].get("load_stroke_csv", "")

    metrics = collect_metrics_from_files(
        initial_microstructure_csv=initial_micro_csv,
        microstructure_csv=final_micro_csv,
        load_stroke_csv=final_load_stroke_csv,
        coordinate_csv=final_coordinate_csv,
        damage_csv=damage_csv,
    )
    if final_load_stroke_csv:
        metrics.update(summarize_labeled_load_stroke(final_load_stroke_csv))

    if objective_weights:
        from metrics import weighted_objective

        metrics.update(weighted_objective(metrics, objective_weights))

    metrics_row = {
        "run_name": run_name,
        "run_dir": str(run_dir),
        "config_path": config_source,
        "num_hits": int(num_hits),
        "initial_microstructure_csv": initial_micro_csv,
        "microstructure_csv": final_micro_csv,
        "hit_summary_csv": str(hit_summary_csv),
        "coordinates_all_csv": coordinates_all_csv,
        "load_stroke_all_csv": load_stroke_all_csv,
        "damage_csv": damage_csv,
    }
    metrics_row.update(metrics)
    run_metrics_csv = output_dir / "run_metrics.csv"
    pd.DataFrame([metrics_row]).to_csv(run_metrics_csv, index=False)

    summary = {
        "run_name": run_name,
        "run_dir": str(run_dir),
        "config_path": config_source,
        "action_path": str(action_path) if action_path else "",
        "num_hits": int(num_hits),
        "output_dir": str(output_dir),
        "initial_microstructure_csv": initial_micro_csv,
        "hit_summary_csv": str(hit_summary_csv),
        "run_metrics_csv": str(run_metrics_csv),
        "coordinates_all_csv": coordinates_all_csv,
        "load_stroke_all_csv": load_stroke_all_csv,
        "damage_csv": damage_csv,
        "notes": notes,
    }
    summary_json = output_dir / "run_summary.json"
    with open(summary_json, "w") as file:
        json.dump(summary, file, indent=2)

    print("Post-processing complete.")
    print(f"  Run folder : {run_dir}")
    print(f"  Output     : {output_dir}")
    print(f"  Hit summary: {hit_summary_csv}")
    print(f"  Metrics    : {run_metrics_csv}")
    return summary


def parse_objective_weights(value):
    """Parse optional objective weights from JSON text or a JSON file."""
    if is_blank(value):
        return None
    text = str(value)
    path = Path(text)
    if path.exists():
        with open(path, "r") as file:
            return json.load(file)
    return json.loads(text)


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser(
        description="Post-process one run_deform_hits_config.py multihit run."
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to the run JSON config. Omit this to post-process a run made "
            "with DEFAULT_CONFIG in run_deform_hits_config.py."
        ),
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Completed run folder. If omitted, data_path/run_name is used.",
    )
    parser.add_argument(
        "--output-subdir",
        default="post_processed",
        help="Post-processing folder name created under the run folder.",
    )
    parser.add_argument(
        "--damage-object",
        default="Workpiece",
        help="DEFORM object used for damage extraction.",
    )
    parser.add_argument(
        "--damage-step-no",
        type=int,
        default=0,
        help="DB step number for damage extraction; 0 is commonly final state.",
    )
    parser.add_argument(
        "--objective-weights",
        default=None,
        help="Optional JSON string or JSON file of metric weights.",
    )
    args = parser.parse_args()

    process_run(
        config_path=args.config,
        run_dir=args.run_dir,
        output_subdir=args.output_subdir,
        damage_object=args.damage_object,
        damage_step_no=args.damage_step_no,
        objective_weights=parse_objective_weights(args.objective_weights),
    )


if __name__ == "__main__":
    main()
