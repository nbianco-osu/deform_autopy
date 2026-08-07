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

- `experimental_analysis/microstructure_targets.py`
  - Defines scalar and distributional microstructure targets.
  - Computes target errors and simple distribution distances.

- `experimental_analysis/uncertainty.py`
  - Provides bootstrap confidence intervals, Gaussian KDE, weighted means, and
    weighted quantiles without requiring scipy or sklearn.

- `experimental_analysis/dci.py`
  - Implements a first data-consistent inversion update using density ratios:
    observed output density divided by predicted prior output density.

- `experimental_analysis/fusion.py`
  - Provides conservative fusion strategies: hit-level joining, nearest spatial
    joining, and target-error joining.

- `experimental_analysis_pipeline.py`
  - Wrapper script that runs the experimental processing workflow.

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
    stock_diameter_mm=15.875,
    contact_area_mode="flat_punch",
)

print(result)
```

## Target CSV Format

```csv
metric,target,tolerance,weight,distribution_csv,distribution_column
grain_mean_um,28.0,2.0,1.0,,
damage_max,0.25,0.05,2.0,,
```

Optional distribution targets can point to another CSV containing measured
values. Distribution comparison is intentionally separated from scalar target
errors so you can decide how to weight it later.

## Outputs

The wrapper writes:

- `af_hit_signal_summary.csv`
- `stress_strain_curves/*_stress_strain.csv`
- `recrystallization_summary.csv`
- `af_experimental_features.csv`
- `af_uncertainty_summary.csv`
- `deform_target_error_dataset.csv` when DEFORM dataset and targets are given
- `experimental_analysis_config.json`
- `experimental_analysis_summary.json`

## Next Recommended Additions

- Import line-scan geometry and estimate local contact area per hit.
- Register microscopy/hardness maps to AF and DEFORM coordinate systems.
- Add friction, heat-transfer, JMAK, and damage-parameter calibration.
- Use GPR with uncertainty when sklearn or gpytorch is available.
- Connect DCI outputs to next-hit recommendation or DOE candidate generation.

