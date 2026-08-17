"""
Analyze all AF datasets and generate temperature histories.

The expected raw-data folder convention is:

    {object_name}_{diameter}in_{material}

Examples:

    Box_1in_316L
    Box_1in_4140
    Cone_1in_4140
    Cylinder_1in_4140

For each valid folder, this script runs the induction-heating temperature
history workflow and writes outputs under:

    <dataset>/experimental_analysis_output/induction_heating

It also writes a cross-dataset summary and comparison plot under:

    <AF Data>/temperature_history_batch_summary
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from experimental_analysis.induction_heating import (
    InductionHeatingConfig,
    run_induction_heating_analysis,
)
from experimental_analysis.material_parameters import (
    parse_af_dataset_folder,
    try_parse_af_dataset_folder,
)


DEFAULT_AF_DATA_ROOT = r"C:\Users\nbian\Desktop\OSU Research\AF Data"
DEFAULT_SUMMARY_FOLDER = "temperature_history_batch_summary"

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
    """Load a common Windows font, falling back to Pillow's default."""
    for font in ["segoeui.ttf", "arial.ttf", "calibri.ttf"]:
        try:
            return ImageFont.truetype(font, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def discover_af_dataset_folders(root: str | Path) -> list[Path]:
    """Return folders that match the AF dataset naming convention."""
    root = Path(root)
    folders = []
    for folder in sorted(root.iterdir()):
        if folder.is_dir() and try_parse_af_dataset_folder(folder) is not None:
            folders.append(folder)
    return folders


def finite_bounds(values: list[float] | np.ndarray, pad_fraction: float = 0.08) -> tuple[float, float]:
    """Return padded numeric bounds for plotting."""
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


def save_contact_temperature_overlay(
    per_hit_table: pd.DataFrame,
    output_png: str | Path,
    lower_temp_c: float,
    upper_temp_c: float,
) -> Path:
    """Save an overlay of contact temperature versus hit order for all datasets."""
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (PLOT_WIDTH, PLOT_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(32)
    label_font = load_font(18)
    tick_font = load_font(14)
    small_font = load_font(13)

    draw.text((MARGIN_LEFT, 32), "AF Contact Temperature Histories", fill=(31, 41, 55), font=title_font)
    draw.text((PLOT_WIDTH // 2 - 80, PLOT_HEIGHT - 52), "Hit order", fill=(31, 41, 55), font=label_font)
    draw.text((22, PLOT_HEIGHT // 2 - 18), "Temp C", fill=(31, 41, 55), font=label_font)

    x_values = pd.to_numeric(per_hit_table["hit_order"], errors="coerce").to_numpy(dtype=float)
    y_values = pd.to_numeric(per_hit_table["hit_temperature_c"], errors="coerce").to_numpy(dtype=float)
    x_bounds = (-0.5, max(1.0, float(np.nanmax(x_values)) + 0.5))
    y_bounds = finite_bounds(np.concatenate([y_values, np.asarray([lower_temp_c, upper_temp_c], dtype=float)]), pad_fraction=0.12)

    left = MARGIN_LEFT
    right = PLOT_WIDTH - MARGIN_RIGHT
    top = MARGIN_TOP
    bottom = PLOT_HEIGHT - MARGIN_BOTTOM

    window_top = scale_xy(0, upper_temp_c, x_bounds, y_bounds)[1]
    window_bottom = scale_xy(0, lower_temp_c, x_bounds, y_bounds)[1]
    draw.rectangle((left, window_top, right, window_bottom), fill=(223, 244, 232))
    draw.text((left + 14, window_top + 10), f"Process window {lower_temp_c:g}-{upper_temp_c:g} C", fill=(35, 118, 76), font=small_font)

    for step in range(6):
        fraction = step / 5.0
        gx = int(left + fraction * (right - left))
        gy = int(bottom - fraction * (bottom - top))
        x_tick = x_bounds[0] + fraction * (x_bounds[1] - x_bounds[0])
        y_tick = y_bounds[0] + fraction * (y_bounds[1] - y_bounds[0])
        draw.line((gx, top, gx, bottom), fill=(224, 231, 241))
        draw.line((left, gy, right, gy), fill=(224, 231, 241))
        draw.text((gx - 16, bottom + 12), f"{x_tick:.0f}", fill=(107, 114, 128), font=tick_font)
        draw.text((left - 72, gy - 8), f"{y_tick:.0f}", fill=(107, 114, 128), font=tick_font)
    draw.rectangle((left, top, right, bottom), outline=(156, 163, 175), width=2)

    legend_x = right + 24
    legend_y = top + 10
    draw.rectangle((legend_x - 14, legend_y - 12, PLOT_WIDTH - 24, legend_y + 220), fill="white", outline=(203, 213, 225))
    draw.text((legend_x, legend_y), "Datasets", fill=(31, 41, 55), font=label_font)

    for index, (dataset, group) in enumerate(per_hit_table.groupby("dataset_name", sort=True)):
        color = COLORS[index % len(COLORS)]
        group = group.sort_values("hit_order")
        points = [
            scale_xy(float(row["hit_order"]), float(row["hit_temperature_c"]), x_bounds, y_bounds)
            for _, row in group.iterrows()
        ]
        if len(points) > 1:
            draw.line(points, fill=color, width=3)
        for px, py in points:
            draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=color, outline="white", width=1)

        y0 = legend_y + 38 + index * 27
        draw.line((legend_x, y0 + 8, legend_x + 28, y0 + 8), fill=color, width=4)
        draw.text((legend_x + 38, y0), str(dataset)[:30], fill=(31, 41, 55), font=small_font)

    image.save(output_png)
    return output_png


def analyze_temperature_histories(
    af_data_root: str | Path = DEFAULT_AF_DATA_ROOT,
    summary_dir: str | Path | None = None,
    lower_temp_c: float = 800.0,
    upper_temp_c: float = 1200.0,
    reheat_delta_c: float = 25.0,
    target_reheat_temp_c: float = 1100.0,
    room_temp_c: float = 25.0,
    quench_after_hits: bool = True,
    quench_duration_s: float = 2.0,
    hit_glob: str = "*.csv",
) -> dict[str, str]:
    """Run induction temperature-history analysis for every valid AF dataset."""
    af_data_root = Path(af_data_root)
    summary_dir = Path(summary_dir) if summary_dir else af_data_root / DEFAULT_SUMMARY_FOLDER
    summary_dir.mkdir(parents=True, exist_ok=True)
    config = InductionHeatingConfig(
        lower_temp_c=lower_temp_c,
        upper_temp_c=upper_temp_c,
        room_temp_c=room_temp_c,
        reheat_delta_c=reheat_delta_c,
        target_reheat_temp_c=target_reheat_temp_c,
        infer_initial_heat_from_reheats=True,
        quench_after_hits=quench_after_hits,
        quench_duration_s=quench_duration_s,
    )

    dataset_rows = []
    all_hit_rows = []
    all_event_rows = []
    errors = []

    for dataset_dir in discover_af_dataset_folders(af_data_root):
        metadata = parse_af_dataset_folder(dataset_dir)
        output_dir = dataset_dir / "experimental_analysis_output" / "induction_heating"
        try:
            outputs = run_induction_heating_analysis(
                raw_af_data_dir=dataset_dir,
                output_dir=output_dir,
                hit_glob=hit_glob,
                config=config,
            )
            hits = pd.read_csv(outputs["induction_heating_hit_temperatures"])
            events = pd.read_csv(outputs["induction_heating_events"])
            timeline = pd.read_csv(outputs["induction_heating_temperature_time_trace"])

            hits["dataset_name"] = dataset_dir.name
            hits["object_name"] = metadata.object_name
            hits["material"] = metadata.material
            hits["diameter_in"] = metadata.diameter_in
            all_hit_rows.append(hits)

            events["dataset_name"] = dataset_dir.name
            events["object_name"] = metadata.object_name
            events["material"] = metadata.material
            events["diameter_in"] = metadata.diameter_in
            all_event_rows.append(events)

            temp = pd.to_numeric(hits["hit_temperature_c"], errors="coerce")
            timeline_time = pd.to_numeric(timeline["time_s"], errors="coerce")
            dataset_rows.append(
                {
                    "dataset_name": dataset_dir.name,
                    "object_name": metadata.object_name,
                    "material": metadata.material,
                    "diameter_in": metadata.diameter_in,
                    "diameter_mm": metadata.diameter_mm,
                    "raw_af_data_dir": str(dataset_dir),
                    "induction_output_dir": str(output_dir),
                    "hit_count": int(len(hits)),
                    "temperature_min_c": float(temp.min()),
                    "temperature_mean_c": float(temp.mean()),
                    "temperature_max_c": float(temp.max()),
                    "outside_window_hit_count": int((hits["below_process_window"] | hits["above_process_window"]).sum()),
                    "inferred_heat_event_count": int(events["event_type"].isin(["initial_heat", "reheat"]).sum()),
                    "modeled_timeline_duration_s": float(timeline_time.max()) if timeline_time.notna().any() else float("nan"),
                    "temperature_history_csv": outputs["induction_heating_temperature_time_trace"],
                    "contact_temperature_csv": outputs["induction_heating_hit_temperatures"],
                    "events_csv": outputs["induction_heating_events"],
                    "temperature_vs_time_plot": outputs["induction_heating_temperature_vs_time_plot"],
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
    all_hits = pd.concat(all_hit_rows, ignore_index=True) if all_hit_rows else pd.DataFrame()
    all_events = pd.concat(all_event_rows, ignore_index=True) if all_event_rows else pd.DataFrame()
    errors_df = pd.DataFrame(errors)

    dataset_summary_csv = summary_dir / "all_temperature_history_summary.csv"
    all_hits_csv = summary_dir / "all_contact_temperature_histories.csv"
    all_events_csv = summary_dir / "all_induction_events.csv"
    errors_csv = summary_dir / "temperature_history_errors.csv"
    comparison_png = summary_dir / "all_contact_temperature_histories.png"
    summary_json = summary_dir / "temperature_history_batch_summary.json"

    dataset_summary.to_csv(dataset_summary_csv, index=False)
    all_hits.to_csv(all_hits_csv, index=False)
    all_events.to_csv(all_events_csv, index=False)
    errors_df.to_csv(errors_csv, index=False)
    if not all_hits.empty:
        save_contact_temperature_overlay(all_hits, comparison_png, lower_temp_c, upper_temp_c)

    outputs = {
        "af_data_root": str(af_data_root),
        "summary_dir": str(summary_dir),
        "dataset_count": str(len(dataset_summary)),
        "error_count": str(len(errors_df)),
        "all_temperature_history_summary": str(dataset_summary_csv),
        "all_contact_temperature_histories": str(all_hits_csv),
        "all_induction_events": str(all_events_csv),
        "temperature_history_errors": str(errors_csv),
        "all_contact_temperature_plot": str(comparison_png) if comparison_png.exists() else "",
    }
    summary_json.write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    outputs["summary_json"] = str(summary_json)
    return outputs


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Analyze all AF data folders and generate temperature histories.")
    parser.add_argument("--af-data-root", default=DEFAULT_AF_DATA_ROOT)
    parser.add_argument("--summary-dir", default=None)
    parser.add_argument("--lower-temp-c", type=float, default=800.0)
    parser.add_argument("--upper-temp-c", type=float, default=1200.0)
    parser.add_argument("--reheat-delta-c", type=float, default=25.0)
    parser.add_argument("--target-reheat-temp-c", type=float, default=1100.0)
    parser.add_argument("--room-temp-c", type=float, default=25.0)
    parser.add_argument("--quench-duration-s", type=float, default=2.0)
    parser.add_argument("--no-quench-after-hits", action="store_true")
    parser.add_argument("--hit-glob", default="*.csv")
    args = parser.parse_args()

    outputs = analyze_temperature_histories(
        af_data_root=args.af_data_root,
        summary_dir=args.summary_dir,
        lower_temp_c=args.lower_temp_c,
        upper_temp_c=args.upper_temp_c,
        reheat_delta_c=args.reheat_delta_c,
        target_reheat_temp_c=args.target_reheat_temp_c,
        room_temp_c=args.room_temp_c,
        quench_after_hits=not args.no_quench_after_hits,
        quench_duration_s=args.quench_duration_s,
        hit_glob=args.hit_glob,
    )
    print(json.dumps(outputs, indent=2))


if __name__ == "__main__":
    main()
