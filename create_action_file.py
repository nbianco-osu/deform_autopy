from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd
import os
import matplotlib.pyplot as plt


# NOTE: This decorator only behaves like a static method when the function is
# inside a class. The helper is currently module-level, so the decorator is kept
# only to preserve the file's current behavior.
@staticmethod
def get_constant_value(df: pd.DataFrame, column: str) -> Optional[float]:
    """Return a column's single non-null value, or None if the value varies.

    Use this for columns where the raw data repeats the same setting on every
    row, such as a tool number or command coordinate. Returning None signals
    that the column is not constant for that file.
    """
    unique_values = df[column].dropna().unique()
    if len(unique_values) == 1:
        return unique_values[0]
    return None


def contact_detection_plots(t, position, force, force_threshold, start_search_idx, contact_time, contact_force,
                            contact_position, min_time, min_position, position_start_threshold_mm, penetration_depth):
    """Plot force contact detection and ram-position penetration depth.

    The AF data pipeline detects first contact from the force trace, then uses
    the position trace to measure how far the die penetrated after that contact
    point. This diagnostic plot lets a user check whether the threshold and depth
    measurement are physically reasonable for each hit.
    """
    fig, ax = plt.subplots(1, 2, figsize=(16, 5))

    # Left panel: raw force with the threshold used to mark first contact.
    ax[0].plot(t, force, label="Raw force")
    ax[0].axhline(force_threshold, linestyle="--", label="Force threshold")
    ax[0].axvline(t[start_search_idx], linestyle="--", label="Start search")
    ax[0].axvline(contact_time, linestyle=":", label="Contact")
    ax[0].scatter(contact_time, contact_force, s=80, zorder=5)

    ax[0].set_xlabel("Time (s)")
    ax[0].set_ylabel("Force (kN)")
    ax[0].set_title("Raw Force Contact Detection")
    ax[0].grid(True)
    ax[0].legend()

    # Right panel: raw position with the contact point, minimum position, and
    # measured penetration depth highlighted.
    ax[1].plot(t, position, label="Raw position")
    ax[1].axhline(position_start_threshold_mm, linestyle="--", label=f"{position_start_threshold_mm} mm search start")
    ax[1].axvline(t[start_search_idx], linestyle="--", label="Start search")
    ax[1].axvline(contact_time, linestyle=":", label="Contact")
    ax[1].axvline(min_time, linestyle=":", label="Minimum position")

    ax[1].scatter(contact_time, contact_position, s=80, zorder=5, color='blue')
    ax[1].scatter(min_time, min_position, s=80, zorder=5, color='orange')

    # Vertical marker showing the depth used in the action CSV.
    ax[1].vlines(x=min_time,
        ymin=min_position,
        ymax=contact_position,
        linestyle="--",
        linewidth=2,
        label=f"Depth = {penetration_depth:.3f} mm")

    ax[1].annotate(f"Contact\n{contact_position:.2f} mm",
        xy=(contact_time, contact_position),
        xytext=(contact_time + 1, contact_position + 15),
        arrowprops=dict(arrowstyle="->"), color='blue')

    ax[1].annotate(f"Min\n{min_position:.2f} mm",
        xy=(min_time, min_position),
        xytext=(min_time - 2, min_position + 15),
        arrowprops=dict(arrowstyle="->"), color='orange')

    ax[1].set_xlabel("Time (s)")
    ax[1].set_ylabel("Position (mm)")
    ax[1].set_title("Raw Position Penetration Depth")
    ax[1].grid(True)
    ax[1].legend()

    plt.tight_layout()
    plt.show()


# Future stress/strain helper. The action-file generators below currently use
# measured depth and position only; this area estimate is kept for later force to
# stress conversion.
def calculate_area(dt, wkpc_diameter_in, die_num=4):
    """Estimate die/workpiece contact area for a given time increment.

    Parameters
    ----------
    dt : float
        Time increment paired with the assumed ram speed.
    wkpc_diameter_in : float
        Workpiece diameter in inches.
    die_num : int
        Die identifier. Die 4 assumes a 2 inch die width; die 2 assumes a
        0.25 inch die width.
    """
    v = 30 / 1000  # Assumed ram speed in m/s.
    d = (wkpc_diameter_in * 25.4) / 1000  # Workpiece diameter, inches to meters.
    l = 2 * d * np.cos(np.arcsin((0.5 * d - 0.5 * v * dt) / (0.5 * d)))
    if die_num == 4:
        w = 2 * (2.54 / 100)  # 2 inch die width to meters.
    elif die_num == 2:
        w = 0.25 * (2.54 / 100)  # 0.25 inch die width to meters.
    return l * w


def create_action_file_from_rl_actions(x_pos_list, theta_list, depth_list, temperature, runName):
    """Create a DEFORM action CSV from externally proposed action values.

    This path is intended for RL or optimization policies that already provide
    the desired relative x positions, workpiece angles, and hit depths. The
    function adds the DEFORM movement columns `offset_in` and `rotation`, which
    are calculated as step-to-step changes between successive absolute commands.
    """
    # Start an instruction table with one hit number per proposed action row.
    # NOTE: np.arange(1, len(x_pos_list)) produces one fewer row than x_pos_list.
    # That behavior is preserved here; check list lengths if pandas raises an
    # assignment-length error during use.
    dfDEFORM_instructs = pd.DataFrame(np.arange(1, len(x_pos_list)), columns=['hit_number'])

    # These columns are direct policy outputs.
    dfDEFORM_instructs['x_rel_pos_in'] = x_pos_list
    dfDEFORM_instructs['angle_of_workpiece'] = theta_list
    dfDEFORM_instructs['depth_in'] = depth_list

    # DEFORM needs incremental movement instructions, not just absolute desired
    # positions. The first row starts from zero offset/rotation, then later rows
    # move by the difference between consecutive commands.
    offset_vals, rotation_vals = [0], [0]
    xposs = dfDEFORM_instructs['x_rel_pos_in'].values
    thetas = dfDEFORM_instructs['angle_of_workpiece'].values

    for idx, xpos in enumerate(xposs[:-1]):
        offset_vals.append(xposs[idx + 1] - xpos)
        rotation_vals.append(thetas[idx + 1] - thetas[idx])

    dfDEFORM_instructs['offset_in'] = offset_vals
    dfDEFORM_instructs['rotation'] = rotation_vals

    # Apply the same forging temperature to all policy-generated hits.
    dfDEFORM_instructs['temperature_of_workpiece_C'] = temperature

    dfDEFORM_instructs.to_csv(f"rl_{runName}_policy_deform_actions.csv", index=False)


def create_action_file_from_af_load_stroke(wkpc_diameter_in, hitFolders, plot=False):
    """Create DEFORM action CSVs from AF machine load-stroke files.

    For each raw AF CSV, this function extracts the commanded workpiece position,
    detects contact from the force signal, measures depth from the position
    trace, converts millimeter values to inches, and computes the incremental
    `offset_in` and `rotation` commands needed by the DEFORM runner.

    Parameters
    ----------
    wkpc_diameter_in : float
        Workpiece diameter in inches. Currently converted to millimeters for
        future geometry/stress use.
    hitFolders : list[str]
        Subfolders under `base_path` that contain raw AF CSV files.
    plot : bool
        When True, show the contact/depth diagnostic plot for every hit.
    """
    # Root folder containing one subfolder per AF run or hit group.
    #TODO: update this.
    base_path = r"C:\Users\nbian\OneDrive\Desktop\OSU Research\AF Data"

    # Converted for future geometry calculations; not currently exported.
    wkpc_diameter_mm = wkpc_diameter_in * 25.4

    # Contact search begins only after the ram position crosses this threshold.
    position_start_threshold_mm = 30.0

    # Accumulates all processed hits. Because this list is defined outside the
    # folder loop, multiple hitFolders will be combined unless it is reset inside
    # the loop later.
    deformInstructions = []

    # Process every selected AF folder.
    for hitFolder in hitFolders:
        print(hitFolder)

        hitPath = os.path.join(base_path, hitFolder)
        hitFiles = os.listdir(hitPath)
        hitNum = 1

        # Each raw file is treated as one forging hit.
        for hitIdx, hitFile in enumerate(hitFiles):
            # Infer material from the filename convention. If the second token is
            # 316L, mark 316L; otherwise default to 4140.
            if hitFile.split("_")[1] == '316L':
                material = '316L'
            else:
                material = '4140'

            # Load raw machine data.
            hitDf = pd.read_csv(os.path.join(hitPath, hitFile))

            # Convert Unix milliseconds to elapsed seconds from the start of this
            # file, so every hit has a local time vector beginning at zero.
            hitDf["Time (s)"] = (hitDf["Time Unix (ms)"] - hitDf["Time Unix (ms)"].min()) / 1000.0

            # Extract repeated metadata and commanded positions. value_counts()
            # chooses the most common command value in case the column contains
            # repeated samples or occasional transient entries.
            die_num = hitDf['Ram Side Tool Number'].values[0]
            x = hitDf['X'].value_counts().index.values[0]
            z = hitDf['Z'].value_counts().index.values[0]
            theta = hitDf['A'].value_counts().index.values[0]
            y_init = hitDf['Y'].values[0]
            Fmax = hitDf['Force (kN)'].max()

            # -----------------------------
            # Extract arrays
            # -----------------------------
            # These arrays drive contact detection and depth measurement.
            t = hitDf["Time (s)"].to_numpy()
            T = hitDf["Thermal Cam Temp (c)"].to_numpy()
            position = hitDf["Position (mm)"].to_numpy()
            force = hitDf['Force (kN)'].to_numpy()

            print(f"### Hit {hitNum} \t {hitFile}")
            print(f"Position Data (x,y,z,A): {x, y_init, z, theta}")
            print(f"Max Force: {Fmax} kN")

            # Sort by elapsed time before any threshold logic.
            sort_idx = np.argsort(t)
            t = t[sort_idx]
            force = force[sort_idx]
            position = position[sort_idx]

            # Duplicate sort retained from the existing script. It is harmless
            # after the first sort and keeps behavior unchanged.
            sort_idx = np.argsort(t)
            t = t[sort_idx]
            force = force[sort_idx]
            position = position[sort_idx]

            # -----------------------------
            # Ignore motion before position reaches threshold
            # -----------------------------

            # Start searching for contact only once the tool is close enough to
            # the workpiece to avoid baseline force noise.
            start_candidates = np.where(position <= position_start_threshold_mm)[0]
            start_search_idx = start_candidates[0]

            # Force values before the search window represent baseline noise.
            baseline_force = force[:start_search_idx]

            force_baseline_mean = np.mean(baseline_force)
            force_baseline_std = np.std(baseline_force)
            force_threshold = force_baseline_mean + 1.5 * force_baseline_std

            # Enforce a minimum threshold so tiny baseline variation does not
            # trigger false contact.
            force_threshold = max(force_threshold, 0.25)  # kN

            # First force value above threshold marks contact. The correction uses
            # the sample immediately before the spike as the contact position.
            contact_idx = None
            correction = 1

            for i in range(start_search_idx, len(t)):
                if force[i] > force_threshold:
                    contact_idx = (i - correction)
                    break

            # -----------------------------
            # Minimum raw position after contact
            # -----------------------------
            try:
                # The deepest point of the stroke is the minimum position after
                # contact. Depth is contact position minus that minimum position.
                min_idx = contact_idx + np.argmin(position[contact_idx:])
                contact_time = t[contact_idx]
                contact_force = force[contact_idx]
                contact_position = position[contact_idx]
                contact_temperature = T[contact_idx]

                min_time = t[min_idx]
                min_position = position[min_idx]

                penetration_depth = contact_position - min_position

                print(f"Contact time: {contact_time:.4f} s")
                print(f"Contact force: {contact_force:.4f} kN")
                print(f"Contact position: {contact_position:.4f} mm")
                print(f"Contact temperature: {contact_temperature:.4f} C")

                print(f"Minimum position: {min_position:.4f} mm")
                print(f"Penetration depth: {penetration_depth:.4f} mm")
                if plot:
                    contact_detection_plots(t, position, force, force_threshold,
                                    start_search_idx, contact_time, contact_force,
                                    contact_position, min_time, min_position, position_start_threshold_mm,
                                    penetration_depth)

            except TypeError:
                # If no contact point is found, contact_idx remains None and the
                # calculations above fail. Current behavior skips the exception
                # and continues to the next file.
                pass

            # Store the measured hit data in millimeter/C/kN units first.
            dataRow = [hitNum, material, x, theta, contact_position, min_position, penetration_depth, contact_temperature, Fmax]
            deformInstructions.append(dataRow)
            hitNum += 1

        # Convert accumulated rows into the action-file schema used by downstream
        # DEFORM automation.
        dfDEFORM_instructs = pd.DataFrame(deformInstructions, columns=['hit_number', 'material', 'x_mm', 'angle_of_workpiece',
                                                    'contact_position_mm', 'min_position_mm', 'depth_mm',
                                                   'temperature_of_workpiece_C', 'max_force_kN'])

        # DEFORM action files use inches for relative position and depth.
        dfDEFORM_instructs['x_in'] = dfDEFORM_instructs['x_mm'] / 25.4  # mm -> in
        dfDEFORM_instructs['x_rel_pos_in'] = dfDEFORM_instructs['x_in'] - np.max(dfDEFORM_instructs['x_in'])
        dfDEFORM_instructs['depth_in'] = dfDEFORM_instructs['depth_mm'] / 25.4

        # Convert absolute relative positions and angles into incremental moves
        # between hits. Hit 1 starts with zero offset and zero rotation.
        offset_vals, rotation_vals = [0], [0]
        xposs = dfDEFORM_instructs['x_rel_pos_in'].values
        thetas = dfDEFORM_instructs['angle_of_workpiece'].values

        for idx, xpos in enumerate(xposs[:-1]):
            offset_vals.append(xposs[idx + 1] - xpos)
            rotation_vals.append(thetas[idx + 1] - thetas[idx])

        dfDEFORM_instructs['offset_in'] = offset_vals
        dfDEFORM_instructs['rotation'] = rotation_vals

        # One action CSV is written per hitFolder. Because deformInstructions is
        # not reset inside the folder loop, later folders include earlier rows.
        dfDEFORM_instructs.to_csv(f"af_{hitFolder}_deform_actions.csv", index=False)


# -----------------------------
# Script entry point
# -----------------------------
# Edit these values when running this file directly.
hitFolders = ["Box"]
wkpc_diameter_in = 1
create_action_file_from_af_load_stroke(wkpc_diameter_in, hitFolders, plot=False)