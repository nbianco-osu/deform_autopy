"""
Post-processing helpers for DEFORM JMAK microstructure data.

This module updates the older `extract_microstructure_data.py` workflow while
keeping its public function names available:

- `save_last_kf_step(...)`
- `save_microstructure_data_to_csv(...)`

It also adds lower-level helpers that are easier to reuse with the current
multihit codebase. The parser expects DEFORM key files with a `GRAIN` block
followed by an `ELMDEN` block, where each element's grain state uses four lines.
"""

from pathlib import Path
import pandas as pd

try:
    from deformModel import defModel
except ImportError:
    defModel = None


GRAIN_COLUMNS = [
    "Element Number",
    "Rex. vol. fraction",
    "Average grain size (um)",
    "Initial grain size (um)",
    "Dynamic rex. vol. fraction",
    "Meta-Dyn rex. vol. fraction",
    "Static rex. vol. fraction",
    "Dynamic rex. grain size",
    "Meta-Dyn rex. grain size",
    "Static Rex. grain size",
    "Evolution mode",
    "Previous step deformation",
    "Retained strain",
    "Deformation time span",
    "Avg. deforming strain rate",
    "Avg. deforming temperature",
    "Peak strain",
]


def find_grain_block(lines):
    """Return start/end indexes for the GRAIN data block in key-file lines."""
    start_idx = None
    end_idx = None

    for idx, line in enumerate(lines):
        if line.lstrip().startswith("GRAIN"):
            start_idx = idx
        elif start_idx is not None and line.lstrip().startswith("ELMDEN"):
            end_idx = idx
            break

    if start_idx is None:
        raise ValueError("No GRAIN block found in key file.")
    if end_idx is None:
        raise ValueError("No ELMDEN block found after GRAIN block.")

    return start_idx, end_idx


def get_num_grain_elements(grain_header_line):
    """Parse the number of grain elements from a DEFORM GRAIN header line."""
    values = grain_header_line.split()
    if len(values) < 3:
        raise ValueError(f"Could not parse GRAIN header: {grain_header_line!r}")
    return int(values[2])


def parse_grain_block_from_lines(lines):
    """Parse a DEFORM GRAIN block into a pandas DataFrame."""
    start_idx, end_idx = find_grain_block(lines)
    num_elements = get_num_grain_elements(lines[start_idx])
    grain_lines = lines[start_idx + 1:end_idx]

    expected_lines = num_elements * 4
    if len(grain_lines) < expected_lines:
        raise ValueError(
            f"GRAIN block has {len(grain_lines)} data lines, expected at least {expected_lines}."
        )

    grain_data = []
    for element_index in range(num_elements):
        raw_element = "".join(grain_lines[element_index * 4:(element_index + 1) * 4])
        values = [value for value in raw_element.split() if value]
        if len(values) != len(GRAIN_COLUMNS):
            raise ValueError(
                "Unexpected GRAIN element width for element "
                f"{element_index + 1}: got {len(values)} values, expected {len(GRAIN_COLUMNS)}."
            )
        grain_data.append([float(value) for value in values])

    return pd.DataFrame(grain_data, columns=GRAIN_COLUMNS)


def parse_grain_block_from_key(key_file_path):
    """Read a key file and parse its final JMAK grain-state data."""
    with open(key_file_path, "r") as file:
        return parse_grain_block_from_lines(file.readlines())


def save_microstructure_csv_from_key(key_file_path, output_csv_path=None):
    """Parse a key file's GRAIN block and save it to CSV."""
    key_file_path = Path(key_file_path)
    if output_csv_path is None:
        output_csv_path = key_file_path.with_name(
            f"{key_file_path.stem}_microstructure_data.csv"
        )
    output_csv_path = Path(output_csv_path)

    df = parse_grain_block_from_key(key_file_path)
    df.to_csv(output_csv_path, index=False)
    return output_csv_path


def save_key_at_db_step(run_dir, key_file_path, db_file_path, output_key_path, step_no=0):
    """Load a DB step and write the corresponding state as a key file.

    DEFORM scripts in this codebase often use `step_no=0` for the final DB
    state. Older DOE workflows sometimes used explicit step numbers such as 100.
    """
    run_dir = Path(run_dir)
    key_file_path = Path(key_file_path)
    db_file_path = Path(db_file_path)
    output_key_path = Path(output_key_path)

    if defModel is None:
        raise ImportError(
            "DEFORM API module deformModel is not available. "
            "Run DB-to-KEY extraction on the lab computer with the DEFORM API path configured."
        )

    defModel.setCurrentDir(str(run_dir))
    defModel.readKey(str(key_file_path))
    defModel.readDb(str(db_file_path), step_no)
    defModel.writeKey(str(output_key_path))
    return output_key_path


def iter_run_folders(base_path, run_ids, folder_pattern):
    """Yield `(run_id, folder_path)` pairs for a folder naming pattern."""
    base_path = Path(base_path)
    run_name = base_path.name

    for run_id in run_ids:
        folder_name = folder_pattern.format(run_name=run_name, run=run_id, hit=run_id)
        yield run_id, base_path / folder_name


def save_last_kf_step(
    dataPath,
    num_of_runs,
    kfName,
    lastStepNo=100,
    folder_pattern="{run_name}_run_{run}",
    db_pattern="{folder_name}.DB",
    output_key_suffix=None,
    strict=False,
):
    """Compatibility wrapper: save each run's selected DB step to a key file.

    Parameters match the older function, with extra optional patterns to support
    both DOE folders (`{run_name}_run_{run}`) and multihit folders
    (`{run_name}-hit{hit}`).
    """
    data_path = Path(dataPath)
    output_paths = []

    for run_id, run_dir in iter_run_folders(data_path, range(1, num_of_runs + 1), folder_pattern):
        folder_name = run_dir.name
        key_path = run_dir / kfName
        db_path = run_dir / db_pattern.format(folder_name=folder_name, run=run_id, hit=run_id)

        if output_key_suffix is None:
            output_key_name = f"{Path(kfName).stem}_step{lastStepNo}.KEY"
        else:
            output_key_name = f"{Path(kfName).stem}{output_key_suffix}.KEY"
        output_key_path = run_dir / output_key_name

        try:
            output_paths.append(
                save_key_at_db_step(run_dir, key_path, db_path, output_key_path, step_no=lastStepNo)
            )
        except Exception:
            if strict:
                raise

    return output_paths


def save_microstructure_data_to_csv(
    dataPath,
    num_of_runs,
    kfName,
    lastStepNo=100,
    folder_pattern="{run_name}_run_{run}",
    output_csv_pattern="{folder_name}_finalStep_microstructure_data.csv",
    strict=False,
):
    """Compatibility wrapper: save microstructure CSVs for a series of runs."""
    save_last_kf_step(
        dataPath,
        num_of_runs,
        kfName,
        lastStepNo=lastStepNo,
        folder_pattern=folder_pattern,
        strict=strict,
    )

    data_path = Path(dataPath)
    output_paths = []

    for run_id, run_dir in iter_run_folders(data_path, range(1, num_of_runs + 1), folder_pattern):
        folder_name = run_dir.name
        key_path = run_dir / f"{Path(kfName).stem}_step{lastStepNo}.KEY"
        output_csv_path = run_dir / output_csv_pattern.format(
            folder_name=folder_name,
            run=run_id,
            hit=run_id,
        )

        try:
            output_paths.append(save_microstructure_csv_from_key(key_path, output_csv_path))
        except Exception:
            if strict:
                raise

    return output_paths


def save_multihit_microstructure_data_to_csv(
    run_base_path,
    run_name,
    num_hits,
    key_pattern="af-hit-{hit}_post.KEY",
    output_csv_pattern="{folder_name}_microstructure_data.csv",
    strict=False,
):
    """Parse already-written multihit post key files into microstructure CSVs.

    Use this when the run script already writes post-hit key files, such as
    `af-hit-12_post.KEY`, and you do not need to reopen DB steps.
    """
    run_base_path = Path(run_base_path)
    output_paths = []

    for hit in range(1, num_hits + 1):
        folder_name = f"{run_name}-hit{hit}"
        run_dir = run_base_path / run_name / folder_name
        key_path = run_dir / key_pattern.format(hit=hit, run=hit)
        output_csv_path = run_dir / output_csv_pattern.format(
            folder_name=folder_name,
            hit=hit,
            run=hit,
        )

        try:
            output_paths.append(save_microstructure_csv_from_key(key_path, output_csv_path))
        except Exception:
            if strict:
                raise

    return output_paths


def summarize_microstructure_csv(csv_path):
    """Return simple summary statistics for a saved microstructure CSV."""
    df = pd.read_csv(csv_path)
    return {
        "num_elements": int(len(df)),
        "mean_grain_size_um": float(df["Average grain size (um)"].mean()),
        "std_grain_size_um": float(df["Average grain size (um)"].std()),
        "mean_rex_fraction": float(df["Rex. vol. fraction"].mean()),
        "mean_retained_strain": float(df["Retained strain"].mean()),
    }
