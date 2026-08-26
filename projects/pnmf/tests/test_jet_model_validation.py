import numpy as np
import pandas as pd  # noqa: PANDAS_OK - tests assert DataFrame fold stability.
import pytest

from pnmf.anp import ANPDatabase
from pnmf.jet_model_validation import build_jet_samples, build_jet_group_folds


@pytest.fixture(scope="module")
def jet_samples():
    return build_jet_samples(ANPDatabase())


def test_jet_population_and_total_operating_cnt_contract(jet_samples):
    assert len(jet_samples) == 2664
    assert jet_samples["npd_id"].nunique() == 94
    assert jet_samples["aircraft_group_id"].nunique() == 93
    assert set(
        jet_samples.groupby(["metric", "op_mode"])["npd_id"].nunique()
    ) == {94}
    assert set(jet_samples["engine_type"]) == {"Jet"}
    expected = jet_samples["log_power_lb"] + np.log10(
        jet_samples["engine_count"]
    )
    np.testing.assert_allclose(
        jet_samples["log_total_operating_cnt_lb"], expected, rtol=0, atol=1e-12
    )


def test_jet_group_folds_are_stratified_and_shuffle_stable(jet_samples):
    first = build_jet_group_folds(jet_samples, folds=5, seed=13)
    shuffled = build_jet_group_folds(
        jet_samples.sample(frac=1, random_state=91), folds=5, seed=13
    )
    first_map = first.set_index("npd_id")["fold"].sort_index()
    shuffled_map = shuffled.set_index("npd_id")["fold"].sort_index()
    pd.testing.assert_series_equal(first_map, shuffled_map)
    assert first["fold"].nunique() == 5
    assert first.groupby("aircraft_group_id")["fold"].nunique().max() == 1
    assert set(first["static_thrust_band"]) == {0, 1, 2}
    assert set(first.columns) >= {
        "npd_id",
        "aircraft_group_id",
        "engine_count",
        "static_thrust_band",
        "stratum",
        "fold",
    }
