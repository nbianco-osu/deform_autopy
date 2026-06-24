"""
Design-of-experiments candidate generation.

Use DOE to seed an optimization study before training a surrogate model.
"""

from pathlib import Path

import numpy as np
import pandas as pd


def latin_hypercube(bounds, n_samples, random_seed=1):
    """Generate Latin hypercube samples for numeric bounds.

    `bounds` should be a dict such as:

    ```
    {
        "depth_in": [0.01, 0.06],
        "speed_in/s": [0.5, 2.0]
    }
    ```
    """
    rng = np.random.default_rng(random_seed)
    names = list(bounds.keys())
    samples = np.zeros((n_samples, len(names)))

    for col, name in enumerate(names):
        low, high = bounds[name]
        cut = np.linspace(0, 1, n_samples + 1)
        points = rng.uniform(cut[:-1], cut[1:])
        rng.shuffle(points)
        samples[:, col] = low + points * (high - low)

    return pd.DataFrame(samples, columns=names)


def grid_samples(bounds, levels):
    """Generate a full-factorial grid for small sweeps."""
    names = list(bounds.keys())
    grids = []
    for name in names:
        low, high = bounds[name]
        grids.append(np.linspace(low, high, levels))

    mesh = np.meshgrid(*grids)
    rows = np.vstack([axis.ravel() for axis in mesh]).T
    return pd.DataFrame(rows, columns=names)


def add_constant_columns(df, constants):
    """Attach fixed settings such as material, die, or action file."""
    df = df.copy()
    for key, value in (constants or {}).items():
        df[key] = value
    return df


def save_candidates(df, output_csv_path):
    """Save candidate inputs to CSV."""
    output_csv_path = Path(output_csv_path)
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv_path, index=False)
    return output_csv_path
