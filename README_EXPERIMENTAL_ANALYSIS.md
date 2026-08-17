# Agility Forge Experimental Analysis Layer

This layer is separate from the DEFORM runner and GUI. It turns raw Agility
Forge data into scientifically traceable features that can later be fused with
DEFORM simulations, microstructure characterization, surrogate models, and
data-consistent inversion.

## Why This Exists

The candidacy workflow requires three coupled data sources:

- prior/supplier material state, such as grain size, chemistry, and heat treat;
- process signals during forging, such as force, die displacement, local
  temperature, contact area, and geometry;
- post-forging state, such as grain size, hardness, porosity, damage, and
  tensile properties.

The current DEFORM automation already handles scripted simulations, JMAK grain
initialization, lag time, local temperatures, post-processing, DOE, Bayesian
proposal, and reports. This new folder starts the experimental side of the same
research loop.

## New Files

- `experimental_analysis/schema.py`
  - Shared dataclasses for column names, contact detection, stress-strain
    assumptions, recrystallization thresholds, and pipeline settings.

- `experimental_analysis/af_signal_processing.py`
  - Reads raw AF hit CSV files.
  - Detects first contact from the force baseline.
  - Computes penetration depth.
  - Writes effective stress-strain curves.

- `experimental_analysis/recrystallization.py`
  - Detects likely dynamic recrystallization indicators from stress-strain
    curves.
  - Uses peak stress, post-peak softening fraction, and terminal slope.

- `experimental_analysis/rex_kinetics.py`
  - Calculates mixed DRX, MDRX, and SRX fractions using parameterized
    Yada/Senuma, Sellars, and Zener-Hollomon based model forms.
  - Runs hit-level kinetics from AF stress-strain curves or local/nodal
    kinetics from DEFORM thermomechanical-history CSVs.

- `experimental_analysis/induction_heating.py`
  - Infers initial heating and reheating events from hit temperatures.
  - Flags hits outside the selected AF process window.
  - Writes an induction-heating schedule plot and CSV event table.

- `experimental_analysis/hit_map_3d.py`
  - Maps raw AF hit coordinates onto a cylindrical workpiece.
  - Uses the butt-reference axial position and `A` angle to place hits on the
    stock surface.
  - Writes a hit-coordinate CSV, static PNG, and interactive HTML map.

- `experimental_analysis/microstructure_evolution.py`
  - Couples the reconstructed temperature history with hit-level deformation.
  - Evaluates DRX at each hit and SRX/MDRX during interpass thermal intervals.
  - Writes a hit-by-hit grain size and recrystallized-fraction history.

- `experimental_analysis/microstructure_targets.py`
  - Defines scalar and distributional microstructure targets.
  - Computes target errors and simple distribution distances.

- `experimental_analysis/uncertainty.py`
  - Provides bootstrap confidence intervals, Gaussian KDE, weighted means, and
    weighted quantiles without requiring scipy or sklearn.

- `experimental_analysis/dci.py`
  - Implements a first data-consistent inversion update using density ratios:
    observed output density divided by predicted prior output density.

- `experimental_analysis/microstructure_import.py`
  - Imports measured grain size, hardness, porosity, damage observations, and
    tensile-property CSVs.
  - Normalizes common column names while preserving source columns.

- `experimental_analysis/validation.py`
  - Flags questionable AF hits and stress-strain curves before they enter
    calibration or model training.

- `experimental_analysis/calibration.py`
  - Runs transparent grid-search calibration over simple force, temperature,
    grain, and damage correction parameters.

- `experimental_analysis/reporting.py`
  - Builds an HTML report and PNG plots without requiring matplotlib.

- `experimental_analysis/pyjmak_adapter.py`
  - Optionally converts AF hit temperature histories into pyJMAK input files.
  - Runs ORNL `pyJMAK` when the package is installed or a local checkout path is
    supplied.
  - Writes phase-fraction predictions for the automated report.

- `experimental_analysis/local_pyjmak_workpiece.py`
  - Runs pyJMAK independently on many local/nodal workpiece temperature
    histories so phase-fraction predictions can be mapped through the
    workpiece.

- `experimental_analysis/material_data/316L_literature_parameters.json`
  - Stores literature-backed 316L phase-stability, hot-deformation, and
    grain-growth priors with source links.

- `experimental_analysis/material_data/4140_literature_parameters.json`
  - Stores literature-backed 4140 phase-transformation, hot-deformation, and
    grain-growth priors with source links.

- `experimental_analysis/material_data/pyjmak_316L_stable_austenite_nist.inp`
  - NIST-backed stable-austenite pyJMAK material input for already-solid 316L.

- `experimental_analysis/material_data/pyjmak_4140_austenite_transformations_prior.inp`
  - Generic steel pyJMAK phase-transformation prior registered for 4140 until
    4140-specific CCT/TTT tables are calibrated.

- `experimental_analysis/material_parameters.py`
  - Parses AF folders named `{object_name}_{diameter}in_{material}`.
  - Selects material-specific pyJMAK input files and DRX/SRX/MDRX priors for
    `316L` and `4140`.

- `experimental_analysis/fusion.py`
  - Provides conservative fusion strategies: hit-level joining, nearest spatial
    joining, and target-error joining.

- `experimental_analysis_pipeline.py`
  - Wrapper script that runs the experimental processing workflow.

- `model_microstructure_evolution.py`
  - Convenience wrapper for running the Box_1in thermal-deformation
    microstructure evolution workflow.

- `create_hit_map_3d.py`
  - Convenience wrapper for generating the Box_1in_316L 3D hit map.

- `analyze_all_temperature_histories.py`
  - Batch-runs induction temperature-history analysis for every AF dataset
    folder matching `{object_name}_{diameter}in_{material}`.

- `analyze_all_microstructure.py`
  - Batch-runs material-specific DRX/SRX/MDRX microstructure evolution for
    every AF dataset folder matching `{object_name}_{diameter}in_{material}`.
  - Generates missing stress-strain curves when needed and reuses/generated
    induction histories.

## Scientifically Defensible Starting Strategy

Because the final data-fusion strategy is not defined yet, the code supports
three staged strategies:

1. **Hit-level fusion**
   - Join AF process signals and DEFORM outputs by `run_name`, `hit`, or
     `global_hit_number`.
   - This is the safest first strategy when the hit sequence is known.

2. **Spatial nearest-neighbor fusion**
   - Join characterization points to the nearest DEFORM node/element coordinate.
   - This is appropriate once microscopy/hardness locations are registered to
     the sample coordinate system.

3. **Distributional target fusion**
   - Compare simulated outputs to experimental target distributions without
     claiming one-to-one spatial correspondence.
   - This is a defensible option while experimental sectioning/registration is
     still maturing.

## Stress-Strain Assumptions

The stress-strain curves are labelled **effective** because Agility Forge
open-die indentation is not uniform uniaxial compression. The conversion is
still useful for comparing hits if the same assumptions are used consistently.

Current contact-area modes:

- `flat_punch`
  - Uses a constant projected circular area.
  - Best when the active die/contact diameter is known.

- `growing_flat`
  - Uses a simple growing projected area with indentation depth.
  - Useful as a sensitivity study before a better contact-area model is
    calibrated from DEFORM or line-scan geometry.

## Recrystallization Indicators

The first implemented recrystallization indicator follows the hot-deformation
interpretation that dynamic recrystallization often produces:

- a peak in flow stress;
- post-peak flow softening;
- approach toward a low terminal slope or steady flow stress.

The output should be treated as a candidate label until validated against
metallography, DEFORM JMAK fields, or both.

## Running In Spyder

```python
from experimental_analysis_pipeline import run_experimental_analysis

result = run_experimental_analysis(
    raw_af_data_dir=r"C:\path\to\AF Data\Hit Folder",
    output_dir=r"C:\path\to\experimental_analysis_output",
    deform_dataset_csv=r"C:\path\to\optimization\study\dataset.csv",
    microstructure_targets_csv=r"C:\path\to\microstructure_targets.csv",
    experimental_microstructure_path=r"C:\path\to\measured_microstructure.csv",
    contact_area_mode="flat_punch",
    run_calibration=True,
    make_report=True,
)

print(result)
```

If `stock_diameter_mm` is omitted, the pipeline tries to infer the diameter from
the AF data folder name. Examples:

- `Box_1in` -> `25.4 mm`
- `Box_1in_316L` -> `25.4 mm`, material `316L`
- `Box_1in_4140` -> `25.4 mm`, material `4140`
- `Cylinder_1in_4140` -> `25.4 mm`, material `4140`
- `Box_0.625in` -> `15.875 mm`
- `Box_5_8in` -> `15.875 mm`

You can still pass `stock_diameter_mm=...` to override this.

The preferred folder convention is:

```text
{object_name}_{diameter}in_{material}
```

When the folder follows that convention, the pipeline records `object_name`,
`material`, `stock_diameter_mm`, the material-prior JSON path, and the default
pyJMAK material input file. Pass `--material 316L` or `--material 4140` only if
you need to override the folder-derived material.

## Optional pyJMAK Integration

ORNL `pyJMAK` models solid-state phase transformations from a time-temperature
history and an Abaqus-style phase-transformation material input file. The
adapter is optional so the AF processing workflow still runs when `pyJMAK` is
not installed.

Install or clone `pyJMAK` separately, then either install it into the active
Spyder environment:

```powershell
pip install -e "C:\path\to\pyJMAK"
```

or pass the checkout path directly:

```python
result = run_experimental_analysis(
    raw_af_data_dir=r"C:\path\to\AF Data\Box_1in",
    output_dir=r"C:\path\to\AF Data\Box_1in\experimental_analysis_output",
    pyjmak_material_input_file=r"C:\path\to\abq_phase_trans_input-Steel.inp",
    pyjmak_source_path=r"C:\path\to\pyJMAK",
)
```

To use the registered material file inferred from the folder name, pass `auto`:

```powershell
python experimental_analysis_pipeline.py `
  --raw-af-data-dir "C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in_4140" `
  --output-dir "C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in_4140\experimental_analysis_output" `
  --pyjmak-material-input-file auto
```

The pipeline writes:

- `pyjmak_temperature_history.csv`
- `pyjmak_phase_fractions.csv`
- `pyjmak_phase_fractions_summary.json`
- `report/pyjmak_phase_fractions.png`

The temperature history is built from the processed AF hit curves in numeric hit
order. Use `pyjmak_inter_hit_gap_s` if a known lag time should be inserted
between hits.

### 316L Interpretation

The codebase now includes a stable-austenite 316L starting file:

```text
C:\Users\nbian\Documents\DEFORM API\experimental_analysis\material_data\pyjmak_316L_stable_austenite_nist.inp
```

This file uses measured 316L solidus/liquidus values from NIST SRM 316L
thermophysical-property work and defines one solid phase, Austenite, with
initial fraction 1.0. It is the defensible default for AF thermal histories that
remain below melting and do not have calibrated evidence of secondary phase
evolution. It does not predict DRX, SRX, MDRX, or grain growth.

The supporting literature-prior file is:

```text
C:\Users\nbian\Documents\DEFORM API\experimental_analysis\material_data\316L_literature_parameters.json
```

Use that JSON as a transparent place to track values gathered from literature
before fitting AF-specific model parameters.

### 4140 Interpretation

The codebase now includes a 4140 starting-prior file:

```text
C:\Users\nbian\Documents\DEFORM API\experimental_analysis\material_data\4140_literature_parameters.json
```

and a registered pyJMAK transformation-prior file:

```text
C:\Users\nbian\Documents\DEFORM API\experimental_analysis\material_data\pyjmak_4140_austenite_transformations_prior.inp
```

The 4140 microstructure priors use AISI 4140 hot-deformation literature for DRX
activation/fraction trends and an AISI 4140 austenite grain-growth model form.
The pyJMAK file is currently a generic steel transformation prior registered
for 4140 so that Austenite/Ferrite/Pearlite/Bainite/Martensite predictions can
be exercised. Replace or calibrate the TTT/JMAK coefficients with 4140-specific
CCT/TTT, dilatometry, hardness, and metallography data before treating phase
fractions as final quantitative predictions.

### Local Workpiece pyJMAK Predictions

To run pyJMAK through the workpiece, export or assemble a CSV containing one
thermal history per node, element, or sampling point:

```csv
location_id,time_s,temperature_c,x_mm,y_mm,z_mm
101,0.00,1050.0,0.0,0.0,0.0
101,0.05,1048.2,0.0,0.0,0.0
102,0.00,998.0,3.0,0.0,0.0
102,0.05,996.5,3.0,0.0,0.0
```

Accepted aliases include `node_id`, `element_id`, or `point_id` for
`location_id`, and common variants of `time_s` and `temperature_c`.

Command-line example:

```powershell
python experimental_analysis_pipeline.py `
  --raw-af-data-dir "C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in" `
  --output-dir "C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in\experimental_analysis_output" `
  --pyjmak-material-input-file "C:\Users\nbian\Documents\DEFORM API\experimental_analysis\material_data\pyjmak_316L_stable_austenite_nist.inp" `
  --local-temperature-history-csv "C:\path\to\deform_local_temperature_histories.csv"
```

Outputs are written under `local_pyjmak`:

- `local_temperature_histories_normalized.csv`
- `local_pyjmak_phase_fractions.csv`
- `local_pyjmak_phase_summary.csv`
- one per-location phase-fraction CSV in `local_phase_fraction_files`

For 316L with the stable-austenite file, the expected result is local
`phase_fraction_Austenite = 1.0` wherever the local temperature path remains in
the solid, stable-austenite range. Recrystallization and grain-size predictions
should be handled by the AF recrystallization/grain model and calibrated to
post-hit microstructure data.

## Target CSV Format

```csv
metric,target,tolerance,weight,distribution_csv,distribution_column
grain_mean_um,28.0,2.0,1.0,,
damage_max,0.25,0.05,2.0,,
```

Optional distribution targets can point to another CSV containing measured
values. Distribution comparison is intentionally separated from scalar target
errors so you can decide how to weight it later.

## Experimental Microstructure CSV Format

The importer accepts flexible column names. These are preferred:

```csv
run_name,hit,region,x_mm,y_mm,z_mm,grain_size_um,hardness_hv,porosity_fraction,damage_observed
run_001,1,center,12.5,0.0,0.0,27.8,210,0.002,no_crack
```

Supported normalized fields include:

- `grain_size_um`
- `hardness_hv`
- `porosity_fraction`
- `damage_observed`
- `yield_strength_mpa`
- `ultimate_strength_mpa`
- `elongation_percent`

All original source columns are preserved with a `source_` prefix.

## Mixed DRX, MDRX, and SRX Kinetics

The mixed recrystallization layer is separate from pyJMAK. pyJMAK handles
phase-fraction histories from temperature. DRX/MDRX/SRX calculations need
thermomechanical history: strain, strain rate, temperature, starting grain size,
and interpass/lag time.

The implemented model families are:

- **DRX activation:** `Z = strain_rate * exp(Q / (R*T_K))`, then
  `epsilon_c = 0.009 * Z^0.084` as a 316L literature-prior screen.
- **DRX fraction:** Yada/Sellars strain-form Avrami expression,
  `X_DRX = 1 - exp[-0.693*((epsilon - epsilon_c)/(epsilon_0.5 - epsilon_c))^n]`.
- **SRX fraction:** Sellars-style static recrystallization timing,
  `t_0.5 = A * epsilon^p * d0^q * strain_rate^s * Z^r * exp(Q_RX/(R*T_K))`,
  followed by `X_SRX = 1 - exp[-0.693*(t/t_0.5)^n]`.
- **MDRX fraction:** Yada/Senuma-style metadynamic timing,
  `t_0.5 = A * epsilon^n * strain_rate^m * exp(Q_MDRX/(R*T_K))`,
  followed by `X_MDRX = 1 - exp[-0.693*(t/t_0.5)^k]`.

The default coefficients are screening priors stored in:

```text
C:\Users\nbian\Documents\DEFORM API\experimental_analysis\material_data\316L_literature_parameters.json
```

Run hit-level kinetics from processed AF curves:

```powershell
python experimental_analysis_pipeline.py `
  --raw-af-data-dir "C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in" `
  --output-dir "C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in\experimental_analysis_output" `
  --run-rex-kinetics `
  --initial-grain-size-um 26.3 `
  --rex-interpass-time-s 1.0
```

For local/nodal DEFORM histories, provide location, temperature, and strain.
Strain rate can be supplied directly or estimated from strain versus time:

```csv
location_id,time_s,temperature_c,true_strain,strain_rate_s,x_mm,y_mm,z_mm
101,0.00,1050.0,0.00,0.10,0.0,0.0,0.0
101,0.10,1048.0,0.05,0.10,0.0,0.0,0.0
102,0.00,990.0,0.00,0.04,3.0,0.0,0.0
102,0.10,988.0,0.02,0.04,3.0,0.0,0.0
```

Command example:

```powershell
python experimental_analysis_pipeline.py `
  --raw-af-data-dir "C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in" `
  --output-dir "C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in\experimental_analysis_output" `
  --run-rex-kinetics `
  --local-thermomechanical-history-csv "C:\path\to\deform_local_thermomechanical_histories.csv"
```

Treat the resulting fractions and grain sizes as screening predictions until
they are calibrated against measured microstructure and DEFORM JMAK output.

## Induction Heating Schedule Inference

The induction-heating model uses the fact that AF temperatures are reported when
each hit occurs. It does not yet solve coil physics. Instead, it infers when
heating must have occurred:

- the first heating event raises the workpiece from room temperature to hit 0;
- a reheat is inferred when temperature increases between consecutive hits by
  at least `reheat_delta_c`;
- a hit below the lower temperature limit is flagged as needing reheat;
- a hit above the upper temperature limit is flagged as outside the process
  window.
- when global timestamps are available, the initial room-temperature heat is
  applied to the exported thermal history. If no heating rate is supplied, its
  duration is inferred from the mean apparent reheat rate measured later in the
  same hit sequence.
- a final quench segment is appended after the last hit by default so the
  thermal history can be used for microstructure modeling.

Default process window:

```text
800-1200 C
```

Run from Spyder:

```python
from model_induction_heating import run_default_box_analysis

result = run_default_box_analysis()
print(result)
```

Run from the command line:

```powershell
python model_induction_heating.py `
  --raw-af-data-dir "C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in" `
  --output-dir "C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in\experimental_analysis_output\induction_heating" `
  --lower-temp-c 800 `
  --upper-temp-c 1200 `
  --room-temp-c 25 `
  --reheat-delta-c 25 `
  --target-reheat-temp-c 1100
```

Useful options:

- `--heating-rate-c-per-s`: use a known induction heating rate.
- `--no-infer-initial-heat-from-reheats`: do not infer the initial heat duration
  from later reheat windows.
- `--quench-duration-s`: assumed quench duration when no quench rate is known.
- `--quench-rate-c-per-s`: use a known quench cooling rate.
- `--no-quench-after-hits`: skip the final quench segment.

Outputs:

- `induction_heating_hit_temperatures.csv`
- `induction_heating_events.csv`
- `induction_heating_schedule.png`
- `induction_heating_events_plot.png`
- `induction_heating_reheat_durations.png`
- `induction_heating_temperature_vs_time.png`
- `induction_heating_temperature_time_trace.csv`
- `induction_heating_full_hit_temperature_traces.csv`
- `induction_heating_config.json`
- `induction_heating_summary.json`

## Thermal-Deformation Microstructure Evolution

After stress-strain curves and the induction-heating temperature trace exist,
run the event-based microstructure model:

```powershell
python model_microstructure_evolution.py --initial-grain-size-um 26.3
```

To calibrate the model to a measured final average grain size, pass the target
value:

```powershell
python model_microstructure_evolution.py --initial-grain-size-um 26.3 --target-final-grain-size-um 33.7
```

This currently fits one transparent parameter, `srx.srx_grain_prefactor`, while
leaving the SRX/DRX/MDRX time, temperature, strain, and Avrami exponents fixed.
For the Box_1in 316L example, a `33.7 um` final target scales the SRX grain-size
prefactor from `343.0` to approximately `1648.45`.

The default wrapper uses:

- `stress_strain_curves/*_stress_strain.csv`
- `induction_heating/induction_heating_temperature_time_trace.csv`
- initial supplier/measured mean grain size of `26.3 um` unless overridden

The model evaluates dynamic recrystallization during each hit from the effective
strain, strain rate, stress, and temperature. It then evaluates static and
metadynamic recrystallization during the thermal interval before the next hit.
The final quench is included in the thermal history, but SRX during quench is
disabled by default because the time is short and the temperature drops rapidly.

Outputs are written to `microstructure_evolution/`:

- `microstructure_evolution.csv`
- `microstructure_evolution.png`
- `microstructure_evolution_parameters.json`
- `microstructure_evolution_summary.json`

Treat these predictions as a screening model until the kinetics are calibrated
against measured microstructure and/or DEFORM JMAK fields. The current
coefficients are transparent starting priors, not final 316L AF calibration
constants.

To run the same microstructure analysis across all AF datasets:

```powershell
python analyze_all_microstructure.py
```

The script writes per-dataset outputs to
`experimental_analysis_output/microstructure_evolution_batch` and combined
outputs to `C:\Users\nbian\Desktop\OSU Research\AF Data\microstructure_batch_summary`.
The current 4140 prior is intentionally bounded with a minimum SRX
recrystallized grain size of `1 um`, but it still trends aggressively toward
fine grain sizes and should be calibrated with measured 4140 microstructure.

## Calibration Workflow

The first calibration workflow is a transparent grid search. It evaluates simple
correction parameters and writes every candidate, objective term, and rank.

Default parameters:

- `force_scale`
- `temperature_offset_c`
- `grain_scale`
- `damage_scale`

Use this as a defensible first pass before adding Bayesian calibration or
fitting full JMAK/friction/heat-transfer parameters.

Command-line example:

```powershell
python experimental_analysis_pipeline.py `
  --raw-af-data-dir "C:\path\to\AF Data\Hit Folder" `
  --output-dir "C:\path\to\experimental_analysis_output" `
  --deform-dataset-csv "C:\path\to\optimization\study\dataset.csv" `
  --microstructure-targets-csv "C:\path\to\targets.csv" `
  --experimental-microstructure-path "C:\path\to\measured_microstructure.csv" `
  --run-calibration
```

## Real AF Data Validation

The validation module writes:

- `stress_strain_validation.csv`
- `af_validation_summary.csv`

Review rows marked `review` before using the hit in model training. Common
flags include low force signal, nonpositive depth, out-of-range temperature,
too few curve points, and low strain range.

## Outputs

The wrapper writes:

- `af_hit_signal_summary.csv`
- `stress_strain_curves/*_stress_strain.csv`
- `recrystallization_summary.csv`
- `recrystallization_kinetics_summary.csv` when `--run-rex-kinetics` is enabled
- `local_rex_kinetics_summary.csv` when a local thermomechanical history CSV is
  provided
- `induction_heating/induction_heating_events.csv` when the induction-heating
  script is run
- `induction_heating/induction_heating_schedule.png` when the induction-heating
  script is run
- `microstructure_evolution/microstructure_evolution.csv` when thermal-
  deformation microstructure evolution is run
- `microstructure_evolution/microstructure_evolution.png` when thermal-
  deformation microstructure evolution is run
- `stress_strain_validation.csv`
- `af_validation_summary.csv`
- `af_experimental_features.csv`
- `af_uncertainty_summary.csv`
- `experimental_microstructure_normalized.csv` when measured microstructure is
  provided
- `experimental_microstructure_summary.csv` when measured microstructure is
  provided
- `deform_target_error_dataset.csv` when DEFORM dataset and targets are given
- `calibration_grid_search.csv` when calibration is enabled
- `calibration_best_parameters.csv` when calibration is enabled
- `report/index.html` when reporting is enabled
- `experimental_analysis_config.json`
- `experimental_analysis_summary.json`

## Next Recommended Additions

- Import line-scan geometry and estimate local contact area per hit.
- Register microscopy/hardness maps to AF and DEFORM coordinate systems.
- Add friction, heat-transfer, JMAK, and damage-parameter calibration.
- Use GPR with uncertainty when sklearn or gpytorch is available.
- Connect DCI outputs to next-hit recommendation or DOE candidate generation.
