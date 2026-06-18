"""
Helpers for positioning DEFORM dies before a multihit run begins.

Use these functions after reading the starting key file and before writing the
first DB. They are intentionally small wrappers around `defModel.position.perform`
so they can be reused by different run scripts without changing the DEFORM API
calls themselves.
"""

from deformModel import defModel
from enumPosition import PositionType


def position_dies_before_hits(
    height,
    top_die_name="Top Die",
    bottom_die_name="Bottom Die",
    workpiece_name="Workpiece",
    top_die_interference=0.0001,
    bottom_die_interference=0.0001,
    position_bottom_die=True,
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

    Notes
    -----
    The top die is moved flush using `dir=(0, 0, -1)` and then backed out by
    `+height` in Z. The bottom die, when enabled, is moved flush using
    `dir=(0, 0, 1)` and then backed out by `-height` in Z.
    """
    if height <= 0:
        raise ValueError("height must be greater than 0.")

    defModel.position.perform(
        top_die_name,
        PositionType.Interference,
        (
            f"interference={top_die_interference}, upStroke=false, "
            f"refObj='{workpiece_name}', dir=(0, 0, -1), moveOut='true'"
        ),
        top_die_name,
    )

    defModel.position.perform(
        top_die_name,
        PositionType.Offset,
        f"offset=(0,0,{height}), upStroke=false",
    )

    if not position_bottom_die:
        return

    defModel.position.perform(
        bottom_die_name,
        PositionType.Interference,
        (
            f"interference={bottom_die_interference}, upStroke=false, "
            f"refObj='{workpiece_name}', dir=(0, 0, 1), moveOut='true'"
        ),
        bottom_die_name,
    )

    defModel.position.perform(
        bottom_die_name,
        PositionType.Offset,
        f"offset=(0,0,-{height}), upStroke=false",
    )
