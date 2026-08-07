"""
Create demo DOE result plots for the DEFORM GUI.

This script builds a small synthetic DOE study that looks like a completed
DEFORM optimization run. It is intended for GUI testing, training, and SOP
screenshots when real DEFORM results are not available yet.

The generated files are written to:

    optimization/demo_gui_results/

After running this file, open the GUI Post/Reports tab, set Study root to the
demo folder above, click "Use Report Folder", then click "Refresh" or
"Show Selected Plot".
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from visualize_doe_results import visualize_doe_results


APP_DIR = Path(__file__).resolve().parent
DEMO_STUDY_ROOT = APP_DIR / "optimization" / "demo_gui_results"
PLOT_WIDTH = 1200
PLOT_HEIGHT = 720
PLOT_MARGIN = 92
COLOR_TEXT = (31, 41, 55)
COLOR_MUTED = (107, 114, 128)
COLOR_GRID = (220, 227, 235)
COLOR_BLUE = (47, 112, 183)
COLOR_GREEN = (28, 145, 98)
COLOR_ORANGE = (219, 121, 41)
COLOR_PURPLE = (124, 92, 183)


def synthetic_demo_dataset() -> pd.DataFrame:
    """Return synthetic completed-run metrics with realistic DOE column names."""
    rows = []
    depths = [0.045, 0.055, 0.065, 0.075, 0.085, 0.050, 0.070, 0.090]
    speeds = [0.35, 0.50, 0.65, 0.80, 0.95, 1.10, 1.25, 1.40]
    temps = [950, 975, 1000, 1025, 1050, 1075, 1100, 1125]

    for index, (depth, speed, temp) in enumerate(zip(depths, speeds, temps), start=1):
        # These values are synthetic, but shaped to resemble common trends:
        # deeper/faster hits raise damage, while hotter forging can reduce
        # objective penalties through more favorable flow and grain evolution.
        damage_max = 0.10 + 1.85 * depth + 0.018 * index + max(0.0, speed - 1.0) * 0.04
        grain_mean = 28.0 - 72.0 * depth + (temp - 1000.0) * 0.018 - 0.65 * speed
        grain_std = 3.2 + 0.45 * index + abs(temp - 1040.0) * 0.006
        initial_grain_mean = 34.5
        initial_grain_std = 4.8
        experimental_fit = abs(grain_mean - 28.0) / 4.0 + max(0.0, damage_max - 0.24) / 0.04
        objective = 1.7 * damage_max + 0.10 * grain_std + 0.35 * experimental_fit

        rows.append(
            {
                "record_id": f"demo_{index:03d}",
                "run_name": f"demo_run_{index:03d}",
                "status": "completed",
                "die_motion_mode": "single_top_die",
                "material": "4140_coarse_demo",
                "action_file": "demo_5hit_single_die.csv",
                "depth_in": depth,
                "speed_in/s": speed,
                "forging_temp_c": temp,
                "height": 0.625,
                "time_step": 0.005,
                "objective": objective,
                "damage_max": damage_max,
                "damage_min": 0.0,
                "grain_mean_um": grain_mean,
                "grain_std_um": grain_std,
                "grain_p50_um": grain_mean - 0.3,
                "initial_state_grain_mean_um": initial_grain_mean,
                "initial_state_grain_std_um": initial_grain_std,
                "top_die_center_distance": 0.015 + 0.004 * index,
                "bottom_die_center_distance": 0.006 + 0.002 * index,
                "expfit_total_abs_error": experimental_fit,
                "expfit_grain_mean_um_target": 28.0,
                "expfit_damage_max_target": 0.24,
            }
        )

    return pd.DataFrame(rows)


def synthetic_demo_manifest(dataset: pd.DataFrame) -> pd.DataFrame:
    """Return a manifest matching the synthetic completed runs."""
    rows = []
    for _, row in dataset.iterrows():
        rows.append(
            {
                "run_name": row["run_name"],
                "status": "completed",
                "config_path": str(DEMO_STUDY_ROOT / "inputs" / f"{row['run_name']}.json"),
                "run_dir": str(DEMO_STUDY_ROOT / "runs" / row["run_name"]),
                "notes": "Synthetic GUI demo run; no DEFORM solve was executed.",
            }
        )
    rows.append(
        {
            "run_name": "demo_run_009",
            "status": "planned",
            "config_path": str(DEMO_STUDY_ROOT / "inputs" / "demo_run_009.json"),
            "run_dir": str(DEMO_STUDY_ROOT / "runs" / "demo_run_009"),
            "notes": "Synthetic planned run included to demonstrate status plots.",
        }
    )
    return pd.DataFrame(rows)


def synthetic_next_candidates() -> pd.DataFrame:
    """Return synthetic Bayesian candidates for the candidate overlay plot."""
    return pd.DataFrame(
        [
            {
                "candidate_id": "next_001",
                "depth_in": 0.060,
                "speed_in/s": 0.72,
                "forging_temp_c": 1080,
                "height": 0.625,
                "time_step": 0.005,
                "predicted_objective": 0.78,
            },
            {
                "candidate_id": "next_002",
                "depth_in": 0.068,
                "speed_in/s": 0.88,
                "forging_temp_c": 1060,
                "height": 0.625,
                "time_step": 0.005,
                "predicted_objective": 0.81,
            },
            {
                "candidate_id": "next_003",
                "depth_in": 0.052,
                "speed_in/s": 0.58,
                "forging_temp_c": 1100,
                "height": 0.625,
                "time_step": 0.005,
                "predicted_objective": 0.84,
            },
        ]
    )


def write_demo_inputs(study_root: Path = DEMO_STUDY_ROOT) -> dict[str, Path]:
    """Write synthetic CSV/JSON inputs consumed by visualize_doe_results.py."""
    study_root.mkdir(parents=True, exist_ok=True)
    (study_root / "inputs").mkdir(exist_ok=True)
    (study_root / "runs").mkdir(exist_ok=True)

    dataset = synthetic_demo_dataset()
    manifest = synthetic_demo_manifest(dataset)
    candidates = synthetic_next_candidates()

    dataset_path = study_root / "dataset.csv"
    manifest_path = study_root / "manifest.csv"
    candidates_path = study_root / "candidates_next.csv"
    surrogate_report_path = study_root / "surrogate_report.json"

    dataset.to_csv(dataset_path, index=False)
    manifest.to_csv(manifest_path, index=False)
    candidates.to_csv(candidates_path, index=False)
    surrogate_report_path.write_text(
        json.dumps(
            {
                "demo": True,
                "model_type": "synthetic",
                "training_rows": int(len(dataset)),
                "best_completed_run": str(dataset.loc[dataset["objective"].idxmin(), "run_name"]),
                "purpose": "GUI plot viewer demonstration.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "study_root": study_root,
        "dataset": dataset_path,
        "manifest": manifest_path,
        "candidates": candidates_path,
        "surrogate_report": surrogate_report_path,
    }


def load_font(size: int) -> ImageFont.ImageFont:
    """Load a readable system font, falling back to Pillow's default font."""
    for font_name in ["arial.ttf", "segoeui.ttf", "calibri.ttf"]:
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def data_bounds(values: list[float]) -> tuple[float, float]:
    """Return padded numeric bounds for a plot axis."""
    low = min(values)
    high = max(values)
    if low == high:
        return low - 1.0, high + 1.0
    padding = 0.08 * (high - low)
    return low - padding, high + padding


def scale_point(
    x: float,
    y: float,
    x_bounds: tuple[float, float],
    y_bounds: tuple[float, float],
) -> tuple[int, int]:
    """Scale data coordinates into image pixel coordinates."""
    x_low, x_high = x_bounds
    y_low, y_high = y_bounds
    left = PLOT_MARGIN
    right = PLOT_WIDTH - PLOT_MARGIN
    top = PLOT_MARGIN
    bottom = PLOT_HEIGHT - PLOT_MARGIN
    x_pixel = left + (x - x_low) / (x_high - x_low) * (right - left)
    y_pixel = bottom - (y - y_low) / (y_high - y_low) * (bottom - top)
    return int(round(x_pixel)), int(round(y_pixel))


def make_canvas(title: str, x_label: str, y_label: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Create a plot canvas with title, axes, and light grid lines."""
    image = Image.new("RGB", (PLOT_WIDTH, PLOT_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(30)
    label_font = load_font(20)
    tick_font = load_font(17)

    draw.text((PLOT_MARGIN, 28), title, fill=COLOR_TEXT, font=title_font)
    draw.text((PLOT_WIDTH // 2 - 55, PLOT_HEIGHT - 50), x_label, fill=COLOR_TEXT, font=label_font)
    draw.text((24, PLOT_HEIGHT // 2 - 15), y_label, fill=COLOR_TEXT, font=label_font)

    left = PLOT_MARGIN
    right = PLOT_WIDTH - PLOT_MARGIN
    top = PLOT_MARGIN
    bottom = PLOT_HEIGHT - PLOT_MARGIN
    for step in range(6):
        fraction = step / 5
        x = int(left + fraction * (right - left))
        y = int(top + fraction * (bottom - top))
        draw.line((x, top, x, bottom), fill=COLOR_GRID)
        draw.line((left, y, right, y), fill=COLOR_GRID)
    draw.rectangle((left, top, right, bottom), outline=(156, 163, 175), width=2)
    draw.text((PLOT_WIDTH - 245, 34), "Synthetic GUI demo data", fill=COLOR_MUTED, font=tick_font)
    return image, draw


def draw_tick_labels(
    draw: ImageDraw.ImageDraw,
    x_bounds: tuple[float, float],
    y_bounds: tuple[float, float],
) -> None:
    """Draw min/max labels so demo plots are understandable in the GUI."""
    tick_font = load_font(16)
    left = PLOT_MARGIN
    right = PLOT_WIDTH - PLOT_MARGIN
    top = PLOT_MARGIN
    bottom = PLOT_HEIGHT - PLOT_MARGIN
    draw.text((left - 20, bottom + 12), f"{x_bounds[0]:.3g}", fill=COLOR_MUTED, font=tick_font)
    draw.text((right - 45, bottom + 12), f"{x_bounds[1]:.3g}", fill=COLOR_MUTED, font=tick_font)
    draw.text((left - 70, bottom - 12), f"{y_bounds[0]:.3g}", fill=COLOR_MUTED, font=tick_font)
    draw.text((left - 70, top - 6), f"{y_bounds[1]:.3g}", fill=COLOR_MUTED, font=tick_font)


def save_line_plot(
    data: pd.DataFrame,
    x_column: str,
    y_column: str,
    title: str,
    output_path: Path,
    color: tuple[int, int, int] = COLOR_BLUE,
) -> Path:
    """Save a simple line plot using Pillow."""
    x_values = [float(value) for value in data[x_column]]
    y_values = [float(value) for value in data[y_column]]
    x_bounds = data_bounds(x_values)
    y_bounds = data_bounds(y_values)
    image, draw = make_canvas(title, x_column, y_column)
    points = [scale_point(x, y, x_bounds, y_bounds) for x, y in zip(x_values, y_values)]
    if len(points) > 1:
        draw.line(points, fill=color, width=4)
    for point in points:
        x, y = point
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color, outline="white", width=2)
    draw_tick_labels(draw, x_bounds, y_bounds)
    image.save(output_path)
    return output_path


def save_scatter_plot(
    data: pd.DataFrame,
    x_column: str,
    y_column: str,
    title: str,
    output_path: Path,
    color: tuple[int, int, int] = COLOR_GREEN,
) -> Path:
    """Save a simple scatter plot using Pillow."""
    x_values = [float(value) for value in data[x_column]]
    y_values = [float(value) for value in data[y_column]]
    x_bounds = data_bounds(x_values)
    y_bounds = data_bounds(y_values)
    image, draw = make_canvas(title, x_column, y_column)
    for x_value, y_value in zip(x_values, y_values):
        x, y = scale_point(x_value, y_value, x_bounds, y_bounds)
        draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=color, outline="white", width=2)
    draw_tick_labels(draw, x_bounds, y_bounds)
    image.save(output_path)
    return output_path


def save_completed_vs_next_plot(dataset: pd.DataFrame, candidates: pd.DataFrame, output_path: Path) -> Path:
    """Save a completed-run versus proposed-candidate overlay plot."""
    completed_x = [float(value) for value in dataset["depth_in"]]
    completed_y = [float(value) for value in dataset["speed_in/s"]]
    candidate_x = [float(value) for value in candidates["depth_in"]]
    candidate_y = [float(value) for value in candidates["speed_in/s"]]
    x_bounds = data_bounds(completed_x + candidate_x)
    y_bounds = data_bounds(completed_y + candidate_y)
    image, draw = make_canvas("Completed DOE Samples vs Next Candidates", "depth_in", "speed_in/s")

    for x_value, y_value in zip(completed_x, completed_y):
        x, y = scale_point(x_value, y_value, x_bounds, y_bounds)
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=COLOR_BLUE, outline="white", width=2)
    for x_value, y_value in zip(candidate_x, candidate_y):
        x, y = scale_point(x_value, y_value, x_bounds, y_bounds)
        draw.rectangle((x - 10, y - 10, x + 10, y + 10), fill=COLOR_ORANGE, outline="white", width=2)

    legend_font = load_font(18)
    draw.ellipse((PLOT_WIDTH - 330, 86, PLOT_WIDTH - 312, 104), fill=COLOR_BLUE)
    draw.text((PLOT_WIDTH - 300, 82), "Completed runs", fill=COLOR_TEXT, font=legend_font)
    draw.rectangle((PLOT_WIDTH - 330, 120, PLOT_WIDTH - 312, 138), fill=COLOR_ORANGE)
    draw.text((PLOT_WIDTH - 300, 116), "Next candidates", fill=COLOR_TEXT, font=legend_font)
    draw_tick_labels(draw, x_bounds, y_bounds)
    image.save(output_path)
    return output_path


def save_manifest_status_plot(manifest: pd.DataFrame, output_path: Path) -> Path:
    """Save a small bar chart for run status counts."""
    counts = manifest["status"].fillna("missing").astype(str).value_counts()
    image, draw = make_canvas("Run Status Counts", "status", "count")
    label_font = load_font(20)
    y_bounds = data_bounds([0.0, float(counts.max())])
    left = PLOT_MARGIN
    right = PLOT_WIDTH - PLOT_MARGIN
    bottom = PLOT_HEIGHT - PLOT_MARGIN
    bar_width = 160
    gap = 80
    start_x = left + 90
    for index, (status, count) in enumerate(counts.items()):
        x0 = start_x + index * (bar_width + gap)
        _, y_top = scale_point(float(index), float(count), (0, max(1, len(counts) - 1)), y_bounds)
        draw.rectangle((x0, y_top, x0 + bar_width, bottom), fill=COLOR_PURPLE)
        draw.text((x0 + 20, bottom + 14), status, fill=COLOR_TEXT, font=label_font)
        draw.text((x0 + 62, y_top - 34), str(int(count)), fill=COLOR_TEXT, font=label_font)
    image.save(output_path)
    return output_path


def create_fallback_png_plots(study_root: Path) -> list[Path]:
    """Create GUI-ready PNG plots when matplotlib is not available."""
    output_dir = study_root / "report"
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset = pd.read_csv(study_root / "dataset.csv")
    manifest = pd.read_csv(study_root / "manifest.csv")
    candidates = pd.read_csv(study_root / "candidates_next.csv")
    completed = dataset.reset_index(drop=True).copy()
    completed["run_order"] = range(1, len(completed) + 1)

    return [
        save_manifest_status_plot(manifest, output_dir / "demo_manifest_status_counts.png"),
        save_line_plot(completed, "run_order", "objective", "Objective vs Completed Run", output_dir / "demo_objective_vs_run.png"),
        save_scatter_plot(completed, "depth_in", "damage_max", "Max Damage vs Hit Depth", output_dir / "demo_damage_vs_depth.png", COLOR_ORANGE),
        save_scatter_plot(completed, "forging_temp_c", "grain_mean_um", "Mean Grain Size vs Forging Temperature", output_dir / "demo_grain_mean_vs_temperature.png", COLOR_GREEN),
        save_completed_vs_next_plot(completed, candidates, output_dir / "demo_completed_vs_next_candidates.png"),
    ]


def create_demo_result_plots(study_root: Path = DEMO_STUDY_ROOT) -> dict[str, str]:
    """Create the demo study files and the report PNGs used by the GUI."""
    paths = write_demo_inputs(study_root)
    report = visualize_doe_results(study_root=paths["study_root"])
    if int(report.get("plot_count", 0)) == 0:
        fallback_plots = create_fallback_png_plots(paths["study_root"])
        report["plot_count"] = len(fallback_plots)
        report["fallback_png_plots"] = [str(path) for path in fallback_plots]
    return {key: str(value) for key, value in {**paths, **report}.items()}


def main() -> None:
    """Command-line entry point."""
    result = create_demo_result_plots()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
