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
        ]:
            path = save_line_plot(af, "row_order", column, report_dir / f"{column}_by_hit.png", title, color=color)
            if path:
                plots.append(path)
    if not validation.empty and "validation_status" in validation.columns:
        counts = validation["validation_status"].fillna("missing").astype(str).value_counts()
        path = save_bar_plot(list(counts.index), [float(v) for v in counts.values], report_dir / "validation_status_counts.png", "Validation Status Counts", COLOR_RED)
        if path:
            plots.append(path)
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

