"""
Grain-size initialization helpers for DEFORM JMAK simulations.

The JMAK model needs an initial `GRAIN` block in the key file. These helpers
support two common cases:

1. Constant grain size for every element.
2. Supplier-data-driven log-normal grain-size distribution.

The functions return DEFORM key strings so run scripts can choose when to call
`defModel.importKeyString(...)` or `defModel.readKeyString(...)`.
"""

import math
import re

import numpy as np


DEFAULT_GRAIN_STATE_VALUES = {
    "rex_fraction": "0.0000000000E+000",
    "dynamic_rex_fraction": "0.0000000000E+000",
    "meta_dynamic_rex_fraction": "0.0000000000E+000",
    "static_rex_fraction": "0.0000000000E+000",
    "dynamic_rex_grain_size": "0.0000000000E+000",
    "meta_dynamic_rex_grain_size": "0.0000000000E+000",
    "static_rex_grain_size": "0.0000000000E+000",
    "evolution_mode": "0.0000000000E+000",
    "previous_step_deformation": "0.0000000000E+000",
    "retained_strain": "0.0000000000E+000",
    "deformation_time_span": "0.0000000000E+000",
    "avg_deforming_strain_rate": "0.0000000000E+000",
    "avg_deforming_temperature": "0.0000000000E+000",
    "peak_strain": "0.0000000000E+000",
}


def format_deform_float(value):
    """Format numeric values in the exponent style DEFORM key files use."""
    return f"{float(value):.10E}"


def read_num_grains_from_key(key_file_path, object_number=1):
    """Read the element/grain count from an `ELMCON` line in a key file.

    DEFORM's `GRAIN` block uses one row group per element. For the current
    workpiece object, this count has been available in lines like `ELMCON 1 ...`.
    """
    pattern = re.compile(rf"^\s*ELMCON\s+{int(object_number)}\s+")

    with open(key_file_path, "r") as file:
        for line in file:
            if pattern.search(line):
                values = line.split()
                if len(values) < 4:
                    raise ValueError(f"Could not parse number of grains from line: {line!r}")
                return int(values[3])

    raise ValueError(f"No ELMCON line found for object {object_number} in {key_file_path}")


def sample_lognormal_grain_sizes(mean_grain_size, num_grains, sigma_ln=0.4, random_seed=None):
    """Sample grain sizes from a log-normal distribution using supplier mean size.

    Parameters
    ----------
    mean_grain_size : float
        Supplier-reported average grain size, usually in microns.
    num_grains : int
        Number of element grain-size values to generate.
    sigma_ln : float
        Standard deviation of ln(grain size). Typical starting values for metals
        are often around 0.3 to 0.5 when detailed distribution data is missing.
    random_seed : int or None
        Use an integer seed to make initialization reproducible.
    """
    if mean_grain_size <= 0:
        raise ValueError("mean_grain_size must be greater than 0.")
    if num_grains < 1:
        raise ValueError("num_grains must be at least 1.")
    if sigma_ln <= 0:
        raise ValueError("sigma_ln must be greater than 0.")

    rng = np.random.default_rng(random_seed)
    mu_ln = math.log(mean_grain_size) - (sigma_ln**2) / 2
    return rng.lognormal(mean=mu_ln, sigma=sigma_ln, size=num_grains)


def create_grain_size_string(grain_sizes, object_number=1, state_values=None):
    """Create a DEFORM `GRAIN` key block from one or many grain sizes.

    `grain_sizes` may be a single float/string for a constant distribution or
    a list/array of values for element-wise initialization.
    """
    if state_values is None:
        state_values = DEFAULT_GRAIN_STATE_VALUES

    if isinstance(grain_sizes, (int, float, str)):
        grain_sizes = [grain_sizes]

    grain_sizes = list(grain_sizes)
    num_grains = len(grain_sizes)
    if num_grains < 1:
        raise ValueError("At least one grain size is required.")

    lines = [f"GRAIN        {int(object_number)}    {num_grains}      16    0.0000000000E+000\n"]

    for grain_num, grain_size in enumerate(grain_sizes, start=1):
        grain_size = format_deform_float(grain_size)
        lines.append(
            f"       {grain_num}    {state_values['rex_fraction']}    {grain_size}    "
            f"{grain_size}    {state_values['dynamic_rex_fraction']}    "
            f"{state_values['meta_dynamic_rex_fraction']}\n"
        )
        lines.append(
            f"            {state_values['static_rex_fraction']}    "
            f"{state_values['dynamic_rex_grain_size']}    "
            f"{state_values['meta_dynamic_rex_grain_size']}    "
            f"{state_values['static_rex_grain_size']}    "
            f"{state_values['evolution_mode']}\n"
        )
        lines.append(
            f"            {state_values['previous_step_deformation']}    "
            f"{state_values['retained_strain']}    "
            f"{state_values['deformation_time_span']}    "
            f"{state_values['avg_deforming_strain_rate']}    "
            f"{state_values['avg_deforming_temperature']}\n"
        )
        lines.append(f"            {state_values['peak_strain']}\n")

    return "".join(lines)


def create_constant_grain_size_string(grain_size, num_grains, object_number=1):
    """Create a `GRAIN` block where every element starts at the same grain size."""
    grain_sizes = [grain_size] * int(num_grains)
    return create_grain_size_string(grain_sizes, object_number=object_number)


def create_supplier_grain_size_string(
    mean_grain_size,
    num_grains,
    sigma_ln=0.4,
    random_seed=None,
    object_number=1,
):
    """Create a reproducible supplier-data-based `GRAIN` block."""
    grain_sizes = sample_lognormal_grain_sizes(
        mean_grain_size=mean_grain_size,
        num_grains=int(num_grains),
        sigma_ln=sigma_ln,
        random_seed=random_seed,
    )
    return create_grain_size_string(grain_sizes, object_number=object_number)


def create_supplier_grain_size_string_from_key(
    key_file_path,
    mean_grain_size,
    sigma_ln=0.4,
    random_seed=None,
    object_number=1,
):
    """Read grain count from a key file and create a supplier-based `GRAIN` block."""
    num_grains = read_num_grains_from_key(key_file_path, object_number=object_number)
    return create_supplier_grain_size_string(
        mean_grain_size=mean_grain_size,
        num_grains=num_grains,
        sigma_ln=sigma_ln,
        random_seed=random_seed,
        object_number=object_number,
    )
