# DEFORM API Automation Codebase

This folder contains the current DEFORM automation workflow for Agility Forge
multihit simulations, post-processing, dataset creation, and Bayesian
optimization.

The current workspace is:

```text
C:\Users\nbian\OneDrive\Documents\DEFORM API
```

Most scripts are designed to run from Spyder on the lab computer where the
DEFORM Python API is available.

## Current Main Workflow

The normal single-run workflow is:

1. Prepare a DEFORM starting `.KEY` file.
2. Prepare an action CSV with one row per hit.
3. Run `run_deform_hits_config.py`.
4. Let automatic post-processing finish.
5. Review the generated `post_processed` folder.

The runner creates one run folder under:

```text
<data_path>/<run_name>/
```

Each hit is stored in its own subfolder:

```text
<run_name>-hit0/
<run_name>-hit1/
...
<run_name>-hitN/
```

## Primary Entry Points

- `run_deform_hits_config.py`
  - Main config-driven DEFORM multihit runner.
  - Reads `DEFAULT_CONFIG` or a JSON config passed with `--config`.
  - Reads the action CSV.
  - Creates and solves hit databases.
  - Supports symmetric both-die movement and single-top-die movement.
  - Supports die motion along either the Z axis or Y axis.
  - Exports final/post-hit key files, coordinate logs, and load-stroke CSVs.
  - Automatically calls `run_deform_post_processing.py` after all hits complete.

- `run_deform_post_processing.py`
  - Post-processes one completed multihit run.
  - Parses initial and post-hit JMAK grain data from key files.
  - Combines coordinate logs and load-stroke CSVs.
  - Extracts or summarizes damage when possible.
  - Writes `hit_summary.csv`, `run_metrics.csv`, and `run_summary.json`.

- `run_initial_doe.py`
  - Spyder-friendly launcher for DOE and Bayesian optimization loops.
  - Can prepare initial runs, execute runs, process completed results, propose
    next candidates, execute next candidates, combine datasets, and make reports.

- `doe_runner.py`
  - Turns candidate rows into DEFORM action CSVs and config JSONs.
  - Logs planned/running/completed records to a manifest.
  - Can optionally execute the DEFORM runner.

- `process_doe_results.py`
  - Processes completed DOE manifest rows.
  - Builds datasets for optimization.
  - Ignores planned/running/failed runs by default.

- `visualize_doe_results.py`
  - Builds HTML/CSV reporting for DOE results.
  - Generates plots when `matplotlib` is available.

## Key Configuration Tags

`run_deform_hits_config.py` can use either the in-file `DEFAULT_CONFIG` or a JSON
config file. Important config fields include:

```json
{
  "key_path": "C:\\path\\to\\key_files",
  "action_path": "C:\\path\\to\\action_files",
  "action_file": "AF_TensileBar_P2-2_deform_info_v5_rev.csv",
  "data_path": "C:\\path\\to\\runs",
  "material": "316L",
  "change_material": false,
  "material_source": "system_library",
  "deform_material_name": "",
  "run_number": 1,
  "num_hits": 5,
  "height": 0.025,
  "die_motion_mode": "symmetric",
  "die_motion_axis": "z",
  "use_jmak": true,
  "mean_grain_size_um": 26.3,
  "post_process_after_run": true
}
```

### Die Motion Mode

`die_motion_mode` controls which die or dies move during the forming stroke:

- `"symmetric"`
  - Top and bottom dies move toward the workpiece and retract away from it.
  - This is the current anti-bending baseline.

- `"single_top_die"`
  - The top die performs the forming stroke.
  - The bottom die retracts near the end using `MOVCTL 3`.

If `apply_action_file_rules` is true and the action filename contains `bdm`, the
runner sets:

```json
"die_motion_mode": "symmetric"
```

and positions the bottom die before hit 0.

### Die Motion Axis

`die_motion_axis` controls the normal direction of die closure:

- `"z"` preserves the original setup.
- `"y"` uses Y-axis die motion and Y-axis die reseating.

For Y-axis runs, generated run names include `_yaxis` to avoid colliding with
older Z-axis results.

Example:

```json
"die_motion_mode": "symmetric",
"die_motion_axis": "y"
```

### Automatic Post-Processing

By default:

```json
"post_process_after_run": true
```

After all hits complete, `run_deform_hits_config.py` calls
`run_deform_post_processing.process_run(...)` with the same in-memory config
that was used for the run. This avoids problems when `DEFAULT_CONFIG` contains
user-specific helper calls or computed paths.

To skip automatic post-processing:

```json
"post_process_after_run": false
```

### Programmatic Material Changes

`material_management.py` can replace or assign the workpiece material after the
starting key is read and before hit 0 is written.

Typical system-library replacement:

```json
{
  "change_material": true,
  "material_source": "system_library",
  "deform_material_name": "AISI-1045",
  "material_object_name": "Workpiece",
  "system_material_library_dir": "C:\\Program Files\\SFTC\\DEFORM\\v14.0\\MaterialLibrary\\Standard"
}
```

Supported `material_source` values:

- `"system_library"` uses `DeformMaterial.importLib(...)`.
- `"user_library"` uses `DeformMaterial.importUsrLib(...)`.
- `"key"` uses `DeformMaterial.importKey(...)`.
- `"db"` uses `DeformMaterial.importDB(...)`.
- `"assign"` uses `DeformObject.assignMat(...)` or `assignMatByNo(...)`.

## Running a Multihit Job

In Spyder:

```python
from run_deform_hits_config import main

CONFIG_PATH = r"C:\path\to\run_config.json"
main(CONFIG_PATH)
```

Using the built-in default config:

```python
from run_deform_hits_config import main

main()
```

From a terminal:

```powershell
python run_deform_hits_config.py --config C:\path\to\run_config.json
```

## Expected Runner Outputs

Per hit folder:

- `af_hit<N>.DB`
- `af-hit-N_final.KEY`
- `af-hit-N_post.KEY`
- `object_coordinates_hit<N>_<stage>.csv`
- `load_stroke_hit<N>.csv`

Automatic post-processing creates:

```text
<data_path>/<run_name>/post_processed/
```

with files such as:

- `initial_microstructure.csv`
- `microstructure_hit<N>.csv`
- `hit_summary.csv`
- `run_metrics.csv`
- `coordinates_all_hits.csv`
- `load_stroke_all_hits.csv`
- `damage_summary.csv`
- `run_summary.json`

## Supporting Modules

- `die_positioning.py`
  - Hit-0 die seating and between-hit coordinate logging.
  - Supports Z-axis and Y-axis die closure.

- `grain_initialization.py`
  - Builds JMAK grain-size initialization key strings.

- `material_management.py`
  - Programmatically changes or assigns DEFORM materials from config.

- `lag_time.py`
  - Experimental lag-time and adaptive timing helpers.

- `microstructure_post_processing.py`
  - Parses `GRAIN` blocks from DEFORM key files.

- `metrics.py`
  - Summarizes microstructure, load-stroke, coordinates, and damage.

- `dataset_builder.py`
  - Builds training rows from completed manifest records.

- `surrogate_model.py`
  - Trains surrogate models for Bayesian optimization.

- `optimizers/doe.py`
  - Generates DOE candidate tables.

- `optimizers/bayesian.py`
  - Proposes next candidates from a trained surrogate.

## Documentation Artifacts

- `output/pdf/run_deform_hits_config_sop.pdf`
  - SOP for running and post-processing `run_deform_hits_config.py`.

- `output/pdf/deform_doe_loop_instructions.pdf`
  - DOE loop instructions.

- `outputs/DEFORM_workflow_and_file_map.pptx`
  - Slide deck explaining the workflow and file map.

## Recommended Practices

- Prefer JSON configs for reproducibility, even though `DEFAULT_CONFIG` is
  supported.
- Inspect hit 0 and hit 1 visually before launching long runs.
- Use symmetric die motion for bending-sensitive studies.
- Use `die_motion_axis = "y"` only when the key file/die geometry is intended
  for Y-axis closure.
- Keep `post_process_after_run = true` for dataset and optimization workflows.
- Train/propose next candidates only from completed runs, not planned runs.

## Optimization

See [README_OPTIMIZATION.md](README_OPTIMIZATION.md) for DOE, dataset, surrogate
modeling, Bayesian proposal, and visualization workflow details.
