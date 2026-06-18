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

- `doe_runner.py`
  - Turns candidate rows into DEFORM action CSVs and runner configs.
  - Logs planned runs to the manifest.
  - Optionally executes `run_deform_hits_v3_improved.py`.

- `run_initial_doe.py`
  - Spyder-friendly one-file launcher for the first DOE.
  - Generates candidates, creates a DOE template config, prepares action/config
    files, and optionally launches runs.

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

The simplest Spyder workflow is to open `run_initial_doe.py`, edit the user
settings at the top, and run it. Keep `EXECUTE_RUNS = False` for the first pass
so it only creates candidate files:

```python
EXECUTE_RUNS = False
```

After inspecting generated action/config files, set:

```python
EXECUTE_RUNS = True
```

and run the file again.

The lower-level manual candidate generation workflow is:

```python
from optimizers.doe import latin_hypercube, save_candidates

candidates = latin_hypercube(bounds, n_samples=20, random_seed=1)
save_candidates(candidates, "optimization/candidates_initial.csv")
```

These candidate rows can be converted into action CSVs or run configs.

### 2b. Turn DOE Candidates Into DEFORM Runs

Use `doe_runner.py` to create one action CSV and one config JSON per candidate.
By default it performs a dry run and does not launch DEFORM:

```powershell
python doe_runner.py `
  --candidates optimization/candidates_initial.csv `
  --template-config configs/run_deform_hits_v3_config.example.json `
  --output-root optimization `
  --study-name grain_bending_study_001 `
  --manifest optimization/manifest.csv `
  --runner-script run_deform_hits_v3_improved.py
```

When the generated inputs look correct, add `--execute`:

```powershell
python doe_runner.py `
  --candidates optimization/candidates_initial.csv `
  --template-config configs/run_deform_hits_v3_config.example.json `
  --output-root optimization `
  --study-name grain_bending_study_001 `
  --manifest optimization/manifest.csv `
  --runner-script run_deform_hits_v3_improved.py `
  --execute
```

Candidate columns that match action CSV columns, such as `depth_in` or
`speed_in/s`, are written into the generated action CSV. Candidate columns that
match config keys, such as `height`, `time_step`, or `run_number`, are written
into the generated config.

The default `--apply-mode all_rows` applies candidate values to every row in
the action CSV. Use `--apply-mode hit_row` with a `hit` column in the candidates
CSV to modify only one action row.

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
