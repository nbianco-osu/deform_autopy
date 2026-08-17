"""
Convenience wrapper for AF microstructure-evolution modeling.

This script expects the induction-heating workflow and experimental-analysis
workflow to have already generated:

- stress_strain_curves/*_stress_strain.csv
- induction_heating/induction_heating_temperature_time_trace.csv
"""

from __future__ import annotations

import argparse
import json

from experimental_analysis.microstructure_evolution import (
    MicrostructureEvolutionConfig,
    calibrate_srx_grain_prefactor_to_final_size,
    run_microstructure_evolution,
)
from experimental_analysis.material_parameters import normalize_material_label, rex_parameters_for_material


DEFAULT_ANALYSIS_DIR = r"C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in_316L\experimental_analysis_output"
DEFAULT_CURVE_DIR = DEFAULT_ANALYSIS_DIR + r"\stress_strain_curves"
DEFAULT_TEMPERATURE_TRACE_CSV = DEFAULT_ANALYSIS_DIR + r"\induction_heating\induction_heating_temperature_time_trace.csv"
DEFAULT_OUTPUT_DIR = DEFAULT_ANALYSIS_DIR + r"\microstructure_evolution"


def run_default_box_microstructure_evolution() -> dict[str, str]:
    """Run the default Box_1in microstructure evolution model."""
    return run_microstructure_evolution(
        curve_dir=DEFAULT_CURVE_DIR,
        temperature_time_trace_csv=DEFAULT_TEMPERATURE_TRACE_CSV,
        output_dir=DEFAULT_OUTPUT_DIR,
        config=MicrostructureEvolutionConfig(initial_grain_size_um=26.3),
        params=rex_parameters_for_material("316L", initial_grain_size_um=26.3),
    )


def calibrate_default_box_to_final_grain_size(target_final_grain_size_um: float = 33.7) -> dict[str, str]:
    """Run the Box_1in model after fitting the SRX grain-size prefactor."""
    return calibrate_srx_grain_prefactor_to_final_size(
        curve_dir=DEFAULT_CURVE_DIR,
        temperature_time_trace_csv=DEFAULT_TEMPERATURE_TRACE_CSV,
        output_dir=DEFAULT_OUTPUT_DIR,
        target_final_grain_size_um=target_final_grain_size_um,
        config=MicrostructureEvolutionConfig(initial_grain_size_um=26.3),
        params=rex_parameters_for_material("316L", initial_grain_size_um=26.3),
    )


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Run AF microstructure evolution.")
    parser.add_argument("--curve-dir", default=DEFAULT_CURVE_DIR)
    parser.add_argument("--temperature-time-trace-csv", default=DEFAULT_TEMPERATURE_TRACE_CSV)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--initial-grain-size-um", type=float, default=26.3)
    parser.add_argument("--initial-recrystallized-fraction", type=float, default=0.0)
    parser.add_argument("--material", default="316L", help="Material parameter set to use: 316L or 4140.")
    parser.add_argument("--apply-srx-during-quench", action="store_true")
    parser.add_argument(
        "--target-final-grain-size-um",
        type=float,
        help="Fit the SRX grain-size prefactor so the final predicted average grain size matches this value.",
    )
    args = parser.parse_args()

    config = MicrostructureEvolutionConfig(
        initial_grain_size_um=args.initial_grain_size_um,
        initial_recrystallized_fraction=args.initial_recrystallized_fraction,
        apply_srx_during_quench=args.apply_srx_during_quench,
    )
    material = normalize_material_label(args.material)
    params = rex_parameters_for_material(
        material=material,
        initial_grain_size_um=args.initial_grain_size_um,
    )
    if args.target_final_grain_size_um:
        outputs = calibrate_srx_grain_prefactor_to_final_size(
            curve_dir=args.curve_dir,
            temperature_time_trace_csv=args.temperature_time_trace_csv,
            output_dir=args.output_dir,
            target_final_grain_size_um=args.target_final_grain_size_um,
            config=config,
            params=params,
        )
    else:
        outputs = run_microstructure_evolution(
            curve_dir=args.curve_dir,
            temperature_time_trace_csv=args.temperature_time_trace_csv,
            output_dir=args.output_dir,
            config=config,
            params=params,
        )
    print(json.dumps(outputs, indent=2))


if __name__ == "__main__":
    main()
