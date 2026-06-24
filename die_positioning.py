"""
Helpers for positioning DEFORM dies before a multihit run begins.

Use these functions after reading the starting key file and before writing the
first DB. They are intentionally small wrappers around `defModel.position.perform`
so they can be reused by different run scripts without changing the DEFORM API
calls themselves.
"""

from deformModel import defModel
from enumPosition import PositionType
import csv
from pathlib import Path


def get_die_motion_axis_vectors(die_motion_axis="z"):
    """Return DEFORM direction/offset vectors for the selected die motion axis.

    `die_motion_axis="z"` preserves the original setup: top die approaches in
    -Z and bottom die approaches in +Z. `die_motion_axis="y"` uses the same
    convention along Y: top die approaches in -Y and bottom die approaches in
    +Y.
    """
    axis = str(die_motion_axis).lower()
    if axis == "z":
        return {
            "axis": "z",
            "top_interference_dir": (0, 0, -1),
            "bottom_interference_dir": (0, 0, 1),
            "top_offset": (0, 0, 1),
            "bottom_offset": (0, 0, -1),
            "movctl_dir": (0, 0, -1),
        }
    if axis == "y":
        return {
            "axis": "y",
            "top_interference_dir": (0, -1, 0),
            "bottom_interference_dir": (0, 1, 0),
            "top_offset": (0, -1, 0),
            "bottom_offset": (0, 1, 0),
            "movctl_dir": (0, -1, 0),
        }
    raise ValueError("die_motion_axis must be 'z' or 'y'.")


def format_vector(values):
    """Format a DEFORM tuple without Python spaces."""
    return f"({values[0]},{values[1]},{values[2]})"


def scale_vector(values, scale):
    """Scale a three-component vector."""
    return (values[0] * scale, values[1] * scale, values[2] * scale)


def position_dies_before_hits(
    height,
    top_die_name="Top Die",
    bottom_die_name="Bottom Die",
    workpiece_name="Workpiece",
    top_die_interference=0.0001,
    bottom_die_interference=0.0001,
    position_bottom_die=True,
    die_motion_axis="z",
):
    """Seat dies on the workpiece, then back them out to the starting clearance.

    Parameters
    ----------
    height : float
        Clearance distance between each seated die and the workpiece before the
        first hit begins.
    top_die_name : str
        DEFORM object name for the top die.
    bottom_die_name : str
        DEFORM object name for the bottom die.
    workpiece_name : str
        DEFORM object name for the workpiece.
    top_die_interference : float
        Interference value used to move the top die flush with the workpiece.
    bottom_die_interference : float
        Interference value used to move the bottom die flush with the workpiece.
    position_bottom_die : bool
        If True, also seats and backs out the bottom die symmetrically. Set to
        False for setups where the starting key already has the bottom die fixed
        in the desired location.
    die_motion_axis : {"z", "y"}
        Axis used for die approach/retract. Use "z" for the original vertical
        motion and "y" for dies that close along the Y axis.

    Notes
    -----
    The selected axis controls both interference directions and the back-out
    offsets. This keeps hit-0 positioning consistent with the MOVCTL axis used
    during the solve.
    """
    if height <= 0:
        raise ValueError("height must be greater than 0.")
    axis_vectors = get_die_motion_axis_vectors(die_motion_axis)

    defModel.position.perform(
        top_die_name,
        PositionType.Interference,
        (
            f"interference={top_die_interference}, upStroke=false, "
            f"refObj='{workpiece_name}', "
            f"dir={format_vector(axis_vectors['top_interference_dir'])}, moveOut='true'"
        ),
        top_die_name,
    )

    defModel.position.perform(
        top_die_name,
        PositionType.Offset,
        f"offset={format_vector(scale_vector(axis_vectors['top_offset'], height))}, upStroke=false",
    )

    if not position_bottom_die:
        return

    defModel.position.perform(
        bottom_die_name,
        PositionType.Interference,
        (
            f"interference={bottom_die_interference}, upStroke=false, "
            f"refObj='{workpiece_name}', "
            f"dir={format_vector(axis_vectors['bottom_interference_dir'])}, moveOut='true'"
        ),
        bottom_die_name,
    )

    defModel.position.perform(
        bottom_die_name,
        PositionType.Offset,
        f"offset={format_vector(scale_vector(axis_vectors['bottom_offset'], height))}, upStroke=false",
    )


def get_object_coordinates(object_name):
    """Return min, max, and center coordinates for one DEFORM object.

    This uses the coordinate accessors added to `DeformObject`:
    `getMinCoord()`, `getMaxCoord()`, and `getCenterCoord()`.
    """
    deform_object = defModel.getObj(object_name)
    return {
        "min": deform_object.getMinCoord(),
        "max": deform_object.getMaxCoord(),
        "center": deform_object.getCenterCoord(),
    }


def collect_object_coordinates(object_names=None):
    """Collect coordinate bounds for the standard workpiece/die objects."""
    if object_names is None:
        object_names = ["Workpiece", "Top Die", "Bottom Die"]

    records = []
    for object_name in object_names:
        coordinates = get_object_coordinates(object_name)
        for coord_type, values in coordinates.items():
            records.append({
                "object": object_name,
                "coord_type": coord_type,
                "x": values[0],
                "y": values[1],
                "z": values[2],
            })
    return records


def save_object_coordinates(output_file_path, hit=None, stage="", object_names=None):
    """Save workpiece/die min, max, and center coordinates to CSV."""
    output_file_path = Path(output_file_path)
    output_file_path.parent.mkdir(parents=True, exist_ok=True)

    records = collect_object_coordinates(object_names=object_names)
    for record in records:
        record["hit"] = hit
        record["stage"] = stage

    fieldnames = ["hit", "stage", "object", "coord_type", "x", "y", "z"]
    with open(output_file_path, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    return output_file_path
