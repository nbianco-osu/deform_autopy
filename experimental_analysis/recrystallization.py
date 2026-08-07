"""
Recrystallization indicators from AF effective stress-strain curves.

For hot deformation, dynamic recrystallization is commonly associated with a
peak in flow stress followed by softening toward a steady state. These functions
do not claim definitive metallographic proof; they produce defensible indicators
that should be validated against microstructure characterization and DEFORM JMAK
outputs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .schema import RecrystallizationConfig


def _linear_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Return least-squares slope, or NaN when too few points are available."""
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 2:
        return float("nan")
    if float(np.nanmax(x[valid]) - np.nanmin(x[valid])) <= 1e-12:
        return 0.0
    return float(np.polyfit(x[valid], y[valid], deg=1)[0])


def detect_recrystallization_from_curve(
    curve: pd.DataFrame,
    config: RecrystallizationConfig | None = None,
) -> dict[str, float | bool | str]:
    """Classify likely recrystallization from one stress-strain curve."""
    config = config or RecrystallizationConfig()
    stress = pd.to_numeric(curve["effective_stress_mpa"], errors="coerce").to_numpy(dtype=float)
    strain = pd.to_numeric(curve["true_strain"], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(stress) & np.isfinite(strain)
    stress = stress[valid]
    strain = strain[valid]

    if len(stress) < max(config.min_post_peak_points + 2, 12):
        return {
            "rx_detected": False,
            "rx_confidence": 0.0,
            "rx_mode": "insufficient_data",
            "peak_stress_mpa": float("nan"),
            "peak_strain": float("nan"),
            "softening_fraction": float("nan"),
            "terminal_slope_mpa_per_strain": float("nan"),
        }

    peak_idx = int(np.nanargmax(stress))
    peak_stress = float(stress[peak_idx])
    terminal_window = max(config.min_post_peak_points, len(stress) // 5)
    terminal_stress = float(np.nanmedian(stress[-terminal_window:]))
    softening_fraction = (peak_stress - terminal_stress) / max(abs(peak_stress), 1e-9)
    terminal_slope = _linear_slope(strain[-terminal_window:], stress[-terminal_window:])
    initial_slope = abs(_linear_slope(strain[:terminal_window], stress[:terminal_window]))
    slope_ratio = abs(terminal_slope) / max(initial_slope, 1e-9)

    has_peak = peak_stress >= config.min_peak_stress_mpa and peak_idx < len(stress) - config.min_post_peak_points
    has_softening = softening_fraction >= config.min_softening_fraction
    near_steady_state = slope_ratio <= config.steady_state_slope_fraction

    if has_peak and has_softening and near_steady_state:
        mode = "probable_dynamic_recrystallization"
        confidence = min(1.0, 0.45 + 2.5 * softening_fraction + 0.20 * (1.0 - slope_ratio))
    elif has_peak and has_softening:
        mode = "possible_dynamic_recrystallization"
        confidence = min(0.75, 0.30 + 2.0 * softening_fraction)
    else:
        mode = "no_clear_recrystallization_signal"
        confidence = max(0.0, min(0.35, softening_fraction))

    return {
        "rx_detected": bool(mode.startswith("probable") or mode.startswith("possible")),
        "rx_confidence": float(confidence),
        "rx_mode": mode,
        "peak_stress_mpa": peak_stress,
        "peak_strain": float(strain[peak_idx]),
        "terminal_stress_mpa": terminal_stress,
        "softening_fraction": float(softening_fraction),
        "terminal_slope_mpa_per_strain": float(terminal_slope),
        "terminal_slope_ratio": float(slope_ratio),
    }


def analyze_curve_file(
    curve_csv: str | Path,
    config: RecrystallizationConfig | None = None,
) -> dict[str, float | bool | str]:
    """Analyze one saved stress-strain curve CSV."""
    curve_csv = Path(curve_csv)
    curve = pd.read_csv(curve_csv)
    result = detect_recrystallization_from_curve(curve, config=config)
    result["curve_file"] = curve_csv.name
    if "hit" in curve.columns and not curve.empty:
        result["hit"] = curve["hit"].iloc[0]
    return result


def analyze_curve_folder(
    curve_dir: str | Path,
    output_csv: str | Path | None = None,
    config: RecrystallizationConfig | None = None,
) -> pd.DataFrame:
    """Analyze every saved stress-strain curve in a folder."""
    curve_dir = Path(curve_dir)
    rows = [
        analyze_curve_file(path, config=config)
        for path in sorted(curve_dir.glob("*_stress_strain.csv"))
    ]
    result = pd.DataFrame(rows)
    if output_csv is not None:
        Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(output_csv, index=False)
    return result
