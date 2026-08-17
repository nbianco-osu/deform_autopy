"""
Material metadata and model-parameter selection for AF experimental analysis.

AF datasets are organized as `{object_name}_{diameter}in_{material}`. This
module parses that convention and provides one place to select:

- stock/object metadata,
- pyJMAK material input files,
- DRX/SRX/MDRX microstructure-model parameters.

The values here are literature-backed priors. They should be calibrated with
AF-specific microscopy, DEFORM JMAK fields, and thermal/deformation histories
before being used as final quantitative material constants.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .rex_kinetics import MixedRecrystallizationParameters


MATERIAL_DATA_DIR = Path(__file__).resolve().parent / "material_data"


@dataclass
class AFDatasetMetadata:
    """Parsed AF dataset folder metadata."""

    object_name: str
    diameter_in: float
    diameter_mm: float
    material: str
    folder_name: str


def normalize_material_label(material: str | None) -> str:
    """Normalize user/folder material names to compact labels."""
    label = str(material or "").strip().upper().replace(" ", "").replace("-", "")
    if label in {"316", "316L", "AISI316L", "SS316L", "STAINLESS316L"}:
        return "316L"
    if label in {"4140", "AISI4140", "STEEL4140"}:
        return "4140"
    return label or "UNKNOWN"


def parse_af_dataset_folder(path: str | Path) -> AFDatasetMetadata:
    """Parse `{object_name}_{diameter}in_{material}` folder names."""
    folder = Path(path).name
    match = re.match(r"(?P<object>.+?)_(?P<diameter>\d+(?:\.\d+)?)in_(?P<material>.+)$", folder, flags=re.I)
    if not match:
        raise ValueError(
            "AF data folders should be named like '{object_name}_{diameter}in_{material}', "
            f"but got '{folder}'."
        )
    diameter_in = float(match.group("diameter"))
    return AFDatasetMetadata(
        object_name=match.group("object"),
        diameter_in=diameter_in,
        diameter_mm=diameter_in * 25.4,
        material=normalize_material_label(match.group("material")),
        folder_name=folder,
    )


def try_parse_af_dataset_folder(path: str | Path) -> AFDatasetMetadata | None:
    """Parse folder metadata if possible, otherwise return None."""
    try:
        return parse_af_dataset_folder(path)
    except ValueError:
        return None


def material_prior_path(material: str) -> Path:
    """Return the JSON prior path for a supported material."""
    material = normalize_material_label(material)
    if material == "316L":
        return MATERIAL_DATA_DIR / "316L_literature_parameters.json"
    if material == "4140":
        return MATERIAL_DATA_DIR / "4140_literature_parameters.json"
    raise ValueError(f"No material prior is registered for '{material}'.")


def load_material_prior(material: str) -> dict:
    """Load the material-prior JSON for a supported material."""
    path = material_prior_path(material)
    if not path.exists():
        raise FileNotFoundError(f"Missing material prior JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def pyjmak_material_input_file(material: str) -> Path:
    """Return the default pyJMAK material input file for a supported material."""
    material = normalize_material_label(material)
    if material == "316L":
        return MATERIAL_DATA_DIR / "pyjmak_316L_stable_austenite_nist.inp"
    if material == "4140":
        return MATERIAL_DATA_DIR / "pyjmak_4140_austenite_transformations_prior.inp"
    raise ValueError(f"No pyJMAK material input file is registered for '{material}'.")


def rex_parameters_for_material(
    material: str,
    initial_grain_size_um: float = 26.3,
    interpass_time_s: float = 1.0,
) -> MixedRecrystallizationParameters:
    """Return material-specific mixed DRX/MDRX/SRX prior parameters."""
    material = normalize_material_label(material)
    params = MixedRecrystallizationParameters(
        initial_grain_size_um=initial_grain_size_um,
        interpass_time_s=interpass_time_s,
    )

    if material == "316L":
        params.preset_name = "316l_mixed_literature_prior"
        params.drx.model_name = "316l_zada_yada_literature_prior"
        params.drx.deformation_activation_energy_j_mol = 460000.0
        params.drx.critical_strain_prefactor = 0.009
        params.drx.critical_strain_z_exponent = 0.084
        params.drx.drx_avrami_exponent = 2.0
        params.drx.drx_half_strain_factor = 1.8
        params.drx.min_half_strain_offset = 0.02
        params.drx.drx_grain_coefficient = 1.4e4
        params.drx.drx_grain_z_exponent = -0.11
        params.srx.model_name = "316l_sellars_srx_prior"
        params.mdrx.model_name = "316l_yada_mdrx_prior"
        return params

    if material == "4140":
        params.preset_name = "4140_mixed_literature_prior"
        params.drx.model_name = "4140_lin_drx_hot_compression_prior"
        params.drx.deformation_activation_energy_j_mol = 599732.1
        params.drx.critical_strain_prefactor = 0.16707
        params.drx.critical_strain_z_exponent = 0.06704
        params.drx.drx_avrami_exponent = 3.85582
        params.drx.drx_half_strain_factor = 3.7
        params.drx.min_half_strain_offset = 0.04
        params.drx.drx_grain_coefficient = 1.2e4
        params.drx.drx_grain_z_exponent = -0.10
        params.srx.model_name = "4140_sellars_srx_prior"
        params.srx.recrystallization_activation_energy_j_mol = 280000.0
        params.srx.t05_prefactor_s = 5.0e-18
        params.srx.avrami_exponent = 1.5
        params.srx.srx_grain_prefactor = 520.0
        params.srx.srx_grain_activation_energy_j_mol = 55000.0
        params.mdrx.model_name = "4140_mdrx_screening_prior"
        params.mdrx.mdrx_activation_energy_j_mol = 220000.0
        params.mdrx.avrami_exponent = 0.7
        return params

    raise ValueError(f"No REX parameters are registered for '{material}'.")


def material_context_from_folder(
    raw_af_data_dir: str | Path,
    initial_grain_size_um: float = 26.3,
    interpass_time_s: float = 1.0,
) -> dict:
    """Return parsed folder metadata and registered model paths/parameters."""
    metadata = parse_af_dataset_folder(raw_af_data_dir)
    params = rex_parameters_for_material(
        metadata.material,
        initial_grain_size_um=initial_grain_size_um,
        interpass_time_s=interpass_time_s,
    )
    pyjmak_file = pyjmak_material_input_file(metadata.material)
    return {
        "metadata": asdict(metadata),
        "material_prior_json": str(material_prior_path(metadata.material)),
        "pyjmak_material_input_file": str(pyjmak_file),
        "rex_parameters": asdict(params),
    }


def copy_rex_parameters(params: MixedRecrystallizationParameters) -> MixedRecrystallizationParameters:
    """Return a deep copy of a REX parameter set."""
    return copy.deepcopy(params)
