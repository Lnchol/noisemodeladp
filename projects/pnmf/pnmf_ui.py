"""PNMF local UI — form-based parametric-aircraft noise prediction and
real-vs-future comparison, on top of the existing pnmf public API.

Launched via `.\\pnmf.ps1 ui` (streamlit run pnmf_ui.py); fully offline.
The application includes aircraft design, learned prediction/results,
real-aircraft comparison, direct component physics, operations and fleet
inspection. Session state keeps the active prediction, physics diagnostics
and form inputs across Streamlit reruns.
"""
from __future__ import annotations

import io
import os
import re
import sqlite3
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")            # headless backend before any pyplot import
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from pnmf.api import NoisePredictor, real_vs_future_table, DEFAULT_MODEL
from pnmf.core import (ParametricAircraft, NPDTable,
                       STANDARD_DISTANCES_FT, ENGINE_TYPES,
                       fleet_input_envelope, evaluate_aircraft_inputs)
from pnmf.anp import DIST_COLS, ANPDatabase, qa_check, PredictionStore
from pnmf.operations import DepartureSynthesizer
from pnmf.models import rank_models
from pnmf.physics import (
    AirframePhysicalInputs,
    AtmosphericPhysicalInputs,
    EnginePhysicalInputs,
    InputStatus,
    PhysicalInput,
    PhysicsDesign,
)
from pnmf.physics_presets import PHYSICS_PRESETS

PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)
DB_PATH = str(PROJECT_ROOT / "anp_data.sqlite")
MODELS = ["et", "rf"]


def _render_calculation_log(slot, record):
    """Render a compact operation trace in a stable placeholder."""
    with slot.container():
        state = record.get("state", "running")
        marker = {"running": "running", "complete": "complete",
                  "error": "failed"}.get(state, state)
        st.caption(f"Calculation log · {record['title']} · {marker}")
        st.code("\n".join(record["entries"]) or "Waiting for operations…",
                language="text")


class _CalculationLog:
    """Live Streamlit trace persisted in session state after completion."""

    def __init__(self, key, title, slot):
        self.key = key
        self.slot = slot
        self.started = time.perf_counter()
        self.record = {
            "title": title, "state": "running", "entries": []}
        st.session_state.setdefault("calculation_logs", {})[key] = self.record
        self.add("START", "Calculation request accepted")

    def add(self, operation, detail):
        elapsed = time.perf_counter() - self.started
        self.record["entries"].append(
            f"[{elapsed:7.2f}s] {operation:<12} {detail}")
        _render_calculation_log(self.slot, self.record)

    def finish(self, detail):
        self.add("DONE", detail)
        self.record["state"] = "complete"
        _render_calculation_log(self.slot, self.record)

    def fail(self, detail):
        self.add("ERROR", detail)
        self.record["state"] = "error"
        _render_calculation_log(self.slot, self.record)


def _render_saved_calculation_log(key, slot):
    record = st.session_state.get("calculation_logs", {}).get(key)
    if record is not None:
        _render_calculation_log(slot, record)
FUTURE_COLOR = "#c53030"         # strong highlight for the future aircraft

MODEL_INFO = {
    "et": "Extra-Trees surrogate — data-driven ensemble trained on the ANP "
          "fleet. Current default (2026-07-15 bake-off winner, 2.99 dB mean "
          "LOO RMSE).",
    "rf": "Random Forest surrogate — same data-driven family as `et`, "
          "classic bootstrap-aggregated trees instead of extremely-"
          "randomized ones.",
}

GLOSSARY = {
    "ANP": "Aircraft Noise and Performance database — EASA's certified-"
           "aircraft noise/performance dataset (ECAC Doc 29 / ICAO Doc "
           "9911 methodology).",
    "NPD": "Noise-Power-Distance — a table of noise level vs. engine power "
           "setting and slant distance; the core structure this framework "
           "predicts.",
    "MTOW": "Maximum Take-Off Weight [lb].",
    "MLW": "Maximum Landing Weight [lb].",
    "BPR": "Bypass ratio — ratio of bypass (fan) airflow to core airflow "
           "in a turbofan engine.",
    "SEL": "Sound Exposure Level [dB] — a single-event flyover's total "
           "noise dose, integrated over time and normalized to 1 second.",
    "EPNL": "Effective Perceived Noise Level [EPNdB] — the certification "
            "metric; combines loudness, tone content, and duration.",
    "LAmax": "Maximum A-weighted sound level [dB(A)] reached during a "
             "flyover.",
    "PNLTM": "Maximum Tone-Corrected Perceived Noise Level [dB] — the peak "
             "of the PNLT time history.",
    "D / A": "Operating mode: Departure (takeoff) vs. Approach (landing) — "
             "ANP keeps separate NPD curves for each.",
    "ACFT_ID / NPD_ID": "ANP database identifiers — ACFT_ID names an "
                        "aircraft record, NPD_ID names the NPD curve set "
                        "it points to (several aircraft can share one "
                        "NPD_ID).",
    "QA gate": "The `qa_check` pass applied to every predicted NPD table "
               "(monotonicity, uncertainty, physics cross-check) before "
               "it's marked ok / caution / rejected.",
    "Power Parameter": "Units of the ANP power-setting column — either "
                       "absolute thrust ('CNT (lb)') or percent of max "
                       "static thrust ('CNT (% of Max Static Thrust)').",
}


def _model_help() -> str:
    return "  \n".join(f"**{m}** — {d}" for m, d in MODEL_INFO.items())


def _metric_help() -> str:
    return "  \n".join(f"**{k}** — {GLOSSARY[k]}"
                       for k in ("SEL", "EPNL", "LAmax", "PNLTM"))


# ===========================================================================
# unit system (Imperial <-> Metric) — every framework call still gets native
# lb/ft (ANP convention); conversion happens only at the display boundary.
# ===========================================================================

KG_PER_LB = 0.45359237
N_PER_LBF = 4.4482216153
M_PER_FT = 0.3048


def lb_to_kg(v): return v * KG_PER_LB
def kg_to_lb(v): return v / KG_PER_LB
def lbf_to_kn(v): return v * N_PER_LBF / 1000.0
def kn_to_lbf(v): return v / N_PER_LBF * 1000.0
def ft_to_m(v): return v * M_PER_FT
def m_to_ft(v): return v / M_PER_FT


def _is_metric() -> bool:
    return st.session_state.get("units", "Imperial (lb, ft)").startswith("Metric")


def _dist_label() -> str:
    return "slant distance [m]" if _is_metric() else "slant distance [ft]"


def _dist_x():
    return ft_to_m(STANDARD_DISTANCES_FT) if _is_metric() else STANDARD_DISTANCES_FT


def _dist_col_labels():
    return [f"{v:,.0f}" for v in _dist_x()]


def _power_label() -> str:
    return "kN/engine" if _is_metric() else "lb/engine"


def _power_disp(p_lb):
    return lbf_to_kn(p_lb) if _is_metric() else p_lb


_UNIT_SHADOW_FIELDS = ("f_thrust", "f_mtow", "f_mlw")


def _clear_unit_shadows():
    """Invalidate the thrust/MTOW/MLW display widgets so they reseed from
    the canonical (lb) value next render — call wherever code sets those
    canonical keys directly (such as prefill), bypassing their own widget."""
    for k in _UNIT_SHADOW_FIELDS:
        st.session_state.pop(f"{k}_ui_imperial", None)
        st.session_state.pop(f"{k}_ui_metric", None)


def _unit_number_input(label_native, label_metric, canonical_key, min_native,
                       max_native, step_native, native_to_metric,
                       metric_to_native, help_native=None, help_metric=None):
    """number_input bound to a canonical native-unit (lb) session key,
    displayed in whichever unit is active. The other unit's shadow widget
    is cleared every render so it always reseeds fresh on switch."""
    metric = _is_metric()
    suffix = "metric" if metric else "imperial"
    ui_key = f"{canonical_key}_ui_{suffix}"
    if ui_key not in st.session_state:
        native = st.session_state.get(canonical_key, min_native)
        seed = native_to_metric(native) if metric else native
        st.session_state[ui_key] = round(seed, 2)
    if metric:
        st.number_input(label_metric,
                        min_value=round(native_to_metric(min_native), 2),
                        max_value=round(native_to_metric(max_native), 2),
                        step=round(native_to_metric(step_native), 2),
                        key=ui_key, help=help_metric or help_native)
        st.session_state[canonical_key] = metric_to_native(st.session_state[ui_key])
    else:
        st.number_input(label_native, min_value=min_native, max_value=max_native,
                        step=step_native, key=ui_key, help=help_native)
        st.session_state[canonical_key] = st.session_state[ui_key]
    st.session_state.pop(f"{canonical_key}_ui_{'imperial' if metric else 'metric'}",
                         None)


# ===========================================================================
# data version + cached resources
# ===========================================================================

def data_version() -> str:
    """Cache key that changes only when the truth tables are rebuilt.

    Reads created_utc from the sqlite anp_meta table (cheap, direct sqlite3);
    falls back to file mtime+size. Raises FileNotFoundError when the datastore
    is absent so the global gate can render the staging recipe.
    """
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(DB_PATH)
    try:
        con = sqlite3.connect(DB_PATH)
        try:
            row = con.execute(
                "SELECT created_utc FROM anp_meta LIMIT 1").fetchone()
        finally:
            con.close()
        if row and row[0]:
            return str(row[0])
    except sqlite3.Error:
        pass
    stat = os.stat(DB_PATH)
    return f"mtime{stat.st_mtime_ns}-size{stat.st_size}"


@st.cache_resource(show_spinner=False)
def get_db(version: str):
    """ANPDatabase for the current data version (fleet load is cached)."""
    _ = version                      # keys the cache; unused in the body
    return ANPDatabase(".")


@st.cache_resource(show_spinner=False)
def get_predictor(model: str, version: str):
    """NoisePredictor for (model, version); construction fits the fleet."""
    _ = version                      # keys the cache; unused in the body
    return NoisePredictor(".", model=model)


@st.cache_data(show_spinner=False)
def get_param_table(version: str):
    """Parametric descriptor table (indexed by NPD_ID), cached as data."""
    return get_db(version).param_table()


@st.cache_data(show_spinner=False)
def get_input_envelope(version: str):
    """Realistic-input envelope from the ANP fleet (for the input checker)."""
    return fleet_input_envelope(get_db(version).aircraft)


@st.cache_data(show_spinner=False)
def load_output_csv(path: str, mtime: float):
    """CSV under outputs/, cached and keyed by mtime so a re-run of
    validate/compare invalidates the cache."""
    _ = mtime                        # keys the cache; unused in the body
    return pd.read_csv(path)


_COMPARE_CSV = "outputs/algorithm_comparison.csv"


@st.cache_data(show_spinner=False)
def load_model_ranking(mtime: float):
    """(ranking_df, info) from the bake-off CSV via pnmf.models.rank_models,
    cached and keyed by the CSV mtime. Returns None when the CSV is absent or
    unrankable (needs >=2 fully-scored models)."""
    _ = mtime                        # keys the cache; unused in the body
    if not os.path.exists(_COMPARE_CSV):
        return None
    try:
        return rank_models(pd.read_csv(_COMPARE_CSV))
    except (ValueError, KeyError):
        return None


# ===========================================================================
# small helpers
# ===========================================================================

def _opt(v):
    """Optional float: None / non-finite -> None, else float."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _opt_int(v):
    v = _opt(v)
    return int(v) if v is not None else None


def _clamp(v, lo, hi, default):
    """Coerce v into [lo, hi]; NaN/None/non-numeric -> default (for prefill)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(v):
        return default
    return min(max(v, lo), hi)


def _sanitize_name(s: str) -> str:
    """Strip filename-hostile characters (the name becomes an NPD_ID / CSV)."""
    return re.sub(r'[<>:"/\\|?*]+', "_", str(s)).strip()


def _label_map(pt):
    """{'Description — ACFT_ID (NPD_ID)': npd_id} over the param table."""
    out = {}
    for npd_id, row in pt.iterrows():
        out[f"{row['Description']} — {row['ACFT_ID']} ({npd_id})"] = npd_id
    return out


def _require_prediction():
    """Shared guard: return the prediction or render an info hint + None.
    Also warns when the prediction is stale versus the current data version."""
    pred = st.session_state.get("prediction")
    if pred is None:
        st.info("Design an aircraft and press the analysis button first.")
        return None
    meta = st.session_state.get("pred_meta", {})
    try:
        cur = data_version()
    except FileNotFoundError:
        cur = None
    if meta.get("version") and cur and meta["version"] != cur:
        st.warning("The datastore changed since this prediction was made — "
                   "re-run the analysis on **Aircraft Designer** for "
                   "up-to-date results.")
    return pred


# ===========================================================================
# Designer callbacks (run before the next render, so they may write f_* keys)
# ===========================================================================

_OPTIONAL_KEYS = ("f_bpr", "f_fan_d", "f_fan_mach", "f_wing_area",
                  "f_wing_span", "f_gear_wheels")
ANALYSIS_APPROACHES = (
    "Compare learned + physics",
    "Learned ET/RF only",
    "Component physics only",
)


def _apply_shared_aircraft_preset():
    """Apply one v6.3 aircraft definition to both independent model routes."""
    key = st.session_state.get("f_aircraft_preset", "__custom__")
    if key == "__custom__":
        st.session_state.pop("phys_active_preset", None)
        st.session_state.pop("physics_result", None)
        st.session_state.pop("calculation_logs", None)
        return

    preset = PHYSICS_PRESETS[key]
    ac = _preset_aircraft(preset)
    st.session_state["phys_active_preset"] = key
    st.session_state["f_name"] = ac.name
    st.session_state["f_engine_type"] = ac.engine_type
    st.session_state["f_n_engines"] = ac.n_engines
    st.session_state["f_thrust"] = ac.max_static_thrust_lb
    st.session_state["f_mtow"] = ac.mtow_lb
    st.session_state["f_mlw"] = ac.mlw_lb
    st.session_state["f_chapter"] = ac.noise_chapter
    st.session_state["f_bpr"] = ac.bypass_ratio
    st.session_state["f_fan_d"] = ac.fan_diameter_m
    st.session_state["f_fan_mach"] = None
    st.session_state["f_wing_area"] = ac.wing_area_m2
    st.session_state["f_wing_span"] = ac.wing_span_m
    st.session_state["f_gear_wheels"] = ac.n_main_gear_wheels
    _apply_physics_preset_values(preset)
    _clear_unit_shadows()
    st.session_state.pop("prediction", None)
    st.session_state.pop("pred_meta", None)
    st.session_state.pop("calculation_logs", None)

def _apply_prefill():
    """Fill the form from a real ANP aircraft row (name suffixed -DERIVED)."""
    version = data_version()
    opts = _label_map(get_param_table(version))
    npd_id = opts.get(st.session_state.get("f_prefill_sel"))
    if npd_id is None:
        return
    row = get_param_table(version).loc[npd_id]
    ac = ParametricAircraft.from_anp_row(npd_id, row)
    st.session_state["f_name"] = _sanitize_name(f"{row['Description']}-DERIVED")
    st.session_state["f_engine_type"] = (ac.engine_type
                                         if ac.engine_type in ENGINE_TYPES
                                         else "Jet")
    st.session_state["f_n_engines"] = int(_clamp(ac.n_engines, 1, 8, 2))
    st.session_state["f_thrust"] = _clamp(ac.max_static_thrust_lb,
                                          50.0, 130000.0, 50.0)
    st.session_state["f_mtow"] = _clamp(ac.mtow_lb, 1000.0, 1500000.0, 1000.0)
    st.session_state["f_mlw"] = _clamp(ac.mlw_lb, 1000.0, 1500000.0, 1000.0)
    st.session_state["f_chapter"] = int(_clamp(ac.noise_chapter, 1, 14, 4))
    # from_anp_row leaves the richer geometry/cycle fields unset
    for k in _OPTIONAL_KEYS:
        st.session_state[k] = None
    st.session_state["f_aircraft_preset"] = "__custom__"
    st.session_state.pop("phys_active_preset", None)
    st.session_state.pop("physics_result", None)
    st.session_state.pop("calculation_logs", None)
    _clear_unit_shadows()


def _init_designer_state():
    """Seed every f_* widget key once (setdefault is idempotent per rerun)."""
    st.session_state.setdefault("f_name", "New aircraft")
    st.session_state.setdefault("f_engine_type", "Jet")
    st.session_state.setdefault("f_n_engines", 2)
    st.session_state.setdefault("f_thrust", 30000.0)
    st.session_state.setdefault("f_mtow", 170000.0)
    st.session_state.setdefault("f_mlw", 145000.0)
    st.session_state.setdefault("f_chapter", 14)
    st.session_state.setdefault("f_bpr", None)
    for k in ("f_fan_d", "f_fan_mach", "f_wing_area", "f_wing_span",
              "f_gear_wheels"):
        st.session_state.setdefault(k, None)
    st.session_state.setdefault("f_model", DEFAULT_MODEL)
    st.session_state.setdefault("f_departure_powers", "")
    st.session_state.setdefault("f_approach_powers", "")
    st.session_state.setdefault("f_aircraft_preset", "__custom__")
    st.session_state.setdefault(
        "f_analysis_approach", ANALYSIS_APPROACHES[0])


def _custom_power_settings_from_state():
    """Return optional per-mode NPD row powers; blank fields keep defaults."""
    def parse(key):
        raw = st.session_state.get(key, "").strip()
        values = None if not raw else [float(part.strip()) for part in raw.split(",")]
        return None if values is None else (
            [kn_to_lbf(value) for value in values] if _is_metric() else values)
    return {"D": parse("f_departure_powers"), "A": parse("f_approach_powers")}


# ===========================================================================
# Page: Aircraft Designer
# ===========================================================================

def page_designer():
    _init_designer_state()
    version = data_version()
    st.header("Aircraft design")
    st.caption(
        "Choose one aircraft definition, then use that same aircraft for the "
        "learned ET/RF route, component physics, or a direct comparison.")

    st.subheader("1. Shared aircraft")
    preset_options = ["__custom__", *PHYSICS_PRESETS]
    p1, p2 = st.columns([3, 1])
    with p1:
        st.selectbox(
            "Aircraft preset",
            preset_options,
            format_func=lambda key: (
                "Custom aircraft"
                if key == "__custom__" else PHYSICS_PRESETS[key].label),
            key="f_aircraft_preset",
            help="A selected v6.3 preset populates one shared aircraft input "
                 "for both independent model routes.")
    with p2:
        st.button(
            "Apply to both models",
            on_click=_apply_shared_aircraft_preset,
            width="stretch")

    active_preset = _matching_active_preset(_aircraft_from_state())
    if active_preset is not None:
        st.success(
            f"Shared aircraft: **{active_preset.label}**. ET/RF and component "
            "physics will use this same aircraft definition.")
        with st.expander("Preset sources and estimated fields"):
            for source in active_preset.sources:
                fields = ", ".join(
                    field.replace("_", " ") for field in source.fields)
                st.markdown(f"- [{source.title}]({source.url}) — {fields}")
            st.caption(
                "MTOW, MLW, thrust and engine count come from local v6.3. "
                "Wing area is estimated as span²/9; incomplete high-lift, "
                "strut and wheel geometry remains editable and estimated.")
    elif st.session_state.get("phys_active_preset") is not None:
        st.warning(
            "The preset values were edited. Both routes will use the edited "
            "shared aircraft, but edited fields are no longer labelled as "
            "manufacturer-supplied preset values.")

    with st.expander("Start from a real aircraft (optional)"):
        labels = list(_label_map(get_param_table(version)))
        st.selectbox("Prefill from real aircraft", labels, key="f_prefill_sel")
        st.button("Apply prefill", on_click=_apply_prefill,
                  width="stretch")

    # ---- core parametric form -------------------------------------------
    st.text_input("Name", key="f_name")
    a, b, c = st.columns(3)
    with a:
        st.selectbox("Engine type", ENGINE_TYPES, key="f_engine_type")
        st.number_input("Number of engines", min_value=1, max_value=8, step=1,
                        key="f_n_engines")
    with b:
        _unit_number_input(
            "Static thrust per engine [lb]", "Static thrust per engine [kN]",
            "f_thrust", 50.0, 130000.0, 500.0, lbf_to_kn, kn_to_lbf,
            help_native="Sea-level static thrust rating per engine, in "
                        "pounds-force (lbf).",
            help_metric="Sea-level static thrust rating per engine, in "
                        "kilonewtons (kN).")
        st.number_input("Noise chapter", min_value=1, max_value=14, step=1,
                        key="f_chapter",
                        help="ICAO Annex 16 Chapter — the noise "
                             "stringency stage the aircraft is "
                             "certified/designed to.")
    with c:
        _unit_number_input(
            "MTOW [lb]", "MTOW [kg]", "f_mtow", 1000.0, 1500000.0, 1000.0,
            lb_to_kg, kg_to_lb, help_native=GLOSSARY["MTOW"],
            help_metric="Maximum Take-Off Weight [kg].")
        _unit_number_input(
            "MLW [lb]", "MLW [kg]", "f_mlw", 1000.0, 1500000.0, 1000.0,
            lb_to_kg, kg_to_lb, help_native=GLOSSARY["MLW"],
            help_metric="Maximum Landing Weight [kg].")

    # ---- optional richer fields -----------------------------------------
    with st.expander("Optional geometry / cycle parameters (leave empty if "
                     "unknown)"):
        o1, o2, o3 = st.columns(3)
        with o1:
            st.number_input("Bypass ratio", min_value=0.0, max_value=20.0,
                            step=0.5, key="f_bpr", help=GLOSSARY["BPR"])
            st.number_input("Fan diameter [m]", min_value=0.0, max_value=6.0,
                            step=0.05, key="f_fan_d",
                            help="Engine fan (inlet) diameter — feeds the "
                                 "physics-route fan noise source term.")
        with o2:
            st.number_input("Fan tip Mach", min_value=0.0, max_value=2.0,
                            step=0.05, key="f_fan_mach",
                            help="Fan blade tip Mach number at max power — "
                                 "feeds the physics-route fan noise source "
                                 "term.")
            st.number_input("Wing area [m^2]", min_value=0.0, max_value=1200.0,
                            step=1.0, key="f_wing_area",
                            help="Reference wing area — feeds the "
                                 "physics-route airframe (Fink) noise "
                                 "source term.")
        with o3:
            st.number_input("Wing span [m]", min_value=0.0, max_value=90.0,
                            step=0.5, key="f_wing_span",
                            help="Wingspan — feeds the physics-route "
                                 "airframe noise source term.")
            st.number_input("Main-gear wheels", min_value=1, max_value=32,
                            step=1, key="f_gear_wheels",
                            help="Number of wheels on the main landing "
                                 "gear — feeds the physics-route airframe "
                                 "(gear) noise source term.")

    # ---- input realism check (after every input, so it reflects all) -----
    _render_input_health(version)

    st.divider()
    st.subheader("2. Choose analysis approach")
    approach = st.radio(
        "Analysis approach",
        ANALYSIS_APPROACHES,
        horizontal=True,
        key="f_analysis_approach",
        help="Compare mode overlays independent ET/RF and component-physics "
             "noise results for the same aircraft and event.")
    if approach == "Learned ET/RF only":
        st.info("Runs the selected tree model and produces NPD tables.")
    elif approach == "Component physics only":
        st.info(
            "Runs the component-source route for SEL/LAmax without displaying "
            "a learned-model overlay.")
    else:
        st.info(
            "Runs ET/RF first, then exposes component-physics event inputs and "
            "a same-aircraft noise comparison below.")

    # ---- advanced prediction settings -----------------------------------
    with st.expander("Advanced prediction settings"):
        st.selectbox("Prediction model", MODELS, key="f_model",
                     help=_model_help())
        st.caption("Extra Trees (`et`) is the default model. Use custom NPD "
                   "row powers only when a specific engine deck is available.")
        st.caption("Enter comma-separated corrected net thrust values per engine. "
                   "These are NPD table row powers, not the engine's maximum "
                   "static rating. Leave either field blank to use its existing "
                   "mode-specific default grid.")
        power_unit = "kN/engine" if _is_metric() else "lb/engine"
        if _is_metric():
            st.caption("Enter kN/engine; PNMF converts the values to its internal "
                       "ANP lb/engine convention before prediction.")
        dep_example = "e.g. 80, 110, 135" if _is_metric() else "e.g. 18000, 24000, 30000"
        app_example = "e.g. 11, 20, 29" if _is_metric() else "e.g. 2500, 4500, 6500"
        st.text_input(f"Departure powers [{power_unit}]", key="f_departure_powers",
                      placeholder=dep_example)
        st.text_input(f"Approach powers [{power_unit}]", key="f_approach_powers",
                      placeholder=app_example)

    run_label = {
        "Learned ET/RF only": "Run learned prediction",
        "Component physics only": "Prepare component physics",
        "Compare learned + physics": "Run learned model and prepare comparison",
    }[approach]
    run_clicked = st.button(run_label, type="primary", width="stretch")
    learned_log_slot = st.empty()
    if run_clicked:
        ac = _aircraft_from_state()
        model = st.session_state["f_model"]
        st.session_state.setdefault("calculation_logs", {}).pop(
            "physics", None)
        calc_log = _CalculationLog(
            "learned",
            f"{model.upper()} aircraft analysis",
            learned_log_slot)
        calc_log.add(
            "AIRCRAFT",
            f"{ac.name}; engines={ac.n_engines}; "
            f"thrust={ac.max_static_thrust_lb:,.0f} lb/engine; "
            f"MTOW={ac.mtow_lb:,.0f} lb")
        if approach != "Learned ET/RF only":
            _sync_physics_widgets_from_aircraft(
                ac, _matching_active_preset(ac))
            calc_log.add(
                "PHYSICS LINK",
                "Copied the shared aircraft into component-physics inputs")
        try:
            power_settings = _custom_power_settings_from_state()
            power_note = "; ".join(
                f"{mode}={'automatic' if powers is None else list(powers)}"
                for mode, powers in power_settings.items())
            calc_log.add(
                "POWER GRID",
                f"Canonicalize corrected net thrust rows: {power_note}")
            calc_log.add(
                "MODEL CACHE",
                f"Resolve `{model}` predictor for datastore {version}; "
                "fit the merged ANP corpus on cache miss")
            with st.spinner(f"Fitting `{model}` on the ANP fleet and "
                            f"predicting…"):
                predictor = get_predictor(model, version)
                calc_log.add(
                    "FEATURES",
                    "Build aircraft descriptors plus log10(power/engine) "
                    "and throttle features")

                def report_progress(event, details):
                    if event == "combo_start":
                        powers = ", ".join(
                            f"{value:,.0f}"
                            for value in details["powers_lbf"])
                        calc_log.add(
                            "MODEL TABLE",
                            f"{details['index']}/{details['total']} "
                            f"{details['metric']}/{details['op_mode']} at "
                            f"[{powers}] lb/engine")
                    elif event == "combo_done":
                        uncertainty = (
                            "tree dispersion calculated"
                            if details["uncertainty"]
                            else "no dispersion output")
                        calc_log.add(
                            "TABLE READY",
                            f"{details['metric']}/{details['op_mode']}: "
                            f"{details['rows']} power rows × "
                            f"{details['distances']} distances; {uncertainty}")
                    elif event == "prediction_done":
                        calc_log.add(
                            "OUTPUT",
                            f"{details['tables']} monotone NPD tables "
                            "assembled")

                pred = predictor.predict(
                    ac, power_settings=power_settings,
                    progress_callback=report_progress)
        except (RuntimeError, ValueError) as e:
            calc_log.fail(str(e))
            st.error(f"Model `{model}` is unavailable: {e}")
        else:
            st.session_state["prediction"] = pred
            st.session_state["pred_meta"] = {
                "model": model, "version": version,
                "aircraft": ac.to_dict(), "name": ac.name}
            st.session_state.pop("crosscheck", None)   # stale on new predict
            st.session_state.pop("physics_result", None)
            calc_log.finish(
                f"Aircraft analysis prepared with {len(pred.tables)} tables")
            if approach == "Learned ET/RF only":
                st.success(
                    "Learned prediction ready. Detailed tables remain "
                    "available under **Prediction results**.")
            elif approach == "Component physics only":
                st.success(
                    "Shared aircraft ready. Set the physics event below and "
                    "run the component model.")
            else:
                st.success(
                    "Learned prediction ready. Set the matching physics event "
                    "below to compare both routes.")
    else:
        _render_saved_calculation_log("learned", learned_log_slot)

    # ---- persistent last-prediction summary -----------------------------
    if "prediction" in st.session_state:
        meta = st.session_state["pred_meta"]
        st.divider()
        st.caption("Current shared-aircraft analysis")
        m1, m2, m3 = st.columns(3)
        m1.metric("Aircraft", meta["name"])
        m2.metric("Model", meta["model"])
        m3.metric("Tables", len(st.session_state["prediction"].tables))
        if approach != "Learned ET/RF only":
            st.divider()
            page_physics(
                embedded=True,
                compare_learned=(approach == "Compare learned + physics"))


def _render_input_health(version: str):
    """Live realism check of the current form inputs (re-runs every render, so
    it updates as fields change). Warn-only — it never blocks Predict."""
    ac = _aircraft_from_state()
    findings = evaluate_aircraft_inputs(ac, get_input_envelope(version))
    errors = [f for f in findings if f["level"] == "error"]
    warnings = [f for f in findings if f["level"] == "warning"]

    if errors:
        st.error("**Unrealistic inputs — the predicted graphs will be "
                 "meaningless.** Fix these before trusting any output:\n\n"
                 + "\n".join(f"- {f['message']}" for f in errors))
    if warnings:
        st.warning("**Unusual inputs — the model is extrapolating beyond the "
                   "real fleet, so uncertainty is high:**\n\n"
                   + "\n".join(f"- {f['message']}" for f in warnings))
    if not findings:
        try:
            db = get_db(version)
            near = db.nearest_aircraft(ac.mtow_lb, engine_type=ac.engine_type,
                                       n_engines=ac.n_engines, n=1)
            nearest_note = ""
            if not near.empty:
                r = near.iloc[0]
                nearest_note = (f" Closest real aircraft: **{r['ACFT_ID']}** "
                                f"(MTOW {r['Max Gross Takeoff Weight (lb)']:,.0f} lb).")
        except Exception:       # pragma: no cover - nearest note is best-effort
            nearest_note = ""
        st.success("Inputs sit within the realistic ANP envelope." + nearest_note)


def _aircraft_from_state() -> ParametricAircraft:
    s = st.session_state
    return ParametricAircraft(
        name=_sanitize_name(s["f_name"]) or "GENERIC",
        engine_type=s["f_engine_type"],
        n_engines=int(s["f_n_engines"]),
        max_static_thrust_lb=float(s["f_thrust"]),
        mtow_lb=float(s["f_mtow"]),
        mlw_lb=float(s["f_mlw"]),
        noise_chapter=int(s["f_chapter"]),
        bypass_ratio=_opt(s["f_bpr"]),
        fan_diameter_m=_opt(s["f_fan_d"]),
        fan_tip_mach=_opt(s["f_fan_mach"]),
        wing_area_m2=_opt(s["f_wing_area"]),
        wing_span_m=_opt(s["f_wing_span"]),
        n_main_gear_wheels=_opt_int(s["f_gear_wheels"]),
    )


# ===========================================================================
# Page: Comparison
# ===========================================================================

def page_comparison():
    pred = _require_prediction()
    if pred is None:
        return
    version = data_version()
    db = get_db(version)
    pt = get_param_table(version)
    meta = st.session_state["pred_meta"]
    acd = meta["aircraft"]
    st.header("Comparison — future vs real ANP aircraft")

    # ---- controls --------------------------------------------------------
    metrics = sorted({m for (m, _om) in pred.tables})
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        metric = str(st.selectbox("Metric", metrics, key="cmp_metric",
                                  help=_metric_help()))
    with c2:
        om = st.radio("Op mode", ["D", "A"], horizontal=True, key="cmp_om",
                      help=GLOSSARY["D / A"])
    with c3:
        n_neighbors = st.slider("Neighbors (table)", 1, 6, 3, key="cmp_nn")

    if (metric, om) not in pred.tables:
        st.warning(f"The prediction has no {metric}/{om} table.")
        return
    tbl = pred.tables[(metric, om)]

    # aircraft multiselect (default = nearest NPD neighbours)
    label_map = _label_map(pt)
    nearest = db.nearest_npd_ids(acd["mtow_lb"], acd["engine_type"],
                                 acd["n_engines"], n=3)
    default_npd = {npd_id for (_acft, npd_id) in nearest}
    default_labels = [lab for lab, nid in label_map.items()
                      if nid in default_npd]
    selected = st.multiselect("Real ANP aircraft to overlay",
                              list(label_map), default=default_labels,
                              key="cmp_aircraft")

    d1, d2 = st.columns([1, 1])
    with d1:
        if _is_metric():
            m_opts = [round(ft_to_m(x)) for x in STANDARD_DISTANCES_FT]
            disp_ref = float(st.select_slider(
                "Reference distance [m]", options=m_opts,
                value=m_opts[3], key="cmp_ref_metric"))
            ref = m_to_ft(disp_ref)
        else:
            disp_ref = float(st.select_slider(
                "Reference distance [ft]",
                options=[float(x) for x in STANDARD_DISTANCES_FT],
                value=1000.0, key="cmp_ref_imperial"))
            ref = disp_ref
    with d2:
        if len(tbl.P) > 1:
            default_p = float(tbl.P[-1] if om == "D" else tbl.P[0])
            if _is_metric():
                p_slider = kn_to_lbf(st.slider(
                    "Future power setting [kN/engine]",
                    min_value=round(lbf_to_kn(float(tbl.P[0])), 1),
                    max_value=round(lbf_to_kn(float(tbl.P[-1])), 1),
                    value=round(lbf_to_kn(default_p), 1), key="cmp_power_metric"))
            else:
                p_slider = float(st.slider(
                    "Future power setting [lb/engine]",
                    min_value=float(tbl.P[0]), max_value=float(tbl.P[-1]),
                    value=default_p, key="cmp_power_imperial"))
        else:
            p_slider = float(tbl.P[0])
            st.caption(f"Single power row: {_power_disp(p_slider):.1f} "
                      f"{_power_label()}")

    # gather selected real curves (skip those without this metric/mode)
    reals, skipped = [], []
    for lab in selected:
        npd_id = label_map[lab]
        acft_id = str(pt.loc[npd_id, "ACFT_ID"])
        cv = db.curve(npd_id, metric, om)
        if cv.empty:
            skipped.append(acft_id)
            continue
        nb = NPDTable(cv["Power Setting"].values.astype(float),
                      cv[DIST_COLS].values, metric, om, npd_id=npd_id)
        reals.append((acft_id, nb))

    # ---- overlay chart ---------------------------------------------------
    dist_x = _dist_x()
    future_L = np.array([tbl.level(p_slider, d)
                         for d in STANDARD_DISTANCES_FT])
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    cmap = plt.cm.Blues(np.linspace(0.45, 0.85, max(len(reals), 1)))
    for k, (acft_id, nb) in enumerate(reals):
        rep = nb.L[-1] if om == "D" else nb.L[0]
        ax.semilogx(dist_x, rep, "-", color=cmap[k], lw=1.1,
                    alpha=0.9, label=acft_id)
    std = pred.uncertainty.get((metric, om))
    if std is not None:
        j = int(np.argmin(np.abs(tbl.P - p_slider)))
        band = np.asarray(std, float)[j]
        ax.fill_between(dist_x, future_L - band,
                        future_L + band, color=FUTURE_COLOR, alpha=0.15)
    ax.semilogx(dist_x, future_L, "o-", color=FUTURE_COLOR,
                lw=2.6, label=f"{acd['name']} (future)")
    ax.axvline(disp_ref, ls="--", color="0.4", lw=1)
    ax.set_xlabel(_dist_label())
    ax.set_ylabel(f"{metric} [dB]")
    ax.set_title(f"{metric}/{om}: future vs real (representative-power rows)",
                 fontsize=10)
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    # ---- bar chart at ref distance --------------------------------------
    bars = [(f"{acd['name']} (future)", float(tbl.level(p_slider, ref)), True)]
    for acft_id, nb in reals:
        p_rep = nb.P[-1] if om == "D" else nb.P[0]
        bars.append((acft_id, float(nb.level(p_rep, ref)), False))
    bars.sort(key=lambda t: t[1])
    fig2, ax2 = plt.subplots(figsize=(7.2, 0.5 * len(bars) + 1.4))
    colors = [FUTURE_COLOR if fut else "#94a3b8" for _n, _v, fut in bars]
    ypos = np.arange(len(bars))
    ax2.barh(ypos, [v for _n, v, _f in bars], color=colors)
    ax2.set_yticks(ypos)
    ax2.set_yticklabels([n for n, _v, _f in bars], fontsize=8)
    for y, (_n, v, _f) in enumerate(bars):
        ax2.text(v, y, f" {v:.1f}", va="center", ha="left", fontsize=8)
    dist_unit = "m" if _is_metric() else "ft"
    ax2.set_xlabel(f"{metric} at {disp_ref:.0f} {dist_unit} [dB]")
    ax2.set_title(f"Level at {disp_ref:.0f} {dist_unit}", fontsize=10)
    ax2.grid(True, axis="x", alpha=0.25)
    fig2.tight_layout()
    st.pyplot(fig2)
    plt.close(fig2)

    if skipped:
        st.caption(f"No {metric}/{om} curve (skipped): {', '.join(skipped)}")

    # ---- canonical table -------------------------------------------------
    cc = st.session_state.get("crosscheck")
    table_df = real_vs_future_table(
        db, pred, crosscheck=cc["result"] if cc else None,
        n_neighbors=n_neighbors, ref_distance_ft=ref)
    st.subheader("Canonical real-vs-future table")
    st.dataframe(table_df, width="stretch", hide_index=True)
    st.caption("Each aircraft is evaluated at its OWN representative power row "
               "(highest tabulated for D, lowest for A): ANP power settings "
               "(lbf / %RPM / …) are not unit-comparable across aircraft, so "
               "raw settings are never compared directly. Neighbours here are "
               "the canonical nearest-NPD set, independent of the overlay "
               "multiselect above.")


# ===========================================================================
# Page: Prediction results
# ===========================================================================

def _qa_badge(status, reasons):
    msg = f"QA status: **{status}**" + (f" — {'; '.join(reasons)}"
                                        if reasons else "")
    {"ok": st.success, "caution": st.warning,
     "rejected": st.error}.get(status, st.info)(msg)


def _render_result_table(pred, metric, om):
    tbl = pred.tables[(metric, om)]
    std = pred.uncertainty.get((metric, om))
    cc = st.session_state.get("crosscheck")
    cc_db = cc["result"].get(metric) if cc else None
    status, reasons = qa_check(tbl.P, tbl.L, std, crosscheck_db=cc_db)
    _qa_badge(status, reasons)

    p_disp = _power_disp(tbl.P)
    idx = pd.Index(np.round(p_disp, 1), name=f"thrust {_power_label()}")
    col_labels = _dist_col_labels()
    L_df = pd.DataFrame(np.round(tbl.L, 1), columns=col_labels, index=idx)
    st.dataframe(L_df, width="stretch")

    if st.checkbox("Show ±1σ", key=f"res_sigma_{metric}_{om}"):
        if std is None:
            st.caption("This model provides no uncertainty estimate.")
        else:
            std_df = pd.DataFrame(np.round(np.asarray(std, float), 1),
                                  columns=col_labels, index=idx)
            st.dataframe(std_df, width="stretch")

    default_p = float(tbl.P[-1] if om == "D" else tbl.P[0])
    if len(tbl.P) == 1:
        selected_p = default_p
        st.caption(f"Single thrust row: {_power_disp(selected_p):.1f} "
                   f"{_power_label()}.")
    elif _is_metric():
        selected_p = kn_to_lbf(st.number_input(
            "Thrust setting [kN/engine]",
            min_value=float(lbf_to_kn(tbl.P[0])),
            max_value=float(lbf_to_kn(tbl.P[-1])),
            value=float(lbf_to_kn(default_p)),
            step=0.1, format="%.1f",
            key=f"res_thrust_{metric}_{om}_metric",
            help="Enter an exact thrust setting within the predicted NPD range."))
    else:
        selected_p = st.number_input(
            "Thrust setting [lb/engine]",
            min_value=float(tbl.P[0]), max_value=float(tbl.P[-1]),
            value=default_p, step=100.0, format="%.0f",
            key=f"res_thrust_{metric}_{om}_imperial",
            help="Enter an exact thrust setting within the predicted NPD range.")

    selected_levels = np.array([
        tbl.level(selected_p, distance_ft) for distance_ft in STANDARD_DISTANCES_FT])
    selected_std = None
    if std is not None:
        std_arr = np.asarray(std, float)
        selected_std = np.array([
            np.interp(selected_p, tbl.P, std_arr[:, j])
            for j in range(std_arr.shape[1])])
    st.caption("Enter an exact thrust setting to inspect the interpolated NPD noise curve. "
               "This does not change the generated prediction table.")

    dist_x = _dist_x()
    reference_indices = (0, 3, 5, 8)
    reference_labels = [
        f"{dist_x[i]:,.0f} {_dist_label().split('[')[1][:-1]}: "
        f"{selected_levels[i]:.1f} dB"
        for i in reference_indices]
    st.caption("Reference noise levels — " + " · ".join(reference_labels))

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    if selected_std is not None:
        ax.fill_between(dist_x, selected_levels - selected_std,
                        selected_levels + selected_std,
                        color="#2b6cb0", alpha=0.15, label="±1σ")
    ax.semilogx(dist_x, selected_levels, "o-", color="#2b6cb0", lw=1.6,
                label=f"{_power_disp(selected_p):.0f} {_power_label()}")
    for n, i in enumerate(reference_indices):
        offset = (6, 8 if n % 2 == 0 else -14)
        ax.annotate(f"{selected_levels[i]:.1f} dB", (dist_x[i], selected_levels[i]),
                    xytext=offset, textcoords="offset points", fontsize=7,
                    color="#1a365d")
    ax.set_xlabel(_dist_label())
    ax.set_ylabel(f"{metric} [dB]")
    ax.set_title(f"{metric} / {om}: noise by thrust setting", fontsize=10)
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(title="Selected thrust", fontsize=7, title_fontsize=8, ncol=2)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def _store_expander(pred, meta):
    with st.expander("Store prediction in anp_data.sqlite"):
        st.caption(
            "Writes the predicted NPD tables into the QA-gated "
            "`predicted_aircraft` / `predicted_npd` tables, keyed by "
            "(name, model) — the same path as `pnmf_cli.py predict`. "
            "Tables that fail `qa_check` are rejected and never written; "
            "existing rows for this (name, model) are replaced.")
        confirm = st.checkbox("I understand this writes to anp_data.sqlite",
                              key="store_confirm")
        if st.button("Store prediction", disabled=not confirm,
                     key="store_button"):
            cc = st.session_state.get("crosscheck")
            cc_result = cc["result"] if cc else None
            ac = ParametricAircraft(**meta["aircraft"])
            store = PredictionStore(DB_PATH)
            results = store.add(ac, pred.tables, pred.uncertainty,
                                model=meta["model"], crosscheck=cc_result)
            for (metric, om), (status, reasons) in sorted(results.items()):
                note = f" — {'; '.join(reasons)}" if reasons else ""
                mark = {"ok": "stored", "caution": "stored [CAUTION]",
                        "rejected": "REJECTED"}[status]
                fn = {"ok": st.success, "caution": st.warning,
                     "rejected": st.error}[status]
                fn(f"{metric}/{om}: {mark}{note}")


def page_results():
    pred = _require_prediction()
    if pred is None:
        return
    meta = st.session_state["pred_meta"]
    st.header("Prediction results")
    st.caption(f"NPD-equivalent tables for **{meta['name']}** "
               f"(model `{meta['model']}`).")

    combos = sorted(pred.tables)
    metrics = sorted({m for m, _om in combos})
    show_all = st.checkbox("Show all metric / op-mode tables",
                           key="res_show_all")

    if show_all:
        for metric, om in combos:
            with st.expander(f"{metric} / {om}"):
                _render_result_table(pred, metric, om)
    else:
        c1, c2 = st.columns([2, 1])
        with c1:
            metric = st.selectbox("Metric", metrics, key="res_metric",
                                  help=_metric_help())
        with c2:
            om = st.radio("Op mode", ["D", "A"], horizontal=True,
                          key="res_om", help=GLOSSARY["D / A"])
        if (metric, om) not in pred.tables:
            st.warning(f"The prediction has no {metric}/{om} table.")
        else:
            _render_result_table(pred, metric, om)

    st.divider()
    buf = io.StringIO()
    pred.to_anp_csv(buf)
    st.download_button("Download ANP-layout CSV", buf.getvalue(),
                       file_name=f"{meta['name']}_NPD.csv", mime="text/csv")

    st.divider()
    _store_expander(pred, meta)


# ===========================================================================
# Page: Physics cross-check
# ===========================================================================

def _physical(value, status, note):
    """Short constructor used by the physics UI's provenance-aware inputs."""
    return PhysicalInput(value, status, note)


def _apply_physics_preset_values(preset):
    """Populate physics widgets from the aircraft shared by both routes."""
    area = preset.estimated_wing_area_m2
    st.session_state["phys_bpr"] = float(preset.bpr)
    st.session_state["phys_thrust_imperial"] = (
        0.85 * preset.max_thrust_lbf)
    st.session_state["phys_thrust_metric"] = lbf_to_kn(
        0.85 * preset.max_thrust_lbf)
    st.session_state["phys_wing_area"] = area
    st.session_state["phys_wing_span"] = preset.wing_span_m
    st.session_state["phys_flap_area"] = 0.17 * area
    st.session_state["phys_slat_area"] = 0.08 * area
    st.session_state["phys_nose_wheels"] = preset.nose_wheel_count
    st.session_state["phys_main_wheels"] = preset.main_wheel_count
    st.session_state["phys_nose_wheel_d"] = (
        preset.nose_wheel_diameter_m)
    st.session_state["phys_main_wheel_d"] = (
        preset.main_wheel_diameter_m)
    st.session_state["phys_fan_diameter_basic"] = preset.fan_diameter_m
    st.session_state["phys_fan_blades_basic"] = preset.fan_blades
    st.session_state["phys_airframe_supplied"] = False
    st.session_state["phys_use_engine_detail"] = False
    st.session_state.pop("physics_result", None)


def _sync_physics_widgets_from_aircraft(ac, preset=None):
    """Reseed physics geometry whenever the shared aircraft analysis changes."""
    area = float(
        ac.wing_area_m2 or ac.mtow_lb * KG_PER_LB / 600.0)
    span = float(ac.wing_span_m or np.sqrt(9.0 * area))
    fan_diameter = float(ac.fan_diameter_m or 1.8)
    main_wheels = int(
        ac.n_main_gear_wheels
        or (4 if ac.mtow_lb * KG_PER_LB < 5e4 else 8))
    st.session_state["phys_bpr"] = float(ac.bypass_ratio or 6.0)
    st.session_state["phys_thrust_imperial"] = (
        0.85 * ac.max_static_thrust_lb)
    st.session_state["phys_thrust_metric"] = lbf_to_kn(
        0.85 * ac.max_static_thrust_lb)
    st.session_state["phys_wing_area"] = area
    st.session_state["phys_wing_span"] = span
    st.session_state["phys_flap_area"] = 0.17 * area
    st.session_state["phys_slat_area"] = 0.08 * area
    st.session_state["phys_nose_wheels"] = (
        preset.nose_wheel_count if preset else 2)
    st.session_state["phys_main_wheels"] = main_wheels
    st.session_state["phys_nose_wheel_d"] = (
        preset.nose_wheel_diameter_m if preset else 0.75)
    st.session_state["phys_main_wheel_d"] = (
        preset.main_wheel_diameter_m if preset else 1.1)
    st.session_state["phys_fan_diameter_basic"] = fan_diameter
    st.session_state["phys_fan_blades_basic"] = (
        preset.fan_blades if preset else 24)
    st.session_state.pop("physics_result", None)


def _apply_physics_preset():
    """Backward-compatible standalone preset callback."""
    key = st.session_state.get("phys_preset_select", "__current__")
    if key == "__current__":
        st.session_state.pop("phys_active_preset", None)
        st.session_state.pop("physics_result", None)
        return
    preset = PHYSICS_PRESETS[key]
    st.session_state["phys_active_preset"] = key
    _apply_physics_preset_values(preset)


def _preset_aircraft(preset):
    return ParametricAircraft(
        name=preset.description,
        engine_type="Jet",
        n_engines=preset.n_engines,
        max_static_thrust_lb=preset.max_thrust_lbf,
        bypass_ratio=preset.bpr,
        fan_diameter_m=preset.fan_diameter_m,
        mtow_lb=preset.mtow_lb,
        mlw_lb=preset.mlw_lb,
        wing_area_m2=preset.estimated_wing_area_m2,
        wing_span_m=preset.wing_span_m,
        n_main_gear_wheels=preset.main_wheel_count,
        noise_chapter=preset.noise_chapter,
    )


def _matching_active_preset(ac):
    """Return the active preset only while the shared form still matches it."""
    preset = PHYSICS_PRESETS.get(
        st.session_state.get("phys_active_preset"))
    if preset is None:
        return None
    expected = _preset_aircraft(preset)
    numeric_fields = (
        "n_engines", "max_static_thrust_lb", "mtow_lb", "mlw_lb",
        "noise_chapter", "bypass_ratio", "fan_diameter_m", "wing_area_m2",
        "wing_span_m", "n_main_gear_wheels",
    )
    for field in numeric_fields:
        actual_value = getattr(ac, field)
        expected_value = getattr(expected, field)
        if actual_value is None or expected_value is None:
            if actual_value != expected_value:
                return None
        elif not np.isclose(
                float(actual_value), float(expected_value), rtol=1e-8,
                atol=1e-8):
            return None
    return preset


def _preset_input_status(preset):
    """Map source fields to the names emitted by PhysicsDesign diagnostics."""
    aliases = {
        "wing_span_m": ("span_m", "airframe.wing_span_m"),
        "fan_diameter_m": ("fan_diameter_m",),
        "fan_blades": ("blade_count",),
        "bpr": ("bypass_ratio",),
        "nose_wheel_count": ("airframe.nose_wheel_count",),
        "main_wheel_count": ("airframe.main_wheel_count",),
        "nose_wheel_diameter_m": (
            "airframe.nose_wheel_diameter_m",),
        "main_wheel_diameter_m": (
            "airframe.main_wheel_diameter_m",),
    }
    statuses = {}
    for source in preset.sources:
        for field in source.fields:
            for name in aliases.get(field, (field,)):
                statuses[name] = InputStatus(
                    "supplied", True, source.title)
    statuses["wing_area_m2"] = InputStatus(
        "estimated", False,
        "derived from published span with assumed aspect ratio 9")
    statuses["airframe.wing_area_m2"] = statuses["wing_area_m2"]
    statuses["thrust"] = InputStatus(
        "supplied", True, "local EASA ANP v6.3 aircraft row")
    if "blade_count" not in statuses:
        statuses["blade_count"] = InputStatus(
            "estimated", False,
            "public fan-blade count unavailable; model default retained")
    for field in ("nose_wheel_diameter_m", "main_wheel_diameter_m"):
        alias = aliases[field][0]
        if alias not in statuses:
            statuses[alias] = InputStatus(
                "estimated", False,
                "representative wheel diameter; public value unavailable")
    return statuses


def _physics_design_from_form(ac, values):
    """Build the typed physics boundary without using learned-model outputs."""
    airframe_status = (
        "supplied" if values["airframe_supplied"] else "estimated")
    airframe_note = (
        "user-declared geometry"
        if airframe_status == "supplied"
        else "concept-stage UI estimate")
    airframe = AirframePhysicalInputs(
        wing_area_m2=_physical(
            values["wing_area_m2"], airframe_status, airframe_note),
        wing_span_m=_physical(
            values["wing_span_m"], airframe_status, airframe_note),
        flap_area_m2=_physical(
            values["flap_area_m2"], airframe_status, airframe_note),
        flap_chord_m=_physical(
            values["flap_chord_m"], airframe_status, airframe_note),
        flap_deflection_deg=_physical(
            values["flap_deflection_deg"], airframe_status, airframe_note),
        slat_area_m2=_physical(
            values["slat_area_m2"], airframe_status, airframe_note),
        slat_chord_m=_physical(
            values["slat_chord_m"], airframe_status, airframe_note),
        slat_deflection_deg=_physical(
            values["slat_deflection_deg"], airframe_status, airframe_note),
        nose_wheel_count=_physical(
            values["nose_wheel_count"], airframe_status, airframe_note),
        nose_wheel_diameter_m=_physical(
            values["nose_wheel_diameter_m"], airframe_status, airframe_note),
        nose_strut_diameter_m=_physical(
            values["nose_strut_diameter_m"], airframe_status, airframe_note),
        main_wheel_count=_physical(
            values["main_wheel_count"], airframe_status, airframe_note),
        main_wheel_diameter_m=_physical(
            values["main_wheel_diameter_m"], airframe_status, airframe_note),
        main_strut_diameter_m=_physical(
            values["main_strut_diameter_m"], airframe_status, airframe_note),
        gear_down=_physical(
            values["gear_down"], airframe_status, airframe_note),
    )
    atmosphere = AtmosphericPhysicalInputs(
        temperature_c=_physical(
            values["temperature_c"], "supplied", "physics UI input"),
        relative_humidity_percent=_physical(
            values["relative_humidity_percent"], "supplied",
            "physics UI input"),
        pressure_kpa=_physical(
            values["pressure_kpa"], "supplied", "physics UI input"),
    )

    engine = None
    if values["use_engine_detail"]:
        engine_status = values["engine_status"]
        engine_note = (
            "user-declared engine-deck input"
            if engine_status == "supplied"
            else "concept-stage UI estimate")
        engine = EnginePhysicalInputs(
            thrust_n=_physical(
                values["thrust_lbf"] * N_PER_LBF,
                engine_status, engine_note),
            bypass_ratio=_physical(
                values["bpr"], engine_status, engine_note),
            mass_flow_kg_s=_physical(
                values["mass_flow_kg_s"], engine_status, engine_note),
            nozzle_exit_area_m2=_physical(
                values["nozzle_exit_area_m2"], engine_status, engine_note),
            nozzle_exit_velocity_ms=_physical(
                values["nozzle_exit_velocity_ms"],
                engine_status, engine_note),
            nozzle_exit_temperature_k=_physical(
                values["nozzle_exit_temperature_k"],
                engine_status, engine_note),
            nozzle_exit_pressure_pa=_physical(
                values["nozzle_exit_pressure_kpa"] * 1000.0,
                engine_status, engine_note),
            fan_diameter_m=_physical(
                values["fan_diameter_m"], engine_status, engine_note),
            rpm=_physical(values["rpm"], engine_status, engine_note),
            n1_percent=_physical(
                values["n1_percent"], engine_status, engine_note),
            blade_count=_physical(
                values["blade_count"], engine_status, engine_note),
            stator_count=_physical(
                values["stator_count"], engine_status, engine_note),
            rotor_stator_spacing_m=_physical(
                values["rotor_stator_spacing_m"],
                engine_status, engine_note),
            fan_temperature_rise_k=_physical(
                values["fan_temperature_rise_k"],
                engine_status, engine_note),
            core_mass_flow_kg_s=_physical(
                values["core_mass_flow_kg_s"],
                engine_status, engine_note),
            combustor_inlet_temperature_k=_physical(
                values["combustor_inlet_temperature_k"],
                engine_status, engine_note),
            combustor_exit_temperature_k=_physical(
                values["combustor_exit_temperature_k"],
                engine_status, engine_note),
            turbine_attenuation_db=_physical(
                values["turbine_attenuation_db"],
                engine_status, engine_note),
        )

    return PhysicsDesign(
        ac.name, values["n_engines"], values["max_thrust_lbf"],
        values["bpr"], values["mtow_lb"],
        wing_area_m2=values["wing_area_m2"],
        span_m=values["wing_span_m"],
        fan_diameter_m=values["fan_diameter_m"],
        n_fan_blades=values["blade_count"],
        n_wheels=values["main_wheel_count"],
        wheel_d_m=values["main_wheel_diameter_m"],
        engine_physical_inputs=engine,
        airframe_physical_inputs=airframe,
        atmospheric_inputs=atmosphere,
        input_status=values.get("input_status"),
    )


def _status_frame(statuses):
    return pd.DataFrame([
        {
            "Input/source": name,
            "Evidence": status.source,
            "Complete": "yes" if status.complete else "no",
            "Note": status.note,
        }
        for name, status in sorted(statuses.items())
    ])


def page_physics(*, embedded=False, compare_learned=True):
    pred = _require_prediction()
    if pred is None:
        return

    if embedded:
        st.subheader("3. Component physics event")
    else:
        st.header("Component physics")
    st.caption(
        "Run the independent, frozen-calibration component model directly. "
        + (
            "ET/RF levels are shown only as an output comparison; they are "
            "never inputs to the physics calculation. "
            if compare_learned else
            "No learned-model overlay is displayed in physics-only mode. ")
        + "Scope: SEL and LAmax.")
    st.warning(
        "Conceptual screening only—not certification. EPNL/PNLTM, tone "
        "corrections, installation shielding, ground reflection and terrain "
        "are not modeled.")

    if not embedded:
        preset_options = ["__current__", *PHYSICS_PRESETS]
        p1, p2 = st.columns([3, 1])
        with p1:
            st.selectbox(
                "v6.3 physical-specification preset",
                preset_options,
                format_func=lambda key: (
                    "Current predicted aircraft"
                    if key == "__current__" else PHYSICS_PRESETS[key].label),
                key="phys_preset_select",
                help="Presets are limited to aircraft in the local EASA ANP "
                     "v6.3 corpus and retain field-level source status.")
        with p2:
            st.button(
                "Apply preset", on_click=_apply_physics_preset,
                width="stretch")

    ac = pred.aircraft
    preset = _matching_active_preset(ac)
    if preset:
        st.success(
            f"Physics aircraft matches the shared **{preset.label}** "
            "definition used by ET/RF.")

    default_bpr = float(ac.bypass_ratio or 6.0)
    default_area = float(ac.wing_area_m2 or ac.mtow_lb * KG_PER_LB / 600.0)
    default_span = float(ac.wing_span_m or np.sqrt(9.0 * default_area))
    default_fan = float(ac.fan_diameter_m or 1.8)
    default_blades = int(preset.fan_blades if preset else 24)
    default_wheels = int(ac.n_main_gear_wheels or
                         (4 if ac.mtow_lb * KG_PER_LB < 5e4 else 8))

    c1, c2 = st.columns(2)
    with c1:
        op_mode = st.radio(
            "Operation", ["D", "A"], horizontal=True, key="phys_op_mode",
            format_func=lambda x: "Departure" if x == "D" else "Approach")
    table_key = ("SEL", op_mode)
    table = None if preset else pred.tables.get(table_key)
    default_thrust = float(
        (table.P[-1] if op_mode == "D" else table.P[0])
        if table is not None else
        ac.max_static_thrust_lb * (0.85 if op_mode == "D" else 0.2))
    with c2:
        bpr = float(st.number_input(
            "Bypass ratio", min_value=0.0, max_value=25.0,
            value=default_bpr, step=0.1, key="phys_bpr"))
    c3, c4 = st.columns(2)
    with c3:
        if _is_metric():
            thrust_lbf = kn_to_lbf(float(st.number_input(
                "Event thrust [kN/engine]", min_value=0.1,
                max_value=max(600.0, lbf_to_kn(ac.max_static_thrust_lb * 1.25)),
                value=lbf_to_kn(default_thrust), step=1.0,
                key="phys_thrust_metric")))
        else:
            thrust_lbf = float(st.number_input(
                "Event thrust [lb/engine]", min_value=1.0,
                max_value=max(130000.0, ac.max_static_thrust_lb * 1.25),
                value=default_thrust, step=100.0,
                key="phys_thrust_imperial"))
    with c4:
        if _is_metric():
            distance_ft = m_to_ft(float(st.number_input(
                "Closest distance [m]", min_value=30.0, max_value=100000.0,
                value=ft_to_m(1000.0), step=50.0,
                key="phys_distance_metric")))
        else:
            distance_ft = float(st.number_input(
                "Closest distance [ft]", min_value=100.0, max_value=300000.0,
                value=1000.0, step=100.0,
                key="phys_distance_imperial"))

    values = {
        "n_engines": int(ac.n_engines),
        "max_thrust_lbf": float(ac.max_static_thrust_lb),
        "mtow_lb": float(ac.mtow_lb),
        "bpr": bpr,
        "thrust_lbf": thrust_lbf,
        "wing_area_m2": default_area,
        "wing_span_m": default_span,
        "fan_diameter_m": default_fan,
        "blade_count": default_blades,
        "main_wheel_count": default_wheels,
        "main_wheel_diameter_m": 1.1,
        "use_engine_detail": False,
        "input_status": (
            _preset_input_status(preset) if preset is not None else None),
    }

    with st.expander("Airframe, configuration and atmosphere"):
        st.caption(
            "These values drive the six airframe components and atmospheric "
            "absorption. Mark them supplied only when they come from an "
            "aircraft definition or geometry source.")
        values["airframe_supplied"] = st.checkbox(
            "Treat airframe values as supplied evidence",
            key="phys_airframe_supplied")
        a1, a2, a3 = st.columns(3)
        with a1:
            values["wing_area_m2"] = float(st.number_input(
                "Wing area [m²]", min_value=1.0, max_value=1500.0,
                value=default_area, step=1.0, key="phys_wing_area"))
            values["wing_span_m"] = float(st.number_input(
                "Wing span [m]", min_value=1.0, max_value=120.0,
                value=default_span, step=0.5, key="phys_wing_span"))
            values["flap_area_m2"] = float(st.number_input(
                "Flap area [m²]", min_value=0.1, max_value=500.0,
                value=0.17 * default_area, step=0.5,
                key="phys_flap_area"))
            values["flap_chord_m"] = float(st.number_input(
                "Flap chord [m]", min_value=0.1, max_value=15.0,
                value=2.0, step=0.1, key="phys_flap_chord"))
            values["flap_deflection_deg"] = float(st.number_input(
                "Flap deflection [deg]", min_value=0.0, max_value=60.0,
                value=10.0 if op_mode == "D" else 30.0, step=1.0,
                key="phys_flap_deg"))
        with a2:
            values["slat_area_m2"] = float(st.number_input(
                "Slat area [m²]", min_value=0.1, max_value=300.0,
                value=0.08 * default_area, step=0.5,
                key="phys_slat_area"))
            values["slat_chord_m"] = float(st.number_input(
                "Slat chord [m]", min_value=0.05, max_value=8.0,
                value=0.7, step=0.05, key="phys_slat_chord"))
            values["slat_deflection_deg"] = float(st.number_input(
                "Slat deflection [deg]", min_value=0.0, max_value=60.0,
                value=20.0, step=1.0, key="phys_slat_deg"))
            values["nose_wheel_count"] = int(st.number_input(
                "Nose wheels", min_value=1, max_value=8, value=2,
                step=1, key="phys_nose_wheels"))
            values["main_wheel_count"] = int(st.number_input(
                "Main wheels", min_value=1, max_value=32,
                value=default_wheels, step=1, key="phys_main_wheels"))
            values["fan_diameter_m"] = float(st.number_input(
                "Fan diameter [m]", min_value=0.1, max_value=8.0,
                value=default_fan, step=0.05,
                key="phys_fan_diameter_basic"))
            values["blade_count"] = int(st.number_input(
                "Fan blades", min_value=2, max_value=100,
                value=default_blades, step=1,
                key="phys_fan_blades_basic"))
        with a3:
            values["nose_wheel_diameter_m"] = float(st.number_input(
                "Nose-wheel diameter [m]", min_value=0.1, max_value=3.0,
                value=0.75, step=0.05, key="phys_nose_wheel_d"))
            values["nose_strut_diameter_m"] = float(st.number_input(
                "Nose-strut diameter [m]", min_value=0.01, max_value=1.0,
                value=0.09, step=0.01, key="phys_nose_strut_d"))
            values["main_wheel_diameter_m"] = float(st.number_input(
                "Main-wheel diameter [m]", min_value=0.1, max_value=3.0,
                value=1.1, step=0.05, key="phys_main_wheel_d"))
            values["main_strut_diameter_m"] = float(st.number_input(
                "Main-strut diameter [m]", min_value=0.01, max_value=1.0,
                value=0.16, step=0.01, key="phys_main_strut_d"))
            values["gear_down"] = st.checkbox(
                "Landing gear down", value=(op_mode == "A"),
                key="phys_gear_down")

        e1, e2, e3 = st.columns(3)
        with e1:
            values["temperature_c"] = float(st.number_input(
                "Temperature [°C]", min_value=-60.0, max_value=60.0,
                value=15.0, step=1.0, key="phys_temperature"))
        with e2:
            values["relative_humidity_percent"] = float(st.number_input(
                "Relative humidity [%]", min_value=1.0, max_value=100.0,
                value=70.0, step=1.0, key="phys_humidity"))
        with e3:
            values["pressure_kpa"] = float(st.number_input(
                "Pressure [kPa]", min_value=50.0, max_value=120.0,
                value=101.325, step=0.1, key="phys_pressure"))

    with st.expander("Detailed engine-deck inputs (optional)"):
        values["use_engine_detail"] = st.checkbox(
            "Enable typed mixed-jet, fan and core inputs",
            key="phys_use_engine_detail")
        st.caption(
            "Disabled: the model estimates mixed-jet and fan state from "
            "thrust/BPR and omits core noise. Enabled: complete fields activate "
            "the detailed fan and optional core paths; the jet remains the "
            "mixed-nozzle path unless multi-stream engine-deck data exist.")
        if values["use_engine_detail"]:
            evidence = st.radio(
                "Engine input evidence",
                ["Estimated concept values", "Supplied engine-deck values"],
                horizontal=True, key="phys_engine_evidence")
            values["engine_status"] = (
                "supplied" if evidence.startswith("Supplied") else "estimated")
            g1, g2, g3 = st.columns(3)
            with g1:
                values["mass_flow_kg_s"] = float(st.number_input(
                    "Engine mass flow [kg/s]", 1.0, 2500.0, 450.0, 5.0,
                    key="phys_mass_flow"))
                values["nozzle_exit_area_m2"] = float(st.number_input(
                    "Nozzle exit area [m²]", 0.01, 20.0, 1.5, 0.05,
                    key="phys_nozzle_area"))
                values["nozzle_exit_velocity_ms"] = float(st.number_input(
                    "Nozzle exit velocity [m/s]", 10.0, 1500.0, 300.0, 5.0,
                    key="phys_nozzle_velocity"))
                values["nozzle_exit_temperature_k"] = float(st.number_input(
                    "Nozzle exit temperature [K]", 150.0, 2500.0, 450.0, 10.0,
                    key="phys_nozzle_temperature"))
                values["nozzle_exit_pressure_kpa"] = float(st.number_input(
                    "Nozzle total pressure [kPa]", 10.0, 3000.0, 160.0, 5.0,
                    key="phys_nozzle_pressure"))
            with g2:
                values["fan_diameter_m"] = float(st.number_input(
                    "Fan diameter [m]", 0.1, 8.0, default_fan, 0.05,
                    key="phys_fan_diameter"))
                values["rpm"] = float(st.number_input(
                    "Fan speed [rpm]", 100.0, 30000.0, 3500.0, 100.0,
                    key="phys_rpm"))
                values["n1_percent"] = float(st.number_input(
                    "N1 [%]", 1.0, 120.0, 90.0, 1.0, key="phys_n1"))
                values["blade_count"] = int(st.number_input(
                    "Fan blades", 2, 100, default_blades, 1,
                    key="phys_blades"))
                values["stator_count"] = int(st.number_input(
                    "Stator vanes", 2, 200, 40, 1, key="phys_stators"))
                values["rotor_stator_spacing_m"] = float(st.number_input(
                    "Rotor–stator spacing [m]", 0.001, 2.0, 0.12, 0.01,
                    key="phys_rotor_stator_spacing"))
                values["fan_temperature_rise_k"] = float(st.number_input(
                    "Fan temperature rise [K]", 1.0, 500.0, 65.0, 5.0,
                    key="phys_fan_temp_rise"))
            with g3:
                values["core_mass_flow_kg_s"] = float(st.number_input(
                    "Core mass flow [kg/s]", 0.1, 1000.0, 55.0, 1.0,
                    key="phys_core_mass_flow"))
                values["combustor_inlet_temperature_k"] = float(
                    st.number_input(
                        "Combustor inlet temperature [K]", 150.0, 2500.0,
                        700.0, 10.0, key="phys_combustor_inlet"))
                values["combustor_exit_temperature_k"] = float(
                    st.number_input(
                        "Combustor exit temperature [K]", 200.0, 3500.0,
                        1350.0, 10.0, key="phys_combustor_exit"))
                values["turbine_attenuation_db"] = float(st.number_input(
                    "Turbine attenuation [dB]", 0.0, 80.0, 18.0, 1.0,
                    key="phys_turbine_attenuation"))

    physics_clicked = st.button(
        "Run component physics", type="primary",
        width="stretch", key="phys_run")
    physics_log_slot = st.empty()
    if physics_clicked:
        calc_log = _CalculationLog(
            "physics",
            f"Component physics · {op_mode} event",
            physics_log_slot)
        try:
            calc_log.add(
                "BOUNDARY",
                f"Convert {thrust_lbf:,.0f} lb/engine and "
                f"{distance_ft:,.0f} ft to SI at the physics boundary")
            design = _physics_design_from_form(ac, values)
            calc_log.add(
                "DESIGN",
                f"Typed PhysicsDesign: BPR={design.bpr:.2f}, "
                f"wing={design.wing_area_m2:.1f} m², "
                f"span={design.span_m:.1f} m, engines={design.n_engines}")
            calc_log.add(
                "CALIBRATION",
                "Resolve frozen A320-211 jet/fan/airframe source anchors")
            calc_log.add(
                "SOURCES",
                "Evaluate mixed jet, fan, optional core and six airframe "
                "sources over 69 emission angles")
            with st.spinner(
                    "Running frozen-calibration component physics..."):
                working_pred = pred
                if preset is not None and not embedded:
                    meta = st.session_state["pred_meta"]
                    calc_log.add(
                        "SYNC",
                        "Recalculate learned tables for the selected physics "
                        "aircraft before comparison")
                    working_pred = get_predictor(
                        meta["model"], meta["version"]).predict(ac)
                diagnostics = working_pred.physics_diagnostics(
                    design, thrust_lbf, op_mode, distance_ft)
                calc_log.add(
                    "PROPAGATE",
                    "Apply spherical spreading, ISO-style atmospheric "
                    "absorption and A-weighting to each component spectrum")
                calc_log.add(
                    "ENERGY SUM",
                    f"Combine {len(diagnostics.component_time_histories_db)} "
                    "component histories in linear acoustic energy")
                calc_log.add(
                    "EVENT METRIC",
                    "LAmax=max(LA(t)); "
                    "SEL=10log10(∫10^(LA(t)/10)dt)")
                physics_tables = {}
                for metric in ("SEL", "LAmax"):
                    calc_log.add(
                        "PHYSICS NPD",
                        f"Generate {metric}/{op_mode} at "
                        f"{thrust_lbf:,.0f} lb/engine across 10 distances")
                    physics_tables[metric] = working_pred.physics_table(
                        design, metric, op_mode, [thrust_lbf])
                learned_tables = {
                    metric: (
                        working_pred.tables.get((metric, op_mode))
                        if compare_learned else None)
                    for metric in ("SEL", "LAmax")
                }
                if compare_learned:
                    calc_log.add(
                        "COMPARE",
                        "Interpolate ET/RF at identical thrust and distance "
                        "coordinates; learned values never enter physics")
        except (RuntimeError, ValueError, FloatingPointError) as exc:
            calc_log.fail(str(exc))
            st.error(f"Physics calculation could not run: {exc}")
        else:
            st.session_state["physics_result"] = {
                "aircraft": ac.name,
                "op_mode": op_mode,
                "thrust_lbf": thrust_lbf,
                "distance_ft": distance_ft,
                "diagnostics": diagnostics,
                "tables": physics_tables,
                "learned_tables": learned_tables,
                "preset": preset.key if preset is not None else None,
                "compare_learned": compare_learned,
            }
            calc_log.finish(
                f"SEL={diagnostics.sel_db:.1f} dB; "
                f"LAmax={diagnostics.lamax_db:.1f} dB(A)")
    else:
        _render_saved_calculation_log("physics", physics_log_slot)

    result = st.session_state.get("physics_result")
    if (result is None
            or result.get("aircraft") != ac.name
            or result.get("compare_learned") != compare_learned):
        st.info("Set the event inputs and press **Run component physics**.")
        return

    diagnostics = result["diagnostics"]
    op_mode = result["op_mode"]
    thrust_lbf = result["thrust_lbf"]
    distance_ft = result["distance_ft"]
    learned_levels = {}
    mean_deltas = {}
    for metric in ("SEL", "LAmax"):
        learned = result["learned_tables"].get(metric)
        if learned is not None:
            learned_levels[metric] = learned.level(thrust_lbf, distance_ft)
            physics_curve = result["tables"][metric].L[0]
            learned_curve = np.array([
                learned.level(thrust_lbf, distance)
                for distance in STANDARD_DISTANCES_FT
            ])
            mean_deltas[metric] = float(
                np.mean(np.abs(physics_curve - learned_curve)))

    st.divider()
    if compare_learned:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Physics SEL", f"{diagnostics.sel_db:.1f} dB",
                  help="Time-integrated A-weighted exposure level.")
        m2.metric("Physics LAmax", f"{diagnostics.lamax_db:.1f} dB(A)",
                  help="Maximum A-weighted level during the event.")
        m3.metric(
            f"Physics − {st.session_state['pred_meta']['model'].upper()} SEL",
            (f"{diagnostics.sel_db - learned_levels['SEL']:+.1f} dB"
             if "SEL" in learned_levels else "n/a"))
        m4.metric(
            f"Physics − {st.session_state['pred_meta']['model'].upper()} LAmax",
            (f"{diagnostics.lamax_db - learned_levels['LAmax']:+.1f} dB"
             if "LAmax" in learned_levels else "n/a"))
    else:
        m1, m2 = st.columns(2)
        m1.metric("Physics SEL", f"{diagnostics.sel_db:.1f} dB",
                  help="Time-integrated A-weighted exposure level.")
        m2.metric("Physics LAmax", f"{diagnostics.lamax_db:.1f} dB(A)",
                  help="Maximum A-weighted level during the event.")
    st.caption(
        f"Event: {op_mode} · {_power_disp(thrust_lbf):,.1f} "
        f"{_power_label()} · {ft_to_m(distance_ft):,.0f} m / "
        f"{distance_ft:,.0f} ft closest "
        "distance. Differences are diagnostics, not acceptance criteria.")

    curve_metric = st.radio(
        "NPD curve metric", ["SEL", "LAmax"], horizontal=True,
        key="phys_curve_metric")
    physics_table = result["tables"][curve_metric]
    physics_curve = physics_table.L[0]
    x = _dist_x()
    fig, ax = plt.subplots(figsize=(8.0, 4.6))
    ax.semilogx(
        x, physics_curve, "o-", lw=2.2, color="#2b6cb0",
        label="Component physics")
    learned = result["learned_tables"].get(curve_metric)
    if learned is not None:
        learned_curve = np.array([
            learned.level(thrust_lbf, distance)
            for distance in STANDARD_DISTANCES_FT
        ])
        ax.semilogx(
            x, learned_curve, "s--", lw=1.7, color=FUTURE_COLOR,
            label=f"{st.session_state['pred_meta']['model'].upper()} overlay")
    ax.set_xlabel(_dist_label())
    ax.set_ylabel(f"{curve_metric} [dB]")
    ax.set_title(
        f"{curve_metric}/{op_mode} at {_power_disp(thrust_lbf):,.1f} "
        f"{_power_label()}", fontsize=10)
    ax.grid(True, which="both", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    if curve_metric in mean_deltas:
        st.caption(
            f"Mean absolute physics–"
            f"{st.session_state['pred_meta']['model'].upper()} difference "
            f"across the ten standard distances: "
            f"{mean_deltas[curve_metric]:.2f} dB.")

    st.subheader("Component contributions")
    component_rows = [
        {
            "Component": name.replace("_", " ").title(),
            "SEL [dB]": metrics["SEL"],
            "LAmax [dB(A)]": metrics["LAmax"],
        }
        for name, metrics in diagnostics.component_metrics_db.items()
    ]
    component_df = pd.DataFrame(component_rows).sort_values(
        "LAmax [dB(A)]", ascending=False)
    st.dataframe(
        component_df.style.format(
            {"SEL [dB]": "{:.1f}", "LAmax [dB(A)]": "{:.1f}"}),
        width="stretch", hide_index=True)

    fig, ax = plt.subplots(figsize=(8.0, 4.6))
    ax.plot(
        diagnostics.time_s, diagnostics.total_time_history_db,
        color="black", lw=2.2, label="Total")
    ranked_components = sorted(
        diagnostics.component_time_histories_db,
        key=lambda name:
        diagnostics.component_metrics_db[name]["LAmax"],
        reverse=True)[:5]
    for name in ranked_components:
        ax.plot(
            diagnostics.time_s,
            diagnostics.component_time_histories_db[name],
            lw=1.2, alpha=0.8, label=name.replace("_", " "))
    ax.set_xlabel("Event time [s]")
    ax.set_ylabel("A-weighted level [dB(A)]")
    ax.set_title("Received component time histories", fontsize=10)
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    with st.expander("Input evidence and model boundaries"):
        st.markdown("**Source-path status**")
        st.dataframe(
            _status_frame(diagnostics.source_status),
            width="stretch", hide_index=True)
        st.markdown("**Input provenance**")
        st.dataframe(
            _status_frame(diagnostics.input_status),
            width="stretch", hide_index=True)
        st.warning(
            "Excluded effects: "
            + ", ".join(effect.replace("_", " ")
                        for effect in diagnostics.excluded_effects))
        st.caption(diagnostics.uncertainty_note)


# ===========================================================================
# Page: Operations (departure synthesis)
# ===========================================================================

def page_operations():
    pred = _require_prediction()
    if pred is None:
        return
    version = data_version()
    db = get_db(version)
    if db.dep_steps is None:
        st.error("Departure procedural steps are not loaded in this "
                 "datastore — synthesis is unavailable.")
        return
    meta = st.session_state["pred_meta"]
    acd = meta["aircraft"]
    st.header("Operations — departure synthesis")
    st.caption("Borrows a real donor aircraft's departure procedure and "
               "rescales its thrust deck for the predicted aircraft "
               "(SAE-AIR-1845-style synthesis, mirroring `pnmf_cli.py demo`).")

    usable = set(db.dep_steps["ACFT_ID"].unique())
    match = db.nearest_aircraft(acd["mtow_lb"], engine_type=acd["engine_type"],
                                n_engines=acd["n_engines"], n=5,
                                restrict_to=usable)
    if match.empty:
        st.error("No donor aircraft with departure procedural steps found "
                 "for this aircraft's class.")
        return

    donor_labels = [
        f"{r['ACFT_ID']} (MTOW {r['Max Gross Takeoff Weight (lb)']:.0f} lb)"
        for _, r in match.iterrows()]
    donor_map = dict(zip(donor_labels, match["ACFT_ID"]))
    donor_label = st.selectbox("Donor aircraft", donor_labels, key="ops_donor")
    donor_id = donor_map[donor_label]
    donor_thrust = float(match[match["ACFT_ID"] == donor_id]
                         ["Max Sea Level Static Thrust (lb)"].iloc[0])

    c1, c2, c3 = st.columns(3)
    with c1:
        frac = st.slider("Weight fraction of MTOW", 0.60, 1.00, 0.85, 0.01,
                         key="ops_frac")
    with c2:
        stages = sorted(db.dep_steps[db.dep_steps["ACFT_ID"] == donor_id]
                        ["Stage Length"].astype(str).unique())
        stage = str(st.selectbox("Stage length", stages,
                                 index=(stages.index("1") if "1" in stages
                                        else 0),
                                 key="ops_stage"))
    with c3:
        d_metrics = sorted(m for (m, om) in pred.tables if om == "D")
        metric = str(st.selectbox(
            "Metric", d_metrics,
            index=(d_metrics.index("LAmax") if "LAmax" in d_metrics else 0),
            key="ops_metric", help=_metric_help()))

    c4, c5 = st.columns(2)
    with c4:
        observer_x = st.number_input("Observer along-track [ft]",
                                     min_value=0.0, value=20000.0,
                                     step=1000.0, key="ops_x")
    with c5:
        lateral = st.number_input("Lateral offset [ft]", min_value=0.0,
                                  value=1476.0, step=50.0, key="ops_lat")

    if st.button("Synthesize", type="primary"):
        try:
            scale = acd["max_static_thrust_lb"] / donor_thrust
            prof = DepartureSynthesizer(db).synthesize(
                donor_id, stage_length=stage, weight_lb=frac * acd["mtow_lb"],
                thrust_scale=scale, out_name=meta["name"])
        except (ValueError, RuntimeError) as e:
            st.error(f"Synthesis failed: {e}")
            return
        st.session_state["ops_profile"] = prof
        st.session_state["ops_profile_donor"] = donor_id

    prof = st.session_state.get("ops_profile")
    if prof is None:
        st.info("Press **Synthesize** to generate a departure profile.")
        return

    tbl = pred.tables.get((metric, "D"))
    if tbl is None:
        st.warning(f"No {metric}/D table in the current prediction.")
        return

    ref_donor_id = st.session_state.get("ops_profile_donor", donor_id)

    fig, (axa, axt) = plt.subplots(2, 1, figsize=(7.5, 6.0), sharex=True)
    axa.plot(prof.points["distance_ft"], prof.points["altitude_ft"], "o-",
             color="#c53030")
    axa.set_ylabel("altitude AFE [ft]")
    axa.set_title(f"Synthesized departure profile — {meta['name']} "
                  f"(donor {ref_donor_id})", fontsize=10)
    axa.grid(True, alpha=0.3)
    axt.plot(prof.points["distance_ft"], prof.points["thrust"], "o-",
             color="#2b6cb0")
    axt.set_xlabel("along-track distance [ft]")
    axt.set_ylabel("thrust [lb/engine]")
    axt.grid(True, alpha=0.3)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    level = prof.flyover_level(tbl, observer_x, lateral)
    st.metric(f"{metric} at observer ({observer_x:.0f} ft along-track, "
             f"{lateral:.0f} ft lateral)", f"{level:.1f} dB")

    xs = np.linspace(2000, 80000, 60)
    future_levels = [prof.flyover_level(tbl, float(x), lateral) for x in xs]
    fig2, ax2 = plt.subplots(figsize=(7.5, 4.2))
    ax2.plot(xs, future_levels, "-", color="#c53030", lw=1.8,
            label=f"{meta['name']} (generated NPD)")

    arow = db.aircraft[db.aircraft["ACFT_ID"] == ref_donor_id]
    if not arow.empty and pd.notna(arow["NPD_ID"].iloc[0]):
        donor_npd_id = str(arow["NPD_ID"].iloc[0])
        cv = db.curve(donor_npd_id, metric, "D")
        if not cv.empty:
            donor_tbl = NPDTable(cv["Power Setting"].values.astype(float),
                                 cv[DIST_COLS].values, metric, "D",
                                 npd_id=donor_npd_id)
            donor_levels = [prof.flyover_level(donor_tbl, float(x), lateral)
                            for x in xs]
            ax2.plot(xs, donor_levels, "-", color="#2b6cb0", lw=1.6,
                    label=f"{ref_donor_id} (ANP truth NPD)")
    ax2.set_xlabel("observer along-track position [ft]")
    ax2.set_ylabel(f"single-event {metric} [dB]")
    ax2.set_title("Flyover level sweep", fontsize=10)
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=8)
    fig2.tight_layout()
    st.pyplot(fig2)
    plt.close(fig2)


# ===========================================================================
# Page: Fleet explorer / validation
# ===========================================================================

def page_fleet():
    version = data_version()
    db = get_db(version)
    pt = get_param_table(version)
    st.header("Fleet explorer / validation")

    s = db.summary()
    m1, m2, m3 = st.columns(3)
    m1.metric("Aircraft", s["n_aircraft"])
    m2.metric("NPD sets", s["n_npd_sets"])
    m3.metric("Metrics", len(s["metrics"]))
    st.caption("Engine types: " + ", ".join(
        f"{k}: {v}" for k, v in s["engine_types"].items()))

    st.divider()
    st.subheader("Aircraft browser")
    a = db.aircraft
    mtow_col = "Max Gross Takeoff Weight (lb)"
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        etypes = st.multiselect("Engine type",
                                sorted(a["Engine Type"].dropna().unique()),
                                key="fleet_etype")
    with c2:
        mtow_range = st.slider("MTOW [lb]", 1.0e3, 1.5e6,
                               (1.0e3, 1.5e6), key="fleet_mtow")
    with c3:
        name_filter = st.text_input("Name contains", key="fleet_name")

    filt = a.copy()
    if etypes:
        filt = filt[filt["Engine Type"].isin(etypes)]
    filt = filt[(filt[mtow_col] >= mtow_range[0]) &
               (filt[mtow_col] <= mtow_range[1])]
    if name_filter:
        pat = name_filter.lower()
        filt = filt[filt["ACFT_ID"].str.lower().str.contains(pat, na=False) |
                   filt["Description"].str.lower().str.contains(pat, na=False)]
    browse_cols = ["ACFT_ID", "Description", "Engine Type",
                  "Number Of Engines", "Max Gross Takeoff Weight (lb)",
                  "Max Gross Landing Weight (lb)",
                  "Max Sea Level Static Thrust (lb)", "Noise Chapter",
                  "Power Parameter"]
    st.dataframe(filt[browse_cols], width="stretch", hide_index=True)
    st.caption(f"{len(filt)} of {len(a)} aircraft shown.")

    st.divider()
    st.subheader("NPD curve browser")
    label_map = _label_map(pt)
    label = st.selectbox("Aircraft", list(label_map), key="fleet_npd_acft")
    npd_id = label_map[label]
    c4, c5 = st.columns([2, 1])
    with c4:
        metric = st.selectbox("Metric", s["metrics"], key="fleet_npd_metric",
                              help=_metric_help())
    with c5:
        om = st.radio("Op mode", ["D", "A"], horizontal=True,
                      key="fleet_npd_om", help=GLOSSARY["D / A"])
    cv = db.curve(npd_id, metric, om)
    if cv.empty:
        st.info(f"No curves for {label} at {metric}/{om}.")
    else:
        st.dataframe(cv, width="stretch", hide_index=True)
        P = cv["Power Setting"].values.astype(float)
        Lv = cv[DIST_COLS].values
        dist_x = _dist_x()
        p_disp = _power_disp(P)
        fig, ax = plt.subplots(figsize=(7.2, 4.2))
        cmap = plt.cm.viridis(np.linspace(0, 0.8, len(P)))
        for i in range(len(P)):
            ax.semilogx(dist_x, Lv[i], "o-", color=cmap[i],
                        lw=1.4, label=f"{p_disp[i]:.0f}")
        ax.set_xlabel(_dist_label())
        ax.set_ylabel(f"{metric} [dB]")
        ax.set_title(f"{label} — {metric}/{om}", fontsize=10)
        ax.grid(True, which="both", alpha=0.25)
        ax.legend(fontsize=7, ncol=2, title=f"power [{_power_label()}]")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

    st.divider()
    st.subheader("Model ranking")
    st.caption("Which prediction model to trust, ranked by **average rank** "
               "across the leave-one-aircraft-out bake-off's metric:op combos "
               "(Friedman / Nemenyi mean-rank method, Demšar 2006 — the "
               "standard way to compare several predictors over several "
               "tasks). Lower average rank is better; ranking within each "
               "combo first makes it scale-free, so an easy high-dB combo "
               "can't dominate.")
    ranked = (load_model_ranking(os.path.getmtime(_COMPARE_CSV))
              if os.path.exists(_COMPARE_CSV) else None)
    if ranked is None:
        st.info("Run `.\\pnmf.ps1 compare` to generate "
                "`outputs/algorithm_comparison.csv`, then the ranking appears "
                "here.")
    else:
        ranking_df, info = ranked
        (st.success if info["significant"] else st.info)(info["note"])
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        show = ranking_df.copy()
        show.insert(0, "", [medals.get(i, f"{i + 1}")
                            for i in range(len(show))])
        show = show.rename(columns={
            "model": "model", "avg_rank": "avg rank", "wins": "combos won",
            "mean_score": "mean med-RMSE [dB]", "best_combo": "best on",
            "worst_combo": "worst on"})
        st.dataframe(show, width="stretch", hide_index=True)
        if info["dropped"]:
            st.caption("Not ranked because a validation combo is missing: "
                       f"{', '.join(info['dropped'])}.")

        fig, ax = plt.subplots(figsize=(7.2, 0.45 * len(ranking_df) + 1.0))
        ypos = np.arange(len(ranking_df))[::-1]
        bar_colors = [FUTURE_COLOR if m == info["recommended"] else "#94a3b8"
                      for m in ranking_df["model"]]
        ax.barh(ypos, ranking_df["avg_rank"], color=bar_colors)
        for y, (_i, r) in zip(ypos, ranking_df.iterrows()):
            ax.text(r["avg_rank"], y, f" {r['avg_rank']:.2f}", va="center",
                    ha="left", fontsize=8)
        ax.set_yticks(ypos)
        ax.set_yticklabels(ranking_df["model"], fontsize=9)
        ax.set_xlabel("average rank across combos (lower = better)")
        ax.set_title("Model ranking (recommended highlighted)", fontsize=10)
        ax.grid(True, axis="x", alpha=0.25)
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

    st.divider()
    st.subheader("Validation artifacts")
    for path, label in [("outputs/validation_summary.csv",
                         "LOO validation summary"),
                        ("outputs/algorithm_comparison.csv",
                         "Algorithm bake-off")]:
        if os.path.exists(path):
            st.caption(label)
            st.dataframe(load_output_csv(path, os.path.getmtime(path)),
                        width="stretch", hide_index=True)
        else:
            cmd = "validate" if "validation" in path else "compare"
            st.info(f"{label}: run `.\\pnmf.ps1 {cmd}` to generate `{path}`.")

    st.subheader("Figure gallery")
    fig_names = ["gap_rmse_by_combo.png", "gap_per_aircraft_rmse.png",
                "physics_bpr_sweep.png", "physics_fleet_validation.png",
                "end_to_end_sideline.png", "validation_scatter_SEL_D.png"]
    fcols = st.columns(3)
    shown = 0
    for fname in fig_names:
        path = os.path.join("outputs", fname)
        if os.path.exists(path):
            with fcols[shown % 3]:
                st.image(path, caption=fname, width="stretch")
            shown += 1
    if shown == 0:
        st.info("No figures found in `outputs/` yet — run "
                "`.\\pnmf.ps1 validate` / `compare` / `physics` / `demo`.")


PAGES = {
    "Aircraft Designer": page_designer,
    "Prediction results": page_results,
    "Comparison": page_comparison,
    "Operations": page_operations,
    "Fleet explorer": page_fleet,
}


# ===========================================================================
# shell: page config, missing-db gate, sidebar, dispatch
# ===========================================================================

def _sidebar_units():
    st.radio("Units", ["Imperial (lb, ft)", "Metric (kg, m)"], key="units",
             horizontal=True,
             help="Display-only: converts thrust/weight/distance values "
                  "shown across the app. The framework always computes "
                  "internally in lb/ft (ANP convention).")


def _sidebar_status(version: str):
    st.subheader("Status")
    st.write(f"**Model:** `{st.session_state.get('f_model', DEFAULT_MODEL)}`")
    st.write("**Prediction loaded:** "
             f"{'yes' if 'prediction' in st.session_state else 'no'}")
    try:
        s = get_db(version).summary()
        st.write(f"**Aircraft:** {s['n_aircraft']} · "
                 f"**NPD sets:** {s['n_npd_sets']}")
    except Exception as e:                        # pragma: no cover
        st.write(f"db unavailable: {e}")
    st.caption(f"data version: `{version}`")


def _sidebar_how_to_use():
    with st.expander("How to use", expanded="prediction" not in st.session_state):
        st.markdown(
            "1. **Aircraft design** — select one shared preset or custom "
            "aircraft, choose learned, physics, or comparison mode, then run "
            "the analysis. Physics inputs and the same-aircraft comparison "
            "remain on this page.\n"
            "2. **Prediction results** — view the generated NPD tables "
            "and curves, download the ANP-layout CSV, optionally store "
            "the prediction into `anp_data.sqlite`.\n"
            "3. **Comparison** — overlay the predicted aircraft against "
            "its nearest real ANP neighbours.\n"
            "4. **Operations** *(optional)* — synthesize a departure "
            "flight path and read off the noise level at a ground "
            "observer.\n"
            "5. **Fleet explorer** — browse the underlying real ANP "
            "fleet and any validation artifacts, at any time, no "
            "prediction needed.\n\n"
            "Steps 2–4 need an analysis from step 1 first — each page "
            "prompts you back to **Aircraft Designer** until one exists.")


def _sidebar_glossary():
    with st.expander("Glossary"):
        st.caption("Prediction models")
        for m, d in MODEL_INFO.items():
            st.markdown(f"**{m}** — {d}")
        st.caption("Abbreviations")
        for term, d in GLOSSARY.items():
            st.markdown(f"**{term}** — {d}")


def _missing_db_gate():
    st.error(
        "**Datastore `anp_data.sqlite` not found in the project root.**\n\n"
        "Stage the ANP data, then build the datastore:\n\n"
        "1. Copy the CSVs from "
        "`03_data/EASA_ANP_LEGACY_database_v2.3/` into the project root, "
        "renaming the prefix `ANP2.3_` → `ANP2_3_` "
        "(at minimum `Aircraft`, `NPD_data`, `Jet_engine_coefficients`).\n"
        "2. Run `.\\pnmf.ps1 datastore` (or "
        "`.venv\\Scripts\\python.exe pnmf_cli.py datastore`).\n\n"
        "Then reload this page.")
    st.stop()


def main():
    st.set_page_config(page_title="PNMF", layout="wide")
    try:
        version = data_version()
    except FileNotFoundError:
        _missing_db_gate()
        return
    st.title("PNMF — Parametric Noise Modeling Framework")
    with st.sidebar:
        st.header("PNMF")
        page_name = st.radio("Page", list(PAGES), key="nav")
        st.divider()
        _sidebar_units()
        st.divider()
        _sidebar_status(version)
        _sidebar_how_to_use()
        _sidebar_glossary()
    PAGES[page_name]()


main()
