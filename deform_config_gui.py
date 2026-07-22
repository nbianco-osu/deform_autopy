"""
Tkinter GUI for configuring and launching run_deform_hits_config.py.

The GUI intentionally does not import run_deform_hits_config.py. That runner
imports DEFORM API modules, which may only be available in the lab DEFORM Python
environment. Instead, this file safely reads DEFAULT_CONFIG from the runner
source and writes an external JSON config that the runner already supports.
"""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


APP_DIR = Path(__file__).resolve().parent
RUNNER_PATH = APP_DIR / "run_deform_hits_config.py"
CONFIG_DIR = APP_DIR / "configs"


MATERIAL_OPTIONS = [
    "AISI-316L[1650-2000F(900-1100C)]",
    "AISI-4140[70-2200F(20-1200C)]",
    "AISI-4340[1550-2200F(850-1200C)]",
    "15-5-stainless[1550-2200F(850-1200C)]",
]

SHORT_MATERIAL_OPTIONS = ["316L", "4140", "4340", "15-5", "IN625"]
MATERIAL_SOURCE_OPTIONS = ["system_library", "user_library", "key", "db", "assign"]
DIE_MOTION_OPTIONS = ["", "single_top_die", "symmetric"]
DIE_AXIS_OPTIONS = ["z", "y"]
MESH_OPTIONS = ["coarse", "fine"]
BOOLEAN_OPTIONS = ["true", "false"]


def safe_eval_default_config_node(node, names):
    """Evaluate the subset of Python syntax used by DEFAULT_CONFIG."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        return {
            safe_eval_default_config_node(key, names): safe_eval_default_config_node(value, names)
            for key, value in zip(node.keys, node.values)
        }
    if isinstance(node, ast.List):
        return [safe_eval_default_config_node(item, names) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(safe_eval_default_config_node(item, names) for item in node.elts)
    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        raise ValueError(f"Unsupported name in DEFAULT_CONFIG: {node.id}")
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            else:
                raise ValueError("f-strings are not supported in DEFAULT_CONFIG extraction.")
        return "".join(parts)
    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "os"
            and node.func.value.attr == "path"
            and node.func.attr == "join"
        ):
            args = [safe_eval_default_config_node(arg, names) for arg in node.args]
            return os.path.join(*args)
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "os"
            and node.func.value.attr == "path"
            and node.func.attr == "expanduser"
        ):
            args = [safe_eval_default_config_node(arg, names) for arg in node.args]
            return os.path.expanduser(*args)
        raise ValueError(
            "Only os.path.join(...) and os.path.expanduser(...) calls are supported "
            "in DEFAULT_CONFIG extraction."
        )
    raise ValueError(f"Unsupported DEFAULT_CONFIG expression: {ast.dump(node)}")


def load_default_config_from_runner(runner_path=RUNNER_PATH):
    """Read DEFAULT_CONFIG from run_deform_hits_config.py without importing it."""
    source = Path(runner_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(runner_path))
    names = {"USER_PATH": os.path.expanduser("~")}

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "USER_PATH":
                    names["USER_PATH"] = safe_eval_default_config_node(node.value, names)
                if isinstance(target, ast.Name) and target.id == "DEFAULT_CONFIG":
                    return safe_eval_default_config_node(node.value, names)

    raise ValueError(f"DEFAULT_CONFIG was not found in {runner_path}")


def to_bool_text(value):
    """Return a GUI-friendly true/false string."""
    return "true" if bool(value) else "false"


def from_bool_text(value):
    """Convert a GUI true/false string to bool."""
    return str(value).strip().lower() == "true"


def parse_number_or_text(value):
    """Convert GUI text to int/float when appropriate, preserving blank/None/all."""
    text = str(value).strip()
    if text == "":
        return ""
    if text.lower() == "none":
        return None
    if text.lower() == "all":
        return "all"
    try:
        if any(char in text.lower() for char in [".", "e"]):
            return float(text)
        return int(text)
    except ValueError:
        return text


class ConfigField:
    """Small wrapper around one editable config field."""

    def __init__(self, parent, label, key, value, row, kind="entry", options=None, browse=None):
        self.key = key
        self.kind = kind
        self.var = tk.StringVar(value=self.format_value(value, kind))

        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(8, 4), pady=4)

        if kind in ["combo", "combo_bool"]:
            self.widget = ttk.Combobox(parent, textvariable=self.var, values=options or [], width=48)
        else:
            self.widget = ttk.Entry(parent, textvariable=self.var, width=51)
        self.widget.grid(row=row, column=1, sticky="ew", padx=4, pady=4)

        if browse:
            ttk.Button(parent, text="Browse", command=lambda: self.browse_path(browse)).grid(
                row=row, column=2, sticky="ew", padx=(4, 8), pady=4
            )

    @staticmethod
    def format_value(value, kind):
        if kind == "combo_bool":
            return to_bool_text(value)
        if value is None:
            return "None"
        return str(value)

    def browse_path(self, browse):
        if browse == "directory":
            selected = filedialog.askdirectory(initialdir=self.var.get() or str(APP_DIR))
        elif browse == "file":
            selected = filedialog.askopenfilename(initialdir=str(APP_DIR))
        elif browse == "save":
            selected = filedialog.asksaveasfilename(initialdir=str(CONFIG_DIR), defaultextension=".json")
        else:
            selected = ""
        if selected:
            self.var.set(selected)

    def get_value(self):
        if self.kind == "combo_bool":
            return from_bool_text(self.var.get())
        return parse_number_or_text(self.var.get())

    def set_value(self, value):
        self.var.set(self.format_value(value, self.kind))


class DeformConfigGui(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title("DEFORM Multihit Config GUI")
        self.geometry("1120x760")
        self.minsize(980, 680)

        self.default_config = load_default_config_from_runner()
        self.fields = {}
        self.column_fields = {}
        self.key_file_fields = {}

        self.python_executable = tk.StringVar(value=sys.executable)
        self.config_output_path = tk.StringVar(
            value=str(CONFIG_DIR / "run_deform_hits_gui_config.json")
        )
        self.status_var = tk.StringVar(value="Ready.")

        self.build_ui()
        self.refresh_file_dropdowns()

    def build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=10)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(
            header,
            text="DEFORM Multihit Config GUI",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Build JSON configs for run_deform_hits_config.py without editing Python by hand.",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        body = ttk.Notebook(self)
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        self.tabs = {}
        for name in ["Paths", "Run Setup", "Material/JMAK", "Outputs", "Columns", "Run"]:
            frame = ttk.Frame(body, padding=8)
            frame.columnconfigure(1, weight=1)
            body.add(frame, text=name)
            self.tabs[name] = frame

        self.build_paths_tab()
        self.build_run_setup_tab()
        self.build_material_tab()
        self.build_outputs_tab()
        self.build_columns_tab()
        self.build_launch_tab()

        footer = ttk.Frame(self, padding=(10, 0, 10, 8))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

    def add_field(self, tab_name, label, key, row, kind="entry", options=None, browse=None):
        field = ConfigField(
            self.tabs[tab_name],
            label=label,
            key=key,
            value=self.default_config.get(key, ""),
            row=row,
            kind=kind,
            options=options,
            browse=browse,
        )
        self.fields[key] = field
        return field

    def build_paths_tab(self):
        self.add_field("Paths", "Key folder", "key_path", 0, browse="directory")
        self.add_field("Paths", "Action folder", "action_path", 1, browse="directory")
        self.add_field("Paths", "Action CSV", "action_file", 2, kind="combo", options=[])
        self.add_field("Paths", "Output run folder", "data_path", 3, browse="directory")
        self.add_field("Paths", "Use custom key", "custom_key_bool", 4, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Paths", "Custom key file", "custom_key_name", 5, kind="combo", options=[])

        ttk.Button(self.tabs["Paths"], text="Refresh file dropdowns", command=self.refresh_file_dropdowns).grid(
            row=6, column=1, sticky="w", padx=4, pady=(10, 4)
        )

    def build_run_setup_tab(self):
        self.add_field("Run Setup", "Action version", "action_version", 0)
        self.add_field("Run Setup", "Apply action filename rules", "apply_action_file_rules", 1, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Run Setup", "Run number", "run_number", 2)
        self.add_field("Run Setup", "Number of hits", "num_hits", 3, kind="combo", options=["1", "2", "3", "4", "5", "all"])
        self.add_field("Run Setup", "Die motion mode", "die_motion_mode", 4, kind="combo", options=DIE_MOTION_OPTIONS)
        self.add_field("Run Setup", "Die motion axis", "die_motion_axis", 5, kind="combo", options=DIE_AXIS_OPTIONS)
        self.add_field("Run Setup", "Position dies before first hit", "position_dies_before_first_hit", 6, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Run Setup", "Position bottom die before first hit", "position_bottom_die_before_first_hit", 7, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Run Setup", "Height / die backout", "height", 8)
        self.add_field("Run Setup", "Time step", "time_step", 9)
        self.add_field("Run Setup", "Save step size", "save_step_size", 10)
        self.add_field("Run Setup", "Top die interference", "top_die_interference", 11)
        self.add_field("Run Setup", "Bottom die interference", "bottom_die_interference", 12)
        self.add_field("Run Setup", "Bottom die retract speed multiplier", "bottom_die_retract_speed_multiplier", 13)
        self.add_field("Run Setup", "Bottom die retract lead steps", "bottom_die_retract_lead_steps", 14)
        self.add_field("Run Setup", "Mesh type", "mesh_type", 15, kind="combo", options=MESH_OPTIONS)
        self.add_field("Run Setup", "Stock diameter", "stock_diameter", 16)

        ttk.Button(self.tabs["Run Setup"], text="Apply bdm/single-die rule now", command=self.apply_action_rule_preview).grid(
            row=17, column=1, sticky="w", padx=4, pady=(10, 4)
        )

    def build_material_tab(self):
        self.add_field("Material/JMAK", "Change material", "change_material", 0, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Material/JMAK", "Material source", "material_source", 1, kind="combo", options=MATERIAL_SOURCE_OPTIONS)
        self.add_field("Material/JMAK", "DEFORM material name", "deform_material_name", 2, kind="combo", options=MATERIAL_OPTIONS)
        self.add_field("Material/JMAK", "Short material label", "material", 3, kind="combo", options=SHORT_MATERIAL_OPTIONS)
        self.add_field("Material/JMAK", "Material object name", "material_object_name", 4)
        self.add_field("Material/JMAK", "System material library", "system_material_library_dir", 5, browse="directory")
        self.add_field("Material/JMAK", "User material library", "user_material_library_dir", 6, browse="directory")
        self.add_field("Material/JMAK", "Material number", "material_number", 7)
        self.add_field("Material/JMAK", "Use JMAK", "use_jmak", 8, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Material/JMAK", "JMAK simulation modes", "jmak_simulation_modes", 9, kind="combo", options=["D H G", "D G", "D H T G"])
        self.add_field("Material/JMAK", "Mean grain size, um", "mean_grain_size_um", 10)
        self.add_field("Material/JMAK", "Enable lag time", "enable_lag_time", 11, kind="combo_bool", options=BOOLEAN_OPTIONS)

    def build_outputs_tab(self):
        self.add_field("Outputs", "Export post-hit keys", "export_post_hit_keys", 0, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Outputs", "Export coordinate logs", "export_coordinate_logs", 1, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Outputs", "Export load-stroke", "export_load_stroke", 2, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Outputs", "Load-stroke object", "load_stroke_object", 3, kind="combo", options=["Top Die", "Bottom Die", "Workpiece"])
        self.add_field("Outputs", "Post-process after run", "post_process_after_run", 4, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Outputs", "Post-process output subfolder", "post_process_output_subdir", 5)
        self.add_field("Outputs", "Damage object", "post_process_damage_object", 6, kind="combo", options=["Workpiece", "Top Die", "Bottom Die"])
        self.add_field("Outputs", "Damage step number", "post_process_damage_step_no", 7)

    def build_columns_tab(self):
        row = 0
        columns = self.default_config.get("columns", {})
        for key, value in columns.items():
            field = ConfigField(self.tabs["Columns"], f"CSV column: {key}", key, value, row)
            self.column_fields[key] = field
            row += 1

        ttk.Separator(self.tabs["Columns"], orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10
        )
        row += 1

        key_files = self.default_config.get("key_files", {})
        for key, value in key_files.items():
            field = ConfigField(self.tabs["Columns"], f"Key template for die {key}", key, value, row)
            self.key_file_fields[key] = field
            row += 1

    def build_launch_tab(self):
        tab = self.tabs["Run"]
        ttk.Label(tab, text="Python executable").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.python_executable, width=80).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(tab, text="Browse", command=self.browse_python).grid(row=0, column=2, padx=(4, 8), pady=4)

        ttk.Label(tab, text="Config output path").grid(row=1, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.config_output_path, width=80).grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(tab, text="Browse", command=self.browse_config_output).grid(row=1, column=2, padx=(4, 8), pady=4)

        button_frame = ttk.Frame(tab)
        button_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=(8, 4))
        ttk.Button(button_frame, text="Load JSON Config", command=self.load_json_config).pack(side="left", padx=(0, 6))
        ttk.Button(button_frame, text="Save JSON Config", command=self.save_json_config).pack(side="left", padx=6)
        ttk.Button(button_frame, text="Save and Run DEFORM", command=self.save_and_run).pack(side="left", padx=6)
        ttk.Button(button_frame, text="Preview Config", command=self.preview_config).pack(side="left", padx=6)

        self.log_text = scrolledtext.ScrolledText(tab, height=23, wrap="word")
        self.log_text.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
        tab.rowconfigure(3, weight=1)

    def browse_python(self):
        selected = filedialog.askopenfilename(
            initialdir=str(Path(self.python_executable.get()).parent),
            filetypes=[("Python executable", "python*.exe"), ("All files", "*.*")],
        )
        if selected:
            self.python_executable.set(selected)

    def browse_config_output(self):
        selected = filedialog.asksaveasfilename(
            initialdir=str(CONFIG_DIR),
            initialfile="run_deform_hits_gui_config.json",
            defaultextension=".json",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
        )
        if selected:
            self.config_output_path.set(selected)

    def refresh_file_dropdowns(self):
        action_path = Path(str(self.fields.get("action_path", ConfigProxy("")).get_value()))
        key_path = Path(str(self.fields.get("key_path", ConfigProxy("")).get_value()))

        if "action_file" in self.fields:
            action_files = sorted(path.name for path in action_path.glob("*.csv")) if action_path.exists() else []
            self.fields["action_file"].widget.configure(values=action_files)

        if "custom_key_name" in self.fields:
            key_files = sorted(path.name for path in key_path.glob("*.key")) if key_path.exists() else []
            self.fields["custom_key_name"].widget.configure(values=key_files)

        self.status_var.set("File dropdowns refreshed.")

    def apply_action_rule_preview(self):
        action_file = Path(str(self.fields["action_file"].get_value())).name.lower()
        if "bdm" in action_file:
            self.fields["die_motion_mode"].set_value("symmetric")
            self.fields["position_bottom_die_before_first_hit"].set_value(True)
            self.status_var.set("Applied bdm rule: symmetric die movement and bottom-die positioning.")
        else:
            self.fields["die_motion_mode"].set_value("single_top_die")
            self.fields["position_bottom_die_before_first_hit"].set_value(False)
            self.status_var.set("Applied single-die rule: single_top_die and no bottom-die hit-0 positioning.")

    def build_config(self):
        config = dict(self.default_config)
        for key, field in self.fields.items():
            config[key] = field.get_value()
        config["columns"] = {key: field.get_value() for key, field in self.column_fields.items()}
        config["key_files"] = {key: field.get_value() for key, field in self.key_file_fields.items()}
        return config

    def set_config_values(self, config):
        for key, field in self.fields.items():
            if key in config:
                field.set_value(config[key])
        for key, field in self.column_fields.items():
            if key in config.get("columns", {}):
                field.set_value(config["columns"][key])
        for key, field in self.key_file_fields.items():
            if key in config.get("key_files", {}):
                field.set_value(config["key_files"][key])
        self.refresh_file_dropdowns()

    def save_json_config(self):
        config = self.build_config()
        output_path = Path(self.config_output_path.get())
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self.status_var.set(f"Saved config: {output_path}")
        self.log(f"Saved config: {output_path}")
        return output_path

    def load_json_config(self):
        selected = filedialog.askopenfilename(
            initialdir=str(CONFIG_DIR),
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
        )
        if not selected:
            return
        config = json.loads(Path(selected).read_text(encoding="utf-8"))
        self.config_output_path.set(selected)
        self.set_config_values(config)
        self.status_var.set(f"Loaded config: {selected}")
        self.log(f"Loaded config: {selected}")

    def preview_config(self):
        config = self.build_config()
        self.log(json.dumps(config, indent=2))

    def save_and_run(self):
        config_path = self.save_json_config()
        python_path = Path(self.python_executable.get())
        if not python_path.exists():
            messagebox.showerror("Python executable not found", f"Could not find:\n{python_path}")
            return
        if not RUNNER_PATH.exists():
            messagebox.showerror("Runner not found", f"Could not find:\n{RUNNER_PATH}")
            return

        command = [str(python_path), str(RUNNER_PATH), "--config", str(config_path)]
        self.log("Starting DEFORM runner:")
        self.log(" ".join(f'"{part}"' if " " in part else part for part in command))
        self.status_var.set("DEFORM runner is running...")

        thread = threading.Thread(target=self.run_command, args=(command,), daemon=True)
        thread.start()

    def run_command(self, command):
        try:
            process = subprocess.Popen(
                command,
                cwd=str(APP_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in process.stdout:
                self.log(line.rstrip())
            return_code = process.wait()
            self.log(f"Runner exited with code {return_code}")
            self.status_var.set(f"Runner exited with code {return_code}")
        except Exception as exc:
            self.log(f"ERROR: {exc}")
            self.status_var.set("Runner failed to start.")

    def log(self, message):
        self.log_text.insert("end", str(message) + "\n")
        self.log_text.see("end")


class ConfigProxy:
    """Fallback object used before GUI fields are fully initialized."""

    def __init__(self, value):
        self.value = value

    def get_value(self):
        return self.value


def main():
    app = DeformConfigGui()
    app.mainloop()


if __name__ == "__main__":
    main()


