"""
Run the Agility Forge experimental-analysis workflow.

This wrapper is separate from `run_deform_hits_config.py` and the GUI. It can be
used after AF data collection to produce stress-strain curves, recrystallization
indicators, uncertainty summaries, and optional DEFORM/target fusion tables.

Spyder example:

    from experimental_analysis_pipeline import run_experimental_analysis

    run_experimental_analysis(
        raw_af_data_dir=r"C:\\path\\to\\AF Data\\Hit Folder",
        output_dir=r"C:\\path\\to\\analysis_output",
        deform_dataset_csv=r"C:\\path\\to\\dataset.csv",
        microstructure_targets_csv=r"C:\\path\\to\\targets.csv",
    )
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from experimental_analysis.af_signal_processing import process_af_folder
from experimental_analysis.calibration import run_default_calibration
from experimental_analysis.fusion import add_target_errors, load_table
from experimental_analysis.microstructure_import import write_microstructure_import_outputs
from experimental_analysis.microstructure_targets import load_targets_csv
from experimental_analysis.recrystallization import analyze_curve_folder
from experimental_analysis.reporting import build_experimental_report
from experimental_analysis.schema import (
    AFColumnMap,
    ContactDetectionConfig,
    PipelineConfig,
    RecrystallizationConfig,
    StressStrainConfig,
    dataclass_to_dict,
)
from experimental_analysis.uncertainty import summarize_uncertainty_table
from experimental_analysis.validation import combine_validation, validate_curve_folder, validate_hit_summary


DEFAULT_UNCERTAINTY_COLUMNS = [
    "max_force_kn",
    "depth_mm",
    "contact_temperature_c",
    "peak_stress_mpa",
    "softening_fraction",
]


def run_experimental_analysis(
    raw_af_data_dir: str | Path,
    output_dir: str | Path,
    deform_dataset_csv: str | Path | None = None,
    microstructure_targets_csv: str | Path | None = None,
    experimental_microstructure_path: str | Path | None = None,
    calibration_targets_csv: str | Path | None = None,
    hit_glob: str = "*.csv",
    stock_diameter_mm: float = 15.875,
    initial_height_mm: float | None = None,
    contact_area_mode: str = "flat_punch",
    flat_punch_diameter_mm: float | None = None,
    run_calibration: bool = False,
    make_report: bool = True,
) -> dict[str, str]:
    """Run AF experimental processing and optional DEFORM/target fusion."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = PipelineConfig(
        raw_af_data_dir=Path(raw_af_data_dir),
        output_dir=output_dir,
        deform_dataset_csv=Path(deform_dataset_csv) if deform_dataset_csv else None,
        microstructure_targets_csv=Path(microstructure_targets_csv) if microstructure_targets_csv else None,
        hit_glob=hit_glob,
        column_map=AFColumnMap(),
        contact=ContactDetectionConfig(),
        stress_strain=StressStrainConfig(
            stock_diameter_mm=stock_diameter_mm,
            initial_height_mm=initial_height_mm,
            contact_area_mode=contact_area_mode,
            flat_punch_diameter_mm=flat_punch_diameter_mm,
        ),
        recrystallization=RecrystallizationConfig(),
    )

    summary_df, curve_paths = process_af_folder(
        raw_dir=config.raw_af_data_dir,
        output_dir=config.output_dir,
        hit_glob=config.hit_glob,
        column_map=config.column_map,
        contact_config=config.contact,
        stress_config=config.stress_strain,
    )
    curve_dir = output_dir / "stress_strain_curves"
    rx_csv = output_dir / "recrystallization_summary.csv"
    rx_df = analyze_curve_folder(curve_dir, output_csv=rx_csv, config=config.recrystallization)

    hit_validation = validate_hit_summary(summary_df)
    curve_validation_csv = output_dir / "stress_strain_validation.csv"
    curve_validation = validate_curve_folder(curve_dir, output_csv=curve_validation_csv)
    validation_csv = output_dir / "af_validation_summary.csv"
    combine_validation(hit_validation, curve_validation).to_csv(validation_csv, index=False)

    af_summary_csv = output_dir / "af_hit_signal_summary.csv"
    if not summary_df.empty and not rx_df.empty:
        keys = [key for key in ["hit", "curve_file"] if key in summary_df.columns and key in rx_df.columns]
        if "hit" in summary_df.columns and "hit" in rx_df.columns:
            combined = summary_df.merge(rx_df, on="hit", how="left", suffixes=("", "_rx"))
        else:
            combined = pd.concat([summary_df.reset_index(drop=True), rx_df.reset_index(drop=True)], axis=1)
        combined_csv = output_dir / "af_experimental_features.csv"
        combined.to_csv(combined_csv, index=False)
    else:
        combined = summary_df.copy()
        combined_csv = output_dir / "af_experimental_features.csv"
        combined.to_csv(combined_csv, index=False)

    uncertainty_columns = [column for column in DEFAULT_UNCERTAINTY_COLUMNS if column in combined.columns]
    uncertainty_csv = output_dir / "af_uncertainty_summary.csv"
    summarize_uncertainty_table(combined, uncertainty_columns).to_csv(uncertainty_csv, index=False)

    outputs: dict[str, str] = {
        "output_dir": str(output_dir),
        "af_hit_signal_summary": str(af_summary_csv),
        "stress_strain_curve_dir": str(curve_dir),
        "recrystallization_summary": str(rx_csv),
        "stress_strain_validation": str(curve_validation_csv),
        "af_validation_summary": str(validation_csv),
        "af_experimental_features": str(combined_csv),
        "af_uncertainty_summary": str(uncertainty_csv),
        "curve_count": str(len(curve_paths)),
    }

    if experimental_microstructure_path:
        outputs.update(
            write_microstructure_import_outputs(
                input_path=experimental_microstructure_path,
                output_dir=output_dir,
            )
        )

    deform_df = load_table(config.deform_dataset_csv)
    targets = load_targets_csv(config.microstructure_targets_csv) if config.microstructure_targets_csv else []
    if not deform_df.empty and targets:
        fused = add_target_errors(deform_df, targets)
        fused_csv = output_dir / "deform_target_error_dataset.csv"
        fused.to_csv(fused_csv, index=False)
        outputs["deform_target_error_dataset"] = str(fused_csv)

    if run_calibration:
        calibration_source = outputs.get("deform_target_error_dataset") or str(combined_csv)
        calibration_targets = calibration_targets_csv or microstructure_targets_csv
        if calibration_targets:
            outputs.update(
                run_default_calibration(
                    dataset_csv=calibration_source,
                    targets_csv=calibration_targets,
                    output_dir=output_dir,
                )
            )
        else:
            outputs["calibration_warning"] = "run_calibration was true, but no calibration target CSV was provided."

    config_json = output_dir / "experimental_analysis_config.json"
    config_json.write_text(json.dumps(dataclass_to_dict(config), indent=2), encoding="utf-8")
    outputs["config_json"] = str(config_json)

    summary_json = output_dir / "experimental_analysis_summary.json"
    summary_json.write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    outputs["summary_json"] = str(summary_json)

    if make_report:
        outputs.update(build_experimental_report(output_dir=output_dir))
        summary_json.write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    return outputs


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Process Agility Forge experimental data.")
    parser.add_argument("--raw-af-data-dir", required=True, help="Folder containing raw AF hit CSV files.")
    parser.add_argument("--output-dir", required=True, help="Folder for processed outputs.")
    parser.add_argument("--deform-dataset-csv", default=None, help="Optional DEFORM DOE dataset.csv.")
    parser.add_argument("--microstructure-targets-csv", default=None, help="Optional target CSV.")
    parser.add_argument("--experimental-microstructure-path", default=None, help="Optional measured microstructure CSV or folder.")
    parser.add_argument("--calibration-targets-csv", default=None, help="Optional calibration target CSV.")
    parser.add_argument("--hit-glob", default="*.csv", help="Glob pattern for AF hit files.")
    parser.add_argument("--stock-diameter-mm", type=float, default=15.875)
    parser.add_argument("--initial-height-mm", type=float, default=None)
    parser.add_argument("--contact-area-mode", default="flat_punch", choices=["flat_punch", "growing_flat"])
    parser.add_argument("--flat-punch-diameter-mm", type=float, default=None)
    parser.add_argument("--run-calibration", action="store_true", help="Run transparent grid-search calibration.")
    parser.add_argument("--skip-report", action="store_true", help="Skip automated HTML/PNG report generation.")
    args = parser.parse_args()

    result = run_experimental_analysis(
        raw_af_data_dir=args.raw_af_data_dir,
        output_dir=args.output_dir,
        deform_dataset_csv=args.deform_dataset_csv,
        microstructure_targets_csv=args.microstructure_targets_csv,
        experimental_microstructure_path=args.experimental_microstructure_path,
        calibration_targets_csv=args.calibration_targets_csv,
        hit_glob=args.hit_glob,
        stock_diameter_mm=args.stock_diameter_mm,
        initial_height_mm=args.initial_height_mm,
        contact_area_mode=args.contact_area_mode,
        flat_punch_diameter_mm=args.flat_punch_diameter_mm,
        run_calibration=args.run_calibration,
        make_report=not args.skip_report,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
