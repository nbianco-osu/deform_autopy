# Future Capabilities Roadmap

This file lists future capabilities that fit the current codebase structure.
They are not all implemented yet, but they can be added without replacing the
current multihit runner and DOE pipeline.

## Run setup and robustness

- Preflight validation that checks all key paths, action columns, material
  names, DEFORM object names, die axis settings, and output folders before any
  DB is written.
- Restart/resume support that reads the manifest and skips completed hits or
  completed candidate runs.
- Stronger failure classification, such as DEFORM abnormal stop, missing DB,
  post-processing failure, invalid geometry, or missing output file.
- Automatic run archiving that stores the exact config, action CSV, key file
  name, code version, and environment notes with every run.

## Geometry and positioning

- Coordinate-driven die recentering before every hit, using Workpiece, Top Die,
  and Bottom Die center coordinates.
- Optional bending and straightness metrics from workpiece centerline or surface
  point tracking.
- Automatic detection of whether the configured die axis should be Z or Y based
  on key-file object coordinates.
- More general multi-die support where each die pair has named object aliases
  and axis conventions in the config.
- Tooling to compare final workpiece geometry across DOE candidates.

## Material and microstructure

- Material library discovery that lists available DEFORM material names from the
  system and user material folders.
- Material sweeps where candidate rows can select material source, material
  name, or material number.
- Supplier grain-size initialization from distributions, not only a single mean
  grain size.
- Lag-time modeling between hits so JMAK grain growth can occur during hold
  periods or transfer delays.
- JMAK calibration workflows that fit model parameters to measured grain-size
  data.
- Microstructure target matching that compares predicted grain statistics
  against experimental measurements by location or region.

## Process variables and DOE

- Candidate support for speed, depth, temperature, height, time step, friction,
  die axis, die motion mode, lag time, and material choice.
- Per-hit candidate control where different hits can receive different depths,
  speeds, temperatures, or offsets.
- DOE templates for common studies, such as small single-die sweeps,
  both-dies-moving anti-bending sweeps, material comparisons, and JMAK
  calibration studies.
- Batch sizing rules that limit total runs, total estimated wall time, or total
  DEFORM solves per round.

## Optimization

- Bayesian optimization with constraints, such as maximum damage limits,
  target grain-size ranges, or maximum load limits.
- Multi-objective optimization that tracks tradeoffs between damage, grain size,
  load, cycle time, and dimensional accuracy.
- Active learning that proposes candidates where the surrogate uncertainty is
  high.
- Trust-region optimization that proposes conservative changes near successful
  runs.
- Later reinforcement-learning experiments once the dataset and simulator
  interface are stable enough.

## Post-processing and reporting

- Unified run reports that combine load-stroke curves, coordinate histories,
  damage summaries, microstructure summaries, and key config values.
- Live DOE dashboards that update as the manifest changes.
- Automatic comparison reports between baseline, symmetric-die, and
  single-top-die runs.
- Export packages for collaborators, including config, action CSV, summary
  metrics, plots, and notes.

## Data management

- Stable dataset schemas with version tags so old DOE results remain readable
  after the code evolves.
- A run registry that maps every dataset row back to its config, action CSV,
  run folder, processed outputs, and original candidate row.
- Data-quality checks that flag missing microstructure, missing load-stroke
  data, incomplete hit folders, or inconsistent manifest status.
- Optional storage of large output files outside OneDrive while keeping
  metadata and summaries in the project folder.

## User experience

- A guided setup script that creates a config file for a new user by asking for
  their DEFORM code folder, key folder, action folder, output folder, and
  material library paths.
- Config templates for common cases: default single-top-die, symmetric BDM,
  Y-axis dies, material sweep, and DOE optimization.
- A simple command menu for Spyder users that selects common workflows without
  editing many flags by hand.
- Clearer standard operating procedures for adding a new material, adding a new
  die, starting a DOE, processing results, and proposing next candidates.
