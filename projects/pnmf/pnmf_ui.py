"""PNMF local UI — form-based parametric-aircraft noise prediction and
real-vs-future comparison, on top of the existing pnmf public API.

Launched via `.\\pnmf.ps1 ui` (streamlit run pnmf_ui.py); fully offline.
This module implements the shared skeleton, the Aircraft Designer page and
the Comparison page. The Results / Physics / Operations / Fleet pages are
stubs filled by a later build step; the session-state contract they rely on
lives here (keys: prediction, pred_meta, crosscheck, and the f_* widgets).
"""
from __future__ import annotations

import io
import os
import re
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")            # headless backend before any pyplot import
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from pnmf.api import NoisePredictor, real_vs_future_table, DEFAULT_MODEL
from pnmf.core import (ParametricAircraft, FUTURE_UHBR_TWIN, NPDTable,
                       STANDARD_DISTANCES_FT, ENGINE_TYPES,
                       fleet_input_envelope, evaluate_aircraft_inputs)
from pnmf.anp import DIST_COLS, ANPDatabase, qa_check, PredictionStore
from pnmf.operations import DepartureSynthesizer
from pnmf.models import rank_models

PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)
DB_PATH = str(PROJECT_ROOT / "anp_data.sqlite")
MODELS = ["et", "rf"]
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
    canonical keys directly (preset/prefill), bypassing their own widget."""
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
        st.info("Design an aircraft and press **Predict** first.")
        return None
    meta = st.session_state.get("pred_meta", {})
    try:
        cur = data_version()
    except FileNotFoundError:
        cur = None
    if meta.get("version") and cur and meta["version"] != cur:
        st.warning("The datastore changed since this prediction was made — "
                   "re-run **Predict** on the Aircraft Designer for "
                   "up-to-date results.")
    return pred


# ===========================================================================
# Designer callbacks (run before the next render, so they may write f_* keys)
# ===========================================================================

_OPTIONAL_KEYS = ("f_bpr", "f_fan_d", "f_fan_mach", "f_wing_area",
                  "f_wing_span", "f_gear_wheels")


def _apply_preset():
    p = FUTURE_UHBR_TWIN
    st.session_state["f_name"] = p["name"]
    st.session_state["f_engine_type"] = p["engine_type"]
    st.session_state["f_n_engines"] = int(p["n_engines"])
    st.session_state["f_thrust"] = float(p["max_static_thrust_lb"])
    st.session_state["f_mtow"] = float(p["mtow_lb"])
    st.session_state["f_mlw"] = float(p["mlw_lb"])
    st.session_state["f_chapter"] = int(p["noise_chapter"])
    for k in _OPTIONAL_KEYS:
        st.session_state[k] = None
    st.session_state["f_bpr"] = float(p["bypass_ratio"])
    _clear_unit_shadows()


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
    _clear_unit_shadows()


def _init_designer_state():
    """Seed every f_* widget key once (setdefault is idempotent per rerun)."""
    p = FUTURE_UHBR_TWIN
    st.session_state.setdefault("f_name", p["name"])
    st.session_state.setdefault("f_engine_type", p["engine_type"])
    st.session_state.setdefault("f_n_engines", int(p["n_engines"]))
    st.session_state.setdefault("f_thrust", float(p["max_static_thrust_lb"]))
    st.session_state.setdefault("f_mtow", float(p["mtow_lb"]))
    st.session_state.setdefault("f_mlw", float(p["mlw_lb"]))
    st.session_state.setdefault("f_chapter", int(p["noise_chapter"]))
    st.session_state.setdefault("f_bpr", float(p["bypass_ratio"]))
    for k in ("f_fan_d", "f_fan_mach", "f_wing_area", "f_wing_span",
              "f_gear_wheels"):
        st.session_state.setdefault(k, None)
    st.session_state.setdefault("f_model", DEFAULT_MODEL)


# ===========================================================================
# Page: Aircraft Designer
# ===========================================================================

def page_designer():
    _init_designer_state()
    version = data_version()
    st.header("Aircraft Designer")
    st.caption("Define a parametric / future aircraft, choose a model, and "
               "predict its NPD-equivalent noise tables.")

    # ---- preset + prefill ------------------------------------------------
    c1, c2 = st.columns([1, 2])
    with c1:
        st.button("Load preset (FUTURE-UHBR-TWIN)", on_click=_apply_preset,
                  width="stretch")
    with c2:
        labels = list(_label_map(get_param_table(version)))
        st.selectbox("Prefill from real aircraft", labels, key="f_prefill_sel")
        st.button("Apply prefill", on_click=_apply_prefill,
                  width="stretch")

    st.divider()

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

    # ---- model + predict -------------------------------------------------
    st.selectbox("Prediction model", MODELS, key="f_model",
                 help=_model_help())
    ranked = (load_model_ranking(os.path.getmtime(_COMPARE_CSV))
              if os.path.exists(_COMPARE_CSV) else None)
    if ranked is not None:
        ranking_df, info = ranked
        top = ranking_df.iloc[0]
        st.caption(
            f"Ranking system recommends **{info['recommended']}** "
            f"(avg rank {top['avg_rank']:.2f} across {info['n_combos']} "
            f"metric:op combos, Friedman p="
            f"{info['friedman_p']:.3f}). See **Fleet explorer → Model "
            "ranking** for the full leaderboard.")
    else:
        st.caption("Model ranking needs the bake-off CSV — run "
                   "`.\\pnmf.ps1 compare`. Meanwhile `et` is the shipped "
                   "default.")

    if st.button("Predict", type="primary", width="stretch"):
        ac = _aircraft_from_state()
        model = st.session_state["f_model"]
        try:
            with st.spinner(f"Fitting `{model}` on the ANP fleet and "
                            f"predicting…"):
                predictor = get_predictor(model, version)
                pred = predictor.predict(ac)
        except RuntimeError as e:
            st.error(f"Model `{model}` is unavailable: {e}")
        else:
            st.session_state["prediction"] = pred
            st.session_state["pred_meta"] = {
                "model": model, "version": version,
                "aircraft": ac.to_dict(), "name": ac.name}
            st.session_state.pop("crosscheck", None)   # stale on new predict
            st.success("Prediction ready — open **Prediction results** or "
                       "**Comparison** from the sidebar.")

    # ---- persistent last-prediction summary -----------------------------
    if "prediction" in st.session_state:
        meta = st.session_state["pred_meta"]
        st.divider()
        st.caption("Last prediction")
        m1, m2, m3 = st.columns(3)
        m1.metric("Aircraft", meta["name"])
        m2.metric("Model", meta["model"])
        m3.metric("Tables", len(st.session_state["prediction"].tables))


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

    dist_x = _dist_x()
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    cmap = plt.cm.viridis(np.linspace(0, 0.8, len(tbl.P)))
    for i, p in enumerate(p_disp):
        if std is not None:
            band = np.asarray(std, float)[i]
            ax.fill_between(dist_x, tbl.L[i] - band,
                            tbl.L[i] + band, color=cmap[i], alpha=0.15)
        ax.semilogx(dist_x, tbl.L[i], "o-", color=cmap[i],
                    lw=1.4, label=f"{p:.0f} {_power_label()}")
    ax.set_xlabel(_dist_label())
    ax.set_ylabel(f"{metric} [dB]")
    ax.set_title(f"{metric} / {om}", fontsize=10)
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(fontsize=7, ncol=2)
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

def page_physics():
    pred = _require_prediction()
    if pred is None:
        return
    meta = st.session_state["pred_meta"]
    default_bpr = float(meta["aircraft"].get("bypass_ratio") or 6.0)
    st.header("Physics cross-check")
    st.caption("Independent physics-route (frozen A320-211 calibration) "
               "SEL/LAmax comparison against the primary prediction. "
               "EPNL/PNLTM are out of scope for the physics route.")

    bpr = st.number_input("Bypass ratio", min_value=0.0, max_value=20.0,
                          step=0.5, value=default_bpr, key="phys_bpr")

    if st.button("Run cross-check", type="primary"):
        with st.spinner("Calibrating physics route (A320-211) — first run "
                        "only..."):
            result = pred.crosscheck_physics(bpr=bpr)
        st.session_state["crosscheck"] = {"bpr": float(bpr), "result": result}

    cc = st.session_state.get("crosscheck")
    if cc is None:
        st.info("Run the cross-check to compare against the physics route.")
        return

    threshold = 5.0
    cols = st.columns(max(len(cc["result"]), 1))
    for col, (metric, delta) in zip(cols, sorted(cc["result"].items())):
        col.metric(f"{metric} mean |Δ| vs physics", f"{delta:.2f} dB",
                  delta=f"{delta - threshold:+.2f} dB vs {threshold:.1f} dB "
                  "caution", delta_color="inverse")
    st.caption("EPNL / PNLTM are outside the physics route's scope "
               "(SEL / LAmax only — no tone correction modeled).")

    st.divider()
    if st.checkbox("BPR sweep (4.0 – 19.0)", key="phys_sweep"):
        cache_key = (meta["name"], meta["model"])
        cache = st.session_state.setdefault("phys_sweep_cache", {})
        if cache.get("key") != cache_key:
            bprs = np.arange(4.0, 19.1, 1.5)
            sweep = {"SEL": [], "LAmax": []}
            with st.spinner("Sweeping BPR..."):
                for b in bprs:
                    r = pred.crosscheck_physics(bpr=float(b))
                    for m in sweep:
                        sweep[m].append(r.get(m, np.nan))
            cache.update(key=cache_key, bprs=bprs, sweep=sweep)
        bprs, sweep = cache["bprs"], cache["sweep"]
        fig, ax = plt.subplots(figsize=(7.2, 4.0))
        for m, col in (("SEL", "#2b6cb0"), ("LAmax", "#c53030")):
            ax.plot(bprs, sweep[m], "o-", color=col, label=m)
        ax.axhline(threshold, ls="--", color="0.4", lw=1,
                  label="caution threshold")
        ax.set_xlabel("bypass ratio")
        ax.set_ylabel("mean |Δ| [dB]")
        ax.set_title("Physics cross-check sensitivity to BPR", fontsize=10)
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=8)
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
        st.caption("The sweep does not overwrite the stored cross-check "
                  "result used on the other pages.")


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
    "Physics cross-check": page_physics,
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
            "1. **Aircraft Designer** — define a parametric aircraft (or "
            "click **Load preset** / **Apply prefill**), pick a "
            "**Prediction model**, then press **Predict**.\n"
            "2. **Prediction results** — view the generated NPD tables "
            "and curves, download the ANP-layout CSV, optionally store "
            "the prediction into `anp_data.sqlite`.\n"
            "3. **Comparison** — overlay the predicted aircraft against "
            "its nearest real ANP neighbours.\n"
            "4. **Physics cross-check** *(optional)* — sanity-check the "
            "prediction against the independent physics route "
            "(SEL / LAmax only).\n"
            "5. **Operations** *(optional)* — synthesize a departure "
            "flight path and read off the noise level at a ground "
            "observer.\n"
            "6. **Fleet explorer** — browse the underlying real ANP "
            "fleet and any validation artifacts, at any time, no "
            "prediction needed.\n\n"
            "Steps 2–5 need a prediction from step 1 first — each page "
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
