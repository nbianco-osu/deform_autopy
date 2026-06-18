"""
DOE runner/orchestrator for DEFORM multihit studies.

This script turns candidate rows into concrete DEFORM inputs:

1. Read a candidates CSV from `optimizers/doe.py` or `optimizers/bayesian.py`.
2. Copy a template action CSV and overwrite selected columns with candidate values.
3. Write one DEFORM runner config per candidate.
4. Append each planned run to a manifest.
5. Optionally execute `run_deform_hits_v3_improved.py --config ...`.

By default this script plans runs only. Pass `--execute` when you actually want
to launch DEFORM jobs.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from run_manifest import append_manifest_record, update_manifest_status


DEFAULT_RUNNER_SCRIPT = "run_deform_hits_v3_improved.py"


def load_json(path):
    """Load a JSON file into a dictionary."""
    with open(path, "r") as file:
        return json.load(file)


def write_json(data, path):
    """Write a dictionary as pretty JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as file:
        json.dump(data, file, indent=2)
    return path


def resolve_template_action_path(template_config_path, template_config):
    """Resolve the action CSV referenced by a runner config."""
    config_dir = Path(template_config_path).resolve().parent
    action_file = Path(template_config["action_file"])
    if action_file.is_absolute():
        return action_file

    base_path = Path(template_config["base_path"])
    if not base_path.is_absolute():
        base_path = (config_dir / base_path).resolve()
    return base_path / action_file


def candidate_value_columns(candidate_row, reserved_columns=None):
    """Return candidate columns that should be applied to action/config data."""
    if reserved_columns is None:
        reserved_columns = {
            "candidate_id",
            "run_name",
            "hit",
            "notes",
            "status",
            "predicted_mean",
            "predicted_std",
            "expected_improvement",
        }

    return [
        column
        for column in candidate_row.index
        if column not in reserved_columns and not pd.isna(candidate_row[column])
    ]


def apply_candidate_to_action_df(action_df, candidate_row, action_columns, apply_mode="all_rows"):
    """Overwrite action CSV columns using one candidate row.

    If `apply_mode == "all_rows"`, every row receives the candidate value for
    matching columns. If `apply_mode == "hit_row"`, the candidates file must
    include a `hit` column and only that action row is modified.
    """
    action_df = action_df.copy()
    candidate_columns = candidate_value_columns(candidate_row)

    if apply_mode == "hit_row":
        if "hit" not in candidate_row or pd.isna(candidate_row["hit"]):
            raise ValueError("apply_mode='hit_row' requires a hit column in candidates CSV.")
        target_index = int(candidate_row["hit"])
        if target_index < 0 or target_index >= len(action_df):
            raise ValueError(f"Candidate hit {target_index} is outside action CSV row range.")
        row_selector = [target_index]
    elif apply_mode == "all_rows":
        row_selector = action_df.index
    else:
        raise ValueError("apply_mode must be 'all_rows' or 'hit_row'.")

    applied = {}
    reverse_column_map = {value: key for key, value in action_columns.items()}

    for column in candidate_columns:
        if column in action_df.columns:
            action_df.loc[row_selector, column] = candidate_row[column]
            applied[column] = candidate_row[column]
        elif column in action_columns:
            action_column = action_columns[column]
            action_df.loc[row_selector, action_column] = candidate_row[column]
            applied[action_column] = candidate_row[column]
        elif column in reverse_column_map:
            action_df.loc[row_selector, column] = candidate_row[column]
            applied[column] = candidate_row[column]

    return action_df, applied


def apply_candidate_to_config(config, candidate_row):
    """Apply candidate columns that correspond directly to config keys."""
    config = dict(config)
    applied = {}

    for column in candidate_value_columns(candidate_row):
        if column in config and column not in ("action_file", "base_path", "data_path", "run_name"):
            value = candidate_row[column]
            if hasattr(value, "item"):
                value = value.item()
            config[column] = value
            applied[column] = value

    return config, applied


def make_candidate_run_name(study_name, candidate_index, candidate_row):
    """Return a stable run name for a candidate."""
    if "run_name" in candidate_row and not pd.isna(candidate_row["run_name"]):
        return str(candidate_row["run_name"])
    candidate_id = candidate_row.get("candidate_id", candidate_index + 1)
    return f"{study_name}_candidate_{int(candidate_id):04d}"


def prepare_candidate_run(
    candidate_row,
    candidate_index,
    template_config,
    template_config_path,
    output_root,
    study_name,
    apply_mode,
):
    """Create action CSV and config JSON for one candidate."""
    run_name = make_candidate_run_name(study_name, candidate_index, candidate_row)
    run_input_dir = Path(output_root) / study_name / "inputs" / run_name
    run_input_dir.mkdir(parents=True, exist_ok=True)

    template_action_path = resolve_template_action_path(template_config_path, template_config)
    action_df = pd.read_csv(template_action_path)
    action_df, applied_action_values = apply_candidate_to_action_df(
        action_df,
        candidate_row,
        action_columns=template_config["columns"],
        apply_mode=apply_mode,
    )

    action_path = run_input_dir / f"{run_name}_actions.csv"
    action_df.to_csv(action_path, index=False)

    run_config, applied_config_values = apply_candidate_to_config(template_config, candidate_row)
    run_config["action_file"] = str(action_path.resolve())
    run_config["run_name"] = run_name
    run_config["data_path"] = str((Path(output_root) / study_name / "runs").resolve())

    config_path = run_input_dir / f"{run_name}_config.json"
    write_json(run_config, config_path)

    return {
        "run_name": run_name,
        "config_path": config_path,
        "action_path": action_path,
        "run_dir": Path(run_config["data_path"]) / run_name,
        "applied_action_values": applied_action_values,
        "applied_config_values": applied_config_values,
    }


def run_deform_config(runner_script, config_path, cwd=None):
    """Execute the DEFORM runner for one generated config."""
    command = [sys.executable, str(runner_script), "--config", str(config_path)]
    return subprocess.run(command, cwd=cwd, check=False)


def orchestrate_doe_runs(
    candidates_csv,
    template_config_path,
    output_root,
    study_name,
    manifest_path,
    runner_script=DEFAULT_RUNNER_SCRIPT,
    apply_mode="all_rows",
    execute=False,
):
    """Prepare and optionally execute all candidates in a DOE CSV."""
    candidates = pd.read_csv(candidates_csv)
    template_config_path = Path(template_config_path).resolve()
    template_config = load_json(template_config_path)
    output_root = Path(output_root).resolve()
    runner_script = Path(runner_script).resolve()

    planned_runs = []
    for idx, candidate_row in candidates.iterrows():
        planned = prepare_candidate_run(
            candidate_row=candidate_row,
            candidate_index=idx,
            template_config=template_config,
            template_config_path=template_config_path,
            output_root=output_root,
            study_name=study_name,
            apply_mode=apply_mode,
        )

        record = append_manifest_record(
            manifest_path,
            {
                "study_name": study_name,
                "run_name": planned["run_name"],
                "run_dir": str(planned["run_dir"]),
                "status": "planned",
                "config_path": str(planned["config_path"]),
                "action_file": str(planned["action_path"]),
                "material": template_config.get("material", ""),
                "die": template_config.get("die", ""),
                "die_motion_mode": template_config.get("die_motion_mode", ""),
                "notes": "DOE candidate generated by doe_runner.py",
            },
            metadata={
                "candidate": candidate_row.to_dict(),
                "applied_action_values": planned["applied_action_values"],
                "applied_config_values": planned["applied_config_values"],
            },
        )
        planned["manifest_record_id"] = record["record_id"]
        planned_runs.append(planned)

        if execute:
            update_manifest_status(manifest_path, record["record_id"], "running")
            result = run_deform_config(
                runner_script=runner_script,
                config_path=planned["config_path"],
                cwd=runner_script.parent,
            )
            if result.returncode == 0:
                update_manifest_status(manifest_path, record["record_id"], "completed")
            else:
                update_manifest_status(
                    manifest_path,
                    record["record_id"],
                    "failed",
                    notes=f"Runner exited with code {result.returncode}",
                )

    return planned_runs


def main():
    parser = argparse.ArgumentParser(description="Create and optionally run DEFORM DOE candidates.")
    parser.add_argument("--candidates", required=True, help="Candidate CSV from DOE/Bayesian optimizer.")
    parser.add_argument("--template-config", required=True, help="Base runner config JSON.")
    parser.add_argument("--output-root", required=True, help="Study output folder.")
    parser.add_argument("--study-name", required=True, help="Study name used for run folders.")
    parser.add_argument("--manifest", required=True, help="Manifest CSV path.")
    parser.add_argument(
        "--runner-script",
        default=DEFAULT_RUNNER_SCRIPT,
        help="Path to run_deform_hits_v3_improved.py.",
    )
    parser.add_argument(
        "--apply-mode",
        choices=["all_rows", "hit_row"],
        default="all_rows",
        help="How candidate values are applied to the action CSV.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually launch DEFORM runs. If omitted, only inputs/configs/manifest are created.",
    )
    args = parser.parse_args()

    planned_runs = orchestrate_doe_runs(
        candidates_csv=args.candidates,
        template_config_path=args.template_config,
        output_root=args.output_root,
        study_name=args.study_name,
        manifest_path=args.manifest,
        runner_script=args.runner_script,
        apply_mode=args.apply_mode,
        execute=args.execute,
    )
    print(f"Prepared {len(planned_runs)} DOE run(s).")
    if not args.execute:
        print("Dry run only. Re-run with --execute to launch DEFORM.")


if __name__ == "__main__":
    main()
