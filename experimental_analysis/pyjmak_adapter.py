"""
Optional pyJMAK integration for Agility Forge experimental analysis.

pyJMAK is an ORNL toolkit for solid-state phase transformation simulations.
This adapter keeps pyJMAK optional: the rest of the experimental pipeline can
run without it, and phase-transformation predictions are enabled only when a
material input file and an importable pyJMAK package are provided.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from .af_signal_processing import infer_hit_number


def add_pyjmak_source_path(source_path: str | Path | None = None) -> None:
    """Add a local pyJMAK checkout path to sys.path when provided."""
    if source_path is None or str(source_path).strip() == "":
        return
    source_path = Path(source_path)
    candidates = [source_path, source_path.parent]
    for candidate in candidates:
        if (candidate / "pyJMAK").exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            return
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))


def import_pyjmak(source_path: str | Path | None = None):
    """Import pyJMAK or raise a helpful error."""
    add_pyjmak_source_path(source_path)
    os.environ.setdefault(
        "MPLCONFIGDIR",
        str(Path(tempfile.gettempdir()) / "deform_api_matplotlib_cache"),
    )
    try:
        return importlib.import_module("pyJMAK")
    except ImportError as exc:
        raise ImportError(
            "pyJMAK is not importable. Install ORNL/pyJMAK with `pip install -e "
            "<pyJMAK checkout>` or pass pyjmak_source_path to a local checkout."
        ) from exc


def curve_sort_key(path: Path) -> tuple[int, str]:
    """Sort stress-strain curve files by hit number when available."""
    hit = infer_hit_number(path.name)
    return (hit if hit is not None else 10**9, path.name)


def build_temperature_history_from_curve_folder(
    curve_dir: str | Path,
    output_file: str | Path,
    inter_hit_gap_s: float = 0.0,
) -> Path:
    """Create a pyJMAK time-temperature file from processed AF curve CSVs.

    The output contains two comma-separated columns: time in seconds and
    temperature in Celsius. Hit files are concatenated in numeric hit order using
    their local relative time axes.
    """
    curve_dir = Path(curve_dir)
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    time_offset = 0.0
    for curve_path in sorted(curve_dir.glob("*_stress_strain.csv"), key=curve_sort_key):
        curve = pd.read_csv(curve_path)
        if "time_s" not in curve.columns or "temperature_c" not in curve.columns:
            continue
        local_time = pd.to_numeric(curve["time_s"], errors="coerce").to_numpy(dtype=float)
        temp = pd.to_numeric(curve["temperature_c"], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(local_time) & np.isfinite(temp)
        local_time = local_time[valid]
        temp = temp[valid]
        if len(local_time) == 0:
            continue
        local_time = local_time - float(local_time[0])
        absolute_time = local_time + time_offset
        if rows and absolute_time[0] <= rows[-1][0]:
            absolute_time = absolute_time + (rows[-1][0] - absolute_time[0]) + 1e-9
        rows.extend((float(t), float(T)) for t, T in zip(absolute_time, temp))
        time_offset = float(absolute_time[-1]) + float(inter_hit_gap_s)

    if not rows:
        raise ValueError(f"No usable stress-strain curve temperature data found in {curve_dir}.")

    pd.DataFrame(rows, columns=["time_s", "temperature_c"]).to_csv(
        output_file,
        index=False,
        header=False,
    )
    return output_file


def run_pyjmak_phase_simulation(
    temperature_file: str | Path,
    material_input_file: str | Path,
    output_csv: str | Path,
    source_path: str | Path | None = None,
    verbose: bool = False,
) -> dict[str, str]:
    """Run pyJMAK and write phase-fraction predictions to CSV."""
    pyjmak = import_pyjmak(source_path)
    model = pyjmak.jmak(VERBOSE=verbose)
    model.loadInputFiles(str(temperature_file), str(material_input_file))
    model.run_phase_trans_sim()
    phase_fractions, rls_state = corrected_initial_solid_state(model)

    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result = pd.DataFrame(
        {
            "time_s": np.asarray(model.time, dtype=float),
            "temperature_c": np.asarray(model.T_C, dtype=float),
        }
    )
    for index, phase_name in enumerate(model.ph_names):
        result[f"phase_fraction_{phase_name}"] = np.asarray(phase_fractions[:, index], dtype=float)
    if rls_state is not None:
        result["raw_liquid_solid_state"] = np.asarray(rls_state, dtype=float)
    result.to_csv(output_csv, index=False)

    final = result.tail(1).to_dict(orient="records")[0]
    summary_json = output_csv.with_name(output_csv.stem + "_summary.json")
    summary = {
        "temperature_file": str(temperature_file),
        "material_input_file": str(material_input_file),
        "output_csv": str(output_csv),
        "phase_names": list(model.ph_names),
        "rows": int(len(result)),
        "final_state": final,
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {
        "pyjmak_phase_fraction_csv": str(output_csv),
        "pyjmak_phase_summary_json": str(summary_json),
        "pyjmak_phase_rows": str(len(result)),
    }


def corrected_initial_solid_state(model):
    """Correct pyJMAK raw-state output for an already-solid single-phase billet.

    pyJMAK's RLS logic is designed for histories that begin as raw material and
    may melt/solidify. AF forging starts from an already-solid workpiece. If the
    material file declares one phase with initial fraction 1.0, no
    transformations occur, and pyJMAK reports all points as raw, this function
    restores the declared solid phase for output purposes.
    """
    phase_fractions = np.asarray(model.F, dtype=float).copy()
    rls_state = None if getattr(model, "RLS_state", None) is None else np.asarray(model.RLS_state, dtype=float).copy()
    tables = getattr(model, "tables", {}) or {}
    transformations = tables.get("ABQ_PHASE_TRANS_Transformations", {}).get("ABQ_PHASE_TRANS_Transformations", [])
    solid_phases = tables.get("ABQ_PHASE_TRANS_SolidPhases", {}).get("ABQ_PHASE_TRANS_SolidPhases", [])

    if transformations or not solid_phases or phase_fractions.size == 0:
        return phase_fractions, rls_state

    initial = np.asarray([float(row[1]) for row in solid_phases], dtype=float)
    single_declared_phase = np.isclose(initial.sum(), 1.0) and np.count_nonzero(initial > 0.0) == 1
    raw_everywhere = rls_state is not None and np.all(rls_state < -0.1)
    zero_fractions = np.allclose(phase_fractions, 0.0)
    if single_declared_phase and raw_everywhere and zero_fractions:
        phase_fractions[:, :] = initial[None, :]
        rls_state[:] = 1.0
    return phase_fractions, rls_state


def run_pyjmak_from_curve_folder(
    curve_dir: str | Path,
    output_dir: str | Path,
    material_input_file: str | Path,
    source_path: str | Path | None = None,
    inter_hit_gap_s: float = 0.0,
    verbose: bool = False,
) -> dict[str, str]:
    """Build an AF temperature history from curves and run pyJMAK."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    temperature_file = build_temperature_history_from_curve_folder(
        curve_dir=curve_dir,
        output_file=output_dir / "pyjmak_temperature_history.csv",
        inter_hit_gap_s=inter_hit_gap_s,
    )
    outputs = {
        "pyjmak_temperature_history": str(temperature_file),
        "pyjmak_material_input_file": str(material_input_file),
    }
    outputs.update(
        run_pyjmak_phase_simulation(
            temperature_file=temperature_file,
            material_input_file=material_input_file,
            output_csv=output_dir / "pyjmak_phase_fractions.csv",
            source_path=source_path,
            verbose=verbose,
        )
    )
    return outputs
