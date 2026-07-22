"""
Tkinter GUI for configuring and launching run_deform_hits_config.py.

The GUI intentionally does not import run_deform_hits_config.py. That runner
imports DEFORM API modules, which may only be available in the lab DEFORM Python
environment. Instead, this file safely reads DEFAULT_CONFIG from the runner
source and writes an external JSON config that the runner already supports.
"""

import ast
import csv
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
DOE_PATH = APP_DIR / "run_initial_doe.py"
POST_PROCESS_PATH = APP_DIR / "run_deform_post_processing.py"
VISUALIZE_DOE_PATH = APP_DIR / "visualize_doe_results.py"
ACTION_CREATOR_PATH = APP_DIR / "action_file_creator.py"
CONFIG_DIR = APP_DIR / "configs"
LOCAL_ACTION_FILES_DIR = APP_DIR / "action_files"
MATERIAL_LIST_PATH = APP_DIR / "material_list_deform.csv"


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

FONT_FAMILY = "Segoe UI"
COLOR_BG = "#f7f8fb"
COLOR_PANEL = "#ffffff"
COLOR_HEADER = "#ffffff"
COLOR_HEADER_MUTED = "#8a93a5"
COLOR_TEXT = "#2f3440"
COLOR_MUTED = "#657085"
COLOR_BORDER = "#d8dde7"
COLOR_ACCENT = "#5ba4cf"
COLOR_ACCENT_DARK = "#3f8eb8"
COLOR_SUCCESS = "#6fa3c8"
COLOR_LOG_BG = "#f5f7fa"
COLOR_LOG_FG = "#2f3440"

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


def short_material_label(material_name):
    """Create a compact run-label-friendly material name."""
    label = str(material_name).strip()
    for suffix in ["_e", "_s"]:
        marker_index = label.rfind(suffix)
        if marker_index > 0 and label[marker_index + 2 :].isdigit():
            label = label[:marker_index]
            break
    for separator in ["[", ",", "("]:
        if separator in label:
            label = label.split(separator, 1)[0]
    return label.strip().replace(" ", "_") or str(material_name).strip()


def load_material_catalog(csv_path=MATERIAL_LIST_PATH):
    """Load DEFORM material names grouped by material type.

    The CSV stores material names without the trailing .KEY extension, which is
    the value expected by the existing material-management workflow.
    """
    catalog = {}
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return catalog

    with csv_path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            material_type = str(row.get("Material Type", "")).strip()
            material = str(row.get("Material", "")).strip()
            if not material_type or not material:
                continue
            catalog.setdefault(material_type, []).append(material)

    return {key: sorted(set(values)) for key, values in sorted(catalog.items())}


def set_simulation_modes_from_jmak(config):
    """Set DEFORM modes from the JMAK toggle: True -> D H G, False -> D H."""
    use_jmak = config.get("use_jmak", False)
    if isinstance(use_jmak, str):
        use_jmak = use_jmak.strip().lower() in {"true", "yes", "1", "on"}
    config["jmak_simulation_modes"] = "D H G" if use_jmak else "D H"
    return config


class ConfigField:
    """Small wrapper around one editable config field."""

    def __init__(self, parent, label, key, value, row, kind="entry", options=None, browse=None):
        self.key = key
        self.kind = kind
        self.var = tk.StringVar(value=self.format_value(value, kind))

        ttk.Label(parent, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", padx=(12, 12), pady=7)

        if kind in ["combo", "combo_bool"]:
            self.widget = ttk.Combobox(parent, textvariable=self.var, values=options or [], width=52)
        else:
            self.widget = ttk.Entry(parent, textvariable=self.var, width=55)
        self.widget.grid(row=row, column=1, sticky="ew", padx=6, pady=6)

        if browse:
            ttk.Button(parent, text="Browse", command=lambda: self.browse_path(browse)).grid(
                row=row, column=2, sticky="ew", padx=(6, 10), pady=6
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
        self.title("DEFORM Automation Studio")
        self.geometry("1280x860")
        self.minsize(1120, 760)
        self.configure(bg=COLOR_BG)
        self.apply_theme()

        self.default_config = load_default_config_from_runner()
        if LOCAL_ACTION_FILES_DIR.exists():
            self.default_config["action_path"] = str(LOCAL_ACTION_FILES_DIR)
        self.material_catalog = load_material_catalog()
        self.material_type_var = tk.StringVar(value="")
        self.fields = {}
        self.column_fields = {}
        self.key_file_fields = {}
        self.doe_fields = {}

        self.python_executable = tk.StringVar(value=sys.executable)
        self.config_output_path = tk.StringVar(
            value=str(CONFIG_DIR / "run_deform_hits_gui_config.json")
        )
        self.status_var = tk.StringVar(value="Ready.")

        self.doe_script_path = tk.StringVar(value=str(DOE_PATH))
        self.doe_project_root = tk.StringVar(value=str(APP_DIR))
        self.doe_base_config_path = tk.StringVar(value=str(CONFIG_DIR / "run_deform_hits_gui_config.json"))
        self.doe_optimization_root = tk.StringVar(value=str(APP_DIR / "optimization"))
        self.doe_study_name = tk.StringVar(value="single_die_5hit_initial_doe")

        self.post_config_path = tk.StringVar(value=str(CONFIG_DIR / "run_deform_hits_gui_config.json"))
        self.post_run_dir = tk.StringVar(value="")
        self.report_study_root = tk.StringVar(value=str(APP_DIR / "optimization" / "single_die_5hit_initial_doe"))
        self.report_dataset_path = tk.StringVar(value="")
        self.report_manifest_path = tk.StringVar(value="")
        self.report_candidates_path = tk.StringVar(value="")
        self.report_surrogate_path = tk.StringVar(value="")
        self.report_output_dir = tk.StringVar(value="")
        self.plot_folder_path = tk.StringVar(value="")
        self.selected_plot_file = tk.StringVar(value="")
        self.current_plot_raw = None
        self.current_plot_image = None

        self.af_base_path = tk.StringVar(value=str(Path.home() / "Desktop" / "OSU Research" / "AF Data"))
        self.af_hit_folders = tk.StringVar(value="Box")
        self.af_output_dir = tk.StringVar(value=str(LOCAL_ACTION_FILES_DIR))
        self.af_output_prefix = tk.StringVar(value="af")
        self.af_position_threshold_mm = tk.StringVar(value="30.0")
        self.af_force_sigma_multiplier = tk.StringVar(value="1.5")

        self.build_ui()
        self.refresh_file_dropdowns()

    def apply_theme(self):
        """Apply a modern ttk theme while keeping the app dependency-free."""
        self.style = ttk.Style(self)
        for theme_name in ("alt", "default", "vista", "xpnative"):
            try:
                self.style.theme_use(theme_name)
                break
            except tk.TclError:
                continue

        self.option_add("*Font", (FONT_FAMILY, 11))
        self.option_add("*TCombobox*Listbox.font", (FONT_FAMILY, 11))
        self.option_add("*TCombobox*Listbox.background", "#ffffff")
        self.option_add("*TCombobox*Listbox.foreground", COLOR_TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", "#dff0fa")
        self.option_add("*TCombobox*Listbox.selectForeground", COLOR_TEXT)

        self.style.configure(".", font=(FONT_FAMILY, 10), background=COLOR_BG, foreground=COLOR_TEXT)
        self.style.configure("App.TFrame", background=COLOR_BG)
        self.style.configure("Hero.TFrame", background=COLOR_HEADER)
        self.style.configure("Card.TFrame", background=COLOR_PANEL)
        self.style.configure("StepNav.TFrame", background="#f3f5f9")
        self.style.configure("Footer.TFrame", background=COLOR_BG)
        self.style.configure("ButtonBar.TFrame", background=COLOR_PANEL)

        self.style.configure("TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT, font=(FONT_FAMILY, 11), padding=(0, 1))
        self.style.configure("Muted.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT, font=(FONT_FAMILY, 11, "bold"))
        self.style.configure("HeroTitle.TLabel", background=COLOR_HEADER, foreground=COLOR_TEXT, font=(FONT_FAMILY, 18, "bold"))
        self.style.configure("HeroSubtitle.TLabel", background=COLOR_HEADER, foreground=COLOR_HEADER_MUTED, font=(FONT_FAMILY, 10))
        self.style.configure("Section.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT, font=(FONT_FAMILY, 13, "bold"))
        self.style.configure("Status.TLabel", background=COLOR_BG, foreground=COLOR_MUTED, font=(FONT_FAMILY, 10))

        self.style.configure("TEntry", fieldbackground="#ffffff", foreground=COLOR_TEXT, insertcolor=COLOR_TEXT, bordercolor=COLOR_BORDER, lightcolor=COLOR_BORDER, darkcolor=COLOR_BORDER, padding=8)
        self.style.map("TEntry", bordercolor=[("focus", COLOR_ACCENT)], fieldbackground=[("disabled", "#f0f2f5")], foreground=[("disabled", "#7d8797")])
        self.style.configure("TCombobox", fieldbackground="#ffffff", background="#ffffff", foreground=COLOR_TEXT, bordercolor=COLOR_BORDER, lightcolor=COLOR_BORDER, darkcolor=COLOR_BORDER, arrowcolor=COLOR_MUTED, padding=8, arrowsize=15)
        self.style.map("TCombobox", bordercolor=[("focus", COLOR_ACCENT)], fieldbackground=[("readonly", "#ffffff")], foreground=[("readonly", COLOR_TEXT)])

        self.style.configure("TButton", background="#f5f7fa", foreground=COLOR_TEXT, bordercolor=COLOR_BORDER, focusthickness=1, focuscolor=COLOR_ACCENT, padding=(13, 8), relief="flat")
        self.style.map("TButton", background=[("active", "#e9eef5"), ("pressed", "#dfe6ef")], foreground=[("active", COLOR_TEXT), ("pressed", COLOR_TEXT), ("disabled", "#9aa3b2")])
        self.style.configure("Accent.TButton", background="#6fa3c8", foreground="#ffffff", bordercolor="#6fa3c8", padding=(15, 9), relief="flat")
        self.style.map("Accent.TButton", background=[("active", "#5d94bb"), ("pressed", "#4c84ab")], foreground=[("active", "#ffffff"), ("pressed", "#ffffff"), ("disabled", "#9aa3b2")])
        self.style.configure("Success.TButton", background="#5d94bb", foreground="#ffffff", bordercolor="#5d94bb", padding=(15, 9), relief="flat")
        self.style.map("Success.TButton", background=[("active", "#4c84ab"), ("pressed", "#3f7398")], foreground=[("active", "#ffffff"), ("pressed", "#ffffff"), ("disabled", "#9aa3b2")])

        self.style.configure("Workflow.TNotebook", background=COLOR_PANEL, borderwidth=0, tabmargins=(0, 0, 0, 0))
        self.style.layout("Workflow.TNotebook.Tab", [])
        self.style.configure("TSeparator", background=COLOR_BORDER)
        self.style.configure("Vertical.TScrollbar", background="#eef2f7", troughcolor="#f7f8fb", bordercolor=COLOR_BORDER, arrowcolor=COLOR_MUTED)

    def create_scrollable_tab(self, notebook, name):
        """Create one notebook tab with its own vertical scrollbar."""
        outer = ttk.Frame(notebook, style="Card.TFrame")
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        canvas = tk.Canvas(
            outer,
            bg=COLOR_PANEL,
            highlightthickness=0,
            bd=0,
            yscrollincrement=24,
        )
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview, style="Vertical.TScrollbar")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        inner = ttk.Frame(canvas, padding=18, style="Card.TFrame")
        inner.columnconfigure(1, weight=1)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def update_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def update_inner_width(event):
            canvas.itemconfigure(window_id, width=event.width)

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        inner.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_inner_width)
        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", on_mousewheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))

        notebook.add(outer, text=name)
        return inner

    def create_fixed_tab(self, notebook, name):
        """Create a notebook tab without a page-level scrollbar."""
        outer = ttk.Frame(notebook, padding=18, style="Card.TFrame")
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(3, weight=1)
        notebook.add(outer, text=name)
        return outer

    def build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(18, 14), style="Hero.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Jobs", style="HeroTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Shared / DEFORM Automation / Multihit Job", style="HeroSubtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Label(header, text="Job ID: deform-gui", style="HeroSubtitle.TLabel").grid(row=0, column=2, sticky="e", padx=(10, 0))

        workspace = ttk.Frame(self, style="App.TFrame")
        workspace.grid(row=1, column=0, sticky="nsew")
        workspace.columnconfigure(1, weight=1)
        workspace.rowconfigure(0, weight=1)

        step_nav = ttk.Frame(workspace, padding=(0, 0), style="StepNav.TFrame")
        step_nav.grid(row=0, column=0, sticky="nsw")
        step_nav.grid_propagate(False)
        step_nav.configure(width=230)

        body = ttk.Notebook(workspace, style="Workflow.TNotebook")
        body.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=(0, 12))

        self.tabs = {}
        self.nav_buttons = {}
        tab_names = ["Paths", "Run Setup", "Material/JMAK", "Outputs", "Columns", "Action Files", "DOE", "Post/Reports", "Run"]
        nav_labels = {
            "Paths": "Setup",
            "Run Setup": "Run setup",
            "Material/JMAK": "Materials",
            "Outputs": "Outputs",
            "Columns": "Columns",
            "Action Files": "Action files",
            "DOE": "DOE",
            "Post/Reports": "Results",
            "Run": "Launch",
        }
        for index, name in enumerate(tab_names):
            if name in {"Paths", "Run"}:
                self.tabs[name] = self.create_fixed_tab(body, name)
            else:
                self.tabs[name] = self.create_scrollable_tab(body, name)
            button = tk.Button(
                step_nav,
                text=nav_labels.get(name, name),
                anchor="w",
                bd=0,
                relief="flat",
                padx=20,
                pady=15,
                font=(FONT_FAMILY, 14),
                command=lambda tab_name=name: self.select_workflow_tab(tab_name),
            )
            button.grid(row=index, column=0, sticky="ew")
            self.nav_buttons[name] = button
        step_nav.columnconfigure(0, weight=1)

        self.build_paths_tab()
        self.build_run_setup_tab()
        self.build_material_tab()
        self.build_outputs_tab()
        self.build_columns_tab()
        self.build_action_files_tab()
        self.build_doe_tab()
        self.build_post_reports_tab()
        self.build_launch_tab()
        self.workflow_body = body
        self.select_workflow_tab("Paths")

        footer = ttk.Frame(self, padding=(16, 0, 16, 10), style="Footer.TFrame")
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")

    def select_workflow_tab(self, tab_name):
        """Select a workflow page from the left navigation rail."""
        if not hasattr(self, "workflow_body"):
            return
        tab_names = list(self.tabs.keys())
        if tab_name not in self.tabs:
            return
        self.workflow_body.select(tab_names.index(tab_name))
        for name, button in self.nav_buttons.items():
            if name == tab_name:
                button.configure(bg="#ffffff", fg="#2f3440")
            else:
                button.configure(bg="#f3f5f9", fg="#4a5568")

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
        self.add_field("Paths", "Custom key file", "custom_key_name", 5, kind="combo", options=[], browse="file")

        ttk.Button(self.tabs["Paths"], text="Refresh file dropdowns", command=self.refresh_file_dropdowns, style="Accent.TButton").grid(
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

        ttk.Button(self.tabs["Run Setup"], text="Apply bdm/single-die rule now", command=self.apply_action_rule_preview, style="Accent.TButton").grid(
            row=17, column=1, sticky="w", padx=4, pady=(10, 4)
        )

    def build_material_tab(self):
        material_types = list(self.material_catalog.keys())
        current_material = str(self.default_config.get("deform_material_name", ""))
        current_type = self.find_material_type(current_material)
        if not current_type and material_types:
            current_type = material_types[0]
        self.material_type_var.set(current_type)

        self.add_field("Material/JMAK", "Change material", "change_material", 0, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Material/JMAK", "Material source", "material_source", 1, kind="combo", options=MATERIAL_SOURCE_OPTIONS)

        ttk.Label(self.tabs["Material/JMAK"], text="Material type", style="Muted.TLabel").grid(row=2, column=0, sticky="w", padx=(12, 12), pady=7)
        self.material_type_combo = ttk.Combobox(
            self.tabs["Material/JMAK"],
            textvariable=self.material_type_var,
            values=material_types,
            width=52,
        )
        self.material_type_combo.grid(row=2, column=1, sticky="ew", padx=6, pady=6)
        self.material_type_combo.bind("<<ComboboxSelected>>", self.on_material_type_changed)

        material_options = self.material_catalog.get(current_type, MATERIAL_OPTIONS)
        self.add_field("Material/JMAK", "DEFORM material name", "deform_material_name", 3, kind="combo", options=material_options)
        self.fields["deform_material_name"].widget.bind("<<ComboboxSelected>>", self.refresh_short_material_labels)
        resolved_material = self.resolve_material_name(current_material, current_type)
        if resolved_material:
            self.fields["deform_material_name"].set_value(resolved_material)

        self.add_field("Material/JMAK", "Short material label", "material", 4, kind="combo", options=SHORT_MATERIAL_OPTIONS)
        self.refresh_short_material_labels()
        self.add_field("Material/JMAK", "Material object name", "material_object_name", 5)
        self.add_field("Material/JMAK", "System material library", "system_material_library_dir", 6, browse="directory")
        self.add_field("Material/JMAK", "User material library", "user_material_library_dir", 7, browse="directory")
        self.add_field("Material/JMAK", "Material number", "material_number", 8)
        self.add_field("Material/JMAK", "Use JMAK", "use_jmak", 9, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Material/JMAK", "JMAK simulation modes", "jmak_simulation_modes", 10, kind="combo", options=["D H G", "D H"])
        self.fields["use_jmak"].widget.bind("<<ComboboxSelected>>", self.update_jmak_simulation_modes)
        self.fields["jmak_simulation_modes"].widget.configure(state="readonly")
        self.add_field("Material/JMAK", "Mean grain size, um", "mean_grain_size_um", 11)
        self.update_jmak_simulation_modes()
        self.add_field("Material/JMAK", "Enable lag time", "enable_lag_time", 12, kind="combo_bool", options=BOOLEAN_OPTIONS)

    def update_jmak_simulation_modes(self, _event=None):
        """Populate simulation modes and grain-size input from the Use JMAK choice."""
        if "use_jmak" not in self.fields or "jmak_simulation_modes" not in self.fields:
            return
        use_jmak = self.fields["use_jmak"].get_value()
        config = {"use_jmak": use_jmak}
        set_simulation_modes_from_jmak(config)
        self.fields["jmak_simulation_modes"].set_value(config["jmak_simulation_modes"])

        if "mean_grain_size_um" in self.fields:
            grain_field = self.fields["mean_grain_size_um"]
            if use_jmak:
                if str(grain_field.var.get()).strip() in {"", "None"}:
                    grain_field.set_value(self.default_config.get("mean_grain_size_um", ""))
            else:
                grain_field.var.set("")

        if _event is not None:
            self.status_var.set(f"JMAK simulation modes set to {config['jmak_simulation_modes']}.")

    def find_material_type(self, material_name):
        """Return the material type containing material_name, if known."""
        material_name = str(material_name).strip()
        for material_type, materials in self.material_catalog.items():
            if material_name in materials:
                return material_type
            if material_name:
                for material in materials:
                    if material.startswith(material_name):
                        return material_type
        return ""

    def resolve_material_name(self, material_name, material_type):
        """Return a valid material name from the selected material type."""
        material_name = str(material_name).strip()
        materials = self.material_catalog.get(material_type, [])
        if material_name in materials:
            return material_name
        if material_name:
            for material in materials:
                if material.startswith(material_name):
                    return material
        return materials[0] if materials else material_name

    def on_material_type_changed(self, _event=None):
        """Populate material choices from the selected material type."""
        material_type = self.material_type_var.get()
        materials = self.material_catalog.get(material_type, [])
        if "deform_material_name" not in self.fields:
            return
        material_field = self.fields["deform_material_name"]
        material_field.widget.configure(values=materials)
        if materials and material_field.var.get() not in materials:
            material_field.set_value(materials[0])
        self.refresh_short_material_labels()
        self.status_var.set(f"Loaded {len(materials)} material(s) for {material_type}.")

    def refresh_short_material_labels(self, _event=None):
        """Populate the short material label dropdown from material choices."""
        if "material" not in self.fields or "deform_material_name" not in self.fields:
            return
        materials = list(self.fields["deform_material_name"].widget.cget("values"))
        labels = sorted({short_material_label(material) for material in materials if str(material).strip()})
        current_material = self.fields["deform_material_name"].var.get()
        suggested_label = short_material_label(current_material)
        if suggested_label and suggested_label not in labels:
            labels.insert(0, suggested_label)
        self.fields["material"].widget.configure(values=labels)
        if suggested_label:
            self.fields["material"].set_value(suggested_label)

    def build_outputs_tab(self):
        self.add_field("Outputs", "Export post-hit keys", "export_post_hit_keys", 0, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Outputs", "Export coordinate logs", "export_coordinate_logs", 1, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Outputs", "Export load-stroke", "export_load_stroke", 2, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Outputs", "Load-stroke object", "load_stroke_object", 3, kind="combo", options=["Top Die", "Bottom Die", "Workpiece"])
        self.add_field("Outputs", "Post-process after run", "post_process_after_run", 4, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_field("Outputs", "Post-process output subfolder", "post_process_output_subdir", 5)
        self.fields["post_process_output_subdir"].widget.configure(state="readonly")
        self.add_field("Outputs", "Damage object", "post_process_damage_object", 6, kind="combo", options=["Workpiece", "Top Die", "Bottom Die"])
        self.add_field("Outputs", "Damage step number", "post_process_damage_step_no", 7)

    def build_columns_tab(self):
        ttk.Label(
            self.tabs["Columns"],
            text="These values are fixed defaults used by the automation scripts and cannot be changed from the GUI.",
            style="Section.TLabel",
            wraplength=820,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 14))
        row = 1
        columns = self.default_config.get("columns", {})
        for key, value in columns.items():
            field = ConfigField(self.tabs["Columns"], f"CSV column: {key}", key, value, row)
            field.widget.configure(state="readonly")
            self.column_fields[key] = field
            row += 1

        ttk.Separator(self.tabs["Columns"], orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10
        )
        row += 1

        key_files = self.default_config.get("key_files", {})
        for key, value in key_files.items():
            field = ConfigField(self.tabs["Columns"], f"Key template for die {key}", key, value, row)
            field.widget.configure(state="readonly")
            self.key_file_fields[key] = field
            row += 1

    def build_action_files_tab(self):
        tab = self.tabs["Action Files"]
        ttk.Label(
            tab,
            text="Create DEFORM action CSVs from AF machine load-stroke folders. Output files are saved into action_files and then appear in the run setup dropdown.",
            style="Section.TLabel",
            wraplength=900,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 14))

        rows = [
            ("AF data root folder", self.af_base_path, "directory"),
            ("Hit folders", self.af_hit_folders, None),
            ("Output action_files folder", self.af_output_dir, "directory"),
            ("Output filename prefix", self.af_output_prefix, None),
            ("Position threshold, mm", self.af_position_threshold_mm, None),
            ("Force sigma multiplier", self.af_force_sigma_multiplier, None),
        ]
        for index, (label, variable, browse_type) in enumerate(rows, start=1):
            ttk.Label(tab, text=label, style="Muted.TLabel").grid(row=index, column=0, sticky="w", padx=(12, 12), pady=7)
            ttk.Entry(tab, textvariable=variable, width=70).grid(row=index, column=1, sticky="ew", padx=6, pady=6)
            if browse_type == "directory":
                ttk.Button(tab, text="Browse", command=lambda var=variable: self.browse_directory_var(var)).grid(row=index, column=2, padx=(6, 10), pady=6)

        ttk.Label(
            tab,
            text="Hit folders can be one name or a comma-separated list, for example: Box, TensileBar_Run1",
            style="Muted.TLabel",
            wraplength=820,
        ).grid(row=7, column=1, columnspan=2, sticky="w", padx=6, pady=(0, 10))

        button_frame = ttk.Frame(tab, style="ButtonBar.TFrame")
        button_frame.grid(row=8, column=1, sticky="w", padx=6, pady=(8, 4))
        ttk.Button(button_frame, text="Create Action File(s)", command=self.create_action_files_from_gui, style="Accent.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(button_frame, text="Refresh Action Dropdown", command=self.refresh_file_dropdowns).pack(side="left", padx=6)

    def add_doe_field(self, label, key, value, row, kind="entry", options=None):
        field = ConfigField(
            self.tabs["DOE"],
            label=label,
            key=key,
            value=value,
            row=row,
            kind=kind,
            options=options,
        )
        self.doe_fields[key] = field
        return field

    def build_doe_tab(self):
        tab = self.tabs["DOE"]
        ttk.Label(tab, text="DOE script").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.doe_script_path, width=70).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(tab, text="Browse", command=lambda: self.browse_file_var(self.doe_script_path, [("Python", "*.py"), ("All files", "*.*")])).grid(row=0, column=2, padx=(6, 10), pady=6)

        ttk.Label(tab, text="Project root").grid(row=1, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.doe_project_root, width=70).grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(tab, text="Browse", command=lambda: self.browse_directory_var(self.doe_project_root)).grid(row=1, column=2, padx=(6, 10), pady=6)

        ttk.Label(tab, text="Base config JSON").grid(row=2, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.doe_base_config_path, width=70).grid(row=2, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(tab, text="Browse", command=lambda: self.browse_file_var(self.doe_base_config_path, [("JSON", "*.json"), ("All files", "*.*")])).grid(row=2, column=2, padx=(6, 10), pady=6)

        ttk.Label(tab, text="Optimization root").grid(row=3, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.doe_optimization_root, width=70).grid(row=3, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(tab, text="Browse", command=lambda: self.browse_directory_var(self.doe_optimization_root)).grid(row=3, column=2, padx=(6, 10), pady=6)

        ttk.Label(tab, text="Study name").grid(row=4, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.doe_study_name, width=70).grid(row=4, column=1, sticky="ew", padx=6, pady=6)

        self.add_doe_field("Prepare runs", "PREPARE_RUNS", False, 5, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_doe_field("Execute runs", "EXECUTE_RUNS", False, 6, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_doe_field("Process results", "PROCESS_RESULTS", False, 7, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_doe_field("Propose next candidates", "PROPOSE_NEXT_CANDIDATES", False, 8, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_doe_field("Run next candidates", "RUN_NEXT_CANDIDATES", False, 9, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_doe_field("Execute next candidates", "EXECUTE_NEXT_CANDIDATES", False, 10, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_doe_field("Process next candidates", "PROCESS_NEXT_CANDIDATES", False, 11, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_doe_field("Combine datasets", "COMBINE_DATASETS", False, 12, kind="combo_bool", options=BOOLEAN_OPTIONS)
        self.add_doe_field("Make report", "MAKE_REPORT", False, 13, kind="combo_bool", options=BOOLEAN_OPTIONS)

        self.add_doe_field("Number of hits", "NUM_HITS", 5, 14)
        self.add_doe_field("Initial candidates", "N_CANDIDATES", 100, 15)
        self.add_doe_field("Random seed", "RANDOM_SEED", 1, 16)
        self.add_doe_field("Apply mode", "APPLY_MODE", "all_rows", 17, kind="combo", options=["all_rows", "hit_row"])
        self.add_doe_field("Model type", "MODEL_TYPE", "random_forest", 18, kind="combo", options=["random_forest", "gaussian_process"])
        self.add_doe_field("Next candidates", "N_NEXT_CANDIDATES", 5, 19)
        self.add_doe_field("Random Bayesian candidates", "N_RANDOM_BAYESIAN_CANDIDATES", 2000, 20)
        self.add_doe_field("Next round number", "NEXT_ROUND_NUMBER", 2, 21)
        self.add_doe_field("Max round number", "MAX_ROUND_NUMBER", 2, 22)
        self.add_doe_field("Bounds JSON", "BOUNDS", '{"depth_in": [0.01, 0.15], "forging_temp_c": [900, 1200]}', 23)
        self.add_doe_field("Objective weights JSON", "OBJECTIVE_WEIGHTS", '{"damage_max": 10.0, "grain_std_um": 10.0, "top_die_center_distance": 10.0, "bottom_die_center_distance": 10.0}', 24)

        button_frame = ttk.Frame(tab, style="ButtonBar.TFrame")
        button_frame.grid(row=25, column=0, columnspan=3, sticky="ew", padx=8, pady=(10, 4))
        ttk.Button(button_frame, text="Save Current Run Config for DOE", command=self.save_json_config).pack(side="left", padx=(0, 6))
        ttk.Button(button_frame, text="Run DOE Workflow", command=self.run_doe_workflow, style="Accent.TButton").pack(side="left", padx=6)
        ttk.Button(button_frame, text="Preview DOE Launcher", command=self.preview_doe_launcher).pack(side="left", padx=6)

    def build_post_reports_tab(self):
        tab = self.tabs["Post/Reports"]
        ttk.Label(tab, text="Single-run post-processing", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 8))

        ttk.Label(tab, text="Run config JSON").grid(row=1, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.post_config_path, width=70).grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(tab, text="Browse", command=lambda: self.browse_file_var(self.post_config_path, [("JSON", "*.json"), ("All files", "*.*")])).grid(row=1, column=2, padx=(6, 10), pady=6)

        ttk.Label(tab, text="Completed run folder").grid(row=2, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.post_run_dir, width=70).grid(row=2, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(tab, text="Browse", command=lambda: self.browse_directory_var(self.post_run_dir)).grid(row=2, column=2, padx=(6, 10), pady=6)

        ttk.Button(tab, text="Run Single-Run Post-Processing", command=self.run_single_post_processing, style="Accent.TButton").grid(row=3, column=1, sticky="w", padx=4, pady=(8, 12))

        ttk.Separator(tab, orient="horizontal").grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(tab, text="DOE visualization/reporting", style="Section.TLabel").grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 8))

        report_rows = [
            ("Study root", self.report_study_root, "directory"),
            ("Dataset CSV", self.report_dataset_path, "file"),
            ("Manifest CSV", self.report_manifest_path, "file"),
            ("Next candidates CSV", self.report_candidates_path, "file"),
            ("Surrogate report JSON", self.report_surrogate_path, "file"),
            ("Report output folder", self.report_output_dir, "directory"),
        ]
        for index, (label, variable, browse_type) in enumerate(report_rows, start=6):
            ttk.Label(tab, text=label).grid(row=index, column=0, sticky="w", padx=(8, 4), pady=4)
            ttk.Entry(tab, textvariable=variable, width=70).grid(row=index, column=1, sticky="ew", padx=6, pady=6)
            if browse_type == "file":
                command = lambda var=variable: self.browse_file_var(var, [("Data files", "*.csv *.json"), ("All files", "*.*")])
            else:
                command = lambda var=variable: self.browse_directory_var(var)
            ttk.Button(tab, text="Browse", command=command).grid(row=index, column=2, padx=(6, 10), pady=6)

        ttk.Button(tab, text="Run DOE Visualization Report", command=self.run_doe_visualization, style="Accent.TButton").grid(row=12, column=1, sticky="w", padx=4, pady=(8, 4))

        ttk.Separator(tab, orient="horizontal").grid(row=13, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(tab, text="Plot viewer", style="Section.TLabel").grid(row=14, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 8))

        ttk.Label(tab, text="Plot folder").grid(row=15, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.plot_folder_path, width=70).grid(row=15, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(tab, text="Browse", command=lambda: self.browse_directory_var(self.plot_folder_path)).grid(row=15, column=2, padx=(6, 10), pady=6)

        ttk.Label(tab, text="Plot image").grid(row=16, column=0, sticky="w", padx=(8, 4), pady=4)
        self.plot_combo = ttk.Combobox(tab, textvariable=self.selected_plot_file, values=[], width=67)
        self.plot_combo.grid(row=16, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(tab, text="Refresh", command=self.refresh_plot_list).grid(row=16, column=2, padx=(6, 10), pady=6)

        plot_buttons = ttk.Frame(tab, style="ButtonBar.TFrame")
        plot_buttons.grid(row=17, column=1, sticky="w", padx=4, pady=(4, 8))
        ttk.Button(plot_buttons, text="Show Selected Plot", command=self.show_selected_plot).pack(side="left", padx=(0, 6))
        ttk.Button(plot_buttons, text="Use Report Folder", command=self.use_report_folder_for_plots).pack(side="left", padx=6)

        self.plot_caption = tk.StringVar(value="No plot selected.")
        ttk.Label(tab, textvariable=self.plot_caption).grid(row=18, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))
        self.plot_display = tk.Label(
            tab,
            text="Refresh plots after generating a DOE report.",
            bg="#ffffff",
            fg=COLOR_MUTED,
            anchor="center",
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_ACCENT,
        )
        self.plot_display.grid(row=19, column=0, columnspan=3, sticky="nsew", padx=8, pady=(0, 8))
        tab.rowconfigure(19, weight=1)

    def build_launch_tab(self):
        tab = self.tabs["Run"]
        ttk.Label(tab, text="Python executable").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.python_executable, width=80).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(tab, text="Browse", command=self.browse_python).grid(row=0, column=2, padx=(6, 10), pady=6)

        ttk.Label(tab, text="Config output path").grid(row=1, column=0, sticky="w", padx=(8, 4), pady=4)
        ttk.Entry(tab, textvariable=self.config_output_path, width=80).grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(tab, text="Browse", command=self.browse_config_output).grid(row=1, column=2, padx=(6, 10), pady=6)

        button_frame = ttk.Frame(tab, style="ButtonBar.TFrame")
        button_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=(8, 4))
        ttk.Button(button_frame, text="Load JSON Config", command=self.load_json_config).pack(side="left", padx=(0, 6))
        ttk.Button(button_frame, text="Save JSON Config", command=self.save_json_config).pack(side="left", padx=6)
        ttk.Button(button_frame, text="Save and Run DEFORM", command=self.save_and_run, style="Success.TButton").pack(side="left", padx=6)
        ttk.Button(button_frame, text="Preview Config", command=self.preview_config).pack(side="left", padx=6)

        self.log_text = scrolledtext.ScrolledText(
            tab,
            height=23,
            wrap="word",
            bg=COLOR_LOG_BG,
            fg=COLOR_LOG_FG,
            insertbackground=COLOR_LOG_FG,
            relief="flat",
            borderwidth=0,
            font=("Consolas", 10),
            padx=12,
            pady=10,
        )
        self.log_text.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=8, pady=10)
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

        if LOCAL_ACTION_FILES_DIR.exists() and (not action_path.exists() or action_path == LOCAL_ACTION_FILES_DIR):
            action_path = LOCAL_ACTION_FILES_DIR
            if "action_path" in self.fields:
                self.fields["action_path"].set_value(str(LOCAL_ACTION_FILES_DIR))

        if "action_file" in self.fields:
            action_files = []
            for folder in [action_path, LOCAL_ACTION_FILES_DIR]:
                if folder.exists():
                    action_files.extend(path.name for path in folder.glob("*.csv"))
            action_files = sorted(set(action_files))
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
        config["material_type"] = self.material_type_var.get()
        set_simulation_modes_from_jmak(config)
        if "jmak_simulation_modes" in self.fields:
            self.fields["jmak_simulation_modes"].set_value(config["jmak_simulation_modes"])
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
        material_name = str(config.get("deform_material_name", ""))
        material_type = str(config.get("material_type", "")) or self.find_material_type(material_name)
        if material_type:
            self.material_type_var.set(material_type)
            self.on_material_type_changed()
        if material_name and "deform_material_name" in self.fields:
            self.fields["deform_material_name"].set_value(
                self.resolve_material_name(material_name, self.material_type_var.get())
            )
        self.refresh_short_material_labels()
        self.update_jmak_simulation_modes()
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
        self.start_command(command, "Starting DEFORM runner...")

    def browse_directory_var(self, variable):
        selected = filedialog.askdirectory(initialdir=variable.get() or str(APP_DIR))
        if selected:
            variable.set(selected)

    def browse_file_var(self, variable, filetypes):
        selected = filedialog.askopenfilename(
            initialdir=str(Path(variable.get()).parent) if variable.get() else str(APP_DIR),
            filetypes=filetypes,
        )
        if selected:
            variable.set(selected)

    def start_command(self, command, label, on_complete=None):
        self.log(label)
        self.log(" ".join(f'"{part}"' if " " in part else part for part in command))
        self.status_var.set(label)
        thread = threading.Thread(target=self.run_command, args=(command, on_complete), daemon=True)
        thread.start()

    def parse_json_field(self, key):
        value = self.doe_fields[key].get_value()
        if isinstance(value, str):
            return json.loads(value)
        return value

    def doe_override_values(self):
        num_hits = int(self.doe_fields["NUM_HITS"].get_value())
        return {
            "PROJECT_ROOT": str(Path(self.doe_project_root.get())),
            "RUNNER_SCRIPT": str(RUNNER_PATH),
            "BASE_CONFIG_PATH": str(Path(self.doe_base_config_path.get())),
            "OPTIMIZATION_ROOT": str(Path(self.doe_optimization_root.get())),
            "STUDY_NAME": self.doe_study_name.get().strip(),
            "NUM_HITS": num_hits,
            "PREPARE_RUNS": self.doe_fields["PREPARE_RUNS"].get_value(),
            "EXECUTE_RUNS": self.doe_fields["EXECUTE_RUNS"].get_value(),
            "PROCESS_RESULTS": self.doe_fields["PROCESS_RESULTS"].get_value(),
            "PROPOSE_NEXT_CANDIDATES": self.doe_fields["PROPOSE_NEXT_CANDIDATES"].get_value(),
            "RUN_NEXT_CANDIDATES": self.doe_fields["RUN_NEXT_CANDIDATES"].get_value(),
            "EXECUTE_NEXT_CANDIDATES": self.doe_fields["EXECUTE_NEXT_CANDIDATES"].get_value(),
            "PROCESS_NEXT_CANDIDATES": self.doe_fields["PROCESS_NEXT_CANDIDATES"].get_value(),
            "COMBINE_DATASETS": self.doe_fields["COMBINE_DATASETS"].get_value(),
            "MAKE_REPORT": self.doe_fields["MAKE_REPORT"].get_value(),
            "APPLY_MODE": self.doe_fields["APPLY_MODE"].get_value(),
            "N_CANDIDATES": int(self.doe_fields["N_CANDIDATES"].get_value()),
            "RANDOM_SEED": int(self.doe_fields["RANDOM_SEED"].get_value()),
            "MODEL_TYPE": self.doe_fields["MODEL_TYPE"].get_value(),
            "N_RANDOM_BAYESIAN_CANDIDATES": int(self.doe_fields["N_RANDOM_BAYESIAN_CANDIDATES"].get_value()),
            "N_NEXT_CANDIDATES": int(self.doe_fields["N_NEXT_CANDIDATES"].get_value()),
            "NEXT_ROUND_NUMBER": int(self.doe_fields["NEXT_ROUND_NUMBER"].get_value()),
            "MAX_ROUND_NUMBER": int(self.doe_fields["MAX_ROUND_NUMBER"].get_value()),
            "BOUNDS": self.parse_json_field("BOUNDS"),
            "OBJECTIVE_WEIGHTS": self.parse_json_field("OBJECTIVE_WEIGHTS"),
            "DOE_CONFIG_OVERRIDES": {
                "num_hits": num_hits,
                "die_motion_mode": self.fields["die_motion_mode"].get_value() or "single_top_die",
                "die_motion_axis": self.fields["die_motion_axis"].get_value(),
                "apply_action_file_rules": False,
                "position_bottom_die_before_first_hit": self.fields["die_motion_mode"].get_value() == "symmetric",
            },
        }

    def build_doe_launcher_text(self):
        values = self.doe_override_values()
        doe_script = str(Path(self.doe_script_path.get()))
        assignments = [
            "import importlib.util",
            "import json",
            "from pathlib import Path",
            "",
            f"DOE_SCRIPT = Path({doe_script!r})",
            "spec = importlib.util.spec_from_file_location('run_initial_doe_gui_module', DOE_SCRIPT)",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            "",
        ]
        path_keys = {"PROJECT_ROOT", "RUNNER_SCRIPT", "BASE_CONFIG_PATH", "OPTIMIZATION_ROOT"}
        for key, value in values.items():
            if key in path_keys:
                assignments.append(f"module.{key} = Path({value!r})")
            else:
                assignments.append(f"module.{key} = {repr(value)}")
        assignments.extend(
            [
                "",
                "# Rebuild derived paths after GUI overrides.",
                "module.CANDIDATES_CSV = module.OPTIMIZATION_ROOT / module.STUDY_NAME / 'candidates_initial.csv'",
                "module.MANIFEST_CSV = module.OPTIMIZATION_ROOT / module.STUDY_NAME / 'manifest.csv'",
                "module.DOE_TEMPLATE_CONFIG = module.OPTIMIZATION_ROOT / module.STUDY_NAME / 'doe_template_config.json'",
                "module.DATASET_CSV = module.OPTIMIZATION_ROOT / module.STUDY_NAME / 'dataset.csv'",
                "module.COMBINED_DATASET_CSV = module.OPTIMIZATION_ROOT / module.STUDY_NAME / 'dataset_all.csv'",
                "module.NEXT_CANDIDATES_CSV = module.OPTIMIZATION_ROOT / module.STUDY_NAME / 'candidates_next.csv'",
                "module.REPORT_DIR = module.OPTIMIZATION_ROOT / module.STUDY_NAME / 'report'",
                "module.NEXT_STUDY_NAME = f'{module.STUDY_NAME}_round_{module.NEXT_ROUND_NUMBER:02d}'",
                "module.NEXT_MANIFEST_CSV = module.OPTIMIZATION_ROOT / module.NEXT_STUDY_NAME / 'manifest.csv'",
                "module.NEXT_DATASET_CSV = module.OPTIMIZATION_ROOT / module.NEXT_STUDY_NAME / 'dataset.csv'",
                "module.NEXT_REPORT_DIR = module.OPTIMIZATION_ROOT / module.NEXT_STUDY_NAME / 'report'",
                "",
                "results = module.run_initial_doe()",
                "print(json.dumps({key: str(value) for key, value in results.items()}, indent=2))",
            ]
        )
        return "\n".join(assignments) + "\n"

    def write_doe_launcher(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        launcher_path = CONFIG_DIR / "run_initial_doe_gui_launcher.py"
        launcher_path.write_text(self.build_doe_launcher_text(), encoding="utf-8")
        self.log(f"Saved DOE launcher: {launcher_path}")
        return launcher_path

    def preview_doe_launcher(self):
        try:
            self.log(self.build_doe_launcher_text())
        except Exception as exc:
            messagebox.showerror("DOE launcher preview failed", str(exc))

    def create_action_files_from_gui(self):
        output_dir = Path(self.af_output_dir.get().strip() or LOCAL_ACTION_FILES_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        if "action_path" in self.fields:
            self.fields["action_path"].set_value(str(output_dir))

        command = [
            self.python_executable.get(),
            str(ACTION_CREATOR_PATH),
            "--base-path",
            self.af_base_path.get().strip(),
            "--hit-folders",
            self.af_hit_folders.get().strip(),
            "--output-dir",
            str(output_dir),
            "--output-prefix",
            self.af_output_prefix.get().strip() or "af",
            "--position-threshold-mm",
            self.af_position_threshold_mm.get().strip() or "30.0",
            "--force-sigma-multiplier",
            self.af_force_sigma_multiplier.get().strip() or "1.5",
        ]
        self.start_command(
            command,
            "Creating action file(s) from AF load-stroke data...",
            on_complete=self.refresh_file_dropdowns,
        )

    def run_doe_workflow(self):
        try:
            config_path = self.save_json_config()
            self.doe_base_config_path.set(str(config_path))
            launcher_path = self.write_doe_launcher()
        except Exception as exc:
            messagebox.showerror("DOE setup failed", str(exc))
            return
        command = [self.python_executable.get(), str(launcher_path)]
        self.start_command(command, "Starting DOE workflow...")

    def run_single_post_processing(self):
        command = [
            self.python_executable.get(),
            str(POST_PROCESS_PATH),
            "--config",
            self.post_config_path.get(),
            "--output-subdir",
            self.fields["post_process_output_subdir"].var.get(),
            "--damage-object",
            self.fields["post_process_damage_object"].var.get(),
            "--damage-step-no",
            str(self.fields["post_process_damage_step_no"].get_value()),
        ]
        if self.post_run_dir.get().strip():
            command.extend(["--run-dir", self.post_run_dir.get().strip()])
        self.start_command(command, "Starting single-run post-processing...")

    def run_doe_visualization(self):
        command = [self.python_executable.get(), str(VISUALIZE_DOE_PATH)]
        option_pairs = [
            ("--study-root", self.report_study_root.get()),
            ("--dataset", self.report_dataset_path.get()),
            ("--manifest", self.report_manifest_path.get()),
            ("--candidates", self.report_candidates_path.get()),
            ("--surrogate-report", self.report_surrogate_path.get()),
            ("--output-dir", self.report_output_dir.get()),
        ]
        for option, value in option_pairs:
            if str(value).strip():
                command.extend([option, str(value).strip()])
        self.start_command(
            command,
            "Starting DOE visualization report...",
            on_complete=self.refresh_and_show_first_plot,
        )

    def refresh_and_show_first_plot(self):
        """Refresh generated plots and display one inside the GUI."""
        self.use_report_folder_for_plots()
        if self.selected_plot_file.get().strip():
            self.show_selected_plot()

    def default_plot_folder(self):
        if self.plot_folder_path.get().strip():
            return Path(self.plot_folder_path.get().strip())
        if self.report_output_dir.get().strip():
            return Path(self.report_output_dir.get().strip())
        if self.report_study_root.get().strip():
            return Path(self.report_study_root.get().strip()) / "report"
        return APP_DIR

    def use_report_folder_for_plots(self):
        if self.report_output_dir.get().strip():
            folder = Path(self.report_output_dir.get().strip())
        else:
            folder = Path(self.report_study_root.get().strip()) / "report"
        self.plot_folder_path.set(str(folder))
        self.refresh_plot_list()

    def refresh_plot_list(self):
        folder = self.default_plot_folder()
        self.plot_folder_path.set(str(folder))
        if not folder.exists():
            self.plot_combo.configure(values=[])
            self.selected_plot_file.set("")
            self.plot_caption.set(f"Plot folder does not exist: {folder}")
            self.log(f"Plot folder does not exist: {folder}")
            return []

        plots = sorted(folder.glob("*.png"))
        display_names = [path.name for path in plots]
        self.plot_combo.configure(values=display_names)
        if display_names and self.selected_plot_file.get() not in display_names:
            self.selected_plot_file.set(display_names[0])
        self.plot_caption.set(f"Found {len(display_names)} plot(s) in {folder}")
        self.log(f"Found {len(display_names)} plot(s) in {folder}")
        return plots

    def selected_plot_path(self):
        folder = self.default_plot_folder()
        selected = self.selected_plot_file.get().strip()
        if not selected:
            return None
        return folder / selected

    def show_selected_plot(self):
        plot_path = self.selected_plot_path()
        if plot_path is None:
            self.refresh_plot_list()
            plot_path = self.selected_plot_path()
        if plot_path is None or not plot_path.exists():
            messagebox.showwarning("Plot not found", "Select a plot after refreshing the plot list.")
            return

        try:
            raw_image = tk.PhotoImage(file=str(plot_path))
        except tk.TclError as exc:
            messagebox.showerror(
                "Could not load plot",
                f"Tkinter could not load this image:\n{plot_path}\n\n{exc}",
            )
            return

        max_width = 980
        max_height = 420
        scale = max(
            1,
            (raw_image.width() + max_width - 1) // max_width,
            (raw_image.height() + max_height - 1) // max_height,
        )
        display_image = raw_image.subsample(scale, scale) if scale > 1 else raw_image
        self.current_plot_raw = raw_image
        self.current_plot_image = display_image
        self.plot_display.configure(image=display_image, text="", bg="#ffffff")
        self.plot_caption.set(
            f"Showing {plot_path.name} ({raw_image.width()} x {raw_image.height()} px, scale 1/{scale})"
        )
        self.log(f"Showing plot: {plot_path}")

    def run_command(self, command, on_complete=None):
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
            if return_code == 0 and on_complete is not None:
                self.after(0, on_complete)
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


