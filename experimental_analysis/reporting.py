"""
Automated reports for Agility Forge experimental analysis.

The report uses HTML, CSV summaries, and Pillow-generated PNG plots so it works
in the lightweight Python environment used during development.
"""

from __future__ import annotations

import html
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


PLOT_WIDTH = 1100
PLOT_HEIGHT = 650
MARGIN = 86
COLOR_TEXT = (31, 41, 55)
COLOR_GRID = (222, 229, 237)
COLOR_BLUE = (45, 105, 178)
COLOR_GREEN = (42, 150, 105)
COLOR_ORANGE = (214, 125, 45)
COLOR_RED = (184, 65, 65)
COLOR_PURPLE = (126, 87, 194)
COLOR_GRAY = (107, 114, 128)
PLOT_COLORS = [
    COLOR_BLUE,
    COLOR_GREEN,
    COLOR_ORANGE,
    COLOR_PURPLE,
    COLOR_RED,
    (20, 132, 143),
    (91, 141, 65),
    (148, 92, 54),
]


def load_font(size: int) -> ImageFont.ImageFont:
    """Load a common Windows font or fall back to Pillow's default."""
    for font in ["segoeui.ttf", "arial.ttf", "calibri.ttf"]:
        try:
            return ImageFont.truetype(font, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def read_csv(path: str | Path | None) -> pd.DataFrame:
    """Read a CSV path if it exists."""
    if path is None or str(path).strip() == "":
        return pd.DataFrame()
    path = Path(path)
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def bounds(values) -> tuple[float, float]:
    """Return padded finite numeric bounds."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return 0.0, 1.0
    low = float(np.min(values))
    high = float(np.max(values))
    if low == high:
        return low - 1.0, high + 1.0
    pad = 0.08 * (high - low)
    return low - pad, high + pad


def scale_xy(x, y, x_bounds, y_bounds) -> tuple[int, int]:
    """Scale data coordinates to image pixels."""
    left, right = MARGIN, PLOT_WIDTH - MARGIN
    top, bottom = MARGIN, PLOT_HEIGHT - MARGIN
    xp = left + (x - x_bounds[0]) / (x_bounds[1] - x_bounds[0]) * (right - left)
    yp = bottom - (y - y_bounds[0]) / (y_bounds[1] - y_bounds[0]) * (bottom - top)
    return int(round(xp)), int(round(yp))


def format_tick(value: float) -> str:
    """Format numeric tick labels compactly."""
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


def canvas(title: str, x_label: str, y_label: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Create a chart canvas."""
    image = Image.new("RGB", (PLOT_WIDTH, PLOT_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(28)
    label_font = load_font(18)
    draw.text((MARGIN, 28), title, fill=COLOR_TEXT, font=title_font)
    draw.text((PLOT_WIDTH // 2 - 70, PLOT_HEIGHT - 46), x_label, fill=COLOR_TEXT, font=label_font)
    draw.text((22, PLOT_HEIGHT // 2 - 16), y_label, fill=COLOR_TEXT, font=label_font)
    left, right = MARGIN, PLOT_WIDTH - MARGIN
    top, bottom = MARGIN, PLOT_HEIGHT - MARGIN
    for step in range(6):
        fraction = step / 5.0
        x = int(left + fraction * (right - left))
        y = int(top + fraction * (bottom - top))
        draw.line((x, top, x, bottom), fill=COLOR_GRID)
        draw.line((left, y, right, y), fill=COLOR_GRID)
    draw.rectangle((left, top, right, bottom), outline=(156, 163, 175), width=2)
    return image, draw


def draw_numeric_ticks(
    draw: ImageDraw.ImageDraw,
    x_bounds: tuple[float, float],
    y_bounds: tuple[float, float],
    tick_count: int = 6,
) -> None:
    """Draw numeric x/y tick labels on an existing canvas."""
    tick_font = load_font(15)
    left, right = MARGIN, PLOT_WIDTH - MARGIN
    top, bottom = MARGIN, PLOT_HEIGHT - MARGIN
    for step in range(tick_count):
        fraction = step / max(tick_count - 1, 1)
        x_value = x_bounds[0] + fraction * (x_bounds[1] - x_bounds[0])
        y_value = y_bounds[0] + fraction * (y_bounds[1] - y_bounds[0])
        x_pixel = int(left + fraction * (right - left))
        y_pixel = int(bottom - fraction * (bottom - top))
        draw.text((x_pixel - 22, bottom + 10), format_tick(x_value), fill=COLOR_GRAY, font=tick_font)
        draw.text((left - 72, y_pixel - 9), format_tick(y_value), fill=COLOR_GRAY, font=tick_font)


def save_line_plot(df: pd.DataFrame, x_col: str, y_col: str, output_path: Path, title: str, color=COLOR_BLUE) -> Path | None:
    """Save a line plot for two numeric columns."""
    if df.empty or x_col not in df.columns or y_col not in df.columns:
        return None
    x = pd.to_numeric(df[x_col], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(df[y_col], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 2:
        return None
    x, y = x[valid], y[valid]
    x_bounds, y_bounds = bounds(x), bounds(y)
    image, draw = canvas(title, x_col, y_col)
    draw_numeric_ticks(draw, x_bounds, y_bounds)
    points = [scale_xy(xi, yi, x_bounds, y_bounds) for xi, yi in zip(x, y)]
    draw.line(points, fill=color, width=4)
    for xp, yp in points:
        draw.ellipse((xp - 6, yp - 6, xp + 6, yp + 6), fill=color, outline="white", width=2)
    image.save(output_path)
    return output_path


def save_bar_plot(labels: list[str], values: list[float], output_path: Path, title: str, color=COLOR_GREEN) -> Path | None:
    """Save a simple bar plot."""
    if not labels or not values:
        return None
    image, draw = canvas(title, "category", "count")
    label_font = load_font(16)
    y_bounds = bounds([0.0] + values)
    draw_numeric_ticks(draw, (0, max(1, len(labels) - 1)), y_bounds)
    left, bottom = MARGIN, PLOT_HEIGHT - MARGIN
    bar_width = max(35, min(120, int((PLOT_WIDTH - 2 * MARGIN) / max(len(labels) * 1.5, 1))))
    gap = max(20, int(bar_width * 0.55))
    for index, (label, value) in enumerate(zip(labels, values)):
        x0 = left + 40 + index * (bar_width + gap)
        _, y0 = scale_xy(index, value, (0, max(1, len(labels) - 1)), y_bounds)
        draw.rectangle((x0, y0, x0 + bar_width, bottom), fill=color)
        draw.text((x0, bottom + 12), str(label)[:12], fill=COLOR_TEXT, font=label_font)
        draw.text((x0 + 8, y0 - 28), f"{value:g}", fill=COLOR_TEXT, font=label_font)
    image.save(output_path)
    return output_path


def save_stress_strain_overlay(
    curve_dir: str | Path,
    output_path: Path,
    max_curves: int = 38,
) -> Path | None:
    """Save an overlay plot of effective stress-strain curves."""
    curve_dir = Path(curve_dir)
    curve_paths = sorted(curve_dir.glob("*_stress_strain.csv"))
    if not curve_paths:
        return None

    curves = []
    for path in curve_paths[:max_curves]:
        df = pd.read_csv(path)
        if "true_strain" not in df.columns or "effective_stress_mpa" not in df.columns:
            continue
        x = pd.to_numeric(df["true_strain"], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(df["effective_stress_mpa"], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        if valid.sum() < 2:
            continue
        hit_label = str(df["hit"].iloc[0]) if "hit" in df.columns and not df.empty else path.stem
        curves.append((hit_label, x[valid], y[valid]))

    if not curves:
        return None

    all_x = np.concatenate([curve[1] for curve in curves])
    all_y = np.concatenate([curve[2] for curve in curves])
    x_bounds, y_bounds = bounds(all_x), bounds(all_y)
    image, draw = canvas("Effective Stress-Strain Curves", "true_strain", "effective_stress_mpa")
    draw_numeric_ticks(draw, x_bounds, y_bounds)

    for index, (hit_label, x, y) in enumerate(curves):
        color = PLOT_COLORS[index % len(PLOT_COLORS)]
        stride = max(1, len(x) // 260)
        points = [scale_xy(xi, yi, x_bounds, y_bounds) for xi, yi in zip(x[::stride], y[::stride])]
        if len(points) > 1:
            draw.line(points, fill=color, width=2)

    legend_font = load_font(15)
    legend_x = PLOT_WIDTH - MARGIN - 170
    legend_y = MARGIN + 12
    draw.rectangle((legend_x - 12, legend_y - 10, PLOT_WIDTH - MARGIN - 8, legend_y + 156), fill="white", outline=(203, 213, 225))
    draw.text((legend_x, legend_y), f"{len(curves)} curves", fill=COLOR_TEXT, font=legend_font)
    draw.text((legend_x, legend_y + 24), "Color cycles by hit", fill=COLOR_GRAY, font=legend_font)
    for i, (hit_label, _x, _y) in enumerate(curves[:6]):
        color = PLOT_COLORS[i % len(PLOT_COLORS)]
        y0 = legend_y + 52 + i * 17
        draw.line((legend_x, y0 + 7, legend_x + 22, y0 + 7), fill=color, width=3)
        draw.text((legend_x + 30, y0), f"hit {hit_label}", fill=COLOR_TEXT, font=legend_font)

    image.save(output_path)
    return output_path


def curve_hit_number(curve_path: Path) -> int | None:
    """Read a curve CSV hit number without assuming filename sort order."""
    try:
        df = pd.read_csv(curve_path, usecols=["hit"], nrows=1)
    except Exception:
        return None
    if df.empty:
        return None
    try:
        return int(df["hit"].iloc[0])
    except Exception:
        return None


def representative_curve_paths(curve_dir: str | Path, count: int = 5) -> list[Path]:
    """Choose representative curve files across the hit sequence."""
    curve_dir = Path(curve_dir)
    paths = list(curve_dir.glob("*_stress_strain.csv"))
    if not paths:
        return []
    paths = sorted(paths, key=lambda path: (curve_hit_number(path) if curve_hit_number(path) is not None else 10**9, path.name))
    if len(paths) <= count:
        return paths
    indices = np.linspace(0, len(paths) - 1, count).round().astype(int)
    return [paths[int(index)] for index in indices]


def read_recrystallization_lookup(rx_csv: str | Path | None) -> dict[int, dict]:
    """Read recrystallization summary rows keyed by hit number."""
    if rx_csv is None:
        return {}
    rx = read_csv(rx_csv)
    if rx.empty or "hit" not in rx.columns:
        return {}
    lookup = {}
    for _, row in rx.iterrows():
        try:
            lookup[int(row["hit"])] = row.to_dict()
        except Exception:
            pass
    return lookup


def first_softening_point(
    strain: np.ndarray,
    stress: np.ndarray,
    peak_idx: int,
    softening_fraction: float = 0.08,
) -> tuple[float, float] | None:
    """Find first post-peak point below a chosen softening threshold."""
    if peak_idx >= len(stress) - 1:
        return None
    peak_stress = float(stress[peak_idx])
    threshold = peak_stress * (1.0 - softening_fraction)
    post = np.where(stress[peak_idx:] <= threshold)[0]
    if len(post) == 0:
        return None
    idx = int(peak_idx + post[0])
    return float(strain[idx]), float(stress[idx])


def save_single_stress_strain_diagnostic(
    curve_path: str | Path,
    output_path: Path,
    rx_row: dict | None = None,
    softening_fraction_threshold: float = 0.08,
) -> Path | None:
    """Save one annotated stress-strain diagnostic plot."""
    curve_path = Path(curve_path)
    df = pd.read_csv(curve_path)
    if "true_strain" not in df.columns or "effective_stress_mpa" not in df.columns:
        return None
    strain = pd.to_numeric(df["true_strain"], errors="coerce").to_numpy(dtype=float)
    stress = pd.to_numeric(df["effective_stress_mpa"], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(strain) & np.isfinite(stress)
    strain = strain[valid]
    stress = stress[valid]
    if len(stress) < 2:
        return None

    hit = curve_hit_number(curve_path)
    peak_idx = int(np.nanargmax(stress))
    peak_point = (float(strain[peak_idx]), float(stress[peak_idx]))
    softening_point = first_softening_point(
        strain,
        stress,
        peak_idx,
        softening_fraction=softening_fraction_threshold,
    )
    terminal_point = (float(np.nanmedian(strain[-max(3, len(strain) // 5):])), float(np.nanmedian(stress[-max(3, len(stress) // 5):])))

    x_bounds, y_bounds = bounds(strain), bounds(stress)
    title = f"Hit {hit} Stress-Strain Diagnostic" if hit is not None else "Stress-Strain Diagnostic"
    image, draw = canvas(title, "true_strain", "effective_stress_mpa")
    draw_numeric_ticks(draw, x_bounds, y_bounds)

    stride = max(1, len(strain) // 420)
    points = [scale_xy(xi, yi, x_bounds, y_bounds) for xi, yi in zip(strain[::stride], stress[::stride])]
    draw.line(points, fill=COLOR_BLUE, width=4)

    annotation_font = load_font(16)
    small_font = load_font(14)
    px, py = scale_xy(*peak_point, x_bounds, y_bounds)
    draw.ellipse((px - 8, py - 8, px + 8, py + 8), fill=COLOR_RED, outline="white", width=2)
    draw.text((px + 12, py - 28), f"Peak {peak_point[1]:.1f} MPa", fill=COLOR_RED, font=annotation_font)
    draw.text((px + 12, py - 8), "softening onset", fill=COLOR_RED, font=small_font)

    if softening_point is not None:
        sx, sy = scale_xy(*softening_point, x_bounds, y_bounds)
        draw.ellipse((sx - 7, sy - 7, sx + 7, sy + 7), fill=COLOR_ORANGE, outline="white", width=2)
        draw.line((px, py, sx, sy), fill=COLOR_ORANGE, width=2)
        draw.text((sx + 12, sy + 4), f"{softening_fraction_threshold:.0%} softening", fill=COLOR_ORANGE, font=annotation_font)

    tx, ty = scale_xy(*terminal_point, x_bounds, y_bounds)
    draw.rectangle((tx - 7, ty - 7, tx + 7, ty + 7), fill=COLOR_GREEN, outline="white", width=2)
    draw.text((tx + 12, ty - 6), f"Terminal ~{terminal_point[1]:.1f} MPa", fill=COLOR_GREEN, font=annotation_font)

    rx_mode = str((rx_row or {}).get("rx_mode", "not classified"))
    rx_confidence = (rx_row or {}).get("rx_confidence", "")
    softening_fraction = (rx_row or {}).get("softening_fraction", "")
    panel_x = MARGIN + 18
    panel_y = MARGIN + 14
    draw.rectangle((panel_x - 10, panel_y - 10, panel_x + 440, panel_y + 105), fill="white", outline=(203, 213, 225))
    draw.text((panel_x, panel_y), f"RX indicator: {rx_mode}", fill=COLOR_TEXT, font=annotation_font)
    draw.text((panel_x, panel_y + 24), f"confidence: {rx_confidence}", fill=COLOR_TEXT, font=small_font)
    draw.text((panel_x, panel_y + 45), f"softening fraction: {softening_fraction}", fill=COLOR_TEXT, font=small_font)
    draw.text((panel_x, panel_y + 66), "Possible DRX when peak + softening + steady terminal slope align.", fill=COLOR_GRAY, font=small_font)

    image.save(output_path)
    return output_path


def save_stress_strain_diagnostics(
    curve_dir: str | Path,
    report_dir: str | Path,
    rx_csv: str | Path | None = None,
    count: int = 5,
) -> list[Path]:
    """Save annotated diagnostic plots for representative stress-strain curves."""
    report_dir = Path(report_dir)
    lookup = read_recrystallization_lookup(rx_csv)
    outputs = []
    for curve_path in representative_curve_paths(curve_dir, count=count):
        hit = curve_hit_number(curve_path)
        name = f"stress_strain_diagnostic_hit{hit}.png" if hit is not None else f"{curve_path.stem}_diagnostic.png"
        output_path = report_dir / name
        path = save_single_stress_strain_diagnostic(
            curve_path,
            output_path,
            rx_row=lookup.get(hit) if hit is not None else None,
        )
        if path:
            outputs.append(path)
    return outputs


def save_phase_fraction_plot(
    phase_csv: str | Path,
    output_path: Path,
) -> Path | None:
    """Save a pyJMAK phase-fraction plot when phase predictions exist."""
    df = read_csv(phase_csv)
    if df.empty or "time_s" not in df.columns:
        return None
    phase_columns = [column for column in df.columns if column.startswith("phase_fraction_")]
    if not phase_columns:
        return None

    time = pd.to_numeric(df["time_s"], errors="coerce").to_numpy(dtype=float)
    values = []
    for column in phase_columns:
        y = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(time) & np.isfinite(y)
        if valid.sum() >= 2:
            values.append((column.replace("phase_fraction_", ""), time[valid], y[valid]))
    if not values:
        return None

    x_bounds = bounds(np.concatenate([item[1] for item in values]))
    y_bounds = (0.0, 1.0)
    image, draw = canvas("pyJMAK Phase Fraction Predictions", "time_s", "phase_fraction")
    draw_numeric_ticks(draw, x_bounds, y_bounds)
    for index, (phase, x, y) in enumerate(values):
        color = PLOT_COLORS[index % len(PLOT_COLORS)]
        stride = max(1, len(x) // 360)
        points = [scale_xy(xi, yi, x_bounds, y_bounds) for xi, yi in zip(x[::stride], y[::stride])]
        if len(points) > 1:
            draw.line(points, fill=color, width=3)

    legend_font = load_font(15)
    legend_x = PLOT_WIDTH - MARGIN - 190
    legend_y = MARGIN + 12
    legend_height = min(180, 42 + 20 * len(values))
    draw.rectangle((legend_x - 12, legend_y - 10, PLOT_WIDTH - MARGIN - 8, legend_y + legend_height), fill="white", outline=(203, 213, 225))
    draw.text((legend_x, legend_y), "Phases", fill=COLOR_TEXT, font=legend_font)
    for index, (phase, _x, _y) in enumerate(values[:7]):
        color = PLOT_COLORS[index % len(PLOT_COLORS)]
        y0 = legend_y + 28 + index * 20
        draw.line((legend_x, y0 + 7, legend_x + 22, y0 + 7), fill=color, width=3)
        draw.text((legend_x + 30, y0), phase[:18], fill=COLOR_TEXT, font=legend_font)
    image.save(output_path)
    return output_path


def dataframe_table_html(df: pd.DataFrame, max_rows: int = 12) -> str:
    """Convert a DataFrame preview to a compact HTML table."""
    if df.empty:
        return "<p>No data available.</p>"
    return df.head(max_rows).to_html(index=False, escape=True, border=0)


def build_experimental_report(
    output_dir: str | Path,
    af_features_csv: str | Path | None = None,
    validation_csv: str | Path | None = None,
    microstructure_summary_csv: str | Path | None = None,
    calibration_csv: str | Path | None = None,
    uncertainty_csv: str | Path | None = None,
    stress_strain_curve_dir: str | Path | None = None,
    recrystallization_csv: str | Path | None = None,
    pyjmak_phase_csv: str | Path | None = None,
) -> dict[str, str]:
    """Build an HTML report and PNG plots for an experimental-analysis folder."""
    output_dir = Path(output_dir)
    report_dir = output_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    af = read_csv(af_features_csv or output_dir / "af_experimental_features.csv")
    validation = read_csv(validation_csv or output_dir / "af_validation_summary.csv")
    micro = read_csv(microstructure_summary_csv or output_dir / "experimental_microstructure_summary.csv")
    calibration = read_csv(calibration_csv or output_dir / "calibration_grid_search.csv")
    uncertainty = read_csv(uncertainty_csv or output_dir / "af_uncertainty_summary.csv")

    plots = []
    if not af.empty:
        af = af.copy()
        af["row_order"] = np.arange(1, len(af) + 1)
        for column, title, color in [
            ("max_force_kn", "Maximum Force by Hit", COLOR_BLUE),
            ("depth_mm", "Penetration Depth by Hit", COLOR_ORANGE),
            ("softening_fraction", "Softening Fraction by Hit", COLOR_GREEN),
            ("total_recrystallized_fraction", "Mixed DRX/MDRX/SRX Fraction by Hit", COLOR_PURPLE),
            ("updated_grain_um", "Predicted Grain Size by Hit", COLOR_BLUE),
        ]:
            path = save_line_plot(af, "row_order", column, report_dir / f"{column}_by_hit.png", title, color=color)
            if path:
                plots.append(path)
    if not validation.empty and "validation_status" in validation.columns:
        counts = validation["validation_status"].fillna("missing").astype(str).value_counts()
        path = save_bar_plot(list(counts.index), [float(v) for v in counts.values], report_dir / "validation_status_counts.png", "Validation Status Counts", COLOR_RED)
        if path:
            plots.append(path)
    curve_dir = stress_strain_curve_dir or output_dir / "stress_strain_curves"
    path = save_stress_strain_overlay(curve_dir, report_dir / "stress_strain_curves.png")
    if path:
        plots.append(path)
    diagnostic_plots = save_stress_strain_diagnostics(
        curve_dir,
        report_dir,
        rx_csv=recrystallization_csv or output_dir / "recrystallization_summary.csv",
        count=5,
    )
    plots.extend(diagnostic_plots)
    phase_path = save_phase_fraction_plot(
        pyjmak_phase_csv or output_dir / "pyjmak_phase_fractions.csv",
        report_dir / "pyjmak_phase_fractions.png",
    )
    if phase_path:
        plots.append(phase_path)
    if not calibration.empty and "calibration_objective" in calibration.columns:
        calibration = calibration.copy()
        calibration["candidate_order"] = np.arange(1, len(calibration) + 1)
        path = save_line_plot(calibration.head(40), "candidate_order", "calibration_objective", report_dir / "calibration_objective.png", "Calibration Objective", COLOR_BLUE)
        if path:
            plots.append(path)

    html_path = report_dir / "index.html"
    image_html = "\n".join(
        f"<section><h3>{html.escape(path.stem.replace('_', ' ').title())}</h3><img src='{html.escape(path.name)}'></section>"
        for path in plots
    )
    html_text = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Agility Forge Experimental Analysis Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 28px; color: #111827; background: #f8fafc; }}
    h1, h2, h3 {{ color: #0f172a; }}
    section, table {{ background: white; border: 1px solid #cbd5e1; }}
    section {{ padding: 14px 18px; margin: 18px 0; }}
    table {{ border-collapse: collapse; margin: 12px 0 24px 0; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 6px 8px; text-align: left; }}
    img {{ max-width: 980px; width: 100%; height: auto; display: block; }}
    code {{ background: #e5e7eb; padding: 2px 5px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Agility Forge Experimental Analysis Report</h1>
  <p><strong>Output folder:</strong> <code>{html.escape(str(output_dir))}</code></p>
  <h2>Plots</h2>
  {image_html if image_html else "<p>No plots were generated.</p>"}
  <h2>AF Features Preview</h2>
  {dataframe_table_html(af)}
  <h2>Validation Preview</h2>
  {dataframe_table_html(validation)}
  <h2>Microstructure Summary Preview</h2>
  {dataframe_table_html(micro)}
  <h2>Calibration Preview</h2>
  {dataframe_table_html(calibration)}
  <h2>Uncertainty Preview</h2>
  {dataframe_table_html(uncertainty)}
</body>
</html>
"""
    html_path.write_text(html_text, encoding="utf-8")
    return {
        "experimental_report": str(html_path),
        "experimental_report_dir": str(report_dir),
        "experimental_report_plot_count": str(len(plots)),
    }
