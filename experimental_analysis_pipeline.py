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
import re
from pathlib import Path

import pandas as pd

from experimental_analysis.af_signal_processing import process_af_folder
from experimental_analysis.calibration import run_default_calibration
from experimental_analysis.fusion import add_target_errors, load_table
from experimental_analysis.local_pyjmak_workpiece import run_pyjmak_for_local_histories
from experimental_analysis.material_parameters import (
    material_context_from_folder,
    material_prior_path as get_material_prior_path,
    normalize_material_label,
    pyjmak_material_input_file as get_pyjmak_material_input_file,
    rex_parameters_for_material,
    try_parse_af_dataset_folder,
)
from experimental_analysis.microstructure_import import write_microstructure_import_outputs
from experimental_analysis.microstructure_targets import load_targets_csv
from experimental_analysis.pyjmak_adapter import run_pyjmak_from_curve_folder
from experimental_analysis.recrystallization import analyze_curve_folder
from experimental_analysis.rex_kinetics import (
    run_rex_kinetics_on_curve_folder,
    run_rex_kinetics_on_local_histories,
)
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
    "total_recrystallized_fraction",
    "updated_grain_um",
]


def infer_stock_diameter_mm_from_path(path: str | Path, fallback_mm: float = 15.875) -> float:
    """Infer stock diameter from a folder/file path.

    Recognized examples include `Box_1in`, `0.625in`, `5_8in`, and `5-8in`.
    If no diameter tag is found, the historical 5/8 inch fallback is used.
    """
    metadata = try_parse_af_dataset_folder(path)
    if metadata:
        return metadata.diameter_mm

    text = " ".join(Path(path).parts).lower()

    fraction_match = re.search(r"(?<!\d)(\d+)[_-](\d+)\s*in(?:ch|ches)?\b", text)
    if fraction_match:
        numerator = float(fraction_match.group(1))
        denominator = float(fraction_match.group(2))
        if denominator != 0:
            return numerator / denominator * 25.4

    decimal_match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*in(?:ch|ches)?\b", text)
    if decimal_match:
        return float(decimal_match.group(1)) * 25.4

    mm_match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*mm\b", text)
    if mm_match:
        return float(mm_match.group(1))

    return float(fallback_mm)


def run_experimental_analysis(
    raw_af_data_dir: str | Path,
    output_dir: str | Path,
    deform_dataset_csv: str | Path | None = None,
    microstructure_targets_csv: str | Path | None = None,
    experimental_microstructure_path: str | Path | None = None,
    calibration_targets_csv: str | Path | None = None,
    pyjmak_material_input_file: str | Path | None = None,
    pyjmak_source_path: str | Path | None = None,
    pyjmak_inter_hit_gap_s: float = 0.0,
    local_temperature_history_csv: str | Path | None = None,
    local_pyjmak_max_locations: int | None = None,
    run_rex_kinetics: bool = False,
    rex_interpass_time_s: float = 1.0,
    initial_grain_size_um: float = 26.3,
    material: str | None = None,
    use_material_defaults: bool = True,
    local_thermomechanical_history_csv: str | Path | None = None,
    hit_glob: str = "*.csv",
    stock_diameter_mm: float | None = None,
    initial_height_mm: float | None = None,
    contact_area_mode: str = "flat_punch",
    flat_punch_diameter_mm: float | None = None,
    run_calibration: bool = False,
    make_report: bool = True,
) -> dict[str, str]:
    """Run AF experimental processing and optional DEFORM/target fusion."""
    raw_af_data_dir = Path(raw_af_data_dir)
    dataset_metadata = try_parse_af_dataset_folder(raw_af_data_dir)
    inferred_material = dataset_metadata.material if dataset_metadata else None
    material = normalize_material_label(material or inferred_material)
    inferred_stock_diameter_mm = infer_stock_diameter_mm_from_path(raw_af_data_dir)
    stock_diameter_mm = float(stock_diameter_mm) if stock_diameter_mm is not None else inferred_stock_diameter_mm
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rex_params = None
    if use_material_defaults and material != "UNKNOWN":
        rex_params = rex_parameters_for_material(
            material=material,
            initial_grain_size_um=initial_grain_size_um,
            interpass_time_s=rex_interpass_time_s,
        )
        if str(pyjmak_material_input_file).lower() == "auto":
            pyjmak_material_input_file = str(get_pyjmak_material_input_file(material))

    config = PipelineConfig(
        raw_af_data_dir=raw_af_data_dir,
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

    rex_kinetics_csv = output_dir / "recrystallization_kinetics_summary.csv"
    rex_df = pd.DataFrame()
    if run_rex_kinetics:
        rex_df = run_rex_kinetics_on_curve_folder(
            curve_dir=curve_dir,
            output_csv=rex_kinetics_csv,
            initial_grain_size_um=initial_grain_size_um,
            interpass_time_s=rex_interpass_time_s,
            params=rex_params,
        )

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

    if not rex_df.empty and "hit" in combined.columns and "hit" in rex_df.columns:
        combined = combined.merge(
            rex_df,
            on="hit",
            how="left",
            suffixes=("", "_rex"),
        )
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
        "stock_diameter_mm": f"{stock_diameter_mm:.6g}",
        "stock_diameter_in": f"{stock_diameter_mm / 25.4:.6g}",
        "material": material,
    }
    if dataset_metadata:
        outputs["object_name"] = dataset_metadata.object_name
        outputs["dataset_folder_name"] = dataset_metadata.folder_name
    if use_material_defaults and material != "UNKNOWN":
        material_context = material_context_from_folder(
            raw_af_data_dir,
            initial_grain_size_um=initial_grain_size_um,
            interpass_time_s=rex_interpass_time_s,
        ) if dataset_metadata else {
            "material_prior_json": str(get_material_prior_path(material)),
            "pyjmak_material_input_file": str(get_pyjmak_material_input_file(material)),
        }
        outputs["material_prior_json"] = str(material_context["material_prior_json"])
        outputs["default_pyjmak_material_input_file"] = str(material_context["pyjmak_material_input_file"])
    if run_rex_kinetics:
        outputs["recrystallization_kinetics_summary"] = str(rex_kinetics_csv)

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

    if pyjmak_material_input_file:
        try:
            outputs.update(
                run_pyjmak_from_curve_folder(
                    curve_dir=curve_dir,
                    output_dir=output_dir,
                    material_input_file=pyjmak_material_input_file,
                    source_path=pyjmak_source_path,
                    inter_hit_gap_s=pyjmak_inter_hit_gap_s,
                )
            )
        except Exception as exc:
            outputs["pyjmak_warning"] = str(exc)

    if local_temperature_history_csv and pyjmak_material_input_file:
        try:
            outputs.update(
                run_pyjmak_for_local_histories(
                    local_temperature_csv=local_temperature_history_csv,
                    output_dir=output_dir / "local_pyjmak",
                    material_input_file=pyjmak_material_input_file,
                    source_path=pyjmak_source_path,
                    max_locations=local_pyjmak_max_locations,
                )
            )
        except Exception as exc:
            outputs["local_pyjmak_warning"] = str(exc)
    elif local_temperature_history_csv and not pyjmak_material_input_file:
        outputs["local_pyjmak_warning"] = "local_temperature_history_csv was provided, but pyjmak_material_input_file was not provided."

    if local_thermomechanical_history_csv:
        try:
            local_rex_csv = output_dir / "local_rex_kinetics_summary.csv"
            run_rex_kinetics_on_local_histories(
                local_history_csv=local_thermomechanical_history_csv,
                output_csv=local_rex_csv,
                initial_grain_size_um=initial_grain_size_um,
                interpass_time_s=rex_interpass_time_s,
                params=rex_params,
            )
            outputs["local_rex_kinetics_summary"] = str(local_rex_csv)
        except Exception as exc:
            outputs["local_rex_kinetics_warning"] = str(exc)

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
    parser.add_argument("--pyjmak-material-input-file", default=None, help="Optional Abaqus-style pyJMAK phase-transformation input file.")
    parser.add_argument("--pyjmak-source-path", default=None, help="Optional local ORNL/pyJMAK checkout path.")
    parser.add_argument("--pyjmak-inter-hit-gap-s", type=float, default=0.0, help="Optional time gap inserted between AF hits in pyJMAK temperature history.")
    parser.add_argument("--local-temperature-history-csv", default=None, help="Optional local/nodal workpiece thermal-history CSV for pointwise pyJMAK predictions.")
    parser.add_argument("--local-pyjmak-max-locations", type=int, default=None, help="Optional limit on local pyJMAK locations for testing large exports.")
    parser.add_argument("--run-rex-kinetics", action="store_true", help="Run mixed DRX/MDRX/SRX kinetics on processed AF stress-strain curves.")
    parser.add_argument("--rex-interpass-time-s", type=float, default=1.0, help="Time after each hit used for SRX/MDRX kinetics.")
    parser.add_argument("--initial-grain-size-um", type=float, default=26.3, help="Initial/supplier grain size for mixed REX kinetics.")
    parser.add_argument("--material", default=None, help="Optional material override, e.g. 316L or 4140. If omitted, inferred from folder name.")
    parser.add_argument("--no-material-defaults", action="store_true", help="Do not auto-select material-specific REX or pyJMAK defaults.")
    parser.add_argument("--local-thermomechanical-history-csv", default=None, help="Optional local/nodal CSV with temperature and strain history for local DRX/MDRX/SRX predictions.")
    parser.add_argument("--hit-glob", default="*.csv", help="Glob pattern for AF hit files.")
    parser.add_argument(
        "--stock-diameter-mm",
        type=float,
        default=None,
        help="Optional stock diameter override. If omitted, inferred from the raw data folder name, then falls back to 15.875 mm.",
    )
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
        pyjmak_material_input_file=args.pyjmak_material_input_file,
        pyjmak_source_path=args.pyjmak_source_path,
        pyjmak_inter_hit_gap_s=args.pyjmak_inter_hit_gap_s,
        local_temperature_history_csv=args.local_temperature_history_csv,
        local_pyjmak_max_locations=args.local_pyjmak_max_locations,
        run_rex_kinetics=args.run_rex_kinetics,
        rex_interpass_time_s=args.rex_interpass_time_s,
        initial_grain_size_um=args.initial_grain_size_um,
        material=args.material,
        use_material_defaults=not args.no_material_defaults,
        local_thermomechanical_history_csv=args.local_thermomechanical_history_csv,
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
