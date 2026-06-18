# deform_autopy
Automated DEFORM Scripting with python 

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
