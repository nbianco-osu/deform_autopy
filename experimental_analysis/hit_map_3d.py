"""
Build a 3D hit map for Agility Forge cylindrical stock.

The raw AF hit files contain one tool-path row per time sample. This module
extracts one representative row per hit at the detected contact index and maps
the hit onto a cylindrical workpiece surface. The axial coordinate comes from
`X pos referenced to target part butt`; the circumferential coordinate comes
from the `A` rotation angle.

Outputs are intentionally dependency-light:

- CSV with the mapped hit coordinates.
- PNG static oblique view for reports.
- Self-contained HTML with a rotatable canvas view.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


DEFAULT_RAW_AF_DIR = r"C:\Users\nbian\Desktop\OSU Research\AF Data\Box_1in_316L"
DEFAULT_ANALYSIS_DIR = DEFAULT_RAW_AF_DIR + r"\experimental_analysis_output"
DEFAULT_OUTPUT_DIR = DEFAULT_ANALYSIS_DIR + r"\hit_map_3d"


@dataclass
class HitMapConfig:
    """Configuration for mapping hits onto cylindrical stock."""

    stock_diameter_mm: float = 25.4
    extra_bar_behind_start_mm: float = 30.0
    extra_bar_after_end_mm: float = 15.0
    radial_lift_mm: float = 1.6
    axial_column: str = "X pos referenced to target part butt"
    angle_column: str = "A"
    x_column: str = "X"
    y_column: str = "Y"
    z_column: str = "Z"


def infer_stock_diameter_mm(path: str | Path, fallback_mm: float = 25.4) -> float:
    """Infer stock diameter from folder names like Box_1in or Box_0.625in."""
    text = str(path)
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*in", text, flags=re.I)
    if match:
        return float(match.group(1)) * 25.4
    if re.search(r"5[_ -]?8\s*in", text, flags=re.I):
        return 0.625 * 25.4
    return float(fallback_mm)


def load_font(size: int) -> ImageFont.ImageFont:
    """Load a common Windows font, falling back to Pillow's default."""
    for font in ["segoeui.ttf", "arial.ttf", "calibri.ttf"]:
        try:
            return ImageFont.truetype(font, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def extract_hit_surface_points(
    raw_af_dir: str | Path,
    analysis_dir: str | Path,
    config: HitMapConfig | None = None,
) -> pd.DataFrame:
    """Extract one mapped cylindrical-surface point per hit."""
    raw_af_dir = Path(raw_af_dir)
    analysis_dir = Path(analysis_dir)
    config = config or HitMapConfig(stock_diameter_mm=infer_stock_diameter_mm(raw_af_dir))
    summary_path = analysis_dir / "af_hit_signal_summary.csv"
    if summary_path.exists():
        summary = pd.read_csv(summary_path).sort_values("hit").reset_index(drop=True)
    else:
        summary = build_contact_summary_from_raw_files(raw_af_dir)
    radius_mm = 0.5 * float(config.stock_diameter_mm)
    rows: list[dict[str, float | int | str]] = []
    for _, hit in summary.iterrows():
        source_file = str(hit["source_file"])
        raw_path = raw_af_dir / source_file
        if not raw_path.exists():
            raise FileNotFoundError(f"Missing raw hit file: {raw_path}")

        raw = pd.read_csv(raw_path)
        contact_idx = int(hit["contact_idx"])
        contact_idx = max(0, min(contact_idx, len(raw) - 1))
        contact = raw.iloc[contact_idx]
        axial_mm = float(contact.get(config.axial_column, np.nan))
        angle_deg = float(contact.get(config.angle_column, 0.0))
        theta = math.radians(angle_deg)
        surface_radius = radius_mm + float(config.radial_lift_mm)

        rows.append(
            {
                "hit": int(hit["hit"]),
                "source_file": source_file,
                "contact_idx": contact_idx,
                "axial_mm": axial_mm,
                "angle_deg": angle_deg,
                "surface_y_mm": surface_radius * math.cos(theta),
                "surface_z_mm": surface_radius * math.sin(theta),
                "stock_radius_mm": radius_mm,
                "depth_mm": float(hit["depth_mm"]),
                "max_force_kn": float(hit["max_force_kn"]),
                "contact_temperature_c": float(hit["contact_temperature_c"]),
                "raw_x": float(contact.get(config.x_column, np.nan)),
                "raw_y": float(contact.get(config.y_column, np.nan)),
                "raw_z": float(contact.get(config.z_column, np.nan)),
            }
        )

    mapped = pd.DataFrame(rows).sort_values("hit").reset_index(drop=True)
    mapped["station"] = mapped.groupby("axial_mm", sort=True).ngroup()
    return mapped


def infer_hit_number_from_name(path: str | Path) -> int:
    """Infer the numeric hit order from a filename."""
    match = re.search(r"hit(?:point)?[_ -]*(\d+)|hit\s*point[_ -]*(\d+)", Path(path).name, flags=re.I)
    if match:
        return int(next(group for group in match.groups() if group is not None))
    values = re.findall(r"\d+", Path(path).stem)
    return int(values[-1]) if values else 0


def build_contact_summary_from_raw_files(raw_af_dir: str | Path) -> pd.DataFrame:
    """
    Build a minimal hit summary directly from raw AF load-stroke files.

    This fallback is used when the full experimental-analysis pipeline has not
    yet produced `af_hit_signal_summary.csv`. Contact is detected from the force
    signal rising above a conservative baseline-derived threshold.
    """
    raw_af_dir = Path(raw_af_dir)
    rows: list[dict[str, float | int | str]] = []
    for raw_path in sorted(raw_af_dir.glob("*.csv"), key=infer_hit_number_from_name):
        raw = pd.read_csv(raw_path)
        force = pd.to_numeric(raw.get("Force (kN)", pd.Series(dtype=float)), errors="coerce")
        position = pd.to_numeric(raw.get("Position (mm)", pd.Series(dtype=float)), errors="coerce")
        temp = pd.to_numeric(raw.get("Thermal Cam Temp (c)", pd.Series(dtype=float)), errors="coerce")
        if raw.empty or force.dropna().empty:
            continue

        baseline_count = max(5, int(0.1 * len(force)))
        baseline = float(force.iloc[:baseline_count].median())
        force_max = float(force.max())
        threshold = baseline + max(1.0, 0.10 * max(force_max - baseline, 0.0))
        contact_candidates = np.flatnonzero((force >= threshold).to_numpy(dtype=bool))
        contact_idx = int(contact_candidates[0]) if len(contact_candidates) else int(force.idxmax())
        min_idx = int(position.idxmin()) if not position.dropna().empty else contact_idx
        contact_position = float(position.iloc[contact_idx]) if np.isfinite(position.iloc[contact_idx]) else float("nan")
        min_position = float(position.iloc[min_idx]) if np.isfinite(position.iloc[min_idx]) else float("nan")

        rows.append(
            {
                "contact_idx": contact_idx,
                "min_idx": min_idx,
                "contact_position_mm": contact_position,
                "min_position_mm": min_position,
                "depth_mm": max(0.0, contact_position - min_position),
                "contact_force_kn": float(force.iloc[contact_idx]),
                "max_force_kn": force_max,
                "contact_temperature_c": float(temp.iloc[contact_idx]) if not temp.dropna().empty else float("nan"),
                "force_threshold_kn": threshold,
                "source_file": raw_path.name,
                "hit": infer_hit_number_from_name(raw_path),
                "curve_rows": len(raw),
                "temperature_mean_c": float(temp.mean()) if not temp.dropna().empty else float("nan"),
            }
        )
    if not rows:
        raise FileNotFoundError(f"No raw AF hit CSV files found in {raw_af_dir}")
    return pd.DataFrame(rows).sort_values("hit").reset_index(drop=True)


def rotation_matrix(rx_deg: float = 25.0, rz_deg: float = -38.0) -> np.ndarray:
    """Return a simple X/Z rotation matrix for static projection."""
    rx = math.radians(rx_deg)
    rz = math.radians(rz_deg)
    rot_x = np.array(
        [
            [1, 0, 0],
            [0, math.cos(rx), -math.sin(rx)],
            [0, math.sin(rx), math.cos(rx)],
        ]
    )
    rot_z = np.array(
        [
            [math.cos(rz), -math.sin(rz), 0],
            [math.sin(rz), math.cos(rz), 0],
            [0, 0, 1],
        ]
    )
    return rot_z @ rot_x


def project_points(points: np.ndarray, width: int, height: int, margin: int = 70) -> np.ndarray:
    """Project 3D points into a 2D image frame."""
    xy = points[:, :2]
    low = xy.min(axis=0)
    high = xy.max(axis=0)
    span = np.maximum(high - low, 1e-9)
    scale = min((width - 2 * margin) / span[0], (height - 2 * margin) / span[1])
    projected = (xy - low) * scale + margin
    projected[:, 1] = height - projected[:, 1]
    return projected


def cylinder_mesh(length_min: float, length_max: float, radius: float) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Create wireframe points and edges for a cylinder."""
    axial_values = np.linspace(length_min, length_max, 24)
    angles = np.linspace(0.0, 2.0 * math.pi, 32, endpoint=False)
    points = []
    for x in axial_values:
        for theta in angles:
            points.append([x, radius * math.cos(theta), radius * math.sin(theta)])

    edges: list[tuple[int, int]] = []
    n_angles = len(angles)
    for i in range(len(axial_values)):
        base = i * n_angles
        for j in range(n_angles):
            edges.append((base + j, base + ((j + 1) % n_angles)))
            if i < len(axial_values) - 1 and j % 4 == 0:
                edges.append((base + j, base + n_angles + j))
    return np.asarray(points, dtype=float), edges


def save_static_hit_map_png(mapped_hits: pd.DataFrame, output_png: str | Path, config: HitMapConfig) -> Path:
    """Save a static 3D-style PNG of the cylindrical stock and hit points."""
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1500, 950
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(34)
    label_font = load_font(18)
    small_font = load_font(14)

    radius = 0.5 * config.stock_diameter_mm
    x_min = float(mapped_hits["axial_mm"].min()) - config.extra_bar_behind_start_mm
    x_max = float(mapped_hits["axial_mm"].max()) + config.extra_bar_after_end_mm
    cyl_points, cyl_edges = cylinder_mesh(x_min, x_max, radius)
    hit_points = mapped_hits[["axial_mm", "surface_y_mm", "surface_z_mm"]].to_numpy(dtype=float)

    rot = rotation_matrix()
    all_rotated = np.vstack([cyl_points, hit_points]) @ rot.T
    projected = project_points(all_rotated, width, height)
    cyl_projected = projected[: len(cyl_points)]
    hit_projected = projected[len(cyl_points) :]

    draw.text((70, 34), "3D Hit Map on 1 in Cylindrical Stock", fill=(28, 35, 50), font=title_font)
    draw.text(
        (70, 80),
        "Markers follow hit order; color is contact temperature and marker size is hit depth.",
        fill=(75, 85, 99),
        font=label_font,
    )

    for i0, i1 in cyl_edges:
        draw.line((*cyl_projected[i0], *cyl_projected[i1]), fill=(195, 204, 217), width=1)

    temps = pd.to_numeric(mapped_hits["contact_temperature_c"], errors="coerce")
    tmin, tmax = float(temps.min()), float(temps.max())
    for idx, row in mapped_hits.iterrows():
        px, py = hit_projected[idx]
        temp_norm = (float(row["contact_temperature_c"]) - tmin) / max(tmax - tmin, 1e-9)
        color = (
            int(46 + 196 * temp_norm),
            int(116 - 44 * temp_norm),
            int(190 - 150 * temp_norm),
        )
        marker_r = 5 + int(2.2 * float(row["depth_mm"]))
        draw.ellipse((px - marker_r, py - marker_r, px + marker_r, py + marker_r), fill=color, outline="white", width=2)
        draw.text((px + marker_r + 3, py - 7), str(int(row["hit"])), fill=(31, 41, 55), font=small_font)

    legend_x, legend_y = width - 360, 120
    draw.rectangle((legend_x, legend_y, width - 70, legend_y + 146), fill=(250, 252, 255), outline=(203, 213, 225))
    draw.text((legend_x + 18, legend_y + 18), "Map Encoding", fill=(31, 41, 55), font=label_font)
    draw.text((legend_x + 18, legend_y + 54), f"Stock diameter: {config.stock_diameter_mm:.1f} mm", fill=(75, 85, 99), font=small_font)
    draw.text((legend_x + 18, legend_y + 78), f"Lead-in bar: {config.extra_bar_behind_start_mm:.1f} mm before hit 0", fill=(75, 85, 99), font=small_font)
    draw.text((legend_x + 18, legend_y + 102), f"Temperature: {tmin:.0f}-{tmax:.0f} C", fill=(75, 85, 99), font=small_font)

    output_png.write_bytes(b"")
    image.save(output_png)
    return output_png


def save_interactive_hit_map_html(mapped_hits: pd.DataFrame, output_html: str | Path, config: HitMapConfig) -> Path:
    """Save a dependency-free interactive HTML canvas view."""
    output_html = Path(output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    radius = 0.5 * config.stock_diameter_mm
    x_min = float(mapped_hits["axial_mm"].min()) - config.extra_bar_behind_start_mm
    x_max = float(mapped_hits["axial_mm"].max()) + config.extra_bar_after_end_mm
    hits_json = mapped_hits.to_dict(orient="records")
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>3D AF Hit Map</title>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; color: #172033; background: #f5f7fb; }}
    header {{ padding: 20px 28px; background: white; border-bottom: 1px solid #d8dee9; }}
    h1 {{ margin: 0; font-size: 28px; }}
    .wrap {{ display: grid; grid-template-columns: 1fr 320px; gap: 18px; padding: 18px; }}
    canvas {{ width: 100%; height: 760px; background: white; border: 1px solid #d8dee9; }}
    aside {{ background: white; border: 1px solid #d8dee9; padding: 18px; }}
    label {{ display: block; margin: 14px 0 6px; font-weight: 600; }}
    input {{ width: 100%; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    td {{ padding: 5px 0; border-bottom: 1px solid #edf1f7; }}
    .muted {{ color: #667085; }}
  </style>
</head>
<body>
  <header>
    <h1>3D Hit Map on Cylindrical Stock</h1>
    <div class="muted">Axial position from the target-part butt reference; circumferential position from A angle.</div>
  </header>
  <div class="wrap">
    <canvas id="scene" width="1300" height="760"></canvas>
    <aside>
      <label for="rotZ">Rotate around stock axis</label>
      <input id="rotZ" type="range" min="-180" max="180" value="-28">
      <label for="rotY">Tilt</label>
      <input id="rotY" type="range" min="-85" max="85" value="22">
      <label for="zoom">Zoom</label>
      <input id="zoom" type="range" min="4" max="16" value="9">
      <h3>Geometry</h3>
      <table>
        <tr><td>Stock diameter</td><td>{config.stock_diameter_mm:.2f} mm</td></tr>
        <tr><td>Extra bar before hit 0</td><td>{config.extra_bar_behind_start_mm:.2f} mm</td></tr>
        <tr><td>Mapped hits</td><td>{len(mapped_hits)}</td></tr>
        <tr><td>Axial range</td><td>{x_min:.1f} to {x_max:.1f} mm</td></tr>
      </table>
      <p class="muted">Marker size scales with depth. Marker color scales with contact temperature. Hover-style labels are shown directly as hit numbers.</p>
    </aside>
  </div>
<script>
const hits = {json.dumps(hits_json)};
const radius = {radius:.8f};
const xMin = {x_min:.8f};
const xMax = {x_max:.8f};
const canvas = document.getElementById('scene');
const ctx = canvas.getContext('2d');
const rotZ = document.getElementById('rotZ');
const rotY = document.getElementById('rotY');
const zoom = document.getElementById('zoom');
const temps = hits.map(h => h.contact_temperature_c);
const tMin = Math.min(...temps), tMax = Math.max(...temps);

function colorForTemp(t) {{
  const n = (t - tMin) / Math.max(tMax - tMin, 1e-9);
  return `rgb(${{Math.round(46 + 196*n)}},${{Math.round(116 - 44*n)}},${{Math.round(190 - 150*n)}})`;
}}
function rotate(p) {{
  const rz = Number(rotZ.value) * Math.PI / 180;
  const ry = Number(rotY.value) * Math.PI / 180;
  let [x, y, z] = p;
  let y1 = y * Math.cos(rz) - z * Math.sin(rz);
  let z1 = y * Math.sin(rz) + z * Math.cos(rz);
  let x2 = x * Math.cos(ry) + z1 * Math.sin(ry);
  let z2 = -x * Math.sin(ry) + z1 * Math.cos(ry);
  return [x2, y1, z2];
}}
function project(p) {{
  const r = rotate(p);
  const s = Number(zoom.value);
  return [canvas.width / 2 + r[0] * s, canvas.height / 2 - r[1] * s, r[2]];
}}
function draw() {{
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = '#ccd6e3';
  ctx.lineWidth = 1;
  const nX = 28, nA = 36;
  for (let i=0; i<nX; i++) {{
    const x = xMin + (xMax - xMin) * i / (nX - 1);
    let prev = null;
    for (let j=0; j<=nA; j++) {{
      const a = 2*Math.PI*j/nA;
      const p = project([x, radius*Math.cos(a), radius*Math.sin(a)]);
      if (prev) {{ ctx.beginPath(); ctx.moveTo(prev[0], prev[1]); ctx.lineTo(p[0], p[1]); ctx.stroke(); }}
      prev = p;
    }}
  }}
  for (let j=0; j<nA; j+=4) {{
    const a = 2*Math.PI*j/nA;
    let prev = null;
    for (let i=0; i<nX; i++) {{
      const x = xMin + (xMax - xMin) * i / (nX - 1);
      const p = project([x, radius*Math.cos(a), radius*Math.sin(a)]);
      if (prev) {{ ctx.beginPath(); ctx.moveTo(prev[0], prev[1]); ctx.lineTo(p[0], p[1]); ctx.stroke(); }}
      prev = p;
    }}
  }}
  const sorted = hits.slice().sort((a,b) => project([a.axial_mm,a.surface_y_mm,a.surface_z_mm])[2] - project([b.axial_mm,b.surface_y_mm,b.surface_z_mm])[2]);
  for (const h of sorted) {{
    const p = project([h.axial_mm, h.surface_y_mm, h.surface_z_mm]);
    const r = 5 + 1.8 * h.depth_mm;
    ctx.fillStyle = colorForTemp(h.contact_temperature_c);
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 2*Math.PI); ctx.fill(); ctx.stroke();
    ctx.fillStyle = '#1f2937';
    ctx.font = '12px Segoe UI, Arial';
    ctx.fillText(String(h.hit), p[0] + r + 3, p[1] - 4);
  }}
  ctx.fillStyle = '#475467';
  ctx.font = '15px Segoe UI, Arial';
  ctx.fillText('Extra cylindrical stock before hit 0 is included from x = ' + xMin.toFixed(1) + ' mm to 0 mm.', 28, canvas.height - 28);
}}
for (const el of [rotZ, rotY, zoom]) el.addEventListener('input', draw);
draw();
</script>
</body>
</html>
"""
    output_html.write_text(page, encoding="utf-8")
    return output_html


def build_hit_map_3d(
    raw_af_dir: str | Path = DEFAULT_RAW_AF_DIR,
    analysis_dir: str | Path = DEFAULT_ANALYSIS_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    stock_diameter_mm: float | None = None,
    extra_bar_behind_start_mm: float = 30.0,
) -> dict[str, str]:
    """Build CSV, PNG, and HTML outputs for a 3D hit map."""
    raw_af_dir = Path(raw_af_dir)
    analysis_dir = Path(analysis_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = HitMapConfig(
        stock_diameter_mm=stock_diameter_mm or infer_stock_diameter_mm(raw_af_dir),
        extra_bar_behind_start_mm=extra_bar_behind_start_mm,
    )
    mapped_hits = extract_hit_surface_points(raw_af_dir, analysis_dir, config)

    output_csv = output_dir / "hit_surface_points_3d.csv"
    output_png = output_dir / "hit_map_3d.png"
    output_html = output_dir / "hit_map_3d.html"
    output_json = output_dir / "hit_map_3d_config.json"

    mapped_hits.to_csv(output_csv, index=False)
    save_static_hit_map_png(mapped_hits, output_png, config)
    save_interactive_hit_map_html(mapped_hits, output_html, config)
    output_json.write_text(
        json.dumps(
            {
                "config": asdict(config),
                "raw_af_dir": str(raw_af_dir),
                "analysis_dir": str(analysis_dir),
                "output_dir": str(output_dir),
                "note": "Hit points are mapped using axial position and A angle from the raw AF files.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "hit_surface_points_csv": str(output_csv),
        "hit_map_png": str(output_png),
        "hit_map_html": str(output_html),
        "hit_map_config": str(output_json),
        "mapped_hit_count": str(len(mapped_hits)),
    }


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Create a 3D AF hit map on cylindrical stock.")
    parser.add_argument("--raw-af-dir", default=DEFAULT_RAW_AF_DIR)
    parser.add_argument("--analysis-dir", default=DEFAULT_ANALYSIS_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stock-diameter-mm", type=float)
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
