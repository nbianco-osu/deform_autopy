"""
Infer induction-heating events from Agility Forge hit temperatures.

Agility Forge hits are performed inside a process window. For the Box 316L work
we have been using 800-1200 C. The recorded temperature is the temperature when
the hit occurs, not a continuous furnace/coil temperature trace. This module
therefore infers heating events from the hit sequence:

- the first heat raises the workpiece from room temperature to the first hit;
- a reheat is inferred when the next hit temperature increases enough that
  ordinary cooling cannot explain it;
- if a hit is below the lower process limit, the row is flagged as requiring
  reheat before that hit or before the next attempted hit.

The model is deliberately traceable. It does not assume a coil geometry or solve
electromagnetic heat transfer yet. Later, heating-rate, dwell, radial gradient,
and local-section parameters can be calibrated from pyrometer/thermal-camera
data and DEFORM thermal histories.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from .af_signal_processing import (
    AFColumnMap,
    ContactDetectionConfig,
    detect_contact,
    infer_hit_number,
    read_af_hit_csv,
    resolve_column,
)


PLOT_WIDTH = 1200
PLOT_HEIGHT = 700
MARGIN_LEFT = 92
MARGIN_RIGHT = 310
MARGIN_TOP = 72
MARGIN_BOTTOM = 94

COLOR_TEXT = (31, 41, 55)
COLOR_GRID = (224, 231, 241)
COLOR_TEMP = (43, 109, 180)
COLOR_TRACE = (95, 148, 207)
COLOR_WINDOW = (223, 244, 232)
COLOR_HEAT = (213, 107, 43)
COLOR_QUENCH = (72, 127, 158)
COLOR_WARN = (184, 65, 65)
COLOR_GRAY = (107, 114, 128)


@dataclass
class InductionHeatingConfig:
    """Settings for process-window and reheat inference."""

    lower_temp_c: float = 800.0
    upper_temp_c: float = 1200.0
    room_temp_c: float = 25.0
    reheat_delta_c: float = 25.0
    target_reheat_temp_c: float = 1100.0
    heating_rate_c_per_s: float | None = None
    cooling_rate_c_per_s: float | None = None
    hit_interval_s: float = 1.0
    inferred_heat_duration_s: float = 0.35
    infer_initial_heat_from_reheats: bool = True
    quench_after_hits: bool = True
    quench_duration_s: float = 2.0
    quench_rate_c_per_s: float | None = None


def load_font(size: int) -> ImageFont.ImageFont:
    """Load a Windows font or fall back to Pillow's default."""
    for font in ["segoeui.ttf", "arial.ttf", "calibri.ttf"]:
        try:
            return ImageFont.truetype(font, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def hit_sort_key(path: Path) -> tuple[int, str]:
    """Sort raw hit files using hit numbers in filenames."""
    hit = infer_hit_number(path.name)
    return (hit if hit is not None else 10**9, path.name)


def load_hit_temperatures_from_raw_folder(
    raw_af_data_dir: str | Path,
    hit_glob: str = "*.csv",
    column_map: AFColumnMap | None = None,
    contact_config: ContactDetectionConfig | None = None,
) -> pd.DataFrame:
    """Read raw AF files and extract the temperature at contact for each hit."""
    raw_af_data_dir = Path(raw_af_data_dir)
    rows = []
    for csv_path in sorted(raw_af_data_dir.glob(hit_glob), key=hit_sort_key):
        raw_df = pd.read_csv(csv_path)
        time_col = resolve_column(raw_df, None, "Time (s)")
        raw_time = pd.to_numeric(raw_df[time_col], errors="coerce")
        if "ms" in str(time_col).lower() or "unix" in str(time_col).lower():
            raw_time = raw_time / 1000.0
        raw_time = raw_time.dropna()
        hit_df = read_af_hit_csv(csv_path, column_map=column_map)
        contact = detect_contact(hit_df, config=contact_config)
        global_start_s = float(raw_time.iloc[0]) if not raw_time.empty else float("nan")
        global_end_s = float(raw_time.iloc[-1]) if not raw_time.empty else float("nan")
        global_contact_s = global_start_s + float(contact["contact_time_s"]) if np.isfinite(global_start_s) else float("nan")
        rows.append(
            {
                "hit": hit_df["hit"].iloc[0],
                "source_file": csv_path.name,
                "hit_temperature_c": float(contact["contact_temperature_c"]),
                "contact_time_s": float(contact["contact_time_s"]),
                "global_start_s": global_start_s,
                "global_end_s": global_end_s,
                "global_contact_s": global_contact_s,
                "global_duration_s": float(global_end_s - global_start_s) if np.isfinite(global_start_s) and np.isfinite(global_end_s) else float("nan"),
                "temperature_mean_c": float(np.nanmean(hit_df["temperature_c"])),
            }
        )
    return pd.DataFrame(rows)


def load_hit_temperature_traces_from_raw_folder(
    raw_af_data_dir: str | Path,
    hit_glob: str = "*.csv",
    column_map: AFColumnMap | None = None,
    contact_config: ContactDetectionConfig | None = None,
) -> pd.DataFrame:
    """Read full temperature-versus-time traces from every raw AF hit file.

    Each raw AF file has a local clock that starts at zero after normalization.
    The global/process clock is reconstructed later by `build_temperature_time_trace`.
    """
    raw_af_data_dir = Path(raw_af_data_dir)
    traces = []
    for csv_path in sorted(raw_af_data_dir.glob(hit_glob), key=hit_sort_key):
        raw_df = pd.read_csv(csv_path)
        time_col = resolve_column(raw_df, None, "Time (s)")
        raw_time = pd.to_numeric(raw_df[time_col], errors="coerce")
        if "ms" in str(time_col).lower() or "unix" in str(time_col).lower():
            raw_time = raw_time / 1000.0
        global_start_s = float(raw_time.dropna().iloc[0]) if not raw_time.dropna().empty else float("nan")
        hit_df = read_af_hit_csv(csv_path, column_map=column_map)
        contact = detect_contact(hit_df, config=contact_config)
        trace = hit_df[["time_s", "temperature_c"]].copy()
        trace["time_s"] = pd.to_numeric(trace["time_s"], errors="coerce")
        trace["temperature_c"] = pd.to_numeric(trace["temperature_c"], errors="coerce")
        trace = trace.dropna(subset=["time_s", "temperature_c"])
        if trace.empty:
            continue
        trace["hit"] = hit_df["hit"].iloc[0]
        trace["source_file"] = csv_path.name
        trace["local_time_s"] = trace["time_s"] - float(trace["time_s"].min())
        trace["global_time_s"] = global_start_s + trace["local_time_s"] if np.isfinite(global_start_s) else np.nan
        trace["contact_time_s"] = float(contact["contact_time_s"])
        trace["global_contact_s"] = global_start_s + float(contact["contact_time_s"]) if np.isfinite(global_start_s) else np.nan
        trace["contact_temperature_c"] = float(contact["contact_temperature_c"])
        traces.append(trace[["hit", "source_file", "local_time_s", "global_time_s", "temperature_c", "contact_time_s", "global_contact_s", "contact_temperature_c"]])
    if not traces:
        return pd.DataFrame(
            columns=["hit", "source_file", "local_time_s", "global_time_s", "temperature_c", "contact_time_s", "global_contact_s", "contact_temperature_c"]
        )
    return pd.concat(traces, ignore_index=True)


def load_hit_temperatures_from_summary(summary_csv: str | Path) -> pd.DataFrame:
    """Load hit temperatures from an existing processed summary/features CSV."""
    summary_csv = Path(summary_csv)
    df = pd.read_csv(summary_csv)
    candidates = [
        "hit_temperature_c",
        "contact_temperature_c",
        "temperature_c",
        "temperature_mean_c",
    ]
    temp_col = next((column for column in candidates if column in df.columns), None)
    if temp_col is None:
        raise ValueError(f"{summary_csv} does not contain one of these temperature columns: {candidates}")
    result = pd.DataFrame(
        {
            "hit": df["hit"] if "hit" in df.columns else np.arange(len(df)),
            "source_file": df["source_file"] if "source_file" in df.columns else "",
            "hit_temperature_c": pd.to_numeric(df[temp_col], errors="coerce"),
        }
    )
    if "contact_time_s" in df.columns:
        result["contact_time_s"] = pd.to_numeric(df["contact_time_s"], errors="coerce")
    return result


def normalize_hit_temperature_table(hit_temperatures: pd.DataFrame, config: InductionHeatingConfig) -> pd.DataFrame:
    """Sort and annotate hit temperatures with process-window flags."""
    data = hit_temperatures.copy()
    if "hit" not in data.columns:
        data["hit"] = np.arange(len(data))
    data["hit_temperature_c"] = pd.to_numeric(data["hit_temperature_c"], errors="coerce")
    data = data.dropna(subset=["hit_temperature_c"]).reset_index(drop=True)
    data["hit_sort"] = pd.to_numeric(data["hit"], errors="coerce")
    data = data.sort_values(["hit_sort", "source_file"], na_position="last").reset_index(drop=True)
    data["hit_order"] = np.arange(len(data))
    data["in_process_window"] = data["hit_temperature_c"].between(config.lower_temp_c, config.upper_temp_c)
    data["below_process_window"] = data["hit_temperature_c"] < config.lower_temp_c
    data["above_process_window"] = data["hit_temperature_c"] > config.upper_temp_c
    data["delta_from_previous_hit_c"] = data["hit_temperature_c"].diff()
    return data


def infer_induction_heating_events(
    hit_temperatures: pd.DataFrame,
    config: InductionHeatingConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Infer heat and reheat events from hit temperature sequence."""
    config = config or InductionHeatingConfig()
    hits = normalize_hit_temperature_table(hit_temperatures, config)
    events = []
    if hits.empty:
        return hits, pd.DataFrame()

    first = hits.iloc[0]
    heat_time_s = estimate_heat_time(config.room_temp_c, first["hit_temperature_c"], config)
    first_contact_global_s = float(first.get("global_contact_s", np.nan))
    first_start_global_s = float(first.get("global_start_s", np.nan))
    events.append(
        {
            "event_id": 1,
            "event_type": "initial_heat",
            "before_hit": "",
            "after_hit": first["hit"],
            "start_temp_c": config.room_temp_c,
            "end_temp_c": float(first["hit_temperature_c"]),
            "delta_temp_c": float(first["hit_temperature_c"] - config.room_temp_c),
            "estimated_heat_time_s": heat_time_s,
            "global_window_start_s": float("nan"),
            "global_window_end_s": first_contact_global_s,
            "global_elapsed_to_next_hit_start_s": float("nan"),
            "global_elapsed_to_next_contact_s": float("nan"),
            "apparent_heating_rate_to_next_hit_start_c_per_s": float("nan"),
            "apparent_heating_rate_to_next_contact_c_per_s": float("nan"),
            "reason": "Initial workpiece starts at room temperature.",
        }
    )

    event_id = 2
    for index in range(1, len(hits)):
        previous = hits.iloc[index - 1]
        current = hits.iloc[index]
        delta = float(current["hit_temperature_c"] - previous["hit_temperature_c"])
        previous_below = bool(previous["below_process_window"])
        current_increase = delta >= config.reheat_delta_c
        if previous_below or current_increase:
            reason = []
            if previous_below:
                reason.append("previous hit was below process window")
            if current_increase:
                reason.append(f"temperature increased by at least {config.reheat_delta_c:g} C")
            previous_end_s = float(previous.get("global_end_s", np.nan))
            current_start_s = float(current.get("global_start_s", np.nan))
            current_contact_s = float(current.get("global_contact_s", np.nan))
            elapsed_to_start = (
                float(current_start_s - previous_end_s)
                if np.isfinite(current_start_s) and np.isfinite(previous_end_s)
                else float("nan")
            )
            elapsed_to_contact = (
                float(current_contact_s - previous_end_s)
                if np.isfinite(current_contact_s) and np.isfinite(previous_end_s)
                else float("nan")
            )
            events.append(
                {
                    "event_id": event_id,
                    "event_type": "reheat",
                    "before_hit": previous["hit"],
                    "after_hit": current["hit"],
                    "start_temp_c": float(previous["hit_temperature_c"]),
                    "end_temp_c": float(current["hit_temperature_c"]),
                    "delta_temp_c": delta,
                    "estimated_heat_time_s": estimate_heat_time(previous["hit_temperature_c"], current["hit_temperature_c"], config),
                    "global_window_start_s": previous_end_s,
                    "global_window_end_s": current_contact_s,
                    "global_elapsed_to_next_hit_start_s": elapsed_to_start,
                    "global_elapsed_to_next_contact_s": elapsed_to_contact,
                    "apparent_heating_rate_to_next_hit_start_c_per_s": (
                        delta / elapsed_to_start if np.isfinite(elapsed_to_start) and elapsed_to_start > 0 else float("nan")
                    ),
                    "apparent_heating_rate_to_next_contact_c_per_s": (
                        delta / elapsed_to_contact if np.isfinite(elapsed_to_contact) and elapsed_to_contact > 0 else float("nan")
                    ),
                    "reason": "; ".join(reason),
                }
            )
            event_id += 1

    cold_hits = hits[hits["below_process_window"]]
    for _, row in cold_hits.iterrows():
        row_end_s = float(row.get("global_end_s", np.nan))
        events.append(
            {
                "event_id": event_id,
                "event_type": "reheat_required",
                "before_hit": row["hit"],
                "after_hit": row["hit"],
                "start_temp_c": float(row["hit_temperature_c"]),
                "end_temp_c": config.target_reheat_temp_c,
                "delta_temp_c": float(config.target_reheat_temp_c - row["hit_temperature_c"]),
                "estimated_heat_time_s": estimate_heat_time(row["hit_temperature_c"], config.target_reheat_temp_c, config),
                "global_window_start_s": row_end_s,
                "global_window_end_s": float("nan"),
                "global_elapsed_to_next_hit_start_s": float("nan"),
                "global_elapsed_to_next_contact_s": float("nan"),
                "apparent_heating_rate_to_next_hit_start_c_per_s": float("nan"),
                "apparent_heating_rate_to_next_contact_c_per_s": float("nan"),
                "reason": f"reported hit temperature was below {config.lower_temp_c:g} C.",
            }
        )
        event_id += 1

    events_df = pd.DataFrame(events)
    return hits, events_df


def estimate_heat_time(start_temp_c: float, end_temp_c: float, config: InductionHeatingConfig) -> float:
    """Estimate heat time when a heating rate is supplied."""
    if config.heating_rate_c_per_s is None or config.heating_rate_c_per_s <= 0:
        return float("nan")
    return max(0.0, float(end_temp_c - start_temp_c) / float(config.heating_rate_c_per_s))


def estimate_quench_time(start_temp_c: float, end_temp_c: float, config: InductionHeatingConfig) -> float:
    """Estimate quench duration from a rate or fixed duration."""
    if config.quench_rate_c_per_s is not None and config.quench_rate_c_per_s > 0:
        return max(0.0, abs(float(start_temp_c - end_temp_c)) / float(config.quench_rate_c_per_s))
    return max(float(config.quench_duration_s), 1e-6)


def effective_heat_duration(start_temp_c: float, end_temp_c: float, config: InductionHeatingConfig) -> float:
    """Return a positive duration for plotting inferred heating ramps."""
    estimated = estimate_heat_time(start_temp_c, end_temp_c, config)
    if np.isfinite(estimated) and estimated > 0:
        return float(estimated)
    return max(float(config.inferred_heat_duration_s), 1e-6)


def apply_initial_heat_duration_from_reheats(
    events: pd.DataFrame,
    config: InductionHeatingConfig,
) -> pd.DataFrame:
    """Use measured reheat rates to infer the initial room-to-hit-0 heat ramp."""
    if events.empty or not config.infer_initial_heat_from_reheats:
        return events
    output = events.copy()
    initial_mask = output["event_type"] == "initial_heat"
    if not initial_mask.any():
        return output
    rate = pd.to_numeric(output.get("apparent_heating_rate_to_next_contact_c_per_s"), errors="coerce")
    rate = rate[(output["event_type"] == "reheat") & np.isfinite(rate) & (rate > 0)]
    if rate.empty:
        return output
    initial_index = output[initial_mask].index[0]
    delta_temp = float(output.at[initial_index, "delta_temp_c"])
    inferred_rate = float(rate.mean())
    inferred_duration = delta_temp / inferred_rate if inferred_rate > 0 else float("nan")
    output.at[initial_index, "estimated_heat_time_s"] = inferred_duration
    output.at[initial_index, "apparent_heating_rate_to_next_contact_c_per_s"] = inferred_rate
    output.at[initial_index, "apparent_heating_rate_to_next_hit_start_c_per_s"] = inferred_rate
    end_global = float(output.at[initial_index, "global_window_end_s"])
    if np.isfinite(end_global) and np.isfinite(inferred_duration):
        output.at[initial_index, "global_window_start_s"] = end_global - inferred_duration
        output.at[initial_index, "global_elapsed_to_next_contact_s"] = inferred_duration
    output.at[initial_index, "reason"] = (
        str(output.at[initial_index, "reason"])
        + f" Initial heat duration inferred from mean measured reheat rate ({inferred_rate:.3g} C/s)."
    )
    return output


def append_quench_event(
    hits: pd.DataFrame,
    events: pd.DataFrame,
    config: InductionHeatingConfig,
) -> pd.DataFrame:
    """Append a post-hit quench event for microstructure thermal histories."""
    if hits.empty or not config.quench_after_hits:
        return events
    output = events.copy()
    last = hits.iloc[-1]
    start_temp = float(last["hit_temperature_c"])
    end_temp = float(config.room_temp_c)
    duration = estimate_quench_time(start_temp, end_temp, config)
    start_global = float(last.get("global_end_s", np.nan))
    end_global = start_global + duration if np.isfinite(start_global) else float("nan")
    next_id = int(pd.to_numeric(output["event_id"], errors="coerce").max() + 1) if not output.empty else 1
    row = {
        "event_id": next_id,
        "event_type": "quench",
        "before_hit": last["hit"],
        "after_hit": "",
        "start_temp_c": start_temp,
        "end_temp_c": end_temp,
        "delta_temp_c": end_temp - start_temp,
        "estimated_heat_time_s": float("nan"),
        "global_window_start_s": start_global,
        "global_window_end_s": end_global,
        "global_elapsed_to_next_hit_start_s": float("nan"),
        "global_elapsed_to_next_contact_s": duration,
        "apparent_heating_rate_to_next_hit_start_c_per_s": float("nan"),
        "apparent_heating_rate_to_next_contact_c_per_s": float("nan"),
        "apparent_quench_rate_c_per_s": abs(start_temp - end_temp) / duration if duration > 0 else float("nan"),
        "reason": "Assumed quench after final hit for microstructure thermal history.",
    }
    return pd.concat([output, pd.DataFrame([row])], ignore_index=True)


def build_temperature_time_trace(
    hits: pd.DataFrame,
    events: pd.DataFrame,
    hit_traces: pd.DataFrame | None = None,
    config: InductionHeatingConfig | None = None,
) -> pd.DataFrame:
    """Create a model timeline with inferred heat ramps and recorded hit points.

    AF hit files usually do not contain one continuous clock across the entire
    forging sequence. This trace therefore uses `hit_interval_s` as the process
    spacing between hits unless a future dataset supplies a global time axis.
    """
    config = config or InductionHeatingConfig()
    if hits.empty:
        return pd.DataFrame(columns=["time_s", "temperature_c", "trace_type", "hit", "event_id", "label"])
    hit_traces = hit_traces if hit_traces is not None else pd.DataFrame()
    if not hit_traces.empty and "global_time_s" in hit_traces.columns:
        global_values = pd.to_numeric(hit_traces["global_time_s"], errors="coerce")
        if global_values.notna().any():
            return build_global_temperature_time_trace(hits, events, hit_traces, config=config)

    event_lookup = {}
    if not events.empty:
        for _, event in events[events["event_type"].isin(["initial_heat", "reheat"])].iterrows():
            event_lookup[str(event["after_hit"])] = event

    rows = [{"time_s": 0.0, "temperature_c": config.room_temp_c, "trace_type": "room_start", "hit": "", "event_id": "", "label": "room"}]
    current_time = 0.0
    current_temp = config.room_temp_c

    for _, hit in hits.iterrows():
        hit_label = str(hit["hit"])
        event = event_lookup.get(hit_label)
        if event is not None:
            heat_duration = effective_heat_duration(float(event["start_temp_c"]), float(event["end_temp_c"]), config)
            rows.append(
                {
                    "time_s": current_time,
                    "temperature_c": float(event["start_temp_c"]),
                    "trace_type": "heat_start",
                    "hit": hit_label,
                    "event_id": event["event_id"],
                    "label": event["event_type"],
                }
            )
            current_time += heat_duration
            current_temp = float(event["end_temp_c"])
            rows.append(
                {
                    "time_s": current_time,
                    "temperature_c": current_temp,
                    "trace_type": "heat_end",
                    "hit": hit_label,
                    "event_id": event["event_id"],
                    "label": event["event_type"],
                }
            )

        if rows and current_time <= float(rows[-1]["time_s"]):
            current_time = float(rows[-1]["time_s"]) + 1e-6
        hit_start_time = current_time
        matching_trace = (
            hit_traces[hit_traces["hit"].astype(str) == hit_label].copy()
            if not hit_traces.empty and "hit" in hit_traces.columns
            else pd.DataFrame()
        )
        if not matching_trace.empty:
            matching_trace["local_time_s"] = pd.to_numeric(matching_trace["local_time_s"], errors="coerce")
            matching_trace["temperature_c"] = pd.to_numeric(matching_trace["temperature_c"], errors="coerce")
            matching_trace = matching_trace.dropna(subset=["local_time_s", "temperature_c"])
            for _, trace_row in matching_trace.iterrows():
                rows.append(
                    {
                        "time_s": hit_start_time + float(trace_row["local_time_s"]),
                        "temperature_c": float(trace_row["temperature_c"]),
                        "trace_type": "hit_trace",
                        "hit": hit_label,
                        "event_id": event["event_id"] if event is not None else "",
                        "label": f"hit {hit_label} trace",
                    }
                )

        recorded_temp = float(hit["hit_temperature_c"])
        contact_offset = 0.0
        if not matching_trace.empty and "contact_time_s" in matching_trace.columns:
            contact_offset_values = pd.to_numeric(matching_trace["contact_time_s"], errors="coerce").dropna()
            if not contact_offset_values.empty:
                contact_offset = max(0.0, float(contact_offset_values.iloc[0]))
        recorded_time = hit_start_time + contact_offset
        rows.append(
            {
                "time_s": recorded_time,
                "temperature_c": recorded_temp,
                "trace_type": "recorded_hit",
                "hit": hit_label,
                "event_id": event["event_id"] if event is not None else "",
                "label": f"hit {hit_label}",
            }
        )
        current_temp = recorded_temp
        trace_duration = 0.0
        if not matching_trace.empty:
            trace_duration = float(pd.to_numeric(matching_trace["local_time_s"], errors="coerce").max())
        current_time = hit_start_time + max(float(config.hit_interval_s), trace_duration, 1e-6)

    timeline = pd.DataFrame(rows)
    timeline = timeline.sort_values(["time_s", "trace_type"]).reset_index(drop=True)
    min_time = float(pd.to_numeric(timeline["time_s"], errors="coerce").min())
    if np.isfinite(min_time) and min_time < 0:
        timeline["time_s"] = pd.to_numeric(timeline["time_s"], errors="coerce") - min_time
    return timeline


def build_global_temperature_time_trace(
    hits: pd.DataFrame,
    events: pd.DataFrame,
    hit_traces: pd.DataFrame,
    config: InductionHeatingConfig | None = None,
) -> pd.DataFrame:
    """Create a temperature timeline using global Unix timestamps from raw hits."""
    config = config or InductionHeatingConfig()
    global_trace_time = pd.to_numeric(hit_traces["global_time_s"], errors="coerce")
    global_hit_times = pd.to_numeric(hits.get("global_start_s", pd.Series(dtype=float)), errors="coerce")
    event_times = pd.Series(dtype=float)
    if not events.empty:
        event_times = pd.concat(
            [
                pd.to_numeric(events.get("global_window_start_s", pd.Series(dtype=float)), errors="coerce"),
                pd.to_numeric(events.get("global_window_end_s", pd.Series(dtype=float)), errors="coerce"),
            ],
            ignore_index=True,
        )
    min_candidates = pd.concat([global_trace_time.dropna(), global_hit_times.dropna(), event_times.dropna()], ignore_index=True)
    if min_candidates.empty:
        return pd.DataFrame(columns=["time_s", "temperature_c", "trace_type", "hit", "event_id", "label"])
    t0 = float(min_candidates.min())
    rows = []

    for _, event in events.iterrows() if not events.empty else []:
        if event["event_type"] not in {"initial_heat", "reheat", "quench"}:
            continue
        end_global = float(event.get("global_window_end_s", np.nan))
        start_global = float(event.get("global_window_start_s", np.nan))
        if not np.isfinite(end_global):
            continue
        if not np.isfinite(start_global):
            start_global = end_global - effective_heat_duration(float(event["start_temp_c"]), float(event["end_temp_c"]), config)
        trace_prefix = "quench" if event["event_type"] == "quench" else "heat"
        hit_label = str(event["after_hit"]) if str(event.get("after_hit", "")).strip() else str(event.get("before_hit", ""))
        rows.append(
            {
                "time_s": start_global - t0,
                "temperature_c": float(event["start_temp_c"]),
                "trace_type": f"{trace_prefix}_start",
                "hit": hit_label,
                "event_id": event["event_id"],
                "label": event["event_type"],
            }
        )
        rows.append(
            {
                "time_s": end_global - t0,
                "temperature_c": float(event["end_temp_c"]),
                "trace_type": f"{trace_prefix}_end",
                "hit": hit_label,
                "event_id": event["event_id"],
                "label": event["event_type"],
            }
        )

    traces = hit_traces.copy()
    traces["global_time_s"] = pd.to_numeric(traces["global_time_s"], errors="coerce")
    traces["temperature_c"] = pd.to_numeric(traces["temperature_c"], errors="coerce")
    traces = traces.dropna(subset=["global_time_s", "temperature_c"])
    for _, row in traces.iterrows():
        rows.append(
            {
                "time_s": float(row["global_time_s"] - t0),
                "temperature_c": float(row["temperature_c"]),
                "trace_type": "hit_trace",
                "hit": str(row["hit"]),
                "event_id": "",
                "label": f"hit {row['hit']} trace",
            }
        )

    for _, hit in hits.iterrows():
        contact_global = float(hit.get("global_contact_s", np.nan))
        if not np.isfinite(contact_global):
            continue
        event_id = ""
        if not events.empty:
            match = events[
                events["event_type"].isin(["initial_heat", "reheat"])
                & (events["after_hit"].astype(str) == str(hit["hit"]))
            ]
            if not match.empty:
                event_id = match.iloc[0]["event_id"]
        rows.append(
            {
                "time_s": contact_global - t0,
                "temperature_c": float(hit["hit_temperature_c"]),
                "trace_type": "recorded_hit",
                "hit": str(hit["hit"]),
                "event_id": event_id,
                "label": f"hit {hit['hit']}",
            }
        )

    timeline = pd.DataFrame(rows)
    if timeline.empty:
        return timeline
    return timeline.sort_values(["time_s", "trace_type"]).reset_index(drop=True)


def bounds(values: np.ndarray, low_pad: float = 40.0, high_pad: float = 40.0) -> tuple[float, float]:
    """Return padded finite bounds for a plot axis."""
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return 0.0, 1.0
    low = float(np.min(finite)) - low_pad
    high = float(np.max(finite)) + high_pad
    if low == high:
        return low - 1.0, high + 1.0
    return low, high


def scale_xy(x: float, y: float, x_bounds: tuple[float, float], y_bounds: tuple[float, float]) -> tuple[int, int]:
    """Scale data coordinates to image coordinates."""
    left = MARGIN_LEFT
    right = PLOT_WIDTH - MARGIN_RIGHT
    top = MARGIN_TOP
    bottom = PLOT_HEIGHT - MARGIN_BOTTOM
    xp = left + (x - x_bounds[0]) / max(x_bounds[1] - x_bounds[0], 1e-9) * (right - left)
    yp = bottom - (y - y_bounds[0]) / max(y_bounds[1] - y_bounds[0], 1e-9) * (bottom - top)
    return int(round(xp)), int(round(yp))


def save_induction_heating_plot(
    hits: pd.DataFrame,
    events: pd.DataFrame,
    output_png: str | Path,
    config: InductionHeatingConfig | None = None,
) -> Path:
    """Save a plot showing hit temperatures, process window, and inferred reheats."""
    config = config or InductionHeatingConfig()
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (PLOT_WIDTH, PLOT_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(28)
    label_font = load_font(18)
    tick_font = load_font(14)
    small_font = load_font(13)

    x = hits["hit_order"].to_numpy(dtype=float)
    y = hits["hit_temperature_c"].to_numpy(dtype=float)
    x_bounds = (-0.6, max(1.0, float(len(hits) - 1) + 0.6))
    y_low = min(config.lower_temp_c, float(np.nanmin(y)), config.room_temp_c)
    y_high = max(config.upper_temp_c, float(np.nanmax(y)), config.target_reheat_temp_c)
    y_bounds = bounds(np.asarray([y_low, y_high], dtype=float), low_pad=50.0, high_pad=50.0)

    left = MARGIN_LEFT
    right = PLOT_WIDTH - MARGIN_RIGHT
    top = MARGIN_TOP
    bottom = PLOT_HEIGHT - MARGIN_BOTTOM

    draw.text((MARGIN_LEFT, 26), "Inferred Induction Heating Schedule", fill=COLOR_TEXT, font=title_font)
    draw.text((PLOT_WIDTH // 2 - 80, PLOT_HEIGHT - 42), "Hit order", fill=COLOR_TEXT, font=label_font)
    draw.text((18, PLOT_HEIGHT // 2 - 18), "Temp C", fill=COLOR_TEXT, font=label_font)

    window_top = scale_xy(0, config.upper_temp_c, x_bounds, y_bounds)[1]
    window_bottom = scale_xy(0, config.lower_temp_c, x_bounds, y_bounds)[1]
    draw.rectangle((left, window_top, right, window_bottom), fill=COLOR_WINDOW)
    draw.text((right - 190, window_top + 8), f"Process window {config.lower_temp_c:g}-{config.upper_temp_c:g} C", fill=(35, 118, 76), font=small_font)

    for step in range(6):
        fraction = step / 5.0
        gx = int(left + fraction * (right - left))
        gy = int(top + fraction * (bottom - top))
        draw.line((gx, top, gx, bottom), fill=COLOR_GRID)
        draw.line((left, gy, right, gy), fill=COLOR_GRID)
        x_value = x_bounds[0] + fraction * (x_bounds[1] - x_bounds[0])
        y_value = y_bounds[0] + fraction * (y_bounds[1] - y_bounds[0])
        draw.text((gx - 12, bottom + 12), f"{x_value:.0f}", fill=COLOR_GRAY, font=tick_font)
        draw.text((left - 72, gy - 8), f"{y_value:.0f}", fill=COLOR_GRAY, font=tick_font)
    draw.rectangle((left, top, right, bottom), outline=(156, 163, 175), width=2)

    points = [scale_xy(float(xi), float(yi), x_bounds, y_bounds) for xi, yi in zip(x, y)]
    if len(points) > 1:
        draw.line(points, fill=COLOR_TEMP, width=4)
    for _, row in hits.iterrows():
        px, py = scale_xy(float(row["hit_order"]), float(row["hit_temperature_c"]), x_bounds, y_bounds)
        fill = COLOR_TEMP
        if bool(row["below_process_window"]) or bool(row["above_process_window"]):
            fill = COLOR_WARN
        draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=fill, outline="white", width=2)
        draw.text((px - 10, py - 30), str(row["hit"]), fill=COLOR_TEXT, font=small_font)

    reheat_events = events[events["event_type"].isin(["initial_heat", "reheat"])] if not events.empty else pd.DataFrame()
    for _, event in reheat_events.iterrows():
        after_hit = event["after_hit"]
        matching = hits[hits["hit"].astype(str) == str(after_hit)]
        if matching.empty:
            continue
        row = matching.iloc[0]
        px, py = scale_xy(float(row["hit_order"]), float(row["hit_temperature_c"]), x_bounds, y_bounds)
        draw.line((px, bottom, px, py + 12), fill=COLOR_HEAT, width=3)
        draw.polygon([(px, py - 12), (px - 8, py + 3), (px + 8, py + 3)], fill=COLOR_HEAT)
        draw.text((px + 8, bottom - 28), "heat", fill=COLOR_HEAT, font=small_font)

    warnings = hits[hits["below_process_window"] | hits["above_process_window"]]
    if not warnings.empty:
        draw.rectangle((MARGIN_LEFT + 12, MARGIN_TOP + 12, MARGIN_LEFT + 450, MARGIN_TOP + 82), fill="white", outline=(203, 213, 225))
        draw.text((MARGIN_LEFT + 24, MARGIN_TOP + 24), f"{len(warnings)} hit(s) outside process window", fill=COLOR_WARN, font=label_font)
        draw.text((MARGIN_LEFT + 24, MARGIN_TOP + 52), "Check these before interpreting microstructure.", fill=COLOR_GRAY, font=small_font)

    legend_x = right - 210
    legend_y = top + 92
    draw.rectangle((legend_x - 12, legend_y - 12, right - 8, legend_y + 92), fill="white", outline=(203, 213, 225))
    draw.line((legend_x, legend_y + 8, legend_x + 30, legend_y + 8), fill=COLOR_TEMP, width=4)
    draw.text((legend_x + 40, legend_y), "hit temperature", fill=COLOR_TEXT, font=small_font)
    draw.line((legend_x, legend_y + 35, legend_x + 30, legend_y + 35), fill=COLOR_HEAT, width=4)
    draw.text((legend_x + 40, legend_y + 27), "inferred heat", fill=COLOR_TEXT, font=small_font)
    draw.rectangle((legend_x, legend_y + 56, legend_x + 30, legend_y + 74), fill=COLOR_WINDOW)
    draw.text((legend_x + 40, legend_y + 55), "target range", fill=COLOR_TEXT, font=small_font)

    image.save(output_png)
    return output_png


def save_heat_events_plot(
    events: pd.DataFrame,
    output_png: str | Path,
) -> Path:
    """Save a bar plot of inferred heat and reheat temperature increases."""
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    heat_events = events[events["event_type"].isin(["initial_heat", "reheat"])].copy() if not events.empty else pd.DataFrame()

    image = Image.new("RGB", (PLOT_WIDTH, PLOT_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(28)
    label_font = load_font(18)
    tick_font = load_font(14)
    small_font = load_font(13)
    draw.text((MARGIN_LEFT, 26), "Inferred Induction Heat Events", fill=COLOR_TEXT, font=title_font)
    draw.text((PLOT_WIDTH // 2 - 120, PLOT_HEIGHT - 42), "Heat event", fill=COLOR_TEXT, font=label_font)
    draw.text((18, PLOT_HEIGHT // 2 - 26), "Delta C", fill=COLOR_TEXT, font=label_font)

    left = MARGIN_LEFT
    right = PLOT_WIDTH - MARGIN_RIGHT
    top = MARGIN_TOP
    bottom = PLOT_HEIGHT - MARGIN_BOTTOM
    if heat_events.empty:
        draw.text((MARGIN_LEFT, MARGIN_TOP + 40), "No inferred heat events.", fill=COLOR_GRAY, font=label_font)
        image.save(output_png)
        return output_png

    values = pd.to_numeric(heat_events["delta_temp_c"], errors="coerce").to_numpy(dtype=float)
    finite_values = values[np.isfinite(values)]
    if len(finite_values) == 0:
        y_bounds = (0.0, 1.0)
    else:
        low = min(0.0, float(np.nanmin(finite_values)))
        high = max(0.0, float(np.nanmax(finite_values)))
        if low == high:
            low -= 1.0
            high += 1.0
        pad = 0.12 * (high - low)
        y_bounds = (low - pad, high + pad)
    zero_y = bottom - (0.0 - y_bounds[0]) / max(y_bounds[1] - y_bounds[0], 1e-9) * (bottom - top)
    for step in range(6):
        fraction = step / 5.0
        gy = int(bottom - fraction * (bottom - top))
        value = y_bounds[0] + fraction * (y_bounds[1] - y_bounds[0])
        draw.line((left, gy, right, gy), fill=COLOR_GRID)
        draw.text((left - 72, gy - 8), f"{value:.0f}", fill=COLOR_GRAY, font=tick_font)
    draw.rectangle((left, top, right, bottom), outline=(156, 163, 175), width=2)

    bar_count = len(heat_events)
    slot = (right - left) / max(bar_count, 1)
    bar_width = min(82, max(22, slot * 0.52))
    for index, (_, event) in enumerate(heat_events.iterrows()):
        value = float(event["delta_temp_c"])
        x_center = left + slot * (index + 0.5)
        y_value = bottom - (value - y_bounds[0]) / max(y_bounds[1] - y_bounds[0], 1e-9) * (bottom - top)
        color = COLOR_HEAT if event["event_type"] == "reheat" else COLOR_TEMP
        y0 = min(y_value, zero_y)
        y1 = max(y_value, zero_y)
        draw.rectangle((x_center - bar_width / 2, y0, x_center + bar_width / 2, y1), fill=color)
        label_y = y0 - 24 if value >= 0 else y1 + 4
        draw.text((x_center - 20, label_y), f"{value:.0f}", fill=COLOR_TEXT, font=small_font)
        label = f"H{event['after_hit']}"
        draw.text((x_center - 18, bottom + 12), label, fill=COLOR_TEXT, font=small_font)

    draw.rectangle((right - 250, top + 14, right - 10, top + 82), fill="white", outline=(203, 213, 225))
    draw.text((right - 236, top + 28), "H# = hit after heating", fill=COLOR_TEXT, font=small_font)
    draw.text((right - 236, top + 52), f"{len(heat_events)} heat events", fill=COLOR_GRAY, font=small_font)
    image.save(output_png)
    return output_png


def save_heat_duration_plot(
    events: pd.DataFrame,
    output_png: str | Path,
) -> Path:
    """Save measured global-time reheat windows from previous hit end."""
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    reheats = events[events["event_type"] == "reheat"].copy() if not events.empty else pd.DataFrame()

    image = Image.new("RGB", (PLOT_WIDTH, PLOT_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(28)
    label_font = load_font(18)
    tick_font = load_font(14)
    small_font = load_font(13)
    draw.text((MARGIN_LEFT, 26), "Measured Reheat Windows from Global Timestamps", fill=COLOR_TEXT, font=title_font)
    draw.text((PLOT_WIDTH // 2 - 130, PLOT_HEIGHT - 42), "Reheat before hit", fill=COLOR_TEXT, font=label_font)
    draw.text((18, PLOT_HEIGHT // 2 - 20), "Time s", fill=COLOR_TEXT, font=label_font)

    left = MARGIN_LEFT
    right = PLOT_WIDTH - MARGIN_RIGHT
    top = MARGIN_TOP
    bottom = PLOT_HEIGHT - MARGIN_BOTTOM
    if reheats.empty:
        draw.text((MARGIN_LEFT, MARGIN_TOP + 40), "No measured reheat windows.", fill=COLOR_GRAY, font=label_font)
        image.save(output_png)
        return output_png

    start_values = pd.to_numeric(reheats["global_elapsed_to_next_hit_start_s"], errors="coerce").to_numpy(dtype=float)
    contact_values = pd.to_numeric(reheats["global_elapsed_to_next_contact_s"], errors="coerce").to_numpy(dtype=float)
    max_value = float(np.nanmax(np.concatenate([start_values, contact_values])))
    y_bounds = (0.0, max(max_value * 1.15, 1.0))
    for step in range(6):
        fraction = step / 5.0
        gy = int(bottom - fraction * (bottom - top))
        value = y_bounds[0] + fraction * (y_bounds[1] - y_bounds[0])
        draw.line((left, gy, right, gy), fill=COLOR_GRID)
        draw.text((left - 66, gy - 8), f"{value:.0f}", fill=COLOR_GRAY, font=tick_font)
    draw.rectangle((left, top, right, bottom), outline=(156, 163, 175), width=2)

    slot = (right - left) / max(len(reheats), 1)
    bar_width = min(34, max(12, slot * 0.22))
    for index, (_, event) in enumerate(reheats.iterrows()):
        x_center = left + slot * (index + 0.5)
        values = [
            (float(event["global_elapsed_to_next_hit_start_s"]), COLOR_HEAT, -bar_width * 0.65),
            (float(event["global_elapsed_to_next_contact_s"]), COLOR_TEMP, bar_width * 0.65),
        ]
        for value, color, offset in values:
            y_top = bottom - (value - y_bounds[0]) / max(y_bounds[1] - y_bounds[0], 1e-9) * (bottom - top)
            x0 = x_center + offset - bar_width / 2
            x1 = x_center + offset + bar_width / 2
            draw.rectangle((x0, y_top, x1, bottom), fill=color)
        draw.text((x_center - 18, bottom + 12), f"H{event['after_hit']}", fill=COLOR_TEXT, font=small_font)

    legend_x = right + 18
    legend_y = top + 20
    draw.rectangle((legend_x - 12, legend_y - 12, PLOT_WIDTH - 14, legend_y + 74), fill="white", outline=(203, 213, 225))
    draw.rectangle((legend_x, legend_y + 2, legend_x + 24, legend_y + 18), fill=COLOR_HEAT)
    draw.text((legend_x + 34, legend_y), "to next hit start", fill=COLOR_TEXT, font=small_font)
    draw.rectangle((legend_x, legend_y + 30, legend_x + 24, legend_y + 46), fill=COLOR_TEMP)
    draw.text((legend_x + 34, legend_y + 28), "to next contact", fill=COLOR_TEXT, font=small_font)
    image.save(output_png)
    return output_png


def save_temperature_vs_time_plot(
    timeline: pd.DataFrame,
    hits: pd.DataFrame,
    output_png: str | Path,
    config: InductionHeatingConfig | None = None,
) -> Path:
    """Save temperature versus modeled process time with hit points overlaid."""
    config = config or InductionHeatingConfig()
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (PLOT_WIDTH, PLOT_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(28)
    label_font = load_font(18)
    tick_font = load_font(14)
    small_font = load_font(13)
    draw.text((MARGIN_LEFT, 26), "Temperature vs Time with Inferred Induction Heating", fill=COLOR_TEXT, font=title_font)
    draw.text((PLOT_WIDTH // 2 - 80, PLOT_HEIGHT - 42), "Modeled time s", fill=COLOR_TEXT, font=label_font)
    draw.text((18, PLOT_HEIGHT // 2 - 18), "Temp C", fill=COLOR_TEXT, font=label_font)

    left = MARGIN_LEFT
    right = PLOT_WIDTH - MARGIN_RIGHT
    top = MARGIN_TOP
    bottom = PLOT_HEIGHT - MARGIN_BOTTOM
    if timeline.empty:
        draw.text((MARGIN_LEFT, MARGIN_TOP + 40), "No timeline data.", fill=COLOR_GRAY, font=label_font)
        image.save(output_png)
        return output_png

    x = pd.to_numeric(timeline["time_s"], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(timeline["temperature_c"], errors="coerce").to_numpy(dtype=float)
    x_bounds = (0.0, max(float(np.nanmax(x)) * 1.03, 1.0))
    y_low = min(config.lower_temp_c, float(np.nanmin(y)), config.room_temp_c)
    y_high = max(config.upper_temp_c, float(np.nanmax(y)), config.target_reheat_temp_c)
    y_bounds = bounds(np.asarray([y_low, y_high], dtype=float), low_pad=50.0, high_pad=50.0)

    window_top = scale_xy(0, config.upper_temp_c, x_bounds, y_bounds)[1]
    window_bottom = scale_xy(0, config.lower_temp_c, x_bounds, y_bounds)[1]
    draw.rectangle((left, window_top, right, window_bottom), fill=COLOR_WINDOW)
    for step in range(6):
        fraction = step / 5.0
        gx = int(left + fraction * (right - left))
        gy = int(bottom - fraction * (bottom - top))
        x_value = x_bounds[0] + fraction * (x_bounds[1] - x_bounds[0])
        y_value = y_bounds[0] + fraction * (y_bounds[1] - y_bounds[0])
        draw.line((gx, top, gx, bottom), fill=COLOR_GRID)
        draw.line((left, gy, right, gy), fill=COLOR_GRID)
        draw.text((gx - 18, bottom + 12), f"{x_value:.1f}", fill=COLOR_GRAY, font=tick_font)
        draw.text((left - 72, gy - 8), f"{y_value:.0f}", fill=COLOR_GRAY, font=tick_font)
    draw.rectangle((left, top, right, bottom), outline=(156, 163, 175), width=2)

    points = [scale_xy(float(xi), float(yi), x_bounds, y_bounds) for xi, yi in zip(x, y)]
    for index in range(1, len(points)):
        prev_type = str(timeline.iloc[index - 1]["trace_type"])
        this_type = str(timeline.iloc[index]["trace_type"])
        if "quench" in prev_type or "quench" in this_type:
            color = COLOR_QUENCH
            width = 4
        elif "heat" in prev_type or "heat" in this_type:
            color = COLOR_HEAT
            width = 4
        elif prev_type == "hit_trace" and this_type == "hit_trace":
            color = COLOR_TRACE
            width = 2
        else:
            color = COLOR_GRAY
            width = 1
        draw.line((*points[index - 1], *points[index]), fill=color, width=width)

    hit_rows = timeline[timeline["trace_type"] == "recorded_hit"]
    for _, row in hit_rows.iterrows():
        px, py = scale_xy(float(row["time_s"]), float(row["temperature_c"]), x_bounds, y_bounds)
        hit_match = hits[hits["hit"].astype(str) == str(row["hit"])]
        color = COLOR_TEMP
        if not hit_match.empty and (bool(hit_match.iloc[0]["below_process_window"]) or bool(hit_match.iloc[0]["above_process_window"])):
            color = COLOR_WARN
        draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=color, outline="white", width=2)
        draw.text((px - 8, py - 28), str(row["hit"]), fill=COLOR_TEXT, font=small_font)

    legend_x = right + 18
    legend_y = top + 20
    legend_right = PLOT_WIDTH - 14
    draw.rectangle((legend_x - 12, legend_y - 12, legend_right, legend_y + 166), fill="white", outline=(203, 213, 225))
    draw.line((legend_x, legend_y + 8, legend_x + 30, legend_y + 8), fill=COLOR_HEAT, width=4)
    draw.text((legend_x + 40, legend_y), "inferred heating ramp", fill=COLOR_TEXT, font=small_font)
    draw.line((legend_x, legend_y + 35, legend_x + 30, legend_y + 35), fill=COLOR_TRACE, width=3)
    draw.text((legend_x + 40, legend_y + 27), "within-hit temp trace", fill=COLOR_TEXT, font=small_font)
    draw.line((legend_x, legend_y + 62, legend_x + 30, legend_y + 62), fill=COLOR_QUENCH, width=4)
    draw.text((legend_x + 40, legend_y + 54), "assumed quench", fill=COLOR_TEXT, font=small_font)
    draw.ellipse((legend_x, legend_y + 82, legend_x + 16, legend_y + 98), fill=COLOR_TEMP, outline="white", width=2)
    draw.text((legend_x + 40, legend_y + 80), "contact temp marker", fill=COLOR_TEXT, font=small_font)
    draw.rectangle((legend_x, legend_y + 110, legend_x + 30, legend_y + 128), fill=COLOR_WINDOW)
    draw.text((legend_x + 40, legend_y + 109), "800-1200 C window", fill=COLOR_TEXT, font=small_font)
    draw.text((legend_x, legend_y + 142), f"hit interval = {config.hit_interval_s:g} s", fill=COLOR_GRAY, font=small_font)

    image.save(output_png)
    return output_png


def run_induction_heating_analysis(
    raw_af_data_dir: str | Path | None = None,
    summary_csv: str | Path | None = None,
    output_dir: str | Path = "induction_heating_output",
    hit_glob: str = "*.csv",
    config: InductionHeatingConfig | None = None,
) -> dict[str, str]:
    """Run the full induction-heating inference and plotting workflow."""
    config = config or InductionHeatingConfig()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    hit_traces = pd.DataFrame()
    if summary_csv:
        hit_temperatures = load_hit_temperatures_from_summary(summary_csv)
    elif raw_af_data_dir:
        hit_temperatures = load_hit_temperatures_from_raw_folder(raw_af_data_dir, hit_glob=hit_glob)
        hit_traces = load_hit_temperature_traces_from_raw_folder(raw_af_data_dir, hit_glob=hit_glob)
    else:
        raise ValueError("Provide either raw_af_data_dir or summary_csv.")

    hits, events = infer_induction_heating_events(hit_temperatures, config=config)
    events = apply_initial_heat_duration_from_reheats(events, config=config)
    events = append_quench_event(hits, events, config=config)
    hits_csv = output_dir / "induction_heating_hit_temperatures.csv"
    events_csv = output_dir / "induction_heating_events.csv"
    plot_png = output_dir / "induction_heating_schedule.png"
    events_plot_png = output_dir / "induction_heating_events_plot.png"
    duration_plot_png = output_dir / "induction_heating_reheat_durations.png"
    time_plot_png = output_dir / "induction_heating_temperature_vs_time.png"
    timeline_csv = output_dir / "induction_heating_temperature_time_trace.csv"
    full_traces_csv = output_dir / "induction_heating_full_hit_temperature_traces.csv"
    config_json = output_dir / "induction_heating_config.json"
    summary_json = output_dir / "induction_heating_summary.json"

    hits.to_csv(hits_csv, index=False)
    events.to_csv(events_csv, index=False)
    if not hit_traces.empty:
        hit_traces.to_csv(full_traces_csv, index=False)
    timeline = build_temperature_time_trace(hits, events, hit_traces=hit_traces, config=config)
    timeline.to_csv(timeline_csv, index=False)
    save_induction_heating_plot(hits, events, plot_png, config=config)
    save_heat_events_plot(events, events_plot_png)
    save_heat_duration_plot(events, duration_plot_png)
    save_temperature_vs_time_plot(timeline, hits, time_plot_png, config=config)
    config_json.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    outputs = {
        "induction_heating_hit_temperatures": str(hits_csv),
        "induction_heating_events": str(events_csv),
        "induction_heating_plot": str(plot_png),
        "induction_heating_events_plot": str(events_plot_png),
        "induction_heating_reheat_duration_plot": str(duration_plot_png),
        "induction_heating_temperature_vs_time_plot": str(time_plot_png),
        "induction_heating_temperature_time_trace": str(timeline_csv),
        "induction_heating_full_hit_temperature_traces": str(full_traces_csv) if not hit_traces.empty else "",
        "induction_heating_config": str(config_json),
        "hit_count": str(len(hits)),
        "full_hit_trace_rows": str(len(hit_traces)),
        "inferred_heat_event_count": str(len(events[events["event_type"].isin(["initial_heat", "reheat"])])) if not events.empty else "0",
        "outside_window_hit_count": str(int((hits["below_process_window"] | hits["above_process_window"]).sum())) if not hits.empty else "0",
    }
    summary_json.write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    outputs["induction_heating_summary"] = str(summary_json)
    return outputs


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Infer AF induction heating/reheating events from hit temperatures.")
    parser.add_argument("--raw-af-data-dir", default=None, help="Folder containing raw AF hit CSV files.")
    parser.add_argument("--summary-csv", default=None, help="Existing AF summary/features CSV with hit temperatures.")
    parser.add_argument("--output-dir", required=True, help="Folder for induction-heating CSVs and plot.")
    parser.add_argument("--hit-glob", default="*.csv", help="Glob for raw AF hit files.")
    parser.add_argument("--lower-temp-c", type=float, default=800.0)
    parser.add_argument("--upper-temp-c", type=float, default=1200.0)
    parser.add_argument("--room-temp-c", type=float, default=25.0)
    parser.add_argument("--reheat-delta-c", type=float, default=25.0, help="Temperature rise between hits that indicates a reheat.")
    parser.add_argument("--target-reheat-temp-c", type=float, default=1100.0)
    parser.add_argument("--heating-rate-c-per-s", type=float, default=None, help="Optional rate for estimating heat duration.")
    parser.add_argument("--hit-interval-s", type=float, default=1.0, help="Modeled process-time spacing between recorded hits when no global clock is available.")
    parser.add_argument("--inferred-heat-duration-s", type=float, default=0.35, help="Plot duration assigned to inferred heat ramps when no heating rate is supplied.")
    parser.add_argument("--no-infer-initial-heat-from-reheats", action="store_true", help="Use the fallback initial heat duration instead of inferring it from later reheats.")
    parser.add_argument("--no-quench-after-hits", action="store_true", help="Do not append an assumed post-hit quench segment.")
    parser.add_argument("--quench-duration-s", type=float, default=2.0, help="Assumed quench duration when no quench rate is provided.")
    parser.add_argument("--quench-rate-c-per-s", type=float, default=None, help="Optional cooling rate used to estimate quench duration.")
    args = parser.parse_args()

    result = run_induction_heating_analysis(
        raw_af_data_dir=args.raw_af_data_dir,
        summary_csv=args.summary_csv,
        output_dir=args.output_dir,
        hit_glob=args.hit_glob,
        config=InductionHeatingConfig(
            lower_temp_c=args.lower_temp_c,
            upper_temp_c=args.upper_temp_c,
            room_temp_c=args.room_temp_c,
            reheat_delta_c=args.reheat_delta_c,
            target_reheat_temp_c=args.target_reheat_temp_c,
            heating_rate_c_per_s=args.heating_rate_c_per_s,
            hit_interval_s=args.hit_interval_s,
            inferred_heat_duration_s=args.inferred_heat_duration_s,
            infer_initial_heat_from_reheats=not args.no_infer_initial_heat_from_reheats,
            quench_after_hits=not args.no_quench_after_hits,
            quench_duration_s=args.quench_duration_s,
            quench_rate_c_per_s=args.quench_rate_c_per_s,
        ),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
