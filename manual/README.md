# DEFORM Automation Manuals

This folder contains user-facing manuals for the current DEFORM automation codebase. The goal is to give a new user enough context to configure the GUI, run normal multihit jobs, create action files, run DOE studies, understand generated files, and see where the codebase can grow next.

## Manuals in this folder

- [deform_config_gui_manual.md](deform_config_gui_manual.md) explains the Tkinter GUI used to configure, launch, post-process, and visualize DEFORM workflows.
- [deform_config_gui_flowchart.md](deform_config_gui_flowchart.md) is a standalone flowchart for the GUI workflow.
- [run_deform_hits_config_manual.md](run_deform_hits_config_manual.md) explains the main multihit DEFORM runner.
- [run_deform_hits_config_flowchart.md](run_deform_hits_config_flowchart.md) is a standalone flowchart for `run_deform_hits_config.py`.
- [run_initial_doe_manual.md](run_initial_doe_manual.md) explains the initial DOE, result processing, surrogate proposal, and reporting loop.
- [run_initial_doe_flowchart.md](run_initial_doe_flowchart.md) is a standalone flowchart for `run_initial_doe.py`.
- [future_capabilities.md](future_capabilities.md) lists future capabilities that fit the current architecture.

Generated PDF copies are created from these Markdown sources by running:

```powershell
python regenerate_manual_pdfs.py
```

## Main workflow

For most users, start with `deform_config_gui.py`. The GUI reads the current defaults from `run_deform_hits_config.py`, lets the user choose paths, materials, action files, die motion, JMAK settings, DOE controls, and post-processing/reporting options, then writes a JSON config for the runner.

For one DEFORM run, `run_deform_hits_config.py` reads a config, an action CSV, and an initial key file, then creates and runs the hit sequence. If post-processing is enabled, it also exports run metrics and summary files.

For optimization studies, `run_initial_doe.py` creates DOE candidates, converts them into DEFORM configs/action files through `doe_runner.py`, optionally runs them, processes completed results, trains a surrogate, proposes new candidates, and refreshes the report.

## Notes for lab use

- The GUI has an `Open Manuals` button that opens this folder.
- The scripts are designed to be Spyder-friendly. The top-level settings in `run_initial_doe.py` can be edited and then the file can be run directly.
- `run_deform_hits_config.py` can use either its built-in `DEFAULT_CONFIG` or an external JSON config passed with `--config`.
- The DOE pipeline should only train on completed runs. Planned, running, and failed runs are ignored during dataset creation unless the status filter is changed intentionally.
- Keep generated DOE files, run folders, manifests, datasets, and reports inside the configured optimization folder so every run can be traced back to the exact config and action CSV that created it.
