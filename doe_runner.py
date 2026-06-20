"""
DOE runner/orchestrator for DEFORM multihit studies.

This script turns candidate rows into concrete DEFORM inputs:

1. Read a candidates CSV from `optimizers/doe.py` or `optimizers/bayesian.py`.
2. Copy a template action CSV and overwrite selected columns with candidate values.
3. Write one DEFORM runner config per candidate.
4. Append each planned run to a manifest.
5. Optionally execute `run_deform_hits_config.py --config ...`.

By default this script plans runs only. Pass `--execute` when you actually want
to launch DEFORM jobs.
"""

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import pandas as pd
from run_manifest import append_manifest_record, update_manifest_status


DEFAULT_RUNNER_SCRIPT = "run_deform_hits_config.py"


def load_json(path):
    """Load a JSON file into a dictionary."""
    with open(path, "r") as file:
        return json.load(file)


def apply_config_overrides(config, overrides=None):
    """Apply explicit overrides to the template runner config.

    This is useful for Spyder workflows where you want the DOE loop to reuse
    your normal config but force study-specific choices, such as `num_hits=5`
    and `die_motion_mode="single_top_die"`.
    """
    config = dict(config)
    for key, value in (overrides or {}).items():
        config[key] = value
    return config


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

    base_path = Path(template_config["action_path"])
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
    """Execute the DEFORM runner for one generated config in a subprocess."""
    command = [sys.executable, str(runner_script), "--config", str(config_path)]
    return subprocess.run(command, cwd=cwd, check=False)


def load_runner_main(runner_script):
    """Load `main(config_path)` from a runner script path."""
    runner_script = Path(runner_script).resolve()
    module_name = f"_deform_runner_{runner_script.stem}"
    spec = importlib.util.spec_from_file_location(module_name, runner_script)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load runner script: {runner_script}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "main"):
        raise AttributeError(f"{runner_script} does not define main(config_path).")
    return module.main


def run_deform_config_direct(runner_main, config_path):
    """Execute the DEFORM runner in-process using `main(config_path)`.

    This is the Spyder-friendly path. It avoids command-line argument passing
    and calls the same function your `run_deform_hits_config.py` launcher uses.
    """
    runner_main(str(config_path))
    return 0


def orchestrate_doe_runs(
    candidates_csv,
    template_config_path,
    output_root,
    study_name,
    manifest_path,
    runner_script=DEFAULT_RUNNER_SCRIPT,
    apply_mode="all_rows",
    execute=False,
    execute_mode="direct",
    config_overrides=None,
):
    """Prepare and optionally execute all candidates in a DOE CSV."""
    candidates = pd.read_csv(candidates_csv)
    template_config_path = Path(template_config_path).resolve()
    template_config = apply_config_overrides(load_json(template_config_path), config_overrides)
    output_root = Path(output_root).resolve()
    runner_script = Path(runner_script).resolve()
    if execute_mode not in ("direct", "subprocess"):
        raise ValueError("execute_mode must be 'direct' or 'subprocess'.")

    runner_main = load_runner_main(runner_script) if execute and execute_mode == "direct" else None

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
            if execute_mode == "direct":
                return_code = run_deform_config_direct(runner_main, planned["config_path"])
            else:
                result = run_deform_config(
                    runner_script=runner_script,
                    config_path=planned["config_path"],
                    cwd=runner_script.parent,
                )
                return_code = result.returncode

            if return_code == 0:
                update_manifest_status(manifest_path, record["record_id"], "completed")
            else:
                update_manifest_status(
                    manifest_path,
                    record["record_id"],
                    "failed",
                    notes=f"Runner exited with code {return_code}",
                )

    return planned_runs


def run_doe_loop_from_config(
    candidates_csv,
    runner_config_path,
    output_root,
    study_name,
    manifest_path,
    runner_script=DEFAULT_RUNNER_SCRIPT,
    apply_mode="all_rows",
    execute=True,
    execute_mode="direct",
    num_hits=None,
    die_motion_mode=None,
):
    overrides = {}
    if num_hits is not None:
        overrides["num_hits"] = int(num_hits)
    if die_motion_mode is not None:
        overrides["die_motion_mode"] = die_motion_mode
        if die_motion_mode == "single_top_die":
            overrides["apply_action_file_rules"] = False

    return orchestrate_doe_runs(
        candidates_csv=candidates_csv,
        template_config_path=runner_config_path,
        output_root=output_root,
        study_name=study_name,
        manifest_path=manifest_path,
        runner_script=runner_script,
        apply_mode=apply_mode,
        execute=execute,
        execute_mode=execute_mode,
        config_overrides=overrides,
    )


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
    parser.add_argument(
        "--execute-mode",
        choices=["direct", "subprocess"],
        default="direct",
        help="Use direct main(config_path) execution or a subprocess.",
    )
    parser.add_argument("--num-hits", type=int, default=None, help="Override num_hits in generated configs.")
    parser.add_argument(
        "--die-motion-mode",
        choices=["symmetric", "single_top_die"],
        default=None,
        help="Override die_motion_mode in generated configs.",
    )
    args = parser.parse_args()

    config_overrides = {}
    if args.num_hits is not None:
        config_overrides["num_hits"] = args.num_hits
    if args.die_motion_mode is not None:
        config_overrides["die_motion_mode"] = args.die_motion_mode
        if args.die_motion_mode == "single_top_die":
            config_overrides["apply_action_file_rules"] = False

    planned_runs = orchestrate_doe_runs(
        candidates_csv=args.candidates,
        template_config_path=args.template_config,
        output_root=args.output_root,
        study_name=args.study_name,
        manifest_path=args.manifest,
        runner_script=args.runner_script,
        apply_mode=args.apply_mode,
        execute=args.execute,
        execute_mode=args.execute_mode,
        config_overrides=config_overrides,
    )
    print(f"Prepared {len(planned_runs)} DOE run(s).")
    if not args.execute:
        print("Dry run only. Re-run with --execute to launch DEFORM.")


if __name__ == "__main__":
    main()
