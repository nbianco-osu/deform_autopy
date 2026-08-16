"""
Mixed DRX, MDRX, and SRX recrystallization models.

This module provides compact, parameterized models that can be calibrated later
against DEFORM grain output and measured microstructure. The defaults are
literature-informed priors, not final 316L constants:

- DRX activation uses a Zener-Hollomon critical-strain screen.
- Dynamic recrystallization uses a Yada/Sellars strain-form Avrami equation.
- Static recrystallization uses Sellars-style t0.5 kinetics.
- Metadynamic recrystallization uses Yada/Senuma-style t0.5 kinetics.

The key design choice is transparency. Every coefficient is collected in a
dataclass and every output CSV records the model family so these results are
easy to audit and replace with calibrated constants.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .af_signal_processing import infer_hit_number


R_GAS_J_PER_MOL_K = 8.314462618


@dataclass
class DRXKineticsParameters:
    """Dynamic recrystallization activation and fraction parameters."""

    model_name: str = "zada_yada_316l_prior"
    deformation_activation_energy_j_mol: float = 460000.0
    critical_strain_prefactor: float = 0.009
    critical_strain_z_exponent: float = 0.084
    drx_avrami_exponent: float = 2.0
    drx_half_strain_factor: float = 1.8
    min_half_strain_offset: float = 0.02
    drx_grain_coefficient: float = 1.4e4
    drx_grain_z_exponent: float = -0.11
    min_rex_grain_um: float = 1.0


@dataclass
class SRXKineticsParameters:
    """Sellars-style static recrystallization kinetics."""

    model_name: str = "sellars_srx_generic_austenite"
    t05_prefactor_s: float = 2.5e-19
    strain_exponent: float = -4.0
    grain_size_exponent: float = 2.0
    strain_rate_exponent: float = 0.0
    zener_exponent: float = 0.0
    recrystallization_activation_energy_j_mol: float = 300000.0
    avrami_exponent: float = 1.7
    srx_grain_prefactor: float = 343.0
    srx_grain_initial_exponent: float = 0.4
    srx_grain_strain_exponent: float = 0.5
    srx_grain_activation_energy_j_mol: float = 45000.0


@dataclass
class MDRXKineticsParameters:
    """Yada/Senuma-style metadynamic recrystallization kinetics."""

    model_name: str = "yada_mdrx_prior"
    t05_prefactor_s: float = 1.73e-7
    strain_exponent: float = -0.33
    grain_size_exponent: float = 0.0
    strain_rate_exponent: float = 0.0
    mdrx_activation_energy_j_mol: float = 191000.0
    avrami_exponent: float = 0.5
    require_drx_activation: bool = True


@dataclass
class MixedRecrystallizationParameters:
    """Complete parameter set for mixed DRX/MDRX/SRX calculations."""

    preset_name: str = "316l_mixed_literature_prior"
    initial_grain_size_um: float = 26.3
    interpass_time_s: float = 1.0
    drx: DRXKineticsParameters = field(default_factory=DRXKineticsParameters)
    srx: SRXKineticsParameters = field(default_factory=SRXKineticsParameters)
    mdrx: MDRXKineticsParameters = field(default_factory=MDRXKineticsParameters)


def clip01(value: float) -> float:
    """Limit a fraction to [0, 1]."""
    if not np.isfinite(value):
        return float("nan")
    return float(min(1.0, max(0.0, value)))


def safe_positive(value: float, fallback: float = 1e-9) -> float:
    """Return a positive finite value for exponent/power-law calculations."""
    if value is None or not np.isfinite(value) or value <= 0:
        return float(fallback)
    return float(value)


def zener_hollomon(strain_rate_s: float, temperature_c: float, activation_energy_j_mol: float) -> float:
    """Compute the Zener-Hollomon parameter."""
    strain_rate_s = safe_positive(strain_rate_s)
    temperature_k = safe_positive(float(temperature_c) + 273.15, fallback=1.0)
    exponent = activation_energy_j_mol / (R_GAS_J_PER_MOL_K * temperature_k)
    return float(strain_rate_s * math.exp(min(exponent, 700.0)))


def critical_drx_strain(zener: float, params: DRXKineticsParameters) -> float:
    """Compute the critical strain for DRX activation."""
    return float(params.critical_strain_prefactor * safe_positive(zener) ** params.critical_strain_z_exponent)


def avrami_fraction(time_or_strain_ratio: float, exponent: float) -> float:
    """Generic Avrami fraction where ratio=1 gives 50 percent transformed."""
    ratio = safe_positive(time_or_strain_ratio, fallback=0.0)
    if ratio <= 0:
        return 0.0
    return clip01(1.0 - math.exp(-0.6931471805599453 * ratio ** exponent))


def estimate_effective_strain_rate(curve: pd.DataFrame) -> float:
    """Estimate a representative strain rate from a curve."""
    if "true_strain" not in curve.columns or "time_s" not in curve.columns:
        return float("nan")
    strain = pd.to_numeric(curve["true_strain"], errors="coerce").to_numpy(dtype=float)
    time = pd.to_numeric(curve["time_s"], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(strain) & np.isfinite(time)
    strain = strain[valid]
    time = time[valid]
    if len(strain) < 3:
        return float("nan")
    delta_strain = np.diff(strain)
    delta_time = np.diff(time)
    valid_rate = np.isfinite(delta_strain) & np.isfinite(delta_time) & (delta_time > 0)
    rates = delta_strain[valid_rate] / delta_time[valid_rate]
    rates = rates[np.isfinite(rates) & (rates > 0)]
    return float(np.nanmedian(rates)) if len(rates) else float("nan")


def summarize_curve_conditions(curve: pd.DataFrame) -> dict[str, float]:
    """Extract strain, strain-rate, temperature, and stress descriptors."""
    strain = pd.to_numeric(curve.get("true_strain", pd.Series(dtype=float)), errors="coerce")
    stress = pd.to_numeric(curve.get("effective_stress_mpa", pd.Series(dtype=float)), errors="coerce")
    temp = pd.to_numeric(curve.get("temperature_c", pd.Series(dtype=float)), errors="coerce")
    return {
        "strain_final": float(strain.max()) if not strain.dropna().empty else float("nan"),
        "strain_rate_s": estimate_effective_strain_rate(curve),
        "temperature_c": float(temp.median()) if not temp.dropna().empty else float("nan"),
        "temperature_max_c": float(temp.max()) if not temp.dropna().empty else float("nan"),
        "peak_stress_mpa": float(stress.max()) if not stress.dropna().empty else float("nan"),
    }


def dynamic_recrystallization_fraction(
    strain: float,
    strain_rate_s: float,
    temperature_c: float,
    params: DRXKineticsParameters,
) -> dict[str, float | bool]:
    """Compute DRX activation and fraction using a strain-form Avrami model."""
    zener = zener_hollomon(strain_rate_s, temperature_c, params.deformation_activation_energy_j_mol)
    epsilon_c = critical_drx_strain(zener, params)
    epsilon_half = max(
        params.drx_half_strain_factor * epsilon_c,
        epsilon_c + params.min_half_strain_offset,
    )
    if not np.isfinite(strain) or strain <= epsilon_c:
        fraction = 0.0
    else:
        ratio = (strain - epsilon_c) / max(epsilon_half - epsilon_c, 1e-9)
        fraction = avrami_fraction(ratio, params.drx_avrami_exponent)

    grain_um = params.drx_grain_coefficient * safe_positive(zener) ** params.drx_grain_z_exponent
    return {
        "drx_active": bool(strain > epsilon_c if np.isfinite(strain) else False),
        "zener_hollomon": zener,
        "critical_strain": epsilon_c,
        "drx_half_strain": epsilon_half,
        "drx_fraction": fraction,
        "drx_rex_grain_um": max(params.min_rex_grain_um, float(grain_um)),
    }


def static_recrystallization_fraction(
    time_s: float,
    strain: float,
    strain_rate_s: float,
    temperature_c: float,
    initial_grain_um: float,
    params: SRXKineticsParameters,
    zener: float | None = None,
) -> dict[str, float]:
    """Compute SRX fraction from Sellars-style t0.5 kinetics."""
    temperature_k = safe_positive(temperature_c + 273.15, fallback=1.0)
    strain = safe_positive(strain)
    strain_rate_s = safe_positive(strain_rate_s)
    initial_grain_um = safe_positive(initial_grain_um)
    zener = safe_positive(zener if zener is not None else 1.0)
    t05 = (
        params.t05_prefactor_s
        * strain ** params.strain_exponent
        * initial_grain_um ** params.grain_size_exponent
        * strain_rate_s ** params.strain_rate_exponent
        * zener ** params.zener_exponent
        * math.exp(min(params.recrystallization_activation_energy_j_mol / (R_GAS_J_PER_MOL_K * temperature_k), 700.0))
    )
    fraction = avrami_fraction(safe_positive(time_s, fallback=0.0) / max(t05, 1e-30), params.avrami_exponent)
    grain_um = (
        params.srx_grain_prefactor
        * initial_grain_um ** params.srx_grain_initial_exponent
        * strain ** params.srx_grain_strain_exponent
        * math.exp(-params.srx_grain_activation_energy_j_mol / (R_GAS_J_PER_MOL_K * temperature_k))
    )
    return {
        "srx_t05_s": float(t05),
        "srx_fraction": fraction,
        "srx_rex_grain_um": max(1e-9, float(grain_um)),
    }


def metadynamic_recrystallization_fraction(
    time_s: float,
    strain: float,
    strain_rate_s: float,
    temperature_c: float,
    initial_grain_um: float,
    drx_active: bool,
    params: MDRXKineticsParameters,
) -> dict[str, float | bool]:
    """Compute MDRX fraction from Yada/Senuma-style t0.5 kinetics."""
    if params.require_drx_activation and not drx_active:
        return {"mdrx_allowed": False, "mdrx_t05_s": float("nan"), "mdrx_fraction": 0.0}

    temperature_k = safe_positive(temperature_c + 273.15, fallback=1.0)
    strain = safe_positive(strain)
    strain_rate_s = safe_positive(strain_rate_s)
    initial_grain_um = safe_positive(initial_grain_um)
    t05 = (
        params.t05_prefactor_s
        * strain ** params.strain_exponent
        * initial_grain_um ** params.grain_size_exponent
        * strain_rate_s ** params.strain_rate_exponent
        * math.exp(min(params.mdrx_activation_energy_j_mol / (R_GAS_J_PER_MOL_K * temperature_k), 700.0))
    )
    fraction = avrami_fraction(safe_positive(time_s, fallback=0.0) / max(t05, 1e-30), params.avrami_exponent)
    return {"mdrx_allowed": True, "mdrx_t05_s": float(t05), "mdrx_fraction": fraction}


def mixed_recrystallization_for_hit(
    strain: float,
    strain_rate_s: float,
    temperature_c: float,
    initial_grain_um: float,
    interpass_time_s: float,
    params: MixedRecrystallizationParameters | None = None,
) -> dict[str, float | bool | str]:
    """Compute mixed DRX/MDRX/SRX fractions and an updated average grain size."""
    params = params or MixedRecrystallizationParameters()
    drx = dynamic_recrystallization_fraction(strain, strain_rate_s, temperature_c, params.drx)
    srx = static_recrystallization_fraction(
        time_s=interpass_time_s,
        strain=strain,
        strain_rate_s=strain_rate_s,
        temperature_c=temperature_c,
        initial_grain_um=initial_grain_um,
        params=params.srx,
        zener=float(drx["zener_hollomon"]),
    )
    mdrx = metadynamic_recrystallization_fraction(
        time_s=interpass_time_s,
        strain=strain,
        strain_rate_s=strain_rate_s,
        temperature_c=temperature_c,
        initial_grain_um=initial_grain_um,
        drx_active=bool(drx["drx_active"]),
        params=params.mdrx,
    )

    drx_fraction = float(drx["drx_fraction"])
    mdrx_fraction = (1.0 - drx_fraction) * float(mdrx["mdrx_fraction"])
    srx_fraction = (1.0 - drx_fraction - mdrx_fraction) * float(srx["srx_fraction"])
    total_fraction = clip01(drx_fraction + mdrx_fraction + srx_fraction)

    rex_grain_um = np.nanmean(
        [
            float(drx["drx_rex_grain_um"]),
            float(srx["srx_rex_grain_um"]),
        ]
    )
    updated_grain_um = (1.0 - total_fraction) * initial_grain_um + total_fraction * rex_grain_um

    result = {
        "rex_model_preset": params.preset_name,
        "initial_grain_um": float(initial_grain_um),
        "interpass_time_s": float(interpass_time_s),
        "strain_final": float(strain),
        "strain_rate_s": float(strain_rate_s),
        "temperature_c": float(temperature_c),
        "drx_model": params.drx.model_name,
        "srx_model": params.srx.model_name,
        "mdrx_model": params.mdrx.model_name,
        "drx_fraction": drx_fraction,
        "mdrx_fraction": clip01(mdrx_fraction),
        "srx_fraction": clip01(srx_fraction),
        "total_recrystallized_fraction": total_fraction,
        "updated_grain_um": float(updated_grain_um),
    }
    result.update(drx)
    result.update(srx)
    result.update(mdrx)
    return result


def curve_sort_key(path: Path) -> tuple[int, str]:
    """Sort curve files by inferred hit number."""
    hit = infer_hit_number(path.name)
    return (hit if hit is not None else 10**9, path.name)


def run_rex_kinetics_on_curve_folder(
    curve_dir: str | Path,
    output_csv: str | Path,
    initial_grain_size_um: float = 26.3,
    interpass_time_s: float = 1.0,
    params: MixedRecrystallizationParameters | None = None,
) -> pd.DataFrame:
    """Run mixed recrystallization kinetics on processed AF curves."""
    params = params or MixedRecrystallizationParameters(initial_grain_size_um=initial_grain_size_um, interpass_time_s=interpass_time_s)
    curve_dir = Path(curve_dir)
    grain_um = float(initial_grain_size_um)
    rows = []
    for curve_path in sorted(curve_dir.glob("*_stress_strain.csv"), key=curve_sort_key):
        curve = pd.read_csv(curve_path)
        conditions = summarize_curve_conditions(curve)
        result = mixed_recrystallization_for_hit(
            strain=conditions["strain_final"],
            strain_rate_s=conditions["strain_rate_s"],
            temperature_c=conditions["temperature_c"],
            initial_grain_um=grain_um,
            interpass_time_s=interpass_time_s,
            params=params,
        )
        grain_um = float(result["updated_grain_um"])
        result.update(conditions)
        result["curve_file"] = curve_path.name
        if "hit" in curve.columns and not curve.empty:
            result["hit"] = curve["hit"].iloc[0]
        rows.append(result)

    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output = pd.DataFrame(rows)
    output.to_csv(output_csv, index=False)
    parameter_json = output_csv.with_name(output_csv.stem + "_parameters.json")
    parameter_json.write_text(json.dumps(asdict(params), indent=2), encoding="utf-8")
    return output


def run_rex_kinetics_on_local_histories(
    local_history_csv: str | Path,
    output_csv: str | Path,
    initial_grain_size_um: float = 26.3,
    interpass_time_s: float = 1.0,
    params: MixedRecrystallizationParameters | None = None,
) -> pd.DataFrame:
    """Run mixed recrystallization kinetics on local thermomechanical histories.

    Required columns are a location id, temperature, and either final strain or a
    time-resolved strain column. Strain rate may be supplied directly; otherwise
    it is estimated from strain versus time.
    """
    params = params or MixedRecrystallizationParameters(initial_grain_size_um=initial_grain_size_um, interpass_time_s=interpass_time_s)
    df = pd.read_csv(local_history_csv)
    columns_lower = {str(column).lower(): column for column in df.columns}
    location_col = next((columns_lower[name] for name in ["location_id", "node_id", "element_id", "point_id", "id"] if name in columns_lower), None)
    temp_col = next((columns_lower[name] for name in ["temperature_c", "temp_c", "temperature (c)"] if name in columns_lower), None)
    strain_col = next((columns_lower[name] for name in ["true_strain", "effective_strain", "strain"] if name in columns_lower), None)
    strain_rate_col = next((columns_lower[name] for name in ["strain_rate_s", "strain_rate", "effective_strain_rate"] if name in columns_lower), None)
    time_col = next((columns_lower[name] for name in ["time_s", "time", "time (s)"] if name in columns_lower), None)
    if location_col is None or temp_col is None or strain_col is None:
        raise ValueError("Local REX histories need location_id/node_id, temperature_c, and true_strain/effective_strain columns.")

    rows = []
    for location_id, group in df.groupby(location_col, sort=True):
        temp = pd.to_numeric(group[temp_col], errors="coerce")
        strain = pd.to_numeric(group[strain_col], errors="coerce")
        if strain_rate_col:
            strain_rate = pd.to_numeric(group[strain_rate_col], errors="coerce").replace([np.inf, -np.inf], np.nan).median()
        elif time_col:
            proxy = pd.DataFrame({"true_strain": strain, "time_s": pd.to_numeric(group[time_col], errors="coerce")})
            strain_rate = estimate_effective_strain_rate(proxy)
        else:
            strain_rate = float("nan")
        result = mixed_recrystallization_for_hit(
            strain=float(strain.max()),
            strain_rate_s=float(strain_rate),
            temperature_c=float(temp.median()),
            initial_grain_um=initial_grain_size_um,
            interpass_time_s=interpass_time_s,
            params=params,
        )
        result["location_id"] = location_id
        for coord in ["x_mm", "y_mm", "z_mm"]:
            if coord in columns_lower:
                result[coord] = pd.to_numeric(group[columns_lower[coord]], errors="coerce").dropna().iloc[0]
        rows.append(result)

    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output = pd.DataFrame(rows)
    output.to_csv(output_csv, index=False)
    parameter_json = output_csv.with_name(output_csv.stem + "_parameters.json")
    parameter_json.write_text(json.dumps(asdict(params), indent=2), encoding="utf-8")
    return output
