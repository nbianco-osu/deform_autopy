"""
Microstructure evolution from AF thermal history plus deformation history.

This module couples two existing experimental-analysis products:

1. `induction_heating_temperature_time_trace.csv`
   - reconstructed temperature versus global/process time, including initial
     heat, within-hit thermal traces, inferred reheats, and final quench.
2. `stress_strain_curves/*_stress_strain.csv`
   - deformation summaries for each hit: strain, strain rate, and temperature.

The model is intentionally event based. Dynamic recrystallization is evaluated
at each hit from the deformation state. Static/metadynamic recrystallization is
then evaluated over the thermal interval until the next hit, using the mean
temperature over that interval. This is a screening model; the coefficients must
be calibrated before quantitative materials claims.
"""

from __future__ import annotations

import argparse
import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from .rex_kinetics import (
    MixedRecrystallizationParameters,
    dynamic_recrystallization_fraction,
    estimate_effective_strain_rate,
    metadynamic_recrystallization_fraction,
    static_recrystallization_fraction,
)


PLOT_WIDTH = 1200
PLOT_HEIGHT = 760
MARGIN_LEFT = 92
MARGIN_RIGHT = 280
MARGIN_TOP = 74
MARGIN_BOTTOM = 94
COLOR_TEXT = (31, 41, 55)
COLOR_GRID = (224, 231, 241)
COLOR_TEMP = (43, 109, 180)
COLOR_GRAIN = (42, 150, 105)
COLOR_REX = (126, 87, 194)
COLOR_HIT = (213, 107, 43)
COLOR_GRAY = (107, 114, 128)


@dataclass
class MicrostructureEvolutionConfig:
    """Settings for event-based microstructure evolution."""

    initial_grain_size_um: float = 26.3
    initial_recrystallized_fraction: float = 0.0
    apply_srx_during_preheat: bool = False
    apply_srx_during_quench: bool = False
    min_interval_s: float = 1e-6


def load_font(size: int) -> ImageFont.ImageFont:
    """Load a Windows font or fall back to Pillow's default."""
    for font in ["segoeui.ttf", "arial.ttf", "calibri.ttf"]:
        try:
            return ImageFont.truetype(font, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def curve_hit_number(curve: pd.DataFrame, path: Path) -> int | None:
    """Get the hit number from curve data or filename fallback."""
    if "hit" in curve.columns and not curve.empty:
        try:
            return int(curve["hit"].iloc[0])
        except Exception:
            pass
    import re

    matches = re.findall(r"(?:hit|h)[ _-]*(\d+)|(?:^|[_-])(\d+)(?:[_-]|$)", path.name, flags=re.I)
    values = [int(item) for match in matches for item in match if item]
    return values[-1] if values else None


def summarize_curve(curve_path: str | Path) -> dict[str, float | int | str]:
    """Summarize deformation conditions for one stress-strain curve."""
    curve_path = Path(curve_path)
    curve = pd.read_csv(curve_path)
    strain = pd.to_numeric(curve.get("true_strain", pd.Series(dtype=float)), errors="coerce")
    stress = pd.to_numeric(curve.get("effective_stress_mpa", pd.Series(dtype=float)), errors="coerce")
    temp = pd.to_numeric(curve.get("temperature_c", pd.Series(dtype=float)), errors="coerce")
    return {
        "hit": curve_hit_number(curve, curve_path),
        "curve_file": curve_path.name,
        "strain_final": float(strain.max()) if not strain.dropna().empty else float("nan"),
        "strain_rate_s": estimate_effective_strain_rate(curve),
        "temperature_c": float(temp.median()) if not temp.dropna().empty else float("nan"),
        "temperature_max_c": float(temp.max()) if not temp.dropna().empty else float("nan"),
        "peak_stress_mpa": float(stress.max()) if not stress.dropna().empty else float("nan"),
    }


def load_deformation_summary(curve_dir: str | Path) -> pd.DataFrame:
    """Load deformation summaries from all processed stress-strain curves."""
    curve_dir = Path(curve_dir)
    rows = [summarize_curve(path) for path in sorted(curve_dir.glob("*_stress_strain.csv"))]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["hit_sort"] = pd.to_numeric(df["hit"], errors="coerce")
        df = df.sort_values(["hit_sort", "curve_file"]).reset_index(drop=True)
    return df


def load_hit_contact_times(timeline: pd.DataFrame) -> pd.DataFrame:
    """Read contact temperature marker times from an induction timeline."""
    contacts = timeline[timeline["trace_type"] == "recorded_hit"].copy()
    if contacts.empty:
        raise ValueError("Temperature timeline does not contain recorded_hit rows.")
    contacts["hit"] = contacts["hit"].astype(str)
    contacts["hit_sort"] = pd.to_numeric(contacts["hit"], errors="coerce")
    contacts["time_s"] = pd.to_numeric(contacts["time_s"], errors="coerce")
    contacts["temperature_c"] = pd.to_numeric(contacts["temperature_c"], errors="coerce")
    return contacts.dropna(subset=["time_s"]).sort_values(["hit_sort", "time_s"]).reset_index(drop=True)


def interval_temperature(
    timeline: pd.DataFrame,
    start_time_s: float,
    end_time_s: float,
) -> dict[str, float]:
    """Summarize temperature over a timeline interval."""
    if end_time_s <= start_time_s:
        return {
            "interval_time_s": 0.0,
            "interval_temperature_mean_c": float("nan"),
            "interval_temperature_max_c": float("nan"),
            "interval_temperature_min_c": float("nan"),
        }
    times = pd.to_numeric(timeline["time_s"], errors="coerce")
    temps = pd.to_numeric(timeline["temperature_c"], errors="coerce")
    mask = (times >= start_time_s) & (times <= end_time_s) & np.isfinite(temps)
    values = temps[mask]
    if values.empty:
        mid = 0.5 * (start_time_s + end_time_s)
        nearest_idx = (times - mid).abs().idxmin()
        values = pd.Series([temps.loc[nearest_idx]])
    return {
        "interval_time_s": float(end_time_s - start_time_s),
        "interval_temperature_mean_c": float(values.mean()),
        "interval_temperature_max_c": float(values.max()),
        "interval_temperature_min_c": float(values.min()),
    }


def combine_fraction(existing: float, new_fraction: float) -> float:
    """Combine recrystallized fractions without exceeding one."""
    existing = 0.0 if not np.isfinite(existing) else float(existing)
    new_fraction = 0.0 if not np.isfinite(new_fraction) else float(new_fraction)
    return min(1.0, existing + (1.0 - existing) * max(0.0, min(1.0, new_fraction)))


def mix_grain_size(current_grain_um: float, new_grain_um: float, fraction: float) -> float:
    """Mix grain size toward a transformed grain size by a fraction."""
    if not np.isfinite(new_grain_um) or new_grain_um <= 0:
        return float(current_grain_um)
    fraction = max(0.0, min(1.0, float(fraction)))
    return float((1.0 - fraction) * current_grain_um + fraction * new_grain_um)


def run_microstructure_evolution(
    curve_dir: str | Path,
    temperature_time_trace_csv: str | Path,
    output_dir: str | Path,
    config: MicrostructureEvolutionConfig | None = None,
    params: MixedRecrystallizationParameters | None = None,
) -> dict[str, str]:
    """Run event-based microstructure evolution from temperature and strain."""
    config = config or MicrostructureEvolutionConfig()
    params = params or MixedRecrystallizationParameters(initial_grain_size_um=config.initial_grain_size_um)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timeline = pd.read_csv(temperature_time_trace_csv)
    deformation = load_deformation_summary(curve_dir)
    contacts = load_hit_contact_times(timeline)
    if deformation.empty:
        raise ValueError(f"No stress-strain curve files found in {curve_dir}.")

    deformation["hit_key"] = deformation["hit"].astype(str)
    contacts["hit_key"] = contacts["hit"].astype(str)
    hit_table = contacts.merge(deformation, on="hit_key", how="left", suffixes=("_contact", ""))
    hit_table = hit_table.sort_values(["time_s", "hit_sort_contact"]).reset_index(drop=True)

    grain_um = float(config.initial_grain_size_um)
    rex_fraction = float(config.initial_recrystallized_fraction)
    rows = [
        {
            "time_s": float(pd.to_numeric(timeline["time_s"], errors="coerce").min()),
            "event_type": "initial_state",
            "hit": "",
            "grain_size_um": grain_um,
            "recrystallized_fraction": rex_fraction,
            "temperature_c": float(pd.to_numeric(timeline["temperature_c"], errors="coerce").iloc[0]),
            "notes": "Initial room-temperature supplier state.",
        }
    ]

    for index, hit in hit_table.iterrows():
        hit_id = hit["hit_key"]
        hit_time = float(hit["time_s"])
        strain = float(hit.get("strain_final", np.nan))
        strain_rate = float(hit.get("strain_rate_s", np.nan))
        hit_temp = float(hit.get("temperature_c", np.nan))
        if not np.isfinite(hit_temp):
            hit_temp = float(hit["temperature_c_contact"])

        drx = dynamic_recrystallization_fraction(strain, strain_rate, hit_temp, params.drx)
        drx_fraction = float(drx["drx_fraction"])
        rex_fraction = combine_fraction(rex_fraction, drx_fraction)
        grain_um = mix_grain_size(grain_um, float(drx["drx_rex_grain_um"]), drx_fraction)
        rows.append(
            {
                "time_s": hit_time,
                "event_type": "hit_drx",
                "hit": hit_id,
                "grain_size_um": grain_um,
                "recrystallized_fraction": rex_fraction,
                "temperature_c": hit_temp,
                "strain_final": strain,
                "strain_rate_s": strain_rate,
                "drx_fraction_increment": drx_fraction,
                "srx_fraction_increment": 0.0,
                "mdrx_fraction_increment": 0.0,
                "critical_strain": drx["critical_strain"],
                "zener_hollomon": drx["zener_hollomon"],
                "notes": "Dynamic recrystallization evaluated at hit deformation.",
            }
        )

        if index < len(hit_table) - 1:
            next_time = float(hit_table.iloc[index + 1]["time_s"])
            interval_type = "interpass"
        else:
            quench_rows = timeline[timeline["trace_type"].astype(str).str.contains("quench", na=False)]
            next_time = float(pd.to_numeric(timeline["time_s"], errors="coerce").max())
            interval_type = "post_hit_quench" if not quench_rows.empty else "post_hit"

        interval = interval_temperature(timeline, hit_time, next_time)
        dt = max(float(interval["interval_time_s"]), 0.0)
        interval_temp = float(interval["interval_temperature_mean_c"])
        apply_static = dt >= config.min_interval_s and (
            interval_type == "interpass"
            or (interval_type == "post_hit_quench" and config.apply_srx_during_quench)
        )
        if apply_static and np.isfinite(interval_temp):
            srx = static_recrystallization_fraction(
                time_s=dt,
                strain=strain,
                strain_rate_s=strain_rate,
                temperature_c=interval_temp,
                initial_grain_um=grain_um,
                params=params.srx,
                zener=float(drx["zener_hollomon"]),
            )
            mdrx = metadynamic_recrystallization_fraction(
                time_s=dt,
                strain=strain,
                strain_rate_s=strain_rate,
                temperature_c=interval_temp,
                initial_grain_um=grain_um,
                drx_active=bool(drx["drx_active"]),
                params=params.mdrx,
            )
            mdrx_inc = (1.0 - drx_fraction) * float(mdrx["mdrx_fraction"])
            srx_inc = (1.0 - drx_fraction - mdrx_inc) * float(srx["srx_fraction"])
            static_inc = max(0.0, min(1.0, mdrx_inc + srx_inc))
            rex_fraction = combine_fraction(rex_fraction, static_inc)
            grain_um = mix_grain_size(grain_um, float(srx["srx_rex_grain_um"]), static_inc)
            rows.append(
                {
                    "time_s": next_time,
                    "event_type": f"{interval_type}_srx_mdrx",
                    "hit": hit_id,
                    "grain_size_um": grain_um,
                    "recrystallized_fraction": rex_fraction,
                    "temperature_c": interval_temp,
                    "interval_time_s": dt,
                    "interval_temperature_mean_c": interval_temp,
                    "interval_temperature_max_c": interval["interval_temperature_max_c"],
                    "interval_temperature_min_c": interval["interval_temperature_min_c"],
                    "strain_final": strain,
                    "strain_rate_s": strain_rate,
                    "drx_fraction_increment": 0.0,
                    "srx_fraction_increment": srx_inc,
                    "mdrx_fraction_increment": mdrx_inc,
                    "srx_t05_s": srx["srx_t05_s"],
                    "mdrx_t05_s": mdrx["mdrx_t05_s"],
                    "notes": "Static/metadynamic recrystallization evaluated over thermal interval.",
                }
            )
        elif interval_type == "post_hit_quench":
            rows.append(
                {
                    "time_s": next_time,
                    "event_type": "quench_end",
                    "hit": hit_id,
                    "grain_size_um": grain_um,
                    "recrystallized_fraction": rex_fraction,
                    "temperature_c": float(pd.to_numeric(timeline["temperature_c"], errors="coerce").iloc[-1]),
                    "interval_time_s": dt,
                    "notes": "Quench segment appended; SRX during quench disabled by default.",
                }
            )

    output_csv = output_dir / "microstructure_evolution.csv"
    parameters_json = output_dir / "microstructure_evolution_parameters.json"
    plot_png = output_dir / "microstructure_evolution.png"
    result = pd.DataFrame(rows)
    result.to_csv(output_csv, index=False)
    parameters_json.write_text(
        json.dumps(
            {
                "config": asdict(config),
                "rex_parameters": asdict(params),
                "temperature_time_trace_csv": str(temperature_time_trace_csv),
                "curve_dir": str(curve_dir),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    save_microstructure_evolution_plot(result, plot_png)
    summary_json = output_dir / "microstructure_evolution_summary.json"
    outputs = {
        "microstructure_evolution_csv": str(output_csv),
        "microstructure_evolution_plot": str(plot_png),
        "microstructure_evolution_parameters": str(parameters_json),
        "microstructure_evolution_rows": str(len(result)),
        "final_grain_size_um": f"{float(result['grain_size_um'].dropna().iloc[-1]):.6g}",
        "final_recrystallized_fraction": f"{float(result['recrystallized_fraction'].dropna().iloc[-1]):.6g}",
    }
    summary_json.write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    outputs["microstructure_evolution_summary"] = str(summary_json)
    return outputs


def calibrate_srx_grain_prefactor_to_final_size(
    curve_dir: str | Path,
    temperature_time_trace_csv: str | Path,
    output_dir: str | Path,
    target_final_grain_size_um: float,
    config: MicrostructureEvolutionConfig | None = None,
    params: MixedRecrystallizationParameters | None = None,
    scale_bounds: tuple[float, float] = (0.05, 50.0),
    max_iterations: int = 32,
    tolerance_um: float = 0.01,
) -> dict[str, str | float]:
    """
    Calibrate the SRX recrystallized grain-size prefactor to a measured final grain size.

    This single-parameter calibration is intentionally conservative: it leaves
    the time/temperature sensitivity and Avrami exponents unchanged, then scales
    only the grain size produced by SRX. For the AF Box_1in case, this is the
    least invasive parameter that can reconcile the model with a final average
    grain size larger than the supplier initial grain size.
    """
    if target_final_grain_size_um <= 0:
        raise ValueError("target_final_grain_size_um must be positive.")

    config = config or MicrostructureEvolutionConfig()
    base_params = copy.deepcopy(params or MixedRecrystallizationParameters(initial_grain_size_um=config.initial_grain_size_um))
    base_prefactor = float(base_params.srx.srx_grain_prefactor)
    low, high = scale_bounds
    evaluations: list[dict[str, float]] = []

    def evaluate(scale: float, scratch_root: Path) -> float:
        trial_params = copy.deepcopy(base_params)
        trial_params.srx.srx_grain_prefactor = base_prefactor * scale
        trial_params.preset_name = f"{base_params.preset_name}_srx_grain_scale_{scale:.6g}"
        trial_dir = scratch_root / f"scale_{scale:.8g}".replace(".", "p")
        outputs = run_microstructure_evolution(
            curve_dir=curve_dir,
            temperature_time_trace_csv=temperature_time_trace_csv,
            output_dir=trial_dir,
            config=config,
            params=trial_params,
        )
        final_grain = float(outputs["final_grain_size_um"])
        evaluations.append(
            {
                "srx_grain_prefactor_scale": float(scale),
                "srx_grain_prefactor": float(trial_params.srx.srx_grain_prefactor),
                "final_grain_size_um": final_grain,
                "error_um": final_grain - target_final_grain_size_um,
                "abs_error_um": abs(final_grain - target_final_grain_size_um),
            }
        )
        return final_grain

    with TemporaryDirectory() as tmp:
        scratch_root = Path(tmp)
        low_value = evaluate(low, scratch_root)
        high_value = evaluate(high, scratch_root)
        if not (min(low_value, high_value) <= target_final_grain_size_um <= max(low_value, high_value)):
            raise ValueError(
                "The target final grain size is outside the calibration bounds. "
                f"Bounds gave {low_value:.6g} to {high_value:.6g} um for scales {low:g} to {high:g}."
            )

        for _ in range(max_iterations):
            mid = 0.5 * (low + high)
            mid_value = evaluate(mid, scratch_root)
            if abs(mid_value - target_final_grain_size_um) <= tolerance_um:
                low = high = mid
                break
            if (low_value - target_final_grain_size_um) * (mid_value - target_final_grain_size_um) <= 0:
                high = mid
                high_value = mid_value
            else:
                low = mid
                low_value = mid_value

    best = min(evaluations, key=lambda row: row["abs_error_um"])
    calibrated_params = copy.deepcopy(base_params)
    calibrated_params.srx.srx_grain_prefactor = float(best["srx_grain_prefactor"])
    calibrated_params.preset_name = (
        f"{base_params.preset_name}_calibrated_final_grain_{target_final_grain_size_um:.6g}um"
    )
    outputs = run_microstructure_evolution(
        curve_dir=curve_dir,
        temperature_time_trace_csv=temperature_time_trace_csv,
        output_dir=output_dir,
        config=config,
        params=calibrated_params,
    )

    output_dir = Path(output_dir)
    calibration_csv = output_dir / "microstructure_evolution_calibration.csv"
    calibration_json = output_dir / "microstructure_evolution_calibration.json"
    pd.DataFrame(evaluations).sort_values("abs_error_um").to_csv(calibration_csv, index=False)
    calibration_summary = {
        "target_final_grain_size_um": float(target_final_grain_size_um),
        "calibrated_parameter": "srx.srx_grain_prefactor",
        "base_srx_grain_prefactor": base_prefactor,
        "calibrated_srx_grain_prefactor": float(best["srx_grain_prefactor"]),
        "srx_grain_prefactor_scale": float(best["srx_grain_prefactor_scale"]),
        "final_grain_size_um": float(outputs["final_grain_size_um"]),
        "error_um": float(outputs["final_grain_size_um"]) - float(target_final_grain_size_um),
        "tolerance_um": float(tolerance_um),
        "calibration_csv": str(calibration_csv),
    }
    calibration_json.write_text(json.dumps(calibration_summary, indent=2), encoding="utf-8")
    outputs.update(
        {
            "calibration_csv": str(calibration_csv),
            "calibration_summary": str(calibration_json),
            "target_final_grain_size_um": f"{target_final_grain_size_um:.6g}",
            "srx_grain_prefactor_scale": f"{best['srx_grain_prefactor_scale']:.8g}",
            "calibrated_srx_grain_prefactor": f"{best['srx_grain_prefactor']:.8g}",
        }
    )
    return outputs


def scale_xy(x: float, y: float, x_bounds: tuple[float, float], y_bounds: tuple[float, float]) -> tuple[int, int]:
    """Map data coordinates to pixels."""
    left = MARGIN_LEFT
    right = PLOT_WIDTH - MARGIN_RIGHT
    top = MARGIN_TOP
    bottom = PLOT_HEIGHT - MARGIN_BOTTOM
    xp = left + (x - x_bounds[0]) / max(x_bounds[1] - x_bounds[0], 1e-9) * (right - left)
    yp = bottom - (y - y_bounds[0]) / max(y_bounds[1] - y_bounds[0], 1e-9) * (bottom - top)
    return int(round(xp)), int(round(yp))


def numeric_bounds(values: pd.Series | np.ndarray, pad_fraction: float = 0.08) -> tuple[float, float]:
    """Return padded numeric bounds."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return 0.0, 1.0
    low = float(arr.min())
    high = float(arr.max())
    if low == high:
        return low - 1.0, high + 1.0
    pad = (high - low) * pad_fraction
    return low - pad, high + pad


def draw_axes(draw: ImageDraw.ImageDraw, x_bounds: tuple[float, float], y_bounds: tuple[float, float], y_label: str) -> None:
    """Draw grid and tick labels."""
    tick_font = load_font(14)
    left = MARGIN_LEFT
    right = PLOT_WIDTH - MARGIN_RIGHT
    top = MARGIN_TOP
    bottom = PLOT_HEIGHT - MARGIN_BOTTOM
    for step in range(6):
        fraction = step / 5.0
        gx = int(left + fraction * (right - left))
        gy = int(bottom - fraction * (bottom - top))
        x_value = x_bounds[0] + fraction * (x_bounds[1] - x_bounds[0])
        y_value = y_bounds[0] + fraction * (y_bounds[1] - y_bounds[0])
        draw.line((gx, top, gx, bottom), fill=COLOR_GRID)
        draw.line((left, gy, right, gy), fill=COLOR_GRID)
        draw.text((gx - 20, bottom + 12), f"{x_value:.0f}", fill=COLOR_GRAY, font=tick_font)
        draw.text((left - 72, gy - 8), f"{y_value:.1f}", fill=COLOR_GRAY, font=tick_font)
    draw.rectangle((left, top, right, bottom), outline=(156, 163, 175), width=2)
    draw.text((18, PLOT_HEIGHT // 2 - 18), y_label, fill=COLOR_TEXT, font=load_font(18))


def draw_line(
    draw: ImageDraw.ImageDraw,
    x: np.ndarray,
    y: np.ndarray,
    x_bounds: tuple[float, float],
    y_bounds: tuple[float, float],
    color: tuple[int, int, int],
    width: int = 3,
) -> None:
    """Draw a line from finite x/y arrays."""
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 2:
        return
    points = [scale_xy(float(xi), float(yi), x_bounds, y_bounds) for xi, yi in zip(x[valid], y[valid])]
    draw.line(points, fill=color, width=width)
    for xp, yp in points:
        draw.ellipse((xp - 4, yp - 4, xp + 4, yp + 4), fill=color, outline="white", width=1)


def save_microstructure_evolution_plot(evolution: pd.DataFrame, output_png: str | Path) -> Path:
    """Save grain-size and recrystallized-fraction evolution plots."""
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (PLOT_WIDTH, PLOT_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(28)
    label_font = load_font(18)
    small_font = load_font(14)
    draw.text((MARGIN_LEFT, 26), "Microstructure Evolution from Thermal and Deformation History", fill=COLOR_TEXT, font=title_font)
    draw.text((PLOT_WIDTH // 2 - 85, PLOT_HEIGHT - 44), "Time s", fill=COLOR_TEXT, font=label_font)

    x = pd.to_numeric(evolution["time_s"], errors="coerce").to_numpy(dtype=float)
    grain = pd.to_numeric(evolution["grain_size_um"], errors="coerce").to_numpy(dtype=float)
    rex = pd.to_numeric(evolution["recrystallized_fraction"], errors="coerce").to_numpy(dtype=float)
    x_bounds = numeric_bounds(x, pad_fraction=0.02)
    x_bounds = (max(0.0, x_bounds[0]), x_bounds[1])
    y_bounds = numeric_bounds(grain[np.isfinite(grain)])
    rex_bounds = (0.0, 1.0)

    draw_axes(draw, x_bounds, y_bounds, "grain size um")
    draw_line(draw, x, grain, x_bounds, y_bounds, COLOR_GRAIN, width=4)

    draw_line(draw, x, rex, x_bounds, rex_bounds, COLOR_REX, width=3)

    tick_font = load_font(14)
    right_axis_x = PLOT_WIDTH - MARGIN_RIGHT
    for step in range(6):
        fraction = step / 5.0
        y_value = rex_bounds[0] + fraction * (rex_bounds[1] - rex_bounds[0])
        _, gy = scale_xy(x_bounds[0], y_value, x_bounds, rex_bounds)
        draw.text((right_axis_x + 10, gy - 8), f"{y_value:.1f}", fill=COLOR_REX, font=tick_font)
    draw.text((right_axis_x + 46, PLOT_HEIGHT // 2 - 18), "recrystallized fraction", fill=COLOR_REX, font=load_font(18))

    hit_rows = evolution[evolution["event_type"].astype(str).str.contains("hit_drx", na=False)]
    for _, row in hit_rows.iterrows():
        px, _ = scale_xy(float(row["time_s"]), y_bounds[0], x_bounds, y_bounds)
        draw.line((px, MARGIN_TOP, px, PLOT_HEIGHT - MARGIN_BOTTOM), fill=(235, 187, 143), width=1)

    legend_x = PLOT_WIDTH - MARGIN_RIGHT + 72
    legend_y = MARGIN_TOP + 10
    draw.rectangle((legend_x - 12, legend_y - 10, PLOT_WIDTH - 24, legend_y + 84), fill="white", outline=(203, 213, 225))
    draw.line((legend_x, legend_y + 8, legend_x + 30, legend_y + 8), fill=COLOR_GRAIN, width=4)
    draw.text((legend_x + 40, legend_y), "grain size", fill=COLOR_TEXT, font=small_font)
    draw.line((legend_x, legend_y + 36, legend_x + 30, legend_y + 36), fill=COLOR_REX, width=3)
    draw.text((legend_x + 40, legend_y + 28), "recrystallized fraction", fill=COLOR_TEXT, font=small_font)
    draw.line((legend_x, legend_y + 64, legend_x + 30, legend_y + 64), fill=(235, 187, 143), width=2)
    draw.text((legend_x + 40, legend_y + 56), "hit event", fill=COLOR_TEXT, font=small_font)

    image.save(output_png)
    return output_png


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Run microstructure evolution from AF thermal and deformation history.")
    parser.add_argument("--curve-dir", required=True, help="Folder containing processed *_stress_strain.csv files.")
    parser.add_argument("--temperature-time-trace-csv", required=True, help="Induction-heating temperature time trace CSV.")
    parser.add_argument("--output-dir", required=True, help="Folder for microstructure evolution outputs.")
    parser.add_argument("--initial-grain-size-um", type=float, default=26.3)
    parser.add_argument("--initial-recrystallized-fraction", type=float, default=0.0)
    parser.add_argument("--apply-srx-during-quench", action="store_true")
    parser.add_argument("--target-final-grain-size-um", type=float)
    args = parser.parse_args()

    config = MicrostructureEvolutionConfig(
        initial_grain_size_um=args.initial_grain_size_um,
        initial_recrystallized_fraction=args.initial_recrystallized_fraction,
        apply_srx_during_quench=args.apply_srx_during_quench,
    )
    if args.target_final_grain_size_um:
        outputs = calibrate_srx_grain_prefactor_to_final_size(
            curve_dir=args.curve_dir,
            temperature_time_trace_csv=args.temperature_time_trace_csv,
            output_dir=args.output_dir,
            target_final_grain_size_um=args.target_final_grain_size_um,
            config=config,
        )
    else:
        outputs = run_microstructure_evolution(
            curve_dir=args.curve_dir,
            temperature_time_trace_csv=args.temperature_time_trace_csv,
            output_dir=args.output_dir,
            config=config,
        )
    print(json.dumps(outputs, indent=2))


if __name__ == "__main__":
    main()
