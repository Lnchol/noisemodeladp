"""Learning-layer tests for the supported ET/RF and storage surfaces."""

import os
import shutil
import sqlite3
import numpy as np
import pandas as pd
import pytest

from pnmf.anp import ANPDatabase
from pnmf.core import ParametricAircraft
from pnmf.core import NPDTable, STANDARD_DISTANCES_FT
from pnmf.anp import build_datastore, qa_check, PredictionStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSVS_STAGED = os.path.exists(os.path.join(ROOT, "ANP2_3_Aircraft.csv"))


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("store") / "anp_data.sqlite")
    if CSVS_STAGED:
        build_datastore(ROOT, db_path=path)
    elif os.path.exists(os.path.join(ROOT, "anp_data.sqlite")):
        # sqlite-only install (e.g. the packaged archive): test against a
        # throwaway copy of the shipped datastore
        shutil.copyfile(os.path.join(ROOT, "anp_data.sqlite"), path)
    else:
        pytest.skip("no ANP data staged (neither CSVs nor anp_data.sqlite)")
    return path


def test_api_default_model_is_et():
    from pnmf.api import DEFAULT_MODEL
    assert DEFAULT_MODEL == "et"


def test_rank_models_orders_by_average_rank():
    from pnmf.models import rank_models
    # ET is best in every combo and must be recommended over RF.
    df = pd.DataFrame({
        "metric_op": ["SEL:D", "SEL:A", "LAmax:D", "LAmax:A"],
        "et_medRMSE": [2.0, 2.1, 1.9, 2.2],
        "rf_medRMSE": [3.0, 3.1, 2.9, 3.2],
    })
    ranking, info = rank_models(df)
    assert list(ranking["model"]) == ["et", "rf"]
    assert ranking.loc[0, "avg_rank"] == 1.0
    assert int(ranking.loc[0, "wins"]) == 4
    assert info["recommended"] == "et"
    assert info["n_combos"] == 4
    assert "friedman_p" in info


def test_rank_models_requires_both_supported_models_scored():
    from pnmf.models import rank_models
    df = pd.DataFrame({
        "metric_op": ["SEL:D", "SEL:A"],
        "et_medRMSE": [2.0, 2.1],
        "rf_medRMSE": [np.nan, np.nan],
    })
    with pytest.raises(ValueError, match="need >=2"):
        rank_models(df)


def _good_table(name="TEST-CONCEPT"):
    P = np.array([15000.0, 22000.0, 28000.0])
    # plausible, strictly decreasing with distance
    base = np.array([100, 96, 93, 90, 84, 78, 74, 70, 65, 60], float)
    L = np.stack([base - 4, base - 1.5, base])
    return NPDTable(P, L, "SEL", "D", STANDARD_DISTANCES_FT, npd_id=name)


@pytest.mark.skipif(not CSVS_STAGED, reason="ANP CSVs not staged (sqlite-only install)")
def test_sqlite_roundtrip_matches_csv(db_path):
    via_sqlite = ANPDatabase(db_path)
    via_csv = ANPDatabase.__new__(ANPDatabase)
    via_csv.root = ROOT
    via_csv._sqlite = None
    via_csv.aircraft = via_csv._csv("ANP2_3_Aircraft.csv")
    via_csv.npd = via_csv._csv("ANP2_3_NPD_data.csv")
    via_csv.jet_coeffs = via_csv._csv("ANP2_3_Jet_engine_coefficients.csv")
    for attr in ("prop_coeffs", "aero", "dep_steps", "app_steps",
                 "profiles", "weights"):
        setattr(via_csv, attr, None)
    # only clean the three tables we compare (others set None)
    via_csv._clean()
    for attr in ("aircraft", "npd", "jet_coeffs"):
        pd.testing.assert_frame_equal(getattr(via_sqlite, attr),
                                      getattr(via_csv, attr),
                                      check_dtype=False)
    # the joined views must behave identically too
    assert list(via_sqlite.param_table().index) == list(via_csv.param_table().index)


def test_qa_accepts_physical_table():
    t = _good_table()
    status, reasons = qa_check(t.P, t.L)
    assert status == "ok" and reasons == []


def test_qa_rejects_unphysical_tables():
    t = _good_table()
    # level increasing with distance
    L_bad = t.L.copy()
    L_bad[0, -1] = L_bad[0, 0] + 10
    status, reasons = qa_check(t.P, L_bad)
    assert status == "rejected"
    # absurd magnitude
    status, _ = qa_check(t.P, t.L + 200)
    assert status == "rejected"
    # non-finite
    L_nan = t.L.copy()
    L_nan[1, 3] = np.nan
    status, _ = qa_check(t.P, L_nan)
    assert status == "rejected"
    # duplicate power settings
    status, _ = qa_check([20000, 20000, 28000], t.L)
    assert status == "rejected"


def test_qa_flags_extrapolation_and_crosscheck():
    t = _good_table()
    std_high = np.full_like(t.L, 4.0)
    status, reasons = qa_check(t.P, t.L, std_high)
    assert status == "caution" and "uncertainty" in reasons[0]
    status, reasons = qa_check(t.P, t.L, crosscheck_db=8.0)
    assert status == "caution" and "physics" in reasons[0]


def test_prediction_store_roundtrip_and_truth_isolation(db_path):
    ac = ParametricAircraft(name="TEST-CONCEPT", max_static_thrust_lb=28000,
                            mtow_lb=160000, mlw_lb=136000)
    good = _good_table(ac.name)
    bad = NPDTable(good.P, good.L[:, ::-1], "SEL", "A")  # increasing w/ dist

    with sqlite3.connect(db_path) as conn:
        truth_rows_before = conn.execute(
            "SELECT COUNT(*) FROM anp_npd_data").fetchone()[0]

    store = PredictionStore(db_path)
    results = store.add(ac, {("SEL", "D"): good, ("SEL", "A"): bad},
                        model="test-model")
    assert results[("SEL", "D")][0] == "ok"
    assert results[("SEL", "A")][0] == "rejected"

    # only the good table landed, values intact
    df = store.npd(name=ac.name)
    assert set(df["metric"] + "/" + df["op_mode"]) == {"SEL/D"}
    assert len(df) == 3
    got = df.sort_values("power_setting")["L_200ft"].to_numpy()
    assert np.allclose(got, good.L[:, 0])

    # re-adding replaces rather than duplicates
    store.add(ac, {("SEL", "D"): good}, model="test-model")
    assert len(store.npd(name=ac.name)) == 3

    # the ANP truth tables were not touched
    with sqlite3.connect(db_path) as conn:
        truth_rows_after = conn.execute(
            "SELECT COUNT(*) FROM anp_npd_data").fetchone()[0]
    assert truth_rows_after == truth_rows_before
    # and ANPDatabase still loads cleanly from the same file
    assert ANPDatabase(db_path).npd.shape[0] == truth_rows_before
