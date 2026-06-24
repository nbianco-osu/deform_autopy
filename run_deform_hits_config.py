"""
Run a DEFORM multihit forging sequence from an action CSV.

High-level workflow:
1. Read a base DEFORM key file.
2. For each hit, generate die stroke(s) from CSV depth/speed values.
3. Write and run a DEFORM database.
4. Read the final state, reposition/rotate the workpiece for the next hit.
5. Re-seat both dies around the workpiece and save the next-hit key file.
"""

from deformModel import defModel
import argparse
import json
import os
import sys
import threading
from deformRun import *
from deformCommon import *
try:
    from deformPost import defPost
except ImportError:
    defPost = None
from enumPosition import *
from enumObject import *
from deformContact import *
from deformObject import *
from die_positioning import (
    format_vector,
    get_die_motion_axis_vectors,
    position_dies_before_hits,
    save_object_coordinates,
    scale_vector,
)
import time
import pandas as pd
import csv
from grain_initialization import create_supplier_grain_size_string_from_key
from run_deform_post_processing import process_run

USER_PATH = os.path.expanduser('~')

DEFAULT_CONFIG = {
    # Folder containing base key files on the lab computer.
    "key_path": os.path.join(USER_PATH,r"Desktop\deform_auto_py\key_files"),
    "custom_key_bool": True,
    "custom_key_name": "agility_forge_die2_1in_stock_IN625mat_coarse_rev.key",
    # Folder containing the action CSV files on the lab computer.
    "action_path": os.path.join(USER_PATH,r"Desktop\deform_auto_py\action_files"),
    # CSV describing pass position, offset, rotation, temperature, speed, and depth.
    # Small die - AF_TensileBar_P1-1_deform_info_v4_rev_bdm - w/ and w/o bdm
    # Large die - AF_TensileBar_P2-2_deform_info_v6_rev_bdm - w/ and w/o bdm
    "action_file": "AF_TensileBar_P2-2_deform_info_v6_rev.csv",
    "action_version": "v6",
    # When true, action filename tags such as "bdm" can set compatible defaults.
    "apply_action_file_rules": True,
    # Parent output folder. A run-specific folder is created under this path.
    "data_path": os.path.join(USER_PATH,r"Desktop\deform_auto_py\runs"),
    "tp_type": "", # to be filled in later
    "material": "316L", # materials supported include 316L, 4140, 4340, 15-5
    "run_number": 2,
    # Use an integer for a partial run, or set to "all" in config to use every CSV row.
    "num_hits": 1,
    # Clearance used when re-seating dies after a hit.
    "height": 0.025,
    # DEFORM max time step for the stroke. Smaller is slower but can improve stability.
    "time_step": 0.001,
    # Save every nth simulation step.
    "save_step_size": 25,
    "bottom_die_retract_speed_multiplier": 1.5,
    "bottom_die_retract_lead_steps": 10,
    "die_motion_mode": '', # to be filled in later - based on action file
    # Axis normal to the dies. "z" preserves the original setup; "y" supports
    # dies that close along the Y axis.
    "die_motion_axis": "z",
    "position_bottom_die_before_first_hit": '', # same for this field # same for this field
    "position_dies_before_first_hit": True, # always true to allow flexibility for runs
    # When true, hit 0 starts from a general key file by seating the dies on the
    # workpiece and backing them out by `height` before the first DB is written.
    "top_die_interference": 0.0001,
    "bottom_die_interference": 0.0001,
    "run_name": '', # to be filled in later
    "die_column": "die", # used to extract which die is used in the run
    "mesh_type" : "coarse", # supports "coarse" or "fine"
    #TODO: update stock diameters to support other diameters only
    "stock_diameter": 0.625, # supports 0.625in only 
    "use_jmak": True, # 316L is the only alloy with grain data
    "mean_grain_size_um": 26.3,
    "enable_lag_time": False, # TODO: update to support lag time between hits and heats
    # Output controls used by DOE/result-processing workflows.
    "export_post_hit_keys": True,
    "export_coordinate_logs": True,
    "export_load_stroke": True,
    "load_stroke_object": "Top Die",
    # When true, run_deform_post_processing.py is called after all hits finish.
    # This creates post_processed/*.csv and run_summary.json for the completed run.
    "post_process_after_run": True,
    "post_process_output_subdir": "post_processed",
    "post_process_damage_object": "Workpiece",
    "post_process_damage_step_no": 0,
    "columns": {
        "offset": "offset_in",
        "rotation": "rotation",
        "position": "x_pos_rel_in",
        "temperature_c": "forging_temp_c",
        "speed": "speed_in/s",
        "depth": "depth_in"
    },
    "key_files": {
        "2": "agility_forge_die2_{stock_diameter}in_stock_{material}mat_{mesh_type}_rev.key",
        "4": "agility_forge_die4_{stock_diameter}in_stock_{material}mat_{mesh_type}_rev.key"
    }
}


def deep_update(base, updates):
    """Merge user config values into DEFAULT_CONFIG while preserving nested defaults."""
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load_config(config_path):
    """Load JSON config if provided; otherwise use the built-in v3 defaults."""
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if config_path:
        with open(config_path, "r") as file:
            deep_update(config, json.load(file))
        config["_config_dir"] = os.path.dirname(os.path.abspath(config_path))
    else:
        config["_config_dir"] = os.getcwd()
    return config


def apply_action_file_rules(config):
    """Infer compatible run settings from action-file naming conventions.

    Current rule:
    - If the action filename contains "bdm", treat it as a both-dies-moving
      sequence. That requires symmetric die motion and bottom-die positioning
      before hit 0.
    """
    
    # Die motion options:
    # - "symmetric": top and bottom dies move toward/away from the workpiece 
    #together.
    # - "single_top_die": top die performs the hit; bottom die retracts near 
    #the end.
    
    if not config.get("apply_action_file_rules", True):
        return config

    action_file = os.path.basename(str(config.get("action_file", ""))).lower()
    if "bdm" in action_file:
        config["die_motion_mode"] = "symmetric"
        config["position_bottom_die_before_first_hit"] = True
    else:
        config["die_motion_mode"] = "single_top_die"
        config["position_bottom_die_before_first_hit"] = False
        
    config['tp_type'] = config['action_file'].split("_")[2]
    if config["custom_key_bool"]:
        config["run_name"] = f"{config["custom_key_name"][:-4]}_run{config['run_number']}_{config['num_hits']}hits"
    else:
        if config['use_jmak']:
            config['run_name'] = f"af_{config['tp_type']}_{config['material']}_rev_{config['action_version']}_run{config['run_number']}_{config['num_hits']}hits_{config['die_motion_mode']}_jmak"
        else:
            config['run_name'] = f"af_{config['tp_type']}_{config['material']}_rev_{config['action_version']}_run{config['run_number']}_{config['num_hits']}hits_{config['die_motion_mode']}"

    return config


def format_config_value(value, config):
    """Apply config placeholders such as {material}, {run_number}, {num_hits},
    {mesh_type}, and {stock_diameter}."""
    if not isinstance(value, str):
        return value

    return value.format(
        tp_type=config.get("tp_type", ""),
        material=config.get("material", ""),
        run_number=config.get("run_number", ""),
        num_hits=config.get("num_hits", ""),
        height=config.get("height", ""),
        die=config.get("die", ""),
        mesh_type=config.get("mesh_type", ""),
        stock_diameter=config.get("stock_diameter", "")
    )


def resolve_path(path_value, config):
    """Resolve absolute paths and config-relative paths consistently."""
    path_value = format_config_value(path_value, config)
    if os.path.isabs(path_value):
        return path_value
    return os.path.abspath(os.path.join(config["_config_dir"], path_value))


def get_action_path(config):
    """Return the CSV path, treating relative action_file values as base_path-relative."""
    action_file = format_config_value(config["action_file"], config)
    if os.path.isabs(action_file):
        return action_file
    return os.path.join(resolve_path(config["action_path"], config), action_file)


def get_die(actions_df, config):
    """Read die number from config or from the configured CSV die column."""
    if config.get("die") is not None:
        return int(config["die"])

    die_column = config.get("die_column", "die")
    if die_column not in actions_df.columns:
        raise ValueError(
            f"Die was not set in the config and CSV column '{die_column}' was not found."
        )
    return int(actions_df[die_column].values[0])


def get_num_hits(actions_df, config):
    """Validate and return the requested number of hits."""
    num_hits = config.get("num_hits", "all")
    if isinstance(num_hits, str) and num_hits.lower() == "all":
        return actions_df.shape[0]

    num_hits = int(num_hits)
    if num_hits < 1:
        raise ValueError("num_hits must be at least 1.")
    if num_hits > actions_df.shape[0]:
        raise ValueError(
            f"num_hits={num_hits} but the action CSV only has {actions_df.shape[0]} rows."
        )
    return num_hits


def get_init_key(config, die):
    """Select the initial key file from an explicit path or die-specific template."""
    if config.get("init_key"):
        return resolve_path(config["init_key"], config)

    key_files = config.get("key_files", {})
    die_key = str(die)
    if die_key not in key_files and config["custom_key_bool"] == False:
        supported = ", ".join(sorted(key_files.keys()))
        raise ValueError(f"No key file configured for die {die}. Supported dies: {supported}")
    elif config["custom_key_name"]:
        return os.path.join(resolve_path(config["key_path"], config), config["custom_key_name"])
    key_file = format_config_value(key_files[die_key], config)
    if config['use_jmak']:
        return os.path.join(resolve_path(config["key_path"], config), key_file[:-4]+"_jmak.key")
    else:
        return os.path.join(resolve_path(config["key_path"], config), key_file)


def validate_config(config, actions_df, action_path, init_key):
    """Fail early for missing files, missing CSV columns, and invalid timing settings."""
    columns = config["columns"]
    required_columns = [
        config.get("die_column", "die"),
        columns["offset"],
        columns["rotation"],
        columns["position"],
        columns["temperature_c"],
        columns["speed"],
        columns["depth"],
    ]
    missing_columns = [column for column in required_columns if column not in actions_df.columns]
    if missing_columns:
        raise ValueError("Action CSV is missing required columns: " + ", ".join(missing_columns))

    if not os.path.exists(action_path):
        raise FileNotFoundError(f"Action CSV was not found: {action_path}")
    if not os.path.exists(init_key):
        raise FileNotFoundError(f"Initial key file was not found: {init_key}")
    if float(config["height"]) <= 0:
        raise ValueError("height must be greater than 0.")
    if float(config["time_step"]) <= 0:
        raise ValueError("time_step must be greater than 0.")
    if int(config["save_step_size"]) <= 0:
        raise ValueError("save_step_size must be greater than 0.")
    if not isinstance(config["apply_action_file_rules"], bool):
        raise ValueError("apply_action_file_rules must be true or false.")        
    if float(config["bottom_die_retract_speed_multiplier"]) <= 0:
        raise ValueError("bottom_die_retract_speed_multiplier must be greater than 0.")
    if int(config["bottom_die_retract_lead_steps"]) < 0:
        raise ValueError("bottom_die_retract_lead_steps must be zero or greater.")
    if not isinstance(config["position_dies_before_first_hit"], bool):
        raise ValueError("position_dies_before_first_hit must be true or false.")
    if not isinstance(config["position_bottom_die_before_first_hit"], bool):
        raise ValueError("position_bottom_die_before_first_hit must be true or false.")
    if str(config.get("die_motion_axis", "z")).lower() not in ["z", "y"]:
        raise ValueError("die_motion_axis must be 'z' or 'y'.")
    for key in ["export_post_hit_keys", "export_coordinate_logs", "export_load_stroke","post_process_after_run"]:
        if not isinstance(config.get(key, True), bool):
            raise ValueError(f"{key} must be true or false.")
    if int(config.get("post_process_damage_step_no", 0)) < 0:
        raise ValueError("post_process_damage_step_no must be zero or greater.")


def celsius_to_fahrenheit(temp_c):
    """DEFORM key strings in this workflow expect temperature in Fahrenheit."""
    temp_f = (9 / 5) * temp_c + 32
    return f"{temp_f:.10E}"


def run_job():
    """Submit the active DEFORM problem and print progress until the solve completes."""
    event = threading.Event()

    def submit_job():
        # submitJobInteractively blocks, so run it on a thread while progress is polled.
        print("Job is running...")
        defRun.submitJobInteractively(defModel.getProbID())
        event.set()

    thread = threading.Thread(target=submit_job)
    thread.start()

    while thread.is_alive():
        time.sleep(1)
        defRun.showProgress()

    stop_code = defRun.getStopCode()
    if defRun.isNormalStop():
        print("\nJob is finished successfully! (Code %d)" % stop_code)
        print("Stop reason: " + defRun.getStopReason())
    else:
        print("\nJob is finished abnormally! (Code %d)" % stop_code)
        print("Stop reason: " + defRun.getStopReason())


def build_stroke_plan(stroke_start, depth, speed, height, time_step, bottom_die_retract_lead_steps):
    """Create timing values for one down-up-stop hit sequence."""
    move_dist = height + depth
    move_time = move_dist / speed
    stroke_down_end = stroke_start + move_time
    mid_change = stroke_down_end + time_step
    stroke_up_start = stroke_down_end + 2 * time_step
    stroke_up_end = stroke_up_start + move_time
    stroke_up_start_bottom_die = stroke_up_end - bottom_die_retract_lead_steps * time_step
    lag_start = stroke_up_end + time_step
    stroke_end = lag_start + time_step

    return {
        "move_dist": move_dist,
        "move_time": move_time,
        "num_steps_to_contact": int(move_time / time_step),
        "stroke_start": stroke_start,
        "stroke_down_end": stroke_down_end,
        "mid_change": mid_change,
        "stroke_up_start": stroke_up_start,
        "stroke_up_end": stroke_up_end,
        "stroke_up_start_bottom_die": stroke_up_start_bottom_die,
        "lag_start": lag_start,
        "stroke_end": stroke_end,
        "hit_steps": int((stroke_end - stroke_start) / time_step),
    }


def format_movctl_direction(die_motion_axis="z"):
    """Return the MOVCTL direction vector in DEFORM key-string formatting."""
    movctl_dir = get_die_motion_axis_vectors(die_motion_axis)["movctl_dir"]
    return (
        f"{movctl_dir[0]:.10E}    "
        f"{movctl_dir[1]:.10E}   "
        f"{movctl_dir[2]:.10E}"
    ).replace("E+00", "E+000").replace("E-00", "E-000")


def set_symmetric_die_motion(plan, speed, die_motion_axis="z"):
    """Write mirrored MOVCTL blocks for Top Die and Bottom Die.

    The signs intentionally oppose each other: as the top die moves toward the
    workpiece, the bottom die moves toward it from the opposite side. This is
    the anti-bending behavior and should be preserved as the default.
    """
    movctl_dir_text = format_movctl_direction(die_motion_axis)

    defModel.importKeyString(f"""MOVCTL       2       1       2    {movctl_dir_text}       7
        {plan["stroke_start"]:.6E}    {speed:.6E}
        {plan["stroke_down_end"]:.6E}    {speed:.6E}
        {plan["mid_change"]:.6E}    0.0000000000E+000
        {plan["stroke_up_start"]:.6E}    -{speed:.6E}
        {plan["stroke_up_end"]:.6E}    -{speed:.6E}
        {plan["lag_start"]:.6E}    0.0000000000E+000
         {plan["stroke_end"]:.6E}    0.0000000000E+000
        """)

    defModel.importKeyString(f"""MOVCTL       3       1       2    {movctl_dir_text}       7
        {plan["stroke_start"]:.6E}    -{speed:.6E}
        {plan["stroke_down_end"]:.6E}    -{speed:.6E}
        {plan["mid_change"]:.6E}    0.0000000000E+000
        {plan["stroke_up_start"]:.6E}    {speed:.6E}
        {plan["stroke_up_end"]:.6E}    {speed:.6E}
        {plan["lag_start"]:.6E}    0.0000000000E+000
        {plan["stroke_end"]:.6E}    0.0000000000E+000
        """)


def set_single_top_die_motion(plan, speed, bottom_die_retract_speed_multiplier, die_motion_axis="z"):
    """Write MOVCTL blocks for top-die-only forming with delayed bottom-die retract.

    The top die performs the normal down-up stroke. The bottom die remains still
    through the downstroke, then retracts shortly before the top die reaches its
    upper position. This matches the earlier single-die movement pattern.
    """
    speed_down = speed * bottom_die_retract_speed_multiplier
    movctl_dir_text = format_movctl_direction(die_motion_axis)

    defModel.importKeyString(f"""MOVCTL       2       1       2    {movctl_dir_text}       7
        {plan["stroke_start"]:.6E}    {speed:.6E}
        {plan["stroke_down_end"]:.6E}    {speed:.6E}
        {plan["mid_change"]:.6E}    0.0000000000E+000
        {plan["stroke_up_start"]:.6E}    -{speed:.6E}
        {plan["stroke_up_end"]:.6E}    -{speed:.6E}
        {plan["lag_start"]:.6E}    0.0000000000E+000
        {plan["stroke_end"]:.6E}    0.0000000000E+000
        """)

    defModel.importKeyString(f"""MOVCTL       3       1       2    {movctl_dir_text}       7
        {plan["stroke_start"]:.6E}    0.0000000000E+000
        {plan["stroke_down_end"]:.6E}    0.0000000000E+000
        {plan["mid_change"]:.6E}    0.0000000000E+000
        {plan["stroke_up_start_bottom_die"]:.6E}    {speed_down:.6E}
        {plan["stroke_up_end"]:.6E}    {speed_down:.6E}
        {plan["lag_start"]:.6E}    0.0000000000E+000
        {plan["stroke_end"]:.6E}    0.0000000000E+000
        """)


def set_die_motion(plan, speed, die_motion_mode, bottom_die_retract_speed_multiplier, die_motion_axis="z"):
    """Apply the configured die-motion strategy for the current hit."""
    if die_motion_mode == "symmetric":
        set_symmetric_die_motion(plan, speed, die_motion_axis=die_motion_axis)
    elif die_motion_mode == "single_top_die":
        set_single_top_die_motion(
            plan,
            speed,
            bottom_die_retract_speed_multiplier,
            die_motion_axis=die_motion_axis,
        )
    else:
        raise ValueError(f"Unsupported die_motion_mode: {die_motion_mode}")


def reseat_dies(height, top_die_interference, bottom_die_interference, position_bottom_die, die_motion_axis="z"):
    """Place both dies back around the solved workpiece before the next hit.

    Interference positioning brings each die to the workpiece surface, then the
    symmetric offsets reopen the die gap by +/- height.
    """
    axis_vectors = get_die_motion_axis_vectors(die_motion_axis)
    defModel.position.perform(
        "Top Die",
        PositionType.Interference,
        (
            f"interference={top_die_interference}, upStroke=false, "
            f"refObj='Workpiece', "
            f"dir={format_vector(axis_vectors['top_interference_dir'])}, moveOut='true'"
        ),
        "Top Die",
    )

    defModel.position.perform(
        "Bottom Die",
        PositionType.Interference,
        (
            f"interference={bottom_die_interference}, upStroke=false, "
            f"refObj='Workpiece', "
            f"dir={format_vector(axis_vectors['bottom_interference_dir'])}, moveOut='true'"
        ),
        "Bottom Die",
    )

    defModel.position.perform(
        "Top Die",
        PositionType.Offset,
        f"offset={format_vector(scale_vector(axis_vectors['top_offset'], height))}, upStroke=false",
    )
    if position_bottom_die:
        defModel.position.perform(
            "Bottom Die",
            PositionType.Offset,
            f"offset={format_vector(scale_vector(axis_vectors['bottom_offset'], height))}, upStroke=false",
        )


def reposition_workpiece(actions_df, columns, hit):
    """Apply the next CSV offset and rotation to the workpiece.

    This preserves the behavior from the working script: the workpiece is
    repositioned between hits, while each hit itself uses symmetric die motion.
    """
    offset_val = -1 * actions_df[columns["offset"]].values[hit]
    rot_ang = actions_df[columns["rotation"]].values[hit]

    defModel.position.perform(
        "Workpiece",
        PositionType.Offset,
        f"offset=({offset_val},0,0), upStroke=false",
    )
    defModel.position.perform(
        "Workpiece",
        PositionType.Rotation,
        f"angle={rot_ang}, axis=(1,0,0), selfCenter=true",
    )


def print_runtime_summary(config, action_path, init_key, die, num_hits, run_name, data_path, die_motion_mode, die_motion_axis):
    """Print the run settings most useful for checking a long DEFORM job."""
    print("Loaded DEFORM multihit configuration:")
    print(f"  Action CSV : {action_path}")
    print(f"  Run name   : {run_name}")
    print(f"  Material   : {config['material']}")
    print(f"  Die        : {die}")
    print(f"  Hits       : {num_hits}")
    print(f"  Init key   : {init_key}")
    print(f"  Runs path  : {data_path}")
    print(f"  Die motion : {die_motion_mode}")
    print(f"  Die axis   : {die_motion_axis}")
   
    
def is_number_token(token):
    """Return True when a load-stroke text token can be parsed as a number."""
    try:
        float(str(token).replace("D", "E"))
        return True
    except ValueError:
        return False


def make_unique_columns(columns):
    """Create safe, unique CSV column names from exporter text headers."""
    seen = {}
    result = []
    for index, column in enumerate(columns, start=1):
        safe = str(column).strip().replace("/", "_").replace("-", "_")
        safe = safe.replace("(", "").replace(")", "").replace(".", "")
        safe = safe or f"column_{index}"
        count = seen.get(safe, 0)
        seen[safe] = count + 1
        result.append(safe if count == 0 else f"{safe}_{count + 1}")
    return result

def convert_load_stroke_text_to_csv(text_path, csv_path):
    """Convert DEFORM load-stroke text output to a simple comma CSV.

    `defPost.export.loadStrokeTime` writes the same style of text file as
    DEFORM text post. The DOE workflow expects these columns:
    Step, Time, S, V, Fx, Fy, Fz.
    """
    header = ["Step", "Time", "S", "V", "Fx", "Fy", "Fz"]
    rows = []
    with open(text_path, "r") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith(("#", "$", "*")):
                continue
            if "," in line:
                tokens = [token.strip() for token in line.split(",") if token.strip()]
            else:
                tokens = line.split()
            if tokens:
                rows.append(tokens)

    if not rows:
        raise ValueError(f"No load-stroke rows found in {text_path}")

    first_row_is_header = any(not is_number_token(token) for token in rows[0])
    if first_row_is_header:
        data_rows = rows[1:]
    else:
        data_rows = rows

    width = len(header)
    normalized_rows = []
    for row in data_rows:
        if len(row) < width:
            row = row + [""] * (width - len(row))
        elif len(row) > width:
            row = row[:width]
        normalized_rows.append(row)

    with open(csv_path, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(normalized_rows)

    return csv_path


def get_object_by_name_or_number(object_name):
    """Return a DEFORM object by name, falling back to object number 1."""
    try:
        return defModel.getObj(object_name)
    except Exception:
        return defModel.getObjByNo(1)


def write_load_stroke_fallback_csv(output_file_path, hit, object_name, source, note):
    """Write one-row load/stroke summary from `getObjInfo()` as a fallback."""
    deform_object = get_object_by_name_or_number(object_name)
    obj_info = deform_object.getObjInfo()
    row = {
        "hit": hit,
        "object": object_name,
        "object_no": getattr(deform_object, "objNo", ""),
        "source": source,
        "note": note,
        "strokeX": getattr(obj_info, "strokeX", ""),
        "strokeY": getattr(obj_info, "strokeY", ""),
        "strokeZ": getattr(obj_info, "strokeZ", ""),
        "loadX": getattr(obj_info, "loadX", ""),
        "loadY": getattr(obj_info, "loadY", ""),
        "loadZ": getattr(obj_info, "loadZ", ""),
    }
    with open(output_file_path, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)
    return output_file_path


def export_load_stroke_csv(run_dir, hit, object_name="Top Die"):
    """Export per-hit load-stroke data to CSV.

    The primary path uses the DEFORM API reference-manual call
    `defPost.export.loadStrokeTime(outputFileName, objNo)`. If that exporter
    fails, a one-row load/stroke summary is written from object info so every
    completed hit still has a load-stroke CSV for the DOE dataset.
    """
    os.makedirs(run_dir, exist_ok=True)
    text_path = os.path.join(run_dir, f"load_stroke_hit{hit}.txt")
    csv_path = os.path.join(run_dir, f"load_stroke_hit{hit}.csv")

    try:
        if defPost is None:
            raise ImportError("deformPost.defPost is not available.")
        deform_object = get_object_by_name_or_number(object_name)
        object_no = int(getattr(deform_object, "objNo"))
        defPost.export.loadStrokeTime(text_path, object_no)
        return convert_load_stroke_text_to_csv(text_path, csv_path)
    except Exception as exc:
        return write_load_stroke_fallback_csv(
            output_file_path=csv_path,
            hit=hit,
            object_name=object_name,
            source="getObjInfo_fallback",
            note=str(exc),
        )


def save_coordinates_if_enabled(config, run_dir, hit, stage):
    """Save coordinate logs when enabled without stopping a completed solve."""
    if not config.get("export_coordinate_logs", True):
        return ""
    output_path = os.path.join(run_dir, f"object_coordinates_hit{hit}_{stage}.csv")
    try:
        save_object_coordinates(output_file_path=output_path, hit=hit, stage=stage)
        return output_path
    except Exception as exc:
        print(f"WARNING: Coordinate export failed for hit {hit}, stage {stage}: {exc}")
        return ""


def export_hit_outputs(config, run_dir, hit, stage, write_key=True):
    """Write standard per-hit artifacts for DOE processing."""
    if config.get("export_coordinate_logs", True):
        save_coordinates_if_enabled(config, run_dir, hit, stage)

    if config.get("export_load_stroke", True) and hit > 0 and stage == "final":
        try:
            export_load_stroke_csv(
                run_dir=run_dir,
                hit=hit,
                object_name=config.get("load_stroke_object", "Top Die"),
            )
        except Exception as exc:
            print(f"WARNING: Load-stroke export failed for hit {hit}: {exc}")

    if write_key and config.get("export_post_hit_keys", True):
        key_path = os.path.join(run_dir, f"af-hit-{hit}_{stage}.KEY")
        defModel.writeKey(key_path)
        return key_path
    return ""


def post_process_completed_run(config, config_path, run_root_dir):
    """Run the standalone post-processor after a successful multihit run.

    Post-processing is useful but should not erase the fact that DEFORM solved
    successfully. Any post-processing exception is reported as a warning and the
    runner exits normally.
    """
    if not config.get("post_process_after_run", True):
        print("\nPost-processing skipped: post_process_after_run is false.")
        return

    print("\n================ POST-PROCESSING RUN ================")
    try:
        print(config_path,run_root_dir)
        summary = process_run(
            config_path=config_path,
            config_override=config,
            run_dir=run_root_dir,
            output_subdir=config.get("post_process_output_subdir", "post_processed"),
            damage_object=config.get("post_process_damage_object", "Workpiece"),
            damage_step_no=int(config.get("post_process_damage_step_no", 0)),
        )
        print("Post-processing finished successfully.")
        summary_json = os.path.join(summary.get("output_dir", ""), "run_summary.json")
        print(f"  Summary JSON: {summary_json}")
    except Exception as exc:
        print(f"WARNING: Post-processing failed after the DEFORM run completed: {exc}")


def main(config_path=None):
    """Load inputs, generate each hit database, run it, and prepare the next hit."""
    config = load_config(config_path)
    apply_action_file_rules(config) # fill in gaps based on action file
    action_path = get_action_path(config)
    actions_df = pd.read_csv(action_path)
    die = get_die(actions_df, config)
    config["die"] = die
    num_hits = get_num_hits(actions_df, config)
    config["num_hits"] = num_hits

    init_key = get_init_key(config, die)
    validate_config(config, actions_df, action_path, init_key)

    columns = config["columns"]
    height = float(config["height"])
    time_step = float(config["time_step"])
    save_step_size = int(config["save_step_size"])
    die_motion_mode = config["die_motion_mode"]
    die_motion_axis = str(config.get("die_motion_axis", "z")).lower()
    bottom_die_retract_speed_multiplier = float(config["bottom_die_retract_speed_multiplier"])
    bottom_die_retract_lead_steps = int(config["bottom_die_retract_lead_steps"])
    top_die_interference = float(config["top_die_interference"])
    bottom_die_interference = float(config["bottom_die_interference"])
    data_path = resolve_path(config["data_path"], config)
    run_name = format_config_value(config["run_name"], config)
    if config["use_jmak"]:
        mean_grain_size_um = float(config["mean_grain_size_um"])
    else:
        mean_grain_size_um = 0 # JMAK not active
        
    print_runtime_summary(config, action_path, init_key, die, num_hits, run_name, data_path, die_motion_mode, die_motion_axis)

    stroke_start = 0
    total_steps = 0

    for hit in range(num_hits + 1):
        # hit 0 only initializes the first DB/key state. Actual forming starts at hit 1.
        print(f"\n================ HIT {hit} of {num_hits} ================")
        run_dir = os.path.join(data_path, run_name, f"{run_name}-hit{hit}")
        os.makedirs(run_dir, exist_ok=True)
        defModel.setCurrentDir(run_dir)

        if hit == 0:
            print("Reading base keyfile......")
            defModel.readKey(init_key)
            
            # Update initial grain size 
            if config["use_jmak"]:
                defModel.importKeyString(create_supplier_grain_size_string_from_key(init_key, mean_grain_size_um))
            
            offset_val = -1 * actions_df[columns["offset"]].values[hit]
            rot_ang = actions_df[columns["rotation"]].values[hit]
            
            if die_motion_mode == 'symmetric':
                position_bottom_die = True
            else:
                position_bottom_die = False
                
            # other arguments in "position_dies_before_hits" are set in 
            # die_positioning.py
            position_dies_before_hits(
                height,
                top_die_interference=top_die_interference,
                bottom_die_interference=bottom_die_interference,
                position_bottom_die=position_bottom_die,
                die_motion_axis=die_motion_axis,
            )
            print(f"""\tOffset = {offset_val},
              Position = {actions_df[columns["position"]].values[hit]},
              Rotation = {rot_ang}""")
               

        else:
            # CSV row hit-1 defines the hit being solved. CSV row hit defines the
            # post-solve position/rotation used to set up the next hit.
            forge_temp = celsius_to_fahrenheit(actions_df[columns["temperature_c"]].values[hit - 1])
            pass_pos = actions_df[columns["position"]].values[hit - 1]
            speed = actions_df[columns["speed"]].values[hit - 1]
            depth = actions_df[columns["depth"]].values[hit - 1]

            try:
                rot_ang = actions_df[columns["rotation"]].values[hit]
                new_pos = actions_df[columns["position"]].values[hit]
            except IndexError:
                rot_ang = 0
                new_pos = "finished"

            if hit == 1:
                stroke_start = 0

            plan = build_stroke_plan(
                stroke_start,
                depth,
                speed,
                height,
                time_step,
                bottom_die_retract_lead_steps,
            )
            total_steps += plan["hit_steps"]

            print(f"""\tNew Position = {new_pos},
              Next Rotation = {rot_ang}
              Hit Position = {pass_pos},
              Hit Depth = {depth},
              Move Distance = {plan["move_dist"]},
              Move Time = {plan["move_time"]},
              Number of Steps = {plan["num_steps_to_contact"]},
              Start Time = {plan["stroke_start"]},
              End Time = {plan["stroke_end"]},
              Total Steps = {total_steps}
              """)
              
            save_coordinates_if_enabled(config, run_dir, hit, "pre_solve")
            
            defModel.simCtrl.setStepSettings(
                f'NSTART=-1, NSTEP={plan["hit_steps"]}, STPINC={save_step_size}, DTMAX={time_step}'
            )
            set_die_motion(
                plan,
                speed,
                die_motion_mode,
                bottom_die_retract_speed_multiplier,
                die_motion_axis=die_motion_axis,
            )
            stroke_start = plan["stroke_end"]

            # Update thermal state and reset target volume before writing the DB.
            defModel.importKeyString(f"NDTMP        1       0    {forge_temp}")
            defModel.importKeyString("TRGVOL       1       1     0")

        db_name = os.path.join(run_dir, f"af_hit{hit}.DB")
        defModel.writeDb(db_name)

        if defModel.doesDbExist() is True:
            print("DB is generated")
            print("  ProblID: " + defModel.getProbID())
        else:
            print("DB is NOT generated")
            sys.exit(1)

        if hit > 0:
            run_job()
            defModel.readDb(os.path.join(run_dir, db_name), 0)
            export_hit_outputs(config, run_dir, hit, "final", write_key=True)
        else:
            export_hit_outputs(config, run_dir, hit, "initial", write_key=True)
            
        if 0 < hit < num_hits:
            # Prepare geometry for the next hit from the final solved state.
            reposition_workpiece(actions_df, columns, hit)
            reseat_dies(
                height,
                top_die_interference,
                bottom_die_interference,
                position_bottom_die,
                die_motion_axis=die_motion_axis,
            )
            export_hit_outputs(config, run_dir, hit, "post", write_key=True)
        elif hit > 0:
            # For the last hit, post and final are intentionally identical.
            export_hit_outputs(config, run_dir, hit, "post", write_key=True)

        if (hit + 1) <= num_hits:
            next_hit_dir = os.path.join(data_path, run_name, f"{run_name}-hit{hit + 1}")
            os.makedirs(next_hit_dir, exist_ok=True)
            defModel.writeKey(os.path.join(next_hit_dir, f"af-hit-{hit + 1}.KEY"))
            
    print("\n================ DONE: ALL HITS COMPLETE ================")
    post_process_completed_run(
        config=config,
        config_path=config_path,
        run_root_dir=os.path.join(data_path, run_name))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run DEFORM multihit sequence.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to a JSON config file. If omitted, built-in v3 defaults are used.",
    )
    args = parser.parse_args()
    main(args.config)
