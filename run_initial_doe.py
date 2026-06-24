"""
Spyder-friendly launcher for creating and optionally running an initial DOE.

This file performs the first optimization workflow end-to-end:

1. Define parameter bounds.
2. Generate a Latin-hypercube DOE candidate table.
3. Create a DOE-specific runner config for 5-hit single-die runs.
4. Use `doe_runner.py` to generate one action CSV and config JSON per candidate.
5. Optionally execute each generated config with `run_deform_hits_config.py`.
6. Optionally process completed runs into `dataset.csv`.
7. Optionally train a surrogate and write `candidates_next.csv`.
8. Optionally prepare or execute one next-candidate batch.
9. Optionally refresh plots and the HTML report.

Recommended first use:
- Set EXECUTE_RUNS = False.
- Run this file in Spyder.
- Inspect the generated action CSVs/config JSONs.
- Set EXECUTE_RUNS = True only when the generated inputs look correct.
- After runs finish, set PROCESS_RESULTS = True.

(1) PREPARE_RUNS = True, others False
(2) Then PREPARE_RUNS = True and EXECUTE_RUNS = True, others False
(3) Set PROCESS_RESULTS = True and PROPOSE_NEXT_CANDIDATES = True, others False
(4) MAKE_REPORT = True, others False
(5) RUN_NEXT_CANDIDATES = True and EXECUTE_NEXT_CANDIDATES = False, others False
(6) RUN_NEXT_CANDIDATES = True and EXECUTE_NEXT_CANDIDATES = True, others False
"""

import json
from pathlib import Path
import pandas as pd
from doe_runner import orchestrate_doe_runs
from optimizers.doe import latin_hypercube, save_candidates
from process_doe_results import process_doe_results, train_and_propose_next
from visualize_doe_results import visualize_doe_results
import warnings
warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

# Folder that contains your current DEFORM automation code.
PROJECT_ROOT = Path(r"C:\Users\bianco.33\Desktop\deform_auto_py")

# Current runner and base config used by your normal Spyder workflow.
RUNNER_SCRIPT = PROJECT_ROOT / "run_deform_hits_config.py"
# Point code to the config file for this DOE
BASE_CONFIG_PATH = PROJECT_ROOT / "configs" / "run_deform_hits_current_config.json"

# Folder where DOE candidate files, generated configs, runs, and manifest live.
OPTIMIZATION_ROOT = PROJECT_ROOT / "optimization"
# Set the number of hits for each run
NUM_HITS = 5
STUDY_NAME = f"single_die_{NUM_HITS}hit_initial_doe"

# Create candidate/action/config files and optionally launch DEFORM.
# Set this to False when you only want to process already-completed runs.
PREPARE_RUNS = False

# Safety switch. Keep False until generated inputs have been inspected.
EXECUTE_RUNS = False

# Process completed runs after execution. You can also set EXECUTE_RUNS = False
# and PROCESS_RESULTS = True to process runs that already finished previously.
PROCESS_RESULTS = False

# Train a surrogate and write the next Bayesian candidate CSV after processing.
# This requires scikit-learn in the Python environment and enough completed runs
# with objective values.
PROPOSE_NEXT_CANDIDATES = False

# Prepare and optionally execute the candidate batch proposed from the first DOE.
# This is intentionally one finite batch, not an infinite optimization loop.
RUN_NEXT_CANDIDATES = False
EXECUTE_NEXT_CANDIDATES = False

# Process the proposed-candidate batch after those runs complete.
PROCESS_NEXT_CANDIDATES = False

# Merge completed datasets across available rounds. Bayesian proposal should
# train on this combined file when it exists.
COMBINE_DATASETS = False

# Refresh `report/index.html` and plot images for the current study.
# This can be True even when PROCESS_RESULTS is False if dataset.csv already exists.
MAKE_REPORT = False

# Stop controls for the proposed-candidate batch. The current launcher only runs
# one next round, and this guard prevents accidental use as an open-ended loop.
NEXT_ROUND_NUMBER = 2
MAX_ROUND_NUMBER = 2

# How candidate values are applied to the action file:
# - "all_rows": apply each candidate value to every hit row.
# - "hit_row": require a hit column in the candidates CSV and modify only that row.
APPLY_MODE = "all_rows"

# Initial DOE size and reproducibility seed.
N_CANDIDATES = 100
RANDOM_SEED = 1

# The first DOE should stay small. Add variables only after the run pipeline is
# producing useful data and metrics.
BOUNDS = {
    "depth_in": [0.01, 0.15],
    "forging_temp_c": [900, 1200],
}

# Objective weights used to combine processed metrics into one scalar objective.
# Lower objective values are treated as better by the Bayesian proposal step.
# Adjust these after seeing the first dataset columns and units.
OBJECTIVE_WEIGHTS = {
    "damage_max": 10.0,
    "grain_std_um": 10.0,
    "top_die_center_distance": 10.0,
    "bottom_die_center_distance": 10.0,
}

# Result-processing settings.
PROCESS_STATUSES = ("completed",)
PROCESSED_OUTPUT_SUBDIR = "processed"
DAMAGE_OBJECT = "Workpiece"
DAMAGE_STEP_NO = 0

# Bayesian candidate proposal settings.
MODEL_TYPE = "random_forest"
N_RANDOM_BAYESIAN_CANDIDATES = 2000
N_NEXT_CANDIDATES = 5

# Force this DOE to use n-hit single-top-die runs.
DOE_CONFIG_OVERRIDES = {
    "num_hits": NUM_HITS,
    "die_motion_mode": "single_top_die",
    "apply_action_file_rules": False,
    "position_bottom_die_before_first_hit": False,
}


# ---------------------------------------------------------------------------
# Derived paths
# ---------------------------------------------------------------------------

CANDIDATES_CSV = OPTIMIZATION_ROOT / STUDY_NAME / "candidates_initial.csv"
MANIFEST_CSV = OPTIMIZATION_ROOT / STUDY_NAME / "manifest.csv"
DOE_TEMPLATE_CONFIG = OPTIMIZATION_ROOT / STUDY_NAME / "doe_template_config.json"
DATASET_CSV = OPTIMIZATION_ROOT / STUDY_NAME / "dataset.csv"
COMBINED_DATASET_CSV = OPTIMIZATION_ROOT / STUDY_NAME / "dataset_all.csv"
NEXT_CANDIDATES_CSV = OPTIMIZATION_ROOT / STUDY_NAME / "candidates_next.csv"
REPORT_DIR = OPTIMIZATION_ROOT / STUDY_NAME / "report"
NEXT_STUDY_NAME = f"{STUDY_NAME}_round_{NEXT_ROUND_NUMBER:02d}"
NEXT_MANIFEST_CSV = OPTIMIZATION_ROOT / NEXT_STUDY_NAME / "manifest.csv"
NEXT_DATASET_CSV = OPTIMIZATION_ROOT / NEXT_STUDY_NAME / "dataset.csv"
NEXT_REPORT_DIR = OPTIMIZATION_ROOT / NEXT_STUDY_NAME / "report"

def load_json(path):
    """Load a JSON config file."""
    with open(path, "r") as file:
        return json.load(file)


def write_json(data, path):
    """Write a JSON config file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as file:
        json.dump(data, file, indent=2)
    return path


def create_doe_template_config(base_config_path, output_config_path, overrides):
    """Create the config used by all generated DOE candidates."""
    config = load_json(base_config_path)
    config.update(overrides)
    return write_json(config, output_config_path)


def generate_initial_candidates(bounds, n_candidates, random_seed, output_csv):
    """Generate and save the initial Latin-hypercube candidate table."""
    candidates = latin_hypercube(bounds, n_samples=n_candidates, random_seed=random_seed)
    candidates.insert(0, "candidate_id", range(1, len(candidates) + 1))
    save_candidates(candidates, output_csv)
    return candidates


def combine_datasets(dataset_paths, output_csv_path):
    """Merge completed per-round datasets into one training table."""
    frames = []
    for dataset_path in dataset_paths:
        dataset_path = Path(dataset_path)
        if dataset_path.exists():
            df = pd.read_csv(dataset_path)
            if not df.empty:
                df["source_dataset"] = str(dataset_path)
                frames.append(df)

    if frames:
        combined = pd.concat(frames, ignore_index=True, sort=False)
    else:
        combined = pd.DataFrame()

    output_csv_path = Path(output_csv_path)
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_csv_path, index=False)
    return combined


def run_initial_doe():
    """Generate DOE files, optionally execute/process them, and propose more."""
    OPTIMIZATION_ROOT.mkdir(parents=True, exist_ok=True)

    planned_runs = []

    if PREPARE_RUNS:
        print("Generating initial DOE candidates...")
        candidates = generate_initial_candidates(
            bounds=BOUNDS,
            n_candidates=N_CANDIDATES,
            random_seed=RANDOM_SEED,
            output_csv=CANDIDATES_CSV,
        )
        print(f"  Saved {len(candidates)} candidates to: {CANDIDATES_CSV}")

        print("Creating DOE template config...")
        create_doe_template_config(
            base_config_path=BASE_CONFIG_PATH,
            output_config_path=DOE_TEMPLATE_CONFIG,
            overrides=DOE_CONFIG_OVERRIDES,
        )
        print(f"  Saved DOE template config to: {DOE_TEMPLATE_CONFIG}")

        print("Preparing DOE action files and candidate configs...")
        planned_runs = orchestrate_doe_runs(
            candidates_csv=CANDIDATES_CSV,
            template_config_path=DOE_TEMPLATE_CONFIG,
            output_root=OPTIMIZATION_ROOT,
            study_name=STUDY_NAME,
            manifest_path=MANIFEST_CSV,
            runner_script=RUNNER_SCRIPT,
            apply_mode=APPLY_MODE,
            execute=EXECUTE_RUNS,
        )

        print(f"Prepared {len(planned_runs)} DOE run(s).")
    else:
        print("Skipping DOE preparation. Existing manifest/results will be used.")

    print(f"Manifest: {MANIFEST_CSV}")
    print(f"Generated inputs folder: {OPTIMIZATION_ROOT / STUDY_NAME / 'inputs'}")
    print(f"Generated runs folder: {OPTIMIZATION_ROOT / STUDY_NAME / 'runs'}")

    if PREPARE_RUNS and not EXECUTE_RUNS:
        print("")
        print("Dry run only. Inspect generated action/config files first.")
        print("Set EXECUTE_RUNS = True when ready to launch DEFORM.")

    processing_result = None
    next_processing_result = None
    proposal_result = None
    report_result = None
    next_report_result = None
    combined_dataset_path = None
    next_planned_runs = []

    if PROCESS_RESULTS:
        print("")
        print("Processing completed DOE results...")
        processing_result = process_doe_results(
            manifest_path=MANIFEST_CSV,
            dataset_path=DATASET_CSV,
            objective_weights=OBJECTIVE_WEIGHTS,
            statuses=PROCESS_STATUSES,
            output_subdir=PROCESSED_OUTPUT_SUBDIR,
            damage_object=DAMAGE_OBJECT,
            damage_step_no=DAMAGE_STEP_NO,
        )
        print(f"  Processed rows: {processing_result['processed_count']}")
        print(f"  Dataset rows: {processing_result['dataset_rows']}")
        print(f"  Dataset: {processing_result['dataset_path']}")

    else:
        print("")
        print("Result processing skipped. Set PROCESS_RESULTS = True after runs complete.")

    if RUN_NEXT_CANDIDATES:
        print("")
        print("Preparing proposed next-candidate batch...")

        if NEXT_ROUND_NUMBER > MAX_ROUND_NUMBER:
            print(
                f"  Skipped: NEXT_ROUND_NUMBER={NEXT_ROUND_NUMBER} is greater "
                f"than MAX_ROUND_NUMBER={MAX_ROUND_NUMBER}."
            )
        elif not NEXT_CANDIDATES_CSV.exists():
            print(f"  Skipped: next-candidates CSV was not found: {NEXT_CANDIDATES_CSV}")
        else:
            next_planned_runs = orchestrate_doe_runs(
                candidates_csv=NEXT_CANDIDATES_CSV,
                template_config_path=DOE_TEMPLATE_CONFIG,
                output_root=OPTIMIZATION_ROOT,
                study_name=NEXT_STUDY_NAME,
                manifest_path=NEXT_MANIFEST_CSV,
                runner_script=RUNNER_SCRIPT,
                apply_mode=APPLY_MODE,
                execute=EXECUTE_NEXT_CANDIDATES,
                config_overrides=DOE_CONFIG_OVERRIDES,
            )
            print(f"  Prepared {len(next_planned_runs)} proposed-candidate run(s).")
            print(f"  Next-round manifest: {NEXT_MANIFEST_CSV}")
            print(f"  Next-round runs folder: {OPTIMIZATION_ROOT / NEXT_STUDY_NAME / 'runs'}")

            if not EXECUTE_NEXT_CANDIDATES:
                print("  Dry run only. Set EXECUTE_NEXT_CANDIDATES = True to launch this batch.")
    
    if PROCESS_NEXT_CANDIDATES:
        print("")
        print("Processing completed next-candidate results...")
        if not NEXT_MANIFEST_CSV.exists():
            print(f"  Skipped: next-round manifest was not found: {NEXT_MANIFEST_CSV}")
        else:
            next_processing_result = process_doe_results(
                manifest_path=NEXT_MANIFEST_CSV,
                dataset_path=NEXT_DATASET_CSV,
                objective_weights=OBJECTIVE_WEIGHTS,
                statuses=PROCESS_STATUSES,
                output_subdir=PROCESSED_OUTPUT_SUBDIR,
                damage_object=DAMAGE_OBJECT,
                damage_step_no=DAMAGE_STEP_NO,
            )
            print(f"  Processed rows: {next_processing_result['processed_count']}")
            print(f"  Dataset rows: {next_processing_result['dataset_rows']}")
            print(f"  Dataset: {next_processing_result['dataset_path']}")

    if COMBINE_DATASETS:
        print("")
        print("Combining completed datasets across DOE rounds...")
        combined = combine_datasets(
            dataset_paths=[DATASET_CSV, NEXT_DATASET_CSV],
            output_csv_path=COMBINED_DATASET_CSV,
        )
        combined_dataset_path = COMBINED_DATASET_CSV
        print(f"  Combined rows: {len(combined)}")
        print(f"  Combined dataset: {COMBINED_DATASET_CSV}")

    if PROPOSE_NEXT_CANDIDATES:
        print("")
        print("Training surrogate and proposing next candidates...")
        training_dataset = COMBINED_DATASET_CSV if COMBINED_DATASET_CSV.exists() else DATASET_CSV
        try:
            proposal_result = train_and_propose_next(
                dataset_path=training_dataset,
                bounds=BOUNDS,
                next_candidates_path=NEXT_CANDIDATES_CSV,
                target_column="objective",
                model_type=MODEL_TYPE,
                n_random_candidates=N_RANDOM_BAYESIAN_CANDIDATES,
                n_select=N_NEXT_CANDIDATES,
                random_seed=RANDOM_SEED,
            )
            print(f"  Training dataset: {training_dataset}")
            print(f"  Next candidates: {proposal_result['next_candidates']}")
            print(f"  Surrogate report: {proposal_result['surrogate_report']}")
        except Exception as exc:
            print("  Bayesian proposal was skipped/failed.")
            print(f"  Reason: {exc}")
    
    if MAKE_REPORT:
        print("")
        print("Refreshing DOE visualization report...")
        try:
            report_result = visualize_doe_results(
                study_root=OPTIMIZATION_ROOT / STUDY_NAME,
                dataset_path=DATASET_CSV,
                manifest_path=MANIFEST_CSV,
                candidates_path=NEXT_CANDIDATES_CSV,
                surrogate_report_path=OPTIMIZATION_ROOT / STUDY_NAME / "surrogate_report.json",
                output_dir=REPORT_DIR,
            )
            print(f"  Report: {report_result['report_path']}")
            print(f"  Plots generated: {report_result['plot_count']}")
            if report_result.get("plot_warning"):
                print(f"  Plot warning: {report_result['plot_warning']}")
        except Exception as exc:
            print("  Report generation failed.")
            print(f"  Reason: {exc}")
            
    if NEXT_DATASET_CSV.exists():
            print("")
            print("Refreshing next-round visualization report...")
            try:
                next_report_result = visualize_doe_results(
                    study_root=OPTIMIZATION_ROOT / NEXT_STUDY_NAME,
                    dataset_path=NEXT_DATASET_CSV,
                    manifest_path=NEXT_MANIFEST_CSV,
                    candidates_path=NEXT_CANDIDATES_CSV,
                    surrogate_report_path=OPTIMIZATION_ROOT / STUDY_NAME / "surrogate_report.json",
                    output_dir=NEXT_REPORT_DIR,
                )
                print(f"  Next-round report: {next_report_result['report_path']}")
                print(f"  Next-round plots generated: {next_report_result['plot_count']}")
                if next_report_result.get("plot_warning"):
                    print(f"  Plot warning: {next_report_result['plot_warning']}")
            except Exception as exc:
                print("  Next-round report generation failed.")
                print(f"  Reason: {exc}")

    return {
        "planned_runs": planned_runs,
        "processing_result": processing_result,
        "next_processing_result": next_processing_result,
        "proposal_result": proposal_result,
        "report_result": report_result,
        "next_report_result": next_report_result,
        "combined_dataset_path": combined_dataset_path,
        "next_planned_runs": next_planned_runs,
    }



if __name__ == "__main__":
    results = run_initial_doe()
