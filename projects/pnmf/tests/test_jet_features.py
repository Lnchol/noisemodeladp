import numpy as np
import pytest

from pnmf.jet_features import (
    JET_CANDIDATE_SCHEMA_IDS,
    JET_V2_SCHEMA_ID,
    JetFeatureError,
    build_jet_feature_matrix,
    jet_feature_names,
    validate_jet_power_parameter,
)


def test_jet_feature_schemas_have_stable_order_without_engine_type_one_hot():
    assert set(JET_CANDIDATE_SCHEMA_IDS) == {
        "jet_compact_v1",
        "jet_drop_count_v1",
        "jet_replace_count_v1",
        "jet_add_total_operating_v1",
    }
    assert JET_V2_SCHEMA_ID == "jet-v2"
    names = jet_feature_names("jet_add_total_operating_v1")
    assert names == (
        "n_engines",
        "log_mtow",
        "log_mlw",
        "mlw_mtow",
        "log_thrust_per_eng",
        "log_total_thrust",
        "noise_chapter",
        "log_power_lb",
        "throttle",
        "log_total_operating_cnt_lb",
    )
    assert not {"is_jet", "is_turboprop", "is_piston"}.intersection(names)


def test_total_operating_cnt_is_per_engine_log_power_plus_log_engine_count():
    base = {
        "n_engines": 2.0,
        "log_mtow": 5.5,
        "log_mlw": 5.4,
        "mlw_mtow": 0.8,
        "log_thrust_per_eng": 4.0,
        "log_total_thrust": 4.30103,
        "noise_chapter": 14.0,
    }
    matrix = build_jet_feature_matrix(
        base,
        np.array([4.0, 4.5]),
        np.array([0.5, 1.0]),
        "jet_add_total_operating_v1",
    )
    np.testing.assert_allclose(
        matrix[:, -1], np.array([4.0 + np.log10(2), 4.5 + np.log10(2)])
    )


def test_unsupported_jet_power_parameter_fails_closed():
    validate_jet_power_parameter("CNT (lb)")
    validate_jet_power_parameter("CNT (% of Max Static Thrust)")
    with pytest.raises(JetFeatureError, match="unsupported Jet power parameter"):
        validate_jet_power_parameter("Other (RPM)")


def test_jet_feature_matrix_rejects_non_finite_aircraft_features():
    base = {
        "n_engines": 2.0,
        "log_mtow": np.nan,
        "log_mlw": 5.4,
        "mlw_mtow": 0.8,
        "log_thrust_per_eng": 4.0,
        "log_total_thrust": 4.30103,
        "noise_chapter": 14.0,
    }

    with pytest.raises(JetFeatureError, match="finite"):
        build_jet_feature_matrix(
            base,
            np.array([4.0]),
            np.array([0.5]),
            "jet_compact_v1",
        )
