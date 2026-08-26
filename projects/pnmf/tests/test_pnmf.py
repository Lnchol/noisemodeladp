"""Unit tests for the PNMF framework.  Run:  python -m pytest tests/ -q"""
import numpy as np
import pytest

from pnmf import (ANPDatabase, ParametricAircraft, NPDTable,
                  SurrogateNPDModel,
                  OperationalProfile, DepartureSynthesizer,
                  STANDARD_DISTANCES_FT)
from pnmf.models import power_features, enforce_distance_monotone
from pnmf.core import (fleet_input_envelope, evaluate_aircraft_inputs,
                       FUTURE_UHBR_TWIN)
from pnmf.anp import DIST_COLS


@pytest.fixture(scope="module")
def db():
    return ANPDatabase('.')


# ---------------- input realism checker -------------------------------------
@pytest.fixture(scope="module")
def envelope(db):
    return fleet_input_envelope(db.aircraft)


def _levels(findings):
    return [f["level"] for f in findings]


def test_input_envelope_is_jet_only(envelope):
    assert set(envelope["per_type"]) == {"Jet"}
    e = envelope["per_type"]["Jet"]
    assert e["thr"] is not None and e["mtow"] is not None
    assert e["n_samples"] > 0


def test_realistic_jet_is_clean(envelope):
    ac = ParametricAircraft(n_engines=2, max_static_thrust_lb=27000, mtow_lb=155000,
                            mlw_lb=137000)
    assert evaluate_aircraft_inputs(ac, envelope) == []


def test_preset_has_warnings_but_no_errors(envelope):
    # the canonical demo concept is deliberately extreme; must never hard-error
    ac = ParametricAircraft(**{k: v for k, v in FUTURE_UHBR_TWIN.items()})
    findings = evaluate_aircraft_inputs(ac, envelope)
    assert "error" not in _levels(findings)
    assert "warning" in _levels(findings)


def test_absurd_inputs_raise_errors(envelope):
    high_tw = ParametricAircraft(n_engines=2, max_static_thrust_lb=100000,
                                 mtow_lb=100000,
                                mlw_lb=95000)
    assert "error" in _levels(evaluate_aircraft_inputs(high_tw, envelope))

    hi_tw = ParametricAircraft(n_engines=4,
                               max_static_thrust_lb=120000, mtow_lb=100000,
                               mlw_lb=90000)
    assert "error" in _levels(evaluate_aircraft_inputs(hi_tw, envelope))

    heavy_mlw = ParametricAircraft(n_engines=2,
                                   max_static_thrust_lb=27000, mtow_lb=100000,
                                   mlw_lb=300000)
    assert "error" in _levels(evaluate_aircraft_inputs(heavy_mlw, envelope))


# ---------------- NPDTable: Doc 29 interpolation math -----------------------
def test_npd_log_distance_interpolation():
    # two power rows; pick distance geometrically between 1000 and 2000 ft:
    # log-midpoint of 1000/2000 is sqrt(2)*1000 ~ 1414.2 ft -> level midway.
    L = np.tile(np.linspace(100, 10, 10), (2, 1))
    t = NPDTable([1000.0, 2000.0], L, "SEL", "D")
    v1000 = t.level(1500, 1000.0)
    v2000 = t.level(1500, 2000.0)
    mid = t.level(1500, np.sqrt(1000.0 * 2000.0))
    assert abs(mid - 0.5 * (v1000 + v2000)) < 1e-9


def test_npd_linear_power_interpolation():
    L = np.vstack([np.full(10, 80.0), np.full(10, 100.0)])
    t = NPDTable([10000.0, 20000.0], L, "SEL", "D")
    assert abs(t.level(15000, 1000) - 90.0) < 1e-9
    # linear extrapolation outside tabulated power
    assert abs(t.level(25000, 1000) - 110.0) < 1e-9
    assert abs(t.level(5000, 1000) - 70.0) < 1e-9


def test_npd_log_distance_extrapolation():
    L = np.tile(np.linspace(100, 10, 10), (1, 1))
    t = NPDTable([10000.0], L, "SEL", "D")
    inner_slope = (t.L[0][1] - t.L[0][0]) / (t.logd[1] - t.logd[0])
    expected = t.L[0][0] + inner_slope * (np.log10(100) - t.logd[0])
    assert abs(t.level(10000, 100.0) - expected) < 1e-9


# ---------------- power unit handling (fault F1) ----------------------------
def test_power_features_units():
    static = 20000.0
    lp_lb, thr_lb = power_features([10000.0], "CNT (lb)", static)
    assert abs(10 ** lp_lb[0] - 10000.0) < 1e-6
    assert abs(thr_lb[0] - 0.5) < 1e-9
    lp_pc, thr_pc = power_features([50.0], "CNT (% of Max Static Thrust)", static)
    assert abs(10 ** lp_pc[0] - 10000.0) < 1e-6      # 50% of 20k lb == 10k lb
    assert abs(thr_pc[0] - 0.5) < 1e-9
    # identical physical state must give identical features across units
    assert abs(lp_lb[0] - lp_pc[0]) < 1e-9
    lp_rpm, thr_rpm = power_features([1500.0, 3000.0], "Other (RPM)", static)
    assert abs(thr_rpm[1] - 1.0) < 1e-9 and abs(thr_rpm[0] - 0.5) < 1e-9


# ---------------- monotonicity enforcement (fault F2) -----------------------
def test_enforce_distance_monotone():
    bad = np.array([[90, 85, 87, 80, 75, 70, 65, 60, 55, 50.0]])
    fixed = enforce_distance_monotone(bad)
    assert (np.diff(fixed[0]) <= 1e-12).all()
    good = np.array([np.linspace(100, 10, 10)])
    assert np.allclose(enforce_distance_monotone(good), good)


# ---------------- database integrity ----------------------------------------
def test_db_load_and_hygiene(db):
    s = db.summary()
    assert s["n_aircraft"] == 136 and s["n_npd_sets"] == 94
    assert s["n_npd_rows"] == 2664
    assert s["npd_rows_by_source"] == {
        "legacy_v2.3": 2244, "supplement_v6.3": 420}
    # whitespace stripped everywhere (fault: 'T_05  ' style cells)
    assert not db.dep_steps['Flap_ID'].str.endswith(' ').any()
    assert not db.aero['Flap_ID'].str.endswith(' ').any()
    # every NPD curve set joins to a parametric descriptor
    assert set(db.npd['NPD_ID'].unique()) <= set(db.param_table().index)
    # every truth row is distance-monotone (the physical premise of F2)
    M = db.npd[DIST_COLS].values
    assert not (np.diff(M, axis=1) > 0).any()


# ---------------- supported learned surrogate --------------------------------
def test_surrogate_predicts_physical_table(db):
    m = SurrogateNPDModel().fit(db, "SEL", "D")
    ac = ParametricAircraft(name="T", max_static_thrust_lb=25000,
                            mtow_lb=160000, mlw_lb=140000)
    tbl, std = m.predict_table(ac, "SEL", "D", [12000, 20000], return_std=True)
    assert tbl.L.shape == (2, 10) and std.shape == (2, 10)
    assert (np.diff(tbl.L, axis=1) <= 1e-9).all()        # monotone in distance
    assert (std >= 0).all()
    assert 40 < tbl.L.mean() < 130                        # plausible dB range


# ---------------- profile synthesis (fault F4) -------------------------------
def test_synthesize_all_departures(db):
    syn = DepartureSynthesizer(db)
    ids = db.dep_steps['ACFT_ID'].unique()
    for acid in ids:
        p = syn.synthesize(acid, stage_length=1).points
        assert (np.diff(p['altitude_ft']) >= -1e-9).all(), acid
        assert p['altitude_ft'].iloc[-1] > 1000, acid
        assert p['distance_ft'].iloc[-1] < 60 * 6076, acid


def test_synthesize_a320_plausibility(db):
    p = DepartureSynthesizer(db).synthesize('A320-211', stage_length=1).points
    assert 100 < p['speed_kt'].iloc[1] < 180          # liftoff CAS
    assert 1500 < p['distance_ft'].iloc[1] < 9000     # ground roll
    assert p['thrust'].iloc[1] > p['thrust'].iloc[-1]  # thrust decays w/ altitude


# ---------------- flyover closest-approach (fault F3) ------------------------
def test_flyover_uses_closest_point_not_midpoint():
    import pandas as pd
    # one long level segment passing directly over the observer:
    pts = pd.DataFrame({'distance_ft': [0.0, 20000.0],
                        'altitude_ft': [1000.0, 1000.0],
                        'speed_kt': [160.0, 160.0],
                        'thrust': [15000.0, 15000.0]})
    prof = OperationalProfile('D', pts)
    L = np.tile(np.linspace(100, 10, 10), (1, 1))
    t = NPDTable([15000.0], L, "LAmax", "D")
    lvl = prof.flyover_level(t, observer_x_ft=10000.0)  # under the midpoint
    # closest approach is exactly 1000 ft overhead -> the tabulated L_1000ft
    assert abs(lvl - t.level(15000, 1000.0)) < 1e-9
    # observer far beyond the segment end: distance from endpoint, not clipped
    lvl2 = prof.flyover_level(t, observer_x_ft=30000.0)
    d = np.sqrt(10000.0**2 + 1000.0**2)
    assert abs(lvl2 - t.level(15000, d)) < 1e-9
