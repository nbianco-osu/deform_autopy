# DEFORM DOE, Dataset, and Bayesian Optimization

This layer turns completed DEFORM runs into a dataset, trains a surrogate model,
and proposes the next candidate runs. It is intentionally staged because DEFORM
runs are expensive and should be inspected before launching large batches.

## Current Loop

The recommended optimization loop is:

1. Generate an initial DOE candidate table.
2. Convert candidates into action CSVs and config JSONs.
3. Run DEFORM.
4. Post-process completed runs.
5. Build/update the dataset using completed runs only.
6. Train a surrogate model.
7. Propose next candidates with Bayesian optimization.
8. Repeat with the next round.

The loop is not an unattended infinite loop. Each stage is controlled by flags
in `run_initial_doe.py`.

## Important Files

- `run_initial_doe.py`
  - Main Spyder launcher for DOE and next-candidate rounds.
  - Controls preparation, execution, processing, proposal, dataset combining,
    and reporting through boolean flags.

- `doe_runner.py`
  - Converts candidate rows into DEFORM action CSVs and config JSONs.
  - Logs records to a manifest.
  - Can execute `run_deform_hits_config.py`.

- `run_deform_hits_config.py`
  - Main DEFORM runner.
  - Automatically creates per-hit outputs and calls post-processing after all
    hits complete when `post_process_after_run` is true.

- `run_deform_post_processing.py`
  - Single-run post-processor.
  - Creates `post_processed` outputs such as `hit_summary.csv`,
    `run_metrics.csv`, and `run_summary.json`.

- `process_doe_results.py`
  - Processes completed manifest rows.
  - Captures initial/post-hit microstructure, damage, coordinates, and
    load-stroke outputs.
  - Builds `dataset.csv`.

- `dataset_builder.py`
  - Joins manifest metadata and metrics into training rows.
  - Uses completed runs by default and ignores planned/running/failed rows.

- `metrics.py`
  - Computes summary metrics for grain size, load-stroke data, coordinates, and
    damage.

- `surrogate_model.py`
  - Trains tabular surrogate models.
  - Supports Random Forest, Extra Trees, and Gaussian Process when dependencies
    are available.

- `optimizers/doe.py`
  - Generates DOE candidates, including Latin hypercube and grid candidates.

- `optimizers/bayesian.py`
  - Proposes new candidates using expected improvement.

- `visualize_doe_results.py`
  - Builds an HTML/CSV report for the current study.
  - Creates plots when `matplotlib` is installed.

## Runner Outputs Used by Optimization

`run_deform_hits_config.py` writes per-hit outputs:

- `af-hit-N_final.KEY`
- `af-hit-N_post.KEY`
- `object_coordinates_hitN_<stage>.csv`
- `load_stroke_hitN.csv`

Automatic post-processing writes:

```text
<run_dir>/post_processed/
```

with:

- `initial_microstructure.csv`
- `microstructure_hit<N>.csv`
- `hit_summary.csv`
- `run_metrics.csv`
- `coordinates_all_hits.csv`
- `load_stroke_all_hits.csv`
- `damage_summary.csv`
- `run_summary.json`

These files are the raw material for DOE result processing and dataset building.

## Key `run_initial_doe.py` Flags

Use these flags in staged passes:

```python
PREPARE_RUNS = True
EXECUTE_RUNS = False

PROCESS_RESULTS = False
PROPOSE_NEXT_CANDIDATES = False

RUN_NEXT_CANDIDATES = False
EXECUTE_NEXT_CANDIDATES = False
PROCESS_NEXT_CANDIDATES = False

COMBINE_DATASETS = False
MAKE_REPORT = False
```

### Pass 1: Prepare Initial DOE Inputs

```python
PREPARE_RUNS = True
EXECUTE_RUNS = False
PROCESS_RESULTS = False
PROPOSE_NEXT_CANDIDATES = False
```

Inspect the generated action CSVs and config JSONs before executing.

### Pass 2: Execute Initial DOE

```python
PREPARE_RUNS = False
EXECUTE_RUNS = True
PROCESS_RESULTS = False
```

This launches the prepared DEFORM runs.

### Pass 3: Process Initial DOE and Propose Next Candidates

```python
PREPARE_RUNS = False
EXECUTE_RUNS = False
PROCESS_RESULTS = True
PROPOSE_NEXT_CANDIDATES = True
MAKE_REPORT = True
```

This builds `dataset.csv`, trains/proposes when possible, and writes
`candidates_next.csv`.

### Pass 4: Prepare Next-Candidate Runs

```python
RUN_NEXT_CANDIDATES = True
EXECUTE_NEXT_CANDIDATES = False
```

Inspect the generated next-round action/config files.

### Pass 5: Execute Next-Candidate Runs

```python
RUN_NEXT_CANDIDATES = False
EXECUTE_NEXT_CANDIDATES = True
```

### Pass 6: Process Next Round and Combine Datasets

```python
PROCESS_NEXT_CANDIDATES = True
COMBINE_DATASETS = True
PROPOSE_NEXT_CANDIDATES = True
MAKE_REPORT = True
```

The combined dataset is written as:

```text
optimization/<study_name>/dataset_all.csv
```

## Completed Runs Only

Training and Bayesian proposal should use completed runs only.

`dataset_builder.py` and `process_doe_results.py` are designed to ignore
planned/running/failed rows unless explicitly told otherwise. This prevents
placeholder manifest rows from being treated as valid training data.

## Candidate Variables

Typical bounded inputs include:

```python
BOUNDS = {
    "depth_in": [0.01, 0.06],
    "speed_in/s": [0.5, 2.0],
    "forging_temp_c": [900, 1150],
}
```

Candidate columns that match action CSV columns are applied to generated action
files. Candidate columns that match config keys are applied to generated config
JSON files.

Examples:

- `depth_in`
- `speed_in/s`
- `forging_temp_c`
- `height`
- `time_step`
- `die_motion_mode`
- `die_motion_axis`

## Objective Weights

Objective weights are intentionally easy to change after results are processed.
The current plan is to tune `OBJECTIVE_WEIGHTS` later with Bayesian
optimization.

Example:

```python
OBJECTIVE_WEIGHTS = {
    "damage_max": 100.0,
    "grain_std_um": 1.0,
    "top_die_center_distance": 10.0,
}
```

Avoid including bending metrics until the project explicitly adds and validates
those measurements.

## Reports and Visualization

`visualize_doe_results.py` reads datasets, manifests, candidate files, and
surrogate reports and writes a reporting folder with:

- `index.html`
- `dataset_numeric_summary.csv`
- plot PNGs when `matplotlib` is available

`run_initial_doe.py` can call this automatically when:

```python
MAKE_REPORT = True
```

## Manual Processing

For one completed run, use:

```python
from run_deform_post_processing import process_run

process_run(config_path=r"C:\path\to\run_config.json")
```

If the run used the in-file `DEFAULT_CONFIG`, automatic post-processing is the
preferred path because the runner passes the evaluated config directly. Manual
`process_run()` with no arguments works only when `DEFAULT_CONFIG` contains
literal values.

## Common Issues

### `No module named surrogate_model`

Run from the codebase folder or make sure Spyder's working directory is:

```text
C:\Users\nbian\OneDrive\Documents\DEFORM API
```

### `columns are missing: {...}`

The dataset probably included planned/running rows or non-feature columns.
Use completed runs only and train only on bounded input columns.

### `malformed node or string ... ast.Call`

This happens when standalone post-processing tries to parse a `DEFAULT_CONFIG`
that contains computed values or function calls. Automatic post-processing from
`run_deform_hits_config.py` avoids this by passing the evaluated config directly.

### No Plots in Report

`visualize_doe_results.py` still writes HTML/CSV summaries without `matplotlib`.
Install `matplotlib` on the lab environment if plot PNGs are needed.

## Supporting Documentation

- `output/pdf/run_deform_hits_config_sop.pdf`
- `output/pdf/deform_doe_loop_instructions.pdf`
- `outputs/DEFORM_workflow_and_file_map.pptx`
