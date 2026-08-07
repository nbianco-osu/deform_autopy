"""
Shared data contracts for Agility Forge experimental analysis.

The experimental workflow intentionally uses plain CSV files and dataclasses so
it can run in Spyder without a database. Each module accepts these lightweight
objects or dictionaries and writes tabular outputs that can be joined with the
existing DEFORM DOE datasets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AFColumnMap:
    """Column names expected in raw Agility Forge hit CSV files."""

    time_s: str = "Time (s)"
    position_mm: str = "Position (mm)"
    force_kn: str = "Force (kN)"
    temperature_c: str = "Thermal Cam Temp (c)"
    x_mm: str | None = None
    y_mm: str | None = None
    z_mm: str | None = None
    rotation_deg: str | None = None


@dataclass
class ContactDetectionConfig:
    """Settings for force-threshold contact detection."""

    position_start_threshold_mm: float = 30.0
    force_sigma_multiplier: float = 1.5
    minimum_force_threshold_kn: float = 0.25
    contact_index_correction: int = 1


@dataclass
class StressStrainConfig:
    """Assumptions used to convert force-displacement to effective stress-strain."""

    stock_diameter_mm: float = 15.875
    initial_height_mm: float | None = None
    contact_area_mode: str = "flat_punch"
    flat_punch_diameter_mm: float | None = None
    contact_area_mm2: float | None = None
    min_contact_area_mm2: float = 1.0


@dataclass
class RecrystallizationConfig:
    """Thresholds for detecting likely recrystallization from stress-strain data."""

    min_peak_stress_mpa: float = 5.0
    min_softening_fraction: float = 0.08
    steady_state_slope_fraction: float = 0.08
    min_post_peak_points: int = 8


@dataclass
class PipelineConfig:
    """Top-level paths and options for the experimental analysis wrapper."""

    raw_af_data_dir: Path
    output_dir: Path
    deform_dataset_csv: Path | None = None
    microstructure_targets_csv: Path | None = None
    hit_glob: str = "*.csv"
    column_map: AFColumnMap = field(default_factory=AFColumnMap)
    contact: ContactDetectionConfig = field(default_factory=ContactDetectionConfig)
    stress_strain: StressStrainConfig = field(default_factory=StressStrainConfig)
    recrystallization: RecrystallizationConfig = field(default_factory=RecrystallizationConfig)


def dataclass_to_dict(value: Any) -> dict[str, Any]:
    """Convert a dataclass to a JSON-safe dictionary."""
    data = asdict(value)
    return _stringify_paths(data)


def _stringify_paths(value: Any) -> Any:
    """Recursively stringify pathlib objects for JSON serialization."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _stringify_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stringify_paths(item) for item in value]
    return value

