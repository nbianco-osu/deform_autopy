"""
Create plots and an HTML report for DEFORM DOE/optimization studies.

Run this after `process_doe_results.py` has rebuilt `dataset.csv`. The script
is intentionally file-based, so it can be rerun after each DOE/Bayesian batch
without needing to reopen DEFORM.

Typical Spyder use:

    STUDY_ROOT = r"C:\\Users\\bianco.33\\Desktop\\deform_auto_py\\optimization\\single_die_5hit_initial_doe"
    visualize_doe_results(study_root=STUDY_ROOT)

Command-line use:

    python visualize_doe_results.py --study-root "C:\\path\\to\\optimization\\study"
"""

import argparse
import json
import math
from pathlib import Path
import pandas as pd


DEFAULT_INPUT_CANDIDATE_COLUMNS = [
    "depth_in",
    "speed_in/s",
    "forging_temp_c",
    "height",
    "time_step",
]

DEFAULT_OUTPUT_METRIC_COLUMNS = [
    "objective",
    "damage_max",
    "grain_mean_um",
    "grain_std_um",
    "grain_p50_um",
    "initial_state_grain_mean_um",
    "initial_state_grain_std_um",
    "top_die_center_distance",
    "bottom_die_center_distance",
]


def require_matplotlib():
    """Import matplotlib lazily so tabular summaries still work if missing."""
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "Visualization requires matplotlib. Install it in the Python "
            "environment used for DOE reporting."
        ) from exc
    return plt


def read_csv_if_exists(path):
    """Read a CSV if it exists, otherwise return an empty DataFrame."""
    path = Path(path)
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()


def read_json_if_exists(path):
    """Read a JSON file if it exists, otherwise return an empty dict."""
    path = Path(path)
    if path.exists():
        with open(path, "r") as file:
            return json.load(file)
    return {}


def find_column(df, logical_name):
    """Find a column by direct name or common metadata-prefixed variants."""
    if df.empty:
        return None

    candidates = [
        logical_name,
        f"meta_candidate_{logical_name}",
        f"meta_applied_action_values_{logical_name}",
        f"meta_applied_config_values_{logical_name}",
    ]

    normalized = {str(column).lower(): column for column in df.columns}
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
        key = candidate.lower()
        if key in normalized:
            return normalized[key]
    return None


def numeric_series(df, column):
    """Return a numeric series for a column, preserving the original index."""
    if column is None or column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


def safe_filename(name):
    """Make a readable filename from a metric/feature name."""
    safe = str(name).replace("/", "_per_").replace("\\", "_")
    for char in " :;,.()[]{}":
        safe = safe.replace(char, "_")
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_").lower()


def save_plot(fig, output_dir, filename):
    """Save a plot and close the figure."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    fig.clf()
    return path


def plot_metric_vs_run(dataset, metric, output_dir):
    """Plot a metric against completed dataset row order."""
    plt = require_matplotlib()
    column = find_column(dataset, metric)
    y = numeric_series(dataset, column)
    valid = y.notna()
    if not valid.any():
        return None

    x = range(1, int(valid.sum()) + 1)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(list(x), y[valid].to_numpy(), marker="o", linewidth=1.8)
    ax.set_xlabel("Completed run order")
    ax.set_ylabel(metric)
    ax.set_title(f"{metric} vs run")
    ax.grid(True, alpha=0.25)
    return save_plot(fig, output_dir, f"{safe_filename(metric)}_vs_run.png")


def plot_feature_vs_metric(dataset, feature, metric, output_dir):
    """Scatter an input feature against an output metric/objective."""
    plt = require_matplotlib()
    x_col = find_column(dataset, feature)
    y_col = find_column(dataset, metric)
    x = numeric_series(dataset, x_col)
    y = numeric_series(dataset, y_col)
    valid = x.notna() & y.notna()
    if valid.sum() < 2:
        return None

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    ax.scatter(x[valid], y[valid], s=48, alpha=0.8)
    ax.set_xlabel(feature)
    ax.set_ylabel(metric)
    ax.set_title(f"{metric} vs {feature}")
    ax.grid(True, alpha=0.25)
    return save_plot(fig, output_dir, f"{safe_filename(metric)}_vs_{safe_filename(feature)}.png")


def plot_metric_tradeoff(dataset, x_metric, y_metric, output_dir, color_metric="objective"):
    """Scatter two output metrics, optionally colored by objective."""
    plt = require_matplotlib()
    x_col = find_column(dataset, x_metric)
    y_col = find_column(dataset, y_metric)
    c_col = find_column(dataset, color_metric)
    x = numeric_series(dataset, x_col)
    y = numeric_series(dataset, y_col)
    c = numeric_series(dataset, c_col)
    valid = x.notna() & y.notna()
    if valid.sum() < 2:
        return None

    fig, ax = plt.subplots(figsize=(6.5, 4.8))
    if c_col and c[valid].notna().any():
        points = ax.scatter(x[valid], y[valid], c=c[valid], s=54, alpha=0.85)
        fig.colorbar(points, ax=ax, label=color_metric)
    else:
        ax.scatter(x[valid], y[valid], s=54, alpha=0.85)
    ax.set_xlabel(x_metric)
    ax.set_ylabel(y_metric)
    ax.set_title(f"{y_metric} vs {x_metric}")
    ax.grid(True, alpha=0.25)
    return save_plot(
        fig,
        output_dir,
        f"{safe_filename(y_metric)}_vs_{safe_filename(x_metric)}.png",
    )


def plot_manifest_status(manifest, output_dir):
    """Plot manifest status counts."""
    if manifest.empty or "status" not in manifest.columns:
        return None

    counts = manifest["status"].fillna("missing").astype(str).value_counts()
    if counts.empty:
        return None

    plt = require_matplotlib()
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    counts.plot(kind="bar", ax=ax)
    ax.set_xlabel("Status")
    ax.set_ylabel("Count")
    ax.set_title("Run status counts")
    ax.grid(True, axis="y", alpha=0.25)
    return save_plot(fig, output_dir, "manifest_status_counts.png")


def plot_completed_vs_next_candidates(dataset, candidates, output_dir):
    """Plot completed DOE samples against proposed next candidates."""
    if dataset.empty or candidates.empty:
        return None

    x_name = "depth_in"
    y_name = "speed_in/s"
    completed_x_col = find_column(dataset, x_name)
    completed_y_col = find_column(dataset, y_name)
    next_x_col = find_column(candidates, x_name)
    next_y_col = find_column(candidates, y_name)

    completed_x = numeric_series(dataset, completed_x_col)
    completed_y = numeric_series(dataset, completed_y_col)
    next_x = numeric_series(candidates, next_x_col)
    next_y = numeric_series(candidates, next_y_col)

    completed_valid = completed_x.notna() & completed_y.notna()
    next_valid = next_x.notna() & next_y.notna()
    if not completed_valid.any() and not next_valid.any():
        return None

    plt = require_matplotlib()
    fig, ax = plt.subplots(figsize=(6.5, 5))
    if completed_valid.any():
        ax.scatter(
            completed_x[completed_valid],
            completed_y[completed_valid],
            s=46,
            alpha=0.75,
            label="Completed",
        )
    if next_valid.any():
        ax.scatter(
            next_x[next_valid],
            next_y[next_valid],
            s=76,
            marker="X",
            alpha=0.95,
            label="Next candidates",
        )
    ax.set_xlabel(x_name)
    ax.set_ylabel(y_name)
    ax.set_title("Completed vs proposed candidates")
    ax.grid(True, alpha=0.25)
    ax.legend()
    return save_plot(fig, output_dir, "completed_vs_next_candidates.png")


def summarize_dataset(dataset):
    """Return high-level dataset summary values for the report."""
    if dataset.empty:
        return {"rows": 0}

    summary = {"rows": int(len(dataset))}
    for metric in DEFAULT_OUTPUT_METRIC_COLUMNS:
        column = find_column(dataset, metric)
        values = numeric_series(dataset, column)
        valid = values.dropna()
        if valid.empty:
            continue
        summary[f"{metric}_min"] = float(valid.min())
        summary[f"{metric}_median"] = float(valid.median())
        summary[f"{metric}_max"] = float(valid.max())

    objective_col = find_column(dataset, "objective")
    objective = numeric_series(dataset, objective_col)
    if objective.notna().any():
        best_idx = objective.idxmin()
        summary["best_objective"] = float(objective.loc[best_idx])
        run_name = dataset.loc[best_idx].get("run_name", "")
        summary["best_run_name"] = str(run_name)

    return summary


def write_summary_csv(dataset, output_dir):
    """Write numeric describe table for quick inspection."""
    if dataset.empty:
        return None
    numeric = dataset.select_dtypes(include="number")
    if numeric.empty:
        return None
    output_path = Path(output_dir) / "dataset_numeric_summary.csv"
    numeric.describe().transpose().to_csv(output_path)
    return output_path


def format_report_value(value):
    """Format report values compactly."""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:.6g}"
    return str(value)


def write_html_report(
    output_path,
    study_root,
    dataset_path,
    manifest_path,
    candidates_path,
    surrogate_report_path,
    summary,
    plot_paths,
    surrogate_report,
):
    """Write a small self-contained index page linking generated plots."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = "\n".join(
        f"<tr><th>{key}</th><td>{format_report_value(value)}</td></tr>"
        for key, value in summary.items()
    )
    images = "\n".join(
        (
            "<section>"
            f"<h3>{path.stem.replace('_', ' ').title()}</h3>"
            f"<img src='{path.name}' alt='{path.stem}' />"
            "</section>"
        )
        for path in plot_paths
        if path is not None
    )
    report_json = json.dumps(surrogate_report, indent=2) if surrogate_report else "{}"

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>DEFORM DOE Optimization Report</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 28px;
      color: #111827;
      background: #f8fafc;
    }}
    h1, h2, h3 {{ color: #0f172a; }}
    code, pre {{
      background: #e2e8f0;
      padding: 2px 5px;
      border-radius: 4px;
    }}
    table {{
      border-collapse: collapse;
      background: white;
      margin-bottom: 24px;
      min-width: 520px;
    }}
    th, td {{
      border: 1px solid #cbd5e1;
      padding: 7px 9px;
      text-align: left;
    }}
    section {{
      background: white;
      border: 1px solid #cbd5e1;
      padding: 14px 18px;
      margin: 18px 0;
    }}
    img {{
      max-width: 920px;
      width: 100%;
      height: auto;
      display: block;
    }}
  </style>
</head>
<body>
  <h1>DEFORM DOE Optimization Report</h1>
  <p><strong>Study root:</strong> <code>{study_root}</code></p>
  <p><strong>Dataset:</strong> <code>{dataset_path}</code></p>
  <p><strong>Manifest:</strong> <code>{manifest_path}</code></p>
  <p><strong>Next candidates:</strong> <code>{candidates_path}</code></p>
  <p><strong>Surrogate report:</strong> <code>{surrogate_report_path}</code></p>

  <h2>Summary</h2>
  <table>{rows}</table>

  <h2>Plots</h2>
  {images if images else "<p>No plots were generated. Check that dataset columns are populated.</p>"}

  <h2>Surrogate Report</h2>
  <pre>{report_json}</pre>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


def visualize_doe_results(
    study_root=None,
    dataset_path=None,
    manifest_path=None,
    candidates_path=None,
    surrogate_report_path=None,
    output_dir=None,
    input_columns=None,
    metric_columns=None,
):
    """Generate DOE plots and an HTML report.

    Parameters can be passed explicitly, or `study_root` can be used to infer:
    `dataset.csv`, `manifest.csv`, `candidates_next.csv`,
    `surrogate_report.json`, and `report/`.
    """
    if study_root is None and dataset_path is None:
        raise ValueError("Pass either study_root or dataset_path.")

    study_root = Path(study_root) if study_root else Path(dataset_path).parent
    dataset_path = Path(dataset_path) if dataset_path else study_root / "dataset.csv"
    manifest_path = Path(manifest_path) if manifest_path else study_root / "manifest.csv"
    candidates_path = Path(candidates_path) if candidates_path else study_root / "candidates_next.csv"
    surrogate_report_path = (
        Path(surrogate_report_path)
        if surrogate_report_path
        else study_root / "surrogate_report.json"
    )
    output_dir = Path(output_dir) if output_dir else study_root / "report"
    output_dir.mkdir(parents=True, exist_ok=True)

    input_columns = input_columns or DEFAULT_INPUT_CANDIDATE_COLUMNS
    metric_columns = metric_columns or DEFAULT_OUTPUT_METRIC_COLUMNS

    dataset = read_csv_if_exists(dataset_path)
    manifest = read_csv_if_exists(manifest_path)
    candidates = read_csv_if_exists(candidates_path)
    surrogate_report = read_json_if_exists(surrogate_report_path)

    plot_paths = []
    plot_warning = ""
    try:
        plot_paths.append(plot_manifest_status(manifest, output_dir))

        for metric in metric_columns:
            plot_paths.append(plot_metric_vs_run(dataset, metric, output_dir))

        if find_column(dataset, "objective"):
            for feature in input_columns:
                plot_paths.append(plot_feature_vs_metric(dataset, feature, "objective", output_dir))

        plot_paths.append(plot_metric_tradeoff(dataset, "damage_max", "grain_mean_um", output_dir))
        plot_paths.append(plot_metric_tradeoff(dataset, "damage_max", "grain_std_um", output_dir))
        plot_paths.append(plot_completed_vs_next_candidates(dataset, candidates, output_dir))
        plot_paths = [path for path in plot_paths if path is not None]
    except RuntimeError as exc:
        plot_warning = str(exc)
        plot_paths = [path for path in plot_paths if path is not None]

    summary = summarize_dataset(dataset)
    summary_csv = write_summary_csv(dataset, output_dir)
    if summary_csv:
        summary["numeric_summary_csv"] = str(summary_csv)
    if plot_warning:
        summary["plot_warning"] = plot_warning

    report_path = write_html_report(
        output_path=output_dir / "index.html",
        study_root=study_root,
        dataset_path=dataset_path,
        manifest_path=manifest_path,
        candidates_path=candidates_path,
        surrogate_report_path=surrogate_report_path,
        summary=summary,
        plot_paths=plot_paths,
        surrogate_report=surrogate_report,
    )

    return {
        "report_path": str(report_path),
        "output_dir": str(output_dir),
        "plot_count": len(plot_paths),
        "summary_csv": str(summary_csv) if summary_csv else "",
        "plot_warning": plot_warning,
    }


def main():
    parser = argparse.ArgumentParser(description="Create DEFORM DOE plots and an HTML report.")
    parser.add_argument("--study-root", default=None, help="Folder containing dataset.csv and manifest.csv.")
    parser.add_argument("--dataset", default=None, help="Explicit dataset CSV path.")
    parser.add_argument("--manifest", default=None, help="Explicit manifest CSV path.")
    parser.add_argument("--candidates", default=None, help="Explicit candidates_next.csv path.")
    parser.add_argument("--surrogate-report", default=None, help="Explicit surrogate_report.json path.")
    parser.add_argument("--output-dir", default=None, help="Report output directory.")
    args = parser.parse_args()

    result = visualize_doe_results(
        study_root=args.study_root,
        dataset_path=args.dataset,
        manifest_path=args.manifest,
        candidates_path=args.candidates,
        surrogate_report_path=args.surrogate_report,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
