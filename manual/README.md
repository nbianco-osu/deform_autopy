# DEFORM Automation Manuals

This folder contains user-facing manuals for the current DEFORM automation codebase.
The goal is to give a new user enough context to run normal multihit jobs, run DOE
studies, understand the generated files, and see where the codebase can grow next.

## Manuals in this folder

- [run_deform_hits_config_manual.md](run_deform_hits_config_manual.md) explains the main multihit DEFORM runner.
- [run_deform_hits_config_flowchart.md](run_deform_hits_config_flowchart.md) is a standalone flowchart for `run_deform_hits_config.py`.
- [run_initial_doe_manual.md](run_initial_doe_manual.md) explains the initial DOE, result processing, surrogate proposal, and reporting loop.
- [run_initial_doe_flowchart.md](run_initial_doe_flowchart.md) is a standalone flowchart for `run_initial_doe.py`.
- [future_capabilities.md](future_capabilities.md) lists future capabilities that fit the current architecture.

## Main workflow

For one DEFORM run, start with `run_deform_hits_config.py`. It reads a config,
an action CSV, and an initial key file, then creates and runs the hit sequence.
If post-processing is enabled, it also exports the run metrics and summary files.

For optimization studies, start with `run_initial_doe.py`. It creates DOE
candidates, converts them into DEFORM configs/action files through `doe_runner.py`,
optionally runs them, processes completed results, trains a surrogate, proposes
new candidates, and refreshes the report.

## Notes for lab use

- The scripts are designed to be Spyder-friendly. The top-level settings in
  `run_initial_doe.py` can be edited and then the file can be run directly.
- `run_deform_hits_config.py` can use either its built-in `DEFAULT_CONFIG` or an
  external JSON config passed with `--config`.
- The DOE pipeline should only train on completed runs. Planned, running, and
  failed runs are ignored during dataset creation unless the status filter is
  changed intentionally.
- Keep generated DOE files, run folders, manifests, datasets, and reports inside
  the configured optimization folder so every run can be traced back to the
  exact config and action CSV that created it.
