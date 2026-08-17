"""
Analyze microstructure evolution for all AF datasets.

This is the microstructure companion to `analyze_all_temperature_histories.py`.
It discovers AF folders named `{object_name}_{diameter}in_{material}`, ensures
the required stress-strain curves and induction temperature histories exist,
then runs material-specific DRX/SRX/MDRX microstructure evolution.

Per-dataset outputs are written under:

    <dataset>/experimental_analysis_output/microstructure_evolution_batch

Batch summaries are written under:

    <AF Data>/microstructure_batch_summary
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from analyze_all_temperature_histories import discover_af_dataset_folders
from experimental_analysis.induction_heating import (
    InductionHeatingConfig,
    run_induction_heating_analysis,
)
from experimental_analysis.material_parameters import (
    parse_af_dataset_folder,
    rex_parameters_for_material,
)
from experimental_analysis.microstructure_evolution import (
    MicrostructureEvolutionConfig,
    calibrate_srx_grain_prefactor_to_final_size,
    run_microstructure_evolution,
)
from experimental_analysis_pipeline import run_experimental_analysis


DEFAULT_AF_DATA_ROOT = r"C:\Users\nbian\Desktop\OSU Research\AF Data"
DEFAULT_SUMMARY_FOLDER = "microstructure_batch_summary"
DEFAULT_INITIAL_GRAIN_SIZE_UM = {
    "316L": 26.3,
    "4140": 26.3,
}
DEFAULT_FINAL_GRAIN_TARGET_UM = {
    "Box_1in_316L": 33.0,
}

PLOT_WIDTH = 1500
PLOT_HEIGHT = 900
MARGIN_LEFT = 100
MARGIN_RIGHT = 340
MARGIN_TOP = 90
MARGIN_BOTTOM = 100
COLORS = [
    (43, 109, 180),
    (42, 150, 105),
    (213, 107, 43),
    (126, 87, 194),
    (184, 65, 65),
    (20, 132, 143),
]


def load_font(size: int) -> ImageFont.ImageFont:
    """Load a common Windows font, falling back to Pillow default."""
    for font in ["segoeui.ttf", "arial.ttf", "calibri.ttf"]:
        try:
            return ImageFont.truetype(font, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def finite_bounds(values: list[float] | np.ndarray, pad_fraction: float = 0.08) -> tuple[float, float]:
    """Return padded finite bounds."""
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if len(array) == 0:
        return 0.0, 1.0
    low = float(array.min())
    high = float(array.max())
    if low == high:
        return low - 1.0, high + 1.0
    pad = (high - low) * pad_fraction
    return low - pad, high + pad


def scale_xy(
    x_value: float,
    y_value: float,
    x_bounds: tuple[float, float],
    y_bounds: tuple[float, float],
) -> tuple[int, int]:
    """Map data coordinates to image pixels."""
    left = MARGIN_LEFT
    right = PLOT_WIDTH - MARGIN_RIGHT
    top = MARGIN_TOP
    bottom = PLOT_HEIGHT - MARGIN_BOTTOM
    x_pixel = left + (x_value - x_bounds[0]) / max(x_bounds[1] - x_bounds[0], 1e-9) * (right - left)
    y_pixel = bottom - (y_value - y_bounds[0]) / max(y_bounds[1] - y_bounds[0], 1e-9) * (bottom - top)
    return int(round(x_pixel)), int(round(y_pixel))


def initial_grain_for_material(material: str, override_um: float | None = None) -> float:
    """Return the configured initial grain size for a material."""
    if override_um is not None:
        return float(override_um)
    return float(DEFAULT_INITIAL_GRAIN_SIZE_UM.get(str(material).upper(), 26.3))


def ensure_stress_strain_curves(
    dataset_dir: Path,
    output_dir: Path,
    initial_grain_size_um: float,
) -> Path:
    """Create stress-strain curves if they do not already exist."""
    curve_dir = output_dir / "stress_strain_curves"
    existing_curves = list(curve_dir.glob("*_stress_strain.csv")) if curve_dir.exists() else []
    if existing_curves:
        return curve_dir

    run_experimental_analysis(
        raw_af_data_dir=dataset_dir,
        output_dir=output_dir,
        run_rex_kinetics=False,
        initial_grain_size_um=initial_grain_size_um,
        make_report=False,
    )
    existing_curves = list(curve_dir.glob("*_stress_strain.csv")) if curve_dir.exists() else []
    if not existing_curves:
        raise FileNotFoundError(f"No stress-strain curves were generated for {dataset_dir}.")
    return curve_dir


def ensure_induction_history(dataset_dir: Path, output_dir: Path) -> Path:
    """Create induction temperature history if it does not already exist."""
    induction_dir = output_dir / "induction_heating"
    trace_csv = induction_dir / "induction_heating_temperature_time_trace.csv"
    if trace_csv.exists():
        return trace_csv

    run_induction_heating_analysis(
        raw_af_data_dir=dataset_dir,
        output_dir=induction_dir,
        config=InductionHeatingConfig(),
    )
    if not trace_csv.exists():
        raise FileNotFoundError(f"No induction temperature history was generated for {dataset_dir}.")
    return trace_csv


def save_grain_evolution_overlay(evolution_table: pd.DataFrame, output_png: str | Path) -> Path:
    """Save grain-size evolution overlay for all datasets."""
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (PLOT_WIDTH, PLOT_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(32)
    label_font = load_font(18)
    tick_font = load_font(14)
    small_font = load_font(13)

    draw.text((MARGIN_LEFT, 32), "AF Microstructure Evolution", fill=(31, 41, 55), font=title_font)
    draw.text((PLOT_WIDTH // 2 - 90, PLOT_HEIGHT - 52), "Modeled time s", fill=(31, 41, 55), font=label_font)
    draw.text((20, PLOT_HEIGHT // 2 - 28), "Grain size um", fill=(31, 41, 55), font=label_font)

    x_all = pd.to_numeric(evolution_table["time_s"], errors="coerce").to_numpy(dtype=float)
    y_all = pd.to_numeric(evolution_table["grain_size_um"], errors="coerce").to_numpy(dtype=float)
    x_bounds = finite_bounds(x_all, pad_fraction=0.03)
    x_bounds = (max(0.0, x_bounds[0]), x_bounds[1])
    y_bounds = finite_bounds(y_all, pad_fraction=0.12)

    left = MARGIN_LEFT
    right = PLOT_WIDTH - MARGIN_RIGHT
    top = MARGIN_TOP
    bottom = PLOT_HEIGHT - MARGIN_BOTTOM
    for step in range(6):
        fraction = step / 5.0
        gx = int(left + fraction * (right - left))
        gy = int(bottom - fraction * (bottom - top))
        x_tick = x_bounds[0] + fraction * (x_bounds[1] - x_bounds[0])
        y_tick = y_bounds[0] + fraction * (y_bounds[1] - y_bounds[0])
        draw.line((gx, top, gx, bottom), fill=(224, 231, 241))
        draw.line((left, gy, right, gy), fill=(224, 231, 241))
        draw.text((gx - 22, bottom + 12), f"{x_tick:.0f}", fill=(107, 114, 128), font=tick_font)
        draw.text((left - 78, gy - 8), f"{y_tick:.1f}", fill=(107, 114, 128), font=tick_font)
    draw.rectangle((left, top, right, bottom), outline=(156, 163, 175), width=2)

    legend_x = right + 24
    legend_y = top + 10
    draw.rectangle((legend_x - 14, legend_y - 12, PLOT_WIDTH - 24, legend_y + 230), fill="white", outline=(203, 213, 225))
    draw.text((legend_x, legend_y), "Datasets", fill=(31, 41, 55), font=label_font)

    for index, (dataset, group) in enumerate(evolution_table.groupby("dataset_name", sort=True)):
        color = COLORS[index % len(COLORS)]
        group = group.sort_values("time_s")
        x = pd.to_numeric(group["time_s"], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(group["grain_size_um"], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        points = [scale_xy(float(xi), float(yi), x_bounds, y_bounds) for xi, yi in zip(x[valid], y[valid])]
        if len(points) > 1:
            draw.line(points, fill=color, width=3)
        for px, py in points[:: max(1, len(points) // 30)]:
            draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=color, outline="white", width=1)

        final_grain = float(pd.to_numeric(group["grain_size_um"], errors="coerce").dropna().iloc[-1])
        y0 = legend_y + 40 + index * 32
        draw.line((legend_x, y0 + 8, legend_x + 28, y0 + 8), fill=color, width=4)
        draw.text((legend_x + 38, y0), f"{dataset[:24]}  final {final_grain:.1f} um", fill=(31, 41, 55), font=small_font)

    image.save(output_png)
    return output_png


def analyze_microstructure_histories(
    af_data_root: str | Path = DEFAULT_AF_DATA_ROOT,
    summary_dir: str | Path | None = None,
    initial_grain_size_um: float | None = None,
    apply_srx_during_quench: bool = False,
    use_default_final_grain_targets: bool = True,
) -> dict[str, str]:
    """Run microstructure evolution for every valid AF dataset."""
    af_data_root = Path(af_data_root)
    summary_dir = Path(summary_dir) if summary_dir else af_data_root / DEFAULT_SUMMARY_FOLDER
    summary_dir.mkdir(parents=True, exist_ok=True)

    dataset_rows = []
    all_evolution_rows = []
    errors = []

    for dataset_dir in discover_af_dataset_folders(af_data_root):
        metadata = parse_af_dataset_folder(dataset_dir)
        output_dir = dataset_dir / "experimental_analysis_output"
        grain0 = initial_grain_for_material(metadata.material, override_um=initial_grain_size_um)
        try:
            curve_dir = ensure_stress_strain_curves(dataset_dir, output_dir, initial_grain_size_um=grain0)
            temperature_trace_csv = ensure_induction_history(dataset_dir, output_dir)
            microstructure_dir = output_dir / "microstructure_evolution_batch"
            params = rex_parameters_for_material(
                metadata.material,
                initial_grain_size_um=grain0,
            )
            config = MicrostructureEvolutionConfig(
                initial_grain_size_um=grain0,
                apply_srx_during_quench=apply_srx_during_quench,
            )
            target_final_grain_size_um = (
                DEFAULT_FINAL_GRAIN_TARGET_UM.get(dataset_dir.name)
                if use_default_final_grain_targets
                else None
            )
            if target_final_grain_size_um:
                outputs = calibrate_srx_grain_prefactor_to_final_size(
                    curve_dir=curve_dir,
                    temperature_time_trace_csv=temperature_trace_csv,
                    output_dir=microstructure_dir,
                    target_final_grain_size_um=target_final_grain_size_um,
                    config=config,
                    params=params,
                )
            else:
                outputs = run_microstructure_evolution(
                    curve_dir=curve_dir,
                    temperature_time_trace_csv=temperature_trace_csv,
                    output_dir=microstructure_dir,
                    config=config,
                    params=params,
                )
            evolution = pd.read_csv(outputs["microstructure_evolution_csv"])
            evolution["dataset_name"] = dataset_dir.name
            evolution["object_name"] = metadata.object_name
            evolution["material"] = metadata.material
            evolution["diameter_in"] = metadata.diameter_in
            all_evolution_rows.append(evolution)

            grain = pd.to_numeric(evolution["grain_size_um"], errors="coerce")
            rex = pd.to_numeric(evolution["recrystallized_fraction"], errors="coerce")
            dataset_rows.append(
                {
                    "dataset_name": dataset_dir.name,
                    "object_name": metadata.object_name,
                    "material": metadata.material,
                    "diameter_in": metadata.diameter_in,
                    "diameter_mm": metadata.diameter_mm,
                    "raw_af_data_dir": str(dataset_dir),
                    "initial_grain_size_um": grain0,
                    "event_rows": int(len(evolution)),
                    "hit_count": int(evolution[evolution["event_type"].astype(str) == "hit_drx"]["hit"].nunique()),
                    "final_grain_size_um": float(grain.dropna().iloc[-1]),
                    "final_recrystallized_fraction": float(rex.dropna().iloc[-1]),
                    "min_grain_size_um": float(grain.min()),
                    "max_grain_size_um": float(grain.max()),
                    "max_recrystallized_fraction": float(rex.max()),
                    "rex_parameter_preset": params.preset_name,
                    "target_final_grain_size_um": target_final_grain_size_um if target_final_grain_size_um else "",
                    "calibrated_parameter": "srx.srx_grain_prefactor" if target_final_grain_size_um else "",
                    "srx_grain_prefactor_scale": outputs.get("srx_grain_prefactor_scale", ""),
                    "calibrated_srx_grain_prefactor": outputs.get("calibrated_srx_grain_prefactor", ""),
                    "calibration_summary": outputs.get("calibration_summary", ""),
                    "microstructure_evolution_csv": outputs["microstructure_evolution_csv"],
                    "microstructure_evolution_plot": outputs["microstructure_evolution_plot"],
                    "microstructure_parameters_json": outputs["microstructure_evolution_parameters"],
                    "temperature_trace_csv": str(temperature_trace_csv),
                    "curve_dir": str(curve_dir),
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "dataset_name": dataset_dir.name,
                    "raw_af_data_dir": str(dataset_dir),
                    "error": str(exc),
                }
            )

    dataset_summary = pd.DataFrame(dataset_rows)
    all_evolution = pd.concat(all_evolution_rows, ignore_index=True) if all_evolution_rows else pd.DataFrame()
    errors_df = pd.DataFrame(errors)

    dataset_summary_csv = summary_dir / "all_microstructure_summary.csv"
    all_evolution_csv = summary_dir / "all_microstructure_evolution.csv"
    errors_csv = summary_dir / "microstructure_analysis_errors.csv"
    grain_plot_png = summary_dir / "all_grain_size_evolution.png"
    summary_json = summary_dir / "microstructure_batch_summary.json"

    dataset_summary.to_csv(dataset_summary_csv, index=False)
    all_evolution.to_csv(all_evolution_csv, index=False)
    errors_df.to_csv(errors_csv, index=False)
    if not all_evolution.empty:
        save_grain_evolution_overlay(all_evolution, grain_plot_png)

    outputs = {
        "af_data_root": str(af_data_root),
        "summary_dir": str(summary_dir),
        "dataset_count": str(len(dataset_summary)),
        "error_count": str(len(errors_df)),
        "all_microstructure_summary": str(dataset_summary_csv),
        "all_microstructure_evolution": str(all_evolution_csv),
        "microstructure_analysis_errors": str(errors_csv),
        "all_grain_size_evolution_plot": str(grain_plot_png) if grain_plot_png.exists() else "",
    }
    summary_json.write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    outputs["summary_json"] = str(summary_json)
    return outputs


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Analyze microstructure evolution for all AF datasets.")
    parser.add_argument("--af-data-root", default=DEFAULT_AF_DATA_ROOT)
    parser.add_argument("--summary-dir", default=None)
    parser.add_argument("--initial-grain-size-um", type=float, default=None)
    parser.add_argument("--apply-srx-during-quench", action="store_true")
    parser.add_argument("--no-default-final-grain-targets", action="store_true")
    args = parser.parse_args()

    outputs = analyze_microstructure_histories(
        af_data_root=args.af_data_root,
        summary_dir=args.summary_dir,
        initial_grain_size_um=args.initial_grain_size_um,
        apply_srx_during_quench=args.apply_srx_during_quench,
        use_default_final_grain_targets=not args.no_default_final_grain_targets,
    )
    print(json.dumps(outputs, indent=2))


if __name__ == "__main__":
    main()
