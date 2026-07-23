# Manual: deform_config_gui.py

`deform_config_gui.py` is the user-facing control panel for the DEFORM automation codebase. It does not import DEFORM API modules directly. Instead, it safely reads `DEFAULT_CONFIG` from `run_deform_hits_config.py`, lets the user edit choices through tabs and dropdowns, saves a JSON config, and launches the runner, DOE workflow, post-processing, and visualization scripts.

## Opening the GUI

Run the file from Spyder or a Python environment that has Tkinter available:

```powershell
python deform_config_gui.py
```

The GUI should be run from the code folder on the lab computer:

```text
C:\Users\nbian\Documents\DEFORM API
```

## Header controls

- `Open Manuals`: opens the local `manual` folder in Windows Explorer.
- The header and workflow rail stay visible while switching between Setup, Run setup, Materials, Outputs, Columns, Action files, DOE, Results, and Launch.

## Setup tab

The Setup tab defines the main input and output paths.

- `Key folder`: folder containing DEFORM key files.
- `Action folder`: folder containing action CSV files.
- `Action CSV`: dropdown populated from the configured action folder and local `action_files` folder.
- `Output run folder`: parent folder where DEFORM run folders are written.
- `Use custom key`: enables selecting a specific key file.
- `Custom key file`: dropdown with a Browse button for key files.

When an action CSV is selected, the GUI infers `Action version` from the filename. For example, `AF_TensileBar_P2-2_deform_info_v6_rev.csv` sets `action_version = v6`. If no version tag is found, the GUI uses `v1`.

## Run Setup tab

This tab controls the hit sequence and die motion choices.

- `Action version`: derived from the selected action CSV filename.
- `Number of hits`: number of forming hits to run, or `all`.
- `Die motion mode`: `single_top_die` or `symmetric`.
- `Die motion axis`: `z` for vertical die motion or `y` for Y-axis die motion.
- `Height / Die Backout [in]`: distance to back the die away after seating flush.
- `Time Step [s]`: DEFORM solve time step.
- `Top Die Interference [in]` and `Bottom Die Interference [in]`: small seating interference values.
- `Stock Diameter [in]`: dropdown with supported choices `0.625` and `1`.

If `Apply action filename rules` is true and the action filename contains `bdm`, the GUI and runner treat the run as both-dies-moving symmetric motion. Otherwise, the run defaults to single-top-die motion.

## Material/JMAK tab

Material options are populated from `material_list_deform.csv`.

- `Material type`: filters the DEFORM material dropdown.
- `DEFORM material name`: material name without the `.KEY` extension.
- `Short material label`: populated from the selected material list for readable run names.
- `Use JMAK`: controls grain simulation mode and grain-size input.

The JMAK mapping is strict:

- `Use JMAK = true` sets `JMAK simulation modes = D H G` and restores the default mean grain size if the field is blank.
- `Use JMAK = false` sets `JMAK simulation modes = D H` and clears `Mean Grain Size [um]`.

## Outputs tab

The Outputs tab controls files exported by each run and whether post-processing runs automatically.

- Post-hit key export creates initial, final, and post-hit key files.
- Coordinate logs store Workpiece, Top Die, and Bottom Die min, max, and center coordinates.
- Load-stroke CSVs use columns `Step`, `Time`, `S`, `V`, `Fx`, `Fy`, and `Fz`.
- Post-processing can run automatically after the DEFORM sequence completes.

## Columns tab

The Columns tab displays fixed default column mappings and key templates used by the automation scripts. These values are locked in the GUI so users do not accidentally change the schema from the interface.

## Action Files tab

The Action Files tab creates DEFORM action CSVs from AF machine load-stroke data.

- `AF data root folder`: browsable. If the user browses to a folder inside `AF Data`, the GUI splits the path at `AF Data`.
- `Hit folders`: dropdown populated from subfolders under the selected `AF Data` folder. If the selected path is `...\AF Data\Box`, the GUI sets the root to `...\AF Data` and the hit folder to `Box`.
- `Output action_files folder`: destination for generated action CSVs.
- `Output filename prefix`: prefix used by the action-file creator.
- `Position Threshold [mm]`: used to begin contact detection. Threshold should be roughly 20% larger than the initial workpiece diameter.

The GUI intentionally hides `force_sigma_multiplier`; the action-file creator uses its script default.

## DOE tab

The DOE tab launches `run_initial_doe.py` through a generated GUI launcher. It can override project root, base config, optimization root, study name, number of hits, execution flags, candidate counts, bounds, and objective weights.

Use staged execution for expensive DEFORM studies:

1. Prepare runs only.
2. Inspect generated action/config files.
3. Execute runs.
4. Process completed results.
5. Propose and prepare next candidates.
6. Execute and process the next batch.
7. Refresh reports.

## Post/Reports tab

This tab runs single-run post-processing and DOE visualization/reporting.

- Single-run post-processing calls `run_deform_post_processing.py`.
- DOE visualization calls `visualize_doe_results.py`.
- Plot images generated by the reporting script can be refreshed and viewed directly inside the GUI.

## Launch tab

The Launch tab writes the JSON config, previews it, and can run the main DEFORM runner.

- `Load JSON Config`: loads an existing config into the GUI.
- `Save JSON Config`: writes the current GUI choices to disk.
- `Save and Run DEFORM`: saves the config and starts `run_deform_hits_config.py --config ...`.
- `Preview Config`: prints the generated JSON to the preview box.

Only the preview/log box scrolls on this tab. The full page does not have a page-level scrollbar.

## Recommended workflow

1. Open the GUI.
2. Use Setup to choose key, action, and output folders.
3. Choose the action CSV and confirm the inferred action version.
4. Use Run Setup to confirm die motion, axis, hit count, height, and stock diameter.
5. Use Material/JMAK to choose material and grain simulation mode.
6. Use Outputs to enable key, coordinate, load-stroke, and post-processing exports.
7. Save and preview the JSON config.
8. Run one short test or one hit before launching long multihit sequences.
9. Use Results to process and visualize outputs.

## Troubleshooting

- If action CSVs do not appear, check `Action folder` and press `Refresh file dropdowns`.
- If `Action version` stays `v1`, the filename likely does not contain a version tag like `_v6_`.
- If JMAK modes do not match the toggle, reselect `Use JMAK`; saving also enforces the strict mapping.
- If generated action files use the wrong hit folder, browse to the folder under `AF Data` and confirm the hit folder dropdown.
- If plot images do not display, regenerate the DOE report and press Refresh in the plot viewer.
