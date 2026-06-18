# DEFORM Automation Codebase Notes

Source code reviewed from:

`C:\Users\nbian\OneDrive\Desktop\DEFORM Codes`

Workspace for notes and future tracked work:

`C:\Users\nbian\OneDrive\Documents\DEFORM API`

## Current Purpose

This code wraps the DEFORM SFTC Python API to automate DEFORM simulations. The main workflow is:

1. Read a base `.KEY` file created in the DEFORM GUI.
2. Generate modified `.KEY` / `.DB` files for one or more runs.
3. Submit DEFORM jobs through `defRun.submitJobInteractively`.
4. Post-process load-stroke, geometry, stress, strain, RZ, material, and microstructure data.
5. Use extracted outputs to drive DOE, optimization, or multihit policy loops.

## Important Directories

- `Lib/`: DEFORM API Python wrappers and DLLs.
- `Manual/`: DEFORM API setup, reference, and use-case PDFs.
- `util/`: environment/path utility helpers.
- Root scripts: project-specific automation runners and post-processing utilities.

## Main Entry Points

- `run_deform_hits.py`: Current multihit runner for Agility Forge style tensile-bar sequences. Uses a CSV action file, applies per-hit die motion, repositions/rotates the workpiece, writes next-hit key files, and runs DEFORM after hit 0.
- `run_deform_hits_both_dies_move.py`: Similar to `run_deform_hits.py`, but moves both dies during the stroke and offsets both dies after each hit.
- `run_deform_hits_jmak_lag.py`: Multihit runner with lag time and adaptive time-step (`DTTYPE`) support. Includes optional log-normal initial grain-size generation.
- `run_policy.py`: Earlier policy-action multihit runner with simpler hard-coded offsets and special-case corrections.
- `run_auto_loop.py`: Top-level DOE/optimization launcher for the older input-file based loop.
- `run_deform_optimizer_loop.py`: Runs DEFORM batches, post-processes outputs, merges results, and proposes next parameter bounds.

## Supporting Scripts

- `create_input_file.py`: Writes JSON input files for DOE/optimization runs.
- `process_input_file.py`: Reads those JSON input files.
- `process_loop_results.py`: Chooses next DOE/optimization points from merged output data.
- `post_process.py`: Exports geometry, load-stroke, mesh, stress, strain, inter-object, sim-control, material, and optional point-tracking data.
- `extract_microstructure_data.py`: Saves final-step key files and parses `GRAIN` blocks into CSV.
- `extract_properties.py`: Converts load-stroke data into engineering stress, strain, and strain rate.
- `update_grain_size.py`: Creates a constant-grain-size `GRAIN` key block.

## Immediate Issues Noted

- Many scripts contain hard-coded paths from the lab computer, especially `C:\Users\bianco.33\Desktop\deform_auto_py`. These should be moved into config files or command-line arguments.
- `run_job` is duplicated in multiple files. It should become one reusable helper.
- Multihit stroke scheduling and workpiece/die repositioning are duplicated and partially divergent across runner scripts.
- `run_deform_optimizer_loop.run_deform_post_process_opt_loop` appears inconsistent: the definition takes fewer arguments than the calls pass, and it references `target` / `opt_type` names that are not in local scope.
- `merge_results` checks `optTargetType == 'prop'`, but later uses `optTargetType == 'mech'`, so mechanical property result creation may not behave as intended.
- Several scripts use bare `except:` or silently pass on missing files, which can hide failed simulations or failed post-processing.
- Grain-size parsing assumes the `GRAIN` block runs until `ELMDEN` and that each element consumes four lines. That may be correct for the current key files but should be validated and turned into a tested parser.
- Time-step settings are manual. Runtime can likely be reduced by separating lag, air travel, contact, and unload regions, with coarser steps away from contact.

## Workpiece Bending: Likely Control Levers

- Enforce symmetric or balanced die motion when appropriate.
- Add pre-run checks for offset, rotation, depth, and die/workpiece interference to flag high bending-risk actions.
- Add per-hit output metrics for centerline curvature, end-to-end displacement, or front/back face deviation using point tracking or exported geometry.
- Add a policy/optimizer penalty for bending, not only grain size or load/stroke targets.
- Compare one-die vs both-die motion for the same action sequence and quantify bending metrics.

## Runtime Reduction: Likely Control Levers

- Use adaptive time stepping more systematically, as started in `run_deform_hits_jmak_lag.py`.
- Increase `DTMAX` and reduce save frequency during lag and non-contact travel.
- Save fewer full states while still exporting target metrics.
- Skip unnecessary exports during exploratory DOE runs.
- Add restart/resume logic to avoid rerunning completed hits.
- Add preflight estimates for per-hit `NSTEP` and total expected steps before launching.

## Grain-Size Matching: Likely Control Levers

- Unify constant and log-normal grain initialization into one tested module.
- Add deterministic random seeds so grain initialization can be reproduced.
- Compare target grain-size distributions using mean, standard deviation, percentiles, and distribution distance, not only mean grain size.
- Add run metadata alongside microstructure CSV outputs: material, initial grain model, hit sequence, temperature history, lag time, time-step settings.
- Support calibration loops over temperature, speed, lag time, friction, and initial grain distribution parameters.

## Suggested Refactor Roadmap

1. Create a small `deform_auto` package with modules for config, job running, stroke planning, repositioning, grain-size blocks, and post-processing.
2. Convert the current hard-coded multihit scripts into config-driven CLI commands.
3. Add validation before launching: file paths, CSV columns, hit depths, offsets, rotations, step counts, material/key compatibility.
4. Add a metrics layer for bending, runtime, and grain-size objectives.
5. Add resumable run manifests so completed hits and post-processing outputs are tracked.
6. Add documentation for lab-computer setup and standard operating workflows.

## Changes Started

- `run_deform_hits.py` has been updated to accept `--config path/to/config.json`.
- Added `configs/run_deform_hits_config.example.json`.
- The config supports changing action CSV, source directory, output directory, run-name template, material, die/key-file mapping, timing controls, die motion settings, and action CSV column names.
- The updated runner was copied into `C:\Users\nbian\OneDrive\Desktop\DEFORM Codes\run_deform_hits.py`.
- A backup of the previous runner was saved beside it as `run_deform_hits.py.bak_20260611_211734`.
- The runner was updated again so the CSV rotation angle is applied to configured die objects instead of the workpiece.
- Default die rotation config: `rotation_objects = ["Top Die", "Bottom Die"]`, `die_rotation_axis = [1, 0, 0]`, `die_rotation_self_center = true`.
- A backup of the config-enabled runner before this rotation change was saved as `run_deform_hits.py.bak_20260612_094518`.
- After visual review, the repositioning model was changed so offsets are applied to the die pair by default instead of the workpiece.
- Default reposition config: `reposition_mode = "dies"`, `die_offset_objects = ["Top Die", "Bottom Die"]`, `recenter_workpiece_after_offset = false`.
- The old workpiece-offset behavior remains available by setting `reposition_mode = "workpiece"`.
- A backup of the die-rotation-only runner before this die-offset fix was saved as `run_deform_hits.py.bak_20260612_210102`.
- Die reseating after rotation now uses hit parity: odd hits seat along Z with `dir=(0, 0, -1)/(0, 0, 1)`, even hits seat along Y with `dir=(0, -1, 0)/(0, 1, 0)`.
- Even-hit top-die rest offset swaps the first two `top_die_rest_offset` components.
- A backup before the odd/even reseating update was saved as `run_deform_hits.py.bak_20260612_210541`.

## Current Up-To-Date Runner From User

- On June 15, 2026, the user supplied `C:\Users\nbian\Downloads\run_deform_hits_v3.txt` as the most up-to-date working code.
- Important result: moving both dies symmetrically during the hit eliminates the bending problem.
- In v3, top die motion uses `MOVCTL 2` with `+speed` down and `-speed` up.
- In v3, bottom die motion mirrors it in `MOVCTL 3` with `-speed` during top-die downstroke and `+speed` during top-die upstroke.
- After each solved hit, v3 re-seats both dies with interference against the workpiece and then applies symmetric rest offsets:
  - Top Die: `offset=(0,0,{height})`
  - Bottom Die: `offset=(0,0,-{height})`
- v3 still moves and rotates the workpiece between hits; it is not the same branch as the die-rotation-only experiment.
- Future refactors should preserve the symmetric die-motion behavior as the baseline anti-bending fix.
- `run_deform_hits_v3_improved.py` was created from the v3 logic and copied to `C:\Users\nbian\OneDrive\Desktop\DEFORM Codes\run_deform_hits_v3_improved.py`.
- The improved v3 runner keeps the symmetric die stroke and symmetric reseating behavior, but adds config support, validation, and helper functions for stroke planning, die motion, die reseating, and workpiece repositioning.
- Example config copied to `C:\Users\nbian\OneDrive\Desktop\DEFORM Codes\configs\run_deform_hits_v3_config.example.json`.
- Added explanatory documentation/comments to `run_deform_hits_v3_improved.py` covering the workflow, config values, symmetric die motion, die reseating, workpiece repositioning, and hit loop behavior.
- Added configurable die motion modes to `run_deform_hits_v3_improved.py`:
  - `die_motion_mode = "symmetric"` keeps the v3 anti-bending behavior.
  - `die_motion_mode = "single_top_die"` uses top-die forming with delayed bottom-die retract.
- Single-top-die mode uses `bottom_die_retract_speed_multiplier` and `bottom_die_retract_lead_steps` from config to build the bottom die `MOVCTL 3` block.
- Added `die_positioning.py` with `position_dies_before_hits(...)` for starting from a more general key file.
- The helper should be called after reading the starting key file and before writing the first DB. It moves the top die flush with the workpiece, backs it out by `height`, and can optionally do the same symmetrically for the bottom die.
- `run_deform_hits_v3_improved.py` now calls `position_dies_before_hits(...)` during hit 0 after reading the starting key and before writing the first DB.
- Config switches: `position_dies_before_first_hit` and `position_bottom_die_before_first_hit`.
- `die_positioning.py` now includes `center_dies_on_workpiece(...)`, which uses `DeformObject.getCenterCoord()` to align die centers to the workpiece center on the axes perpendicular to the active hit axis.
- `position_dies_before_hits(...)` calls the centering helper by default before interference positioning.
- `die_positioning.py` now includes coordinate logging helpers: `get_object_coordinates(...)`, `collect_object_coordinates(...)`, and `save_object_coordinates(...)`.
- Coordinate logging saves Workpiece, Top Die, and Bottom Die min/max/center coordinates to CSV with optional hit/stage labels.
- Added action filename rules to `run_deform_hits_v3_improved.py`.
- If `action_file` contains `bdm`, the runner treats it as both-dies-moving and sets `die_motion_mode = "symmetric"` plus `position_bottom_die_before_first_hit = true`.
- This behavior is controlled by `apply_action_file_rules`.
- Added `grain_initialization.py` for JMAK initial grain-size setup.
- `grain_initialization.py` supports constant grain size, supplier mean grain size with log-normal sampling, reproducible random seeds, and reading the grain/element count from `ELMCON` in a key file.
- Added `lag_time.py` for multihit lag-time support.
- `lag_time.py` builds lag-plus-stroke timing plans, adaptive `DTTYPE` key strings, and top/bottom die `MOVCTL` blocks for lag simulations.
- Added `microstructure_post_processing.py` as an updated separate post-processing helper for JMAK grain data.
- It keeps compatibility functions `save_last_kf_step(...)` and `save_microstructure_data_to_csv(...)`, adds safer GRAIN-block parsing, supports current multihit `runName-hitN` folders, and can summarize saved microstructure CSV files.
- Added the first optimization scaffold:
  - `run_manifest.py` for run/hit metadata logging.
  - `metrics.py` for grain, load-stroke, coordinate, and bending metrics.
  - `dataset_builder.py` for building training tables from manifests and metric files.
  - `surrogate_model.py` for tabular surrogate training with optional scikit-learn.
  - `optimizers/doe.py` for Latin hypercube and grid DOE candidates.
  - `optimizers/bayesian.py` for expected-improvement candidate proposal.
  - `README_OPTIMIZATION.md` explaining the workflow.

# DEFORM Dataset, Metrics, and Bayesian Optimization

This optimization layer is intentionally separate from the DEFORM run script.
The goal is to build a clean dataset first, then use that dataset for surrogate
modeling and Bayesian optimization.

## Why This Order

DEFORM runs are expensive. Reinforcement learning usually needs many trials, so
it is not the best first step. A better first workflow is:

1. Run a designed set of simulations.
2. Save inputs, settings, and post-processed outputs.
3. Compute metrics such as grain-size error, bending, load, and runtime.
4. Train a surrogate model.
5. Use Bayesian optimization to propose the next few DEFORM runs.

The dataset produced by this workflow can later support RL or other policy
learning approaches.

## Files

- `run_manifest.py`
  - CSV manifest utilities for logging run metadata and status.

- `metrics.py`
  - Converts post-processing files into numeric metrics.
  - Supports microstructure summaries, load-stroke summaries, coordinate
    centering errors, and centerline bending from point data.

- `dataset_builder.py`
  - Joins manifest rows, metadata, and metrics into one training table.

- `optimizers/doe.py`
  - Generates initial design-of-experiments candidates.
  - Supports Latin hypercube and small full-factorial grids.

- `surrogate_model.py`
  - Trains tabular surrogate models.
  - Supports Random Forest, Extra Trees, and Gaussian Process if scikit-learn is
    installed.

- `optimizers/bayesian.py`
  - Proposes new candidates using expected improvement.

## Recommended Study Loop

### 1. Define Input Bounds

Example:

```python
bounds = {
    "depth_in": [0.01, 0.06],
    "speed_in/s": [0.5, 2.0],
    "forging_temp_c": [900, 1150],
    "lag_time_s": [0, 10],
}
```

### 2. Generate Initial DOE Candidates

```python
from optimizers.doe import latin_hypercube, save_candidates

candidates = latin_hypercube(bounds, n_samples=20, random_seed=1)
save_candidates(candidates, "optimization/candidates_initial.csv")
```

These candidate rows can be converted into action CSVs or run configs.

### 3. Log Runs to a Manifest

```python
from run_manifest import append_manifest_record

append_manifest_record(
    "optimization/manifest.csv",
    {
        "study_name": "grain_bending_study_001",
        "run_name": "af_tensile_test_001",
        "run_dir": r"C:\path\to\runs\af_tensile_test_001",
        "status": "completed",
        "material": "4140",
        "die": 2,
        "die_motion_mode": "symmetric",
    },
    metadata={
        "depth_in": 0.04,
        "speed_in/s": 1.0,
        "lag_time_s": 2.0,
    },
)
```

### 4. Compute Metrics and Build Dataset

If the manifest includes columns such as `microstructure_csv`,
`load_stroke_csv`, or `coordinate_csv`, `dataset_builder.py` can merge those
metrics automatically.

```python
from dataset_builder import build_dataset_from_manifest

dataset = build_dataset_from_manifest(
    manifest_path="optimization/manifest.csv",
    output_csv_path="optimization/dataset.csv",
    objective_weights={
        "grain_mean_um": 1.0,
        "top_die_center_distance": 10.0,
    },
)
```

For better objectives, add explicit terms such as grain-size error, bending
error, maximum load penalty, and runtime penalty.

### 5. Train a Surrogate

```python
from surrogate_model import train_surrogate, save_training_report

model, report = train_surrogate(
    dataset_csv_path="optimization/dataset.csv",
    target_column="objective",
    model_type="random_forest",
)
save_training_report(report, "optimization/surrogate_report.json")
```

### 6. Propose Bayesian Optimization Candidates

```python
from optimizers.bayesian import propose_bayesian_candidates

next_candidates = propose_bayesian_candidates(
    model=model,
    completed_dataset="optimization/dataset.csv",
    bounds=bounds,
    target_column="objective",
    n_random_candidates=2000,
    n_select=5,
    minimize=True,
)

next_candidates.to_csv("optimization/candidates_next.csv", index=False)
```

## Suggested Objective Metrics

Start with a scalar objective like:

```text
objective =
    grain_size_error_weight * abs(mean_grain_size - target_grain_size)
  + grain_std_weight * grain_size_std
  + bending_weight * centerline_max_deviation
  + load_weight * load_limit_penalty
  + runtime_weight * runtime_minutes
```

Keep individual metrics in the dataset even when using a combined objective.
That lets you later change priorities without rerunning DEFORM.

## Next Integration Step

The next practical step is to have `run_deform_hits_v3_improved.py` write a run
manifest row and save coordinate logs during hit 0 and after each hit. Once
microstructure and load-stroke CSVs are consistently produced, the dataset
builder can assemble training rows automatically.
