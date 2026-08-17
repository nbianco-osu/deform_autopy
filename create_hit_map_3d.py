"""
Create a 3D hit map for the Box_1in Agility Forge data.

Run this file from Spyder or command line after `experimental_analysis_output`
has been generated. The output folder will contain a CSV of mapped hit points,
a PNG figure, and an interactive HTML canvas.
"""

from __future__ import annotations

import argparse
import json

from experimental_analysis.hit_map_3d import (
    DEFAULT_ANALYSIS_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RAW_AF_DIR,
    build_hit_map_3d,
)


def run_default_box_hit_map() -> dict[str, str]:
    """Create the default Box_1in 3D hit map."""
    return build_hit_map_3d(
        raw_af_dir=DEFAULT_RAW_AF_DIR,
        analysis_dir=DEFAULT_ANALYSIS_DIR,
        output_dir=DEFAULT_OUTPUT_DIR,
        stock_diameter_mm=25.4,
        extra_bar_behind_start_mm=30.0,
    )


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Create a 3D AF hit map.")
    parser.add_argument("--raw-af-dir", default=DEFAULT_RAW_AF_DIR)
    parser.add_argument("--analysis-dir", default=DEFAULT_ANALYSIS_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stock-diameter-mm", type=float, default=25.4)
    parser.add_argument("--extra-bar-behind-start-mm", type=float, default=30.0)
    args = parser.parse_args()

    outputs = build_hit_map_3d(
        raw_af_dir=args.raw_af_dir,
        analysis_dir=args.analysis_dir,
        output_dir=args.output_dir,
        stock_diameter_mm=args.stock_diameter_mm,
        extra_bar_behind_start_mm=args.extra_bar_behind_start_mm,
    )
    print(json.dumps(outputs, indent=2))


if __name__ == "__main__":
    main()
