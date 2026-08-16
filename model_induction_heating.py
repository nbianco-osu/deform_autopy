"""
Convenience wrapper for AF induction-heating analysis.

Use this from Spyder or the command line when you want to infer when induction
heats/reheats occurred from Agility Forge hit temperatures.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from experimental_analysis.induction_heating import (
    InductionHeatingConfig,
    run_induction_heating_analysis,
)


DEFAULT_RAW_AF_DATA_DIR = r"C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in"
DEFAULT_OUTPUT_DIR = r"C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in\experimental_analysis_output\induction_heating"


def run_default_box_analysis() -> dict[str, str]:
    """Run the default Box_1in induction-heating analysis."""
    return run_induction_heating_analysis(
        raw_af_data_dir=DEFAULT_RAW_AF_DATA_DIR,
        output_dir=DEFAULT_OUTPUT_DIR,
        config=InductionHeatingConfig(
            lower_temp_c=800.0,
            upper_temp_c=1200.0,
            room_temp_c=25.0,
            reheat_delta_c=25.0,
            target_reheat_temp_c=1100.0,
            hit_interval_s=1.0,
            inferred_heat_duration_s=0.35,
            infer_initial_heat_from_reheats=True,
            quench_after_hits=True,
            quench_duration_s=2.0,
        ),
    )


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Run AF induction-heating inference.")
    parser.add_argument("--raw-af-data-dir", default=DEFAULT_RAW_AF_DATA_DIR)
    parser.add_argument("--summary-csv", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--lower-temp-c", type=float, default=800.0)
    parser.add_argument("--upper-temp-c", type=float, default=1200.0)
    parser.add_argument("--room-temp-c", type=float, default=25.0)
    parser.add_argument("--reheat-delta-c", type=float, default=25.0)
    parser.add_argument("--target-reheat-temp-c", type=float, default=1100.0)
    parser.add_argument("--heating-rate-c-per-s", type=float, default=None)
    parser.add_argument("--hit-interval-s", type=float, default=1.0)
    parser.add_argument("--inferred-heat-duration-s", type=float, default=0.35)
    parser.add_argument("--no-infer-initial-heat-from-reheats", action="store_true")
    parser.add_argument("--no-quench-after-hits", action="store_true")
    parser.add_argument("--quench-duration-s", type=float, default=2.0)
    parser.add_argument("--quench-rate-c-per-s", type=float, default=None)
    args = parser.parse_args()

    result = run_induction_heating_analysis(
        raw_af_data_dir=args.raw_af_data_dir if not args.summary_csv else None,
        summary_csv=args.summary_csv,
        output_dir=Path(args.output_dir),
        config=InductionHeatingConfig(
            lower_temp_c=args.lower_temp_c,
            upper_temp_c=args.upper_temp_c,
            room_temp_c=args.room_temp_c,
            reheat_delta_c=args.reheat_delta_c,
            target_reheat_temp_c=args.target_reheat_temp_c,
            heating_rate_c_per_s=args.heating_rate_c_per_s,
            hit_interval_s=args.hit_interval_s,
            inferred_heat_duration_s=args.inferred_heat_duration_s,
            infer_initial_heat_from_reheats=not args.no_infer_initial_heat_from_reheats,
            quench_after_hits=not args.no_quench_after_hits,
            quench_duration_s=args.quench_duration_s,
            quench_rate_c_per_s=args.quench_rate_c_per_s,
        ),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
