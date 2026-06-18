"""
Spyder-friendly launcher for creating and optionally running an initial DOE.

This file performs the first optimization workflow end-to-end:

1. Define parameter bounds.
2. Generate a Latin-hypercube DOE candidate table.
3. Create a DOE-specific runner config for 5-hit single-die runs.
4. Use `doe_runner.py` to generate one action CSV and config JSON per candidate.
5. Optionally execute each generated config with `run_deform_hits_config.py`.

Recommended first use:
- Set EXECUTE_RUNS = False.
- Run this file in Spyder.
- Inspect the generated action CSVs/config JSONs.
- Set EXECUTE_RUNS = True only when the generated inputs look correct.
"""

import json
from pathlib import Path

from doe_runner import orchestrate_doe_runs
from optimizers.doe import latin_hypercube, save_candidates


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

# Folder that contains your current DEFORM automation code.
PROJECT_ROOT = Path(r"C:\Users\bianco.33\Desktop\deform_auto_py")

# Current runner and base config used by your normal Spyder workflow.
RUNNER_SCRIPT = PROJECT_ROOT / "run_deform_hits_config.py"
BASE_CONFIG_PATH = PROJECT_ROOT / "configs" / "run_deform_hits_current_config.example.json"

# Folder where DOE candidate files, generated configs, runs, and manifest live.
OPTIMIZATION_ROOT = PROJECT_ROOT / "optimization"
STUDY_NAME = "single_die_5hit_initial_doe"

# Safety switch. Keep False until generated inputs have been inspected.
EXECUTE_RUNS = False

# How candidate values are applied to the action file:
# - "all_rows": apply each candidate value to every hit row.
# - "hit_row": require a hit column in the candidates CSV and modify only that row.
APPLY_MODE = "all_rows"

# Initial DOE size and reproducibility seed.
N_CANDIDATES = 10
RANDOM_SEED = 1

# The first DOE should stay small. Add variables only after the run pipeline is
# producing useful data and metrics.
BOUNDS = {
    "depth_in": [0.01, 0.06],
    "speed_in/s": [0.5, 2.0],
    "forging_temp_c": [900, 1150],
}

# Force this DOE to use 5-hit single-top-die runs.
DOE_CONFIG_OVERRIDES = {
    "num_hits": 5,
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


def run_initial_doe():
    """Generate DOE files and optionally execute the candidate runs."""
    OPTIMIZATION_ROOT.mkdir(parents=True, exist_ok=True)

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
    print(f"Manifest: {MANIFEST_CSV}")
    print(f"Generated inputs folder: {OPTIMIZATION_ROOT / STUDY_NAME / 'inputs'}")
    print(f"Generated runs folder: {OPTIMIZATION_ROOT / STUDY_NAME / 'runs'}")

    if not EXECUTE_RUNS:
        print("")
        print("Dry run only. Inspect generated action/config files first.")
        print("Set EXECUTE_RUNS = True when ready to launch DEFORM.")

    return planned_runs


if __name__ == "__main__":
    planned_runs = run_initial_doe()
