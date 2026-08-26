"""Tracked-data-only smoke checks used by GitHub CI.

These tests deliberately do not instantiate ANPDatabase. Full integration and
model validation require the ignored local ANP corpus and datastore.
"""

import numpy as np
import pytest

from pnmf.core import NPDTable, STANDARD_DISTANCES_FT
from pnmf.models import (
    SUPPORTED_LEARNERS,
    SurrogateNPDModel,
    enforce_distance_monotone,
    power_features,
    validation_regressor,
)
from pnmf.physics import PhysicsDesign, PhysicsNPDModel


def test_supported_et_rf_surface_and_exact_production_parameters():
    assert SUPPORTED_LEARNERS == ("et", "rf")
    et = SurrogateNPDModel(random_state=7)._new_regressor()
    rf = validation_regressor("rf", 7)
    assert (et.n_estimators, et.max_depth, et.max_features,
            et.min_samples_leaf, et.n_jobs) == (500, 24, 0.5, 1, -1)
    assert (rf.n_estimators, rf.max_depth, rf.max_features,
            rf.min_samples_leaf, rf.n_jobs) == (200, None, 1.0, 2, -1)
    with pytest.raises(TypeError):
        SurrogateNPDModel("rf")


def test_power_conversion_for_lb_percent_and_rpm_axes():
    log_lb, throttle = power_features(
        [100.0, 500.0], "CNT (lb)", 1000.0)
    np.testing.assert_allclose(10 ** log_lb, [100.0, 500.0])
    np.testing.assert_allclose(throttle, [0.1, 0.5])

    log_lb, throttle = power_features(
        [25.0, 50.0], "CNT (% of Max Static Thrust)", 2000.0)
    np.testing.assert_allclose(10 ** log_lb, [500.0, 1000.0])
    np.testing.assert_allclose(throttle, [0.25, 0.5])

    log_lb, throttle = power_features(
        [1000.0, 2000.0], "Other (RPM)", 2000.0)
    np.testing.assert_allclose(10 ** log_lb, [1000.0, 2000.0])
    np.testing.assert_allclose(throttle, [0.5, 1.0])


def test_doc29_interpolation_and_distance_monotonic_projection():
    log_distance = np.log10(STANDARD_DISTANCES_FT)
    near = 110.0 - 20.0 * (log_distance - log_distance[0])
    levels = np.vstack([near, near + 10.0])
    table = NPDTable([100.0, 200.0], levels, "SEL", "D")
    geometric_midpoint = np.sqrt(200.0 * 400.0)
    expected = (levels[0, 0] + levels[0, 1]) / 2.0 + 5.0
    assert table.level(150.0, geometric_midpoint) == pytest.approx(expected)

    nonphysical = levels.copy()
    nonphysical[0, 5] = nonphysical[0, 4] + 3.0
    projected = enforce_distance_monotone(nonphysical)
    assert (np.diff(projected, axis=1) <= 1e-9).all()


def test_physics_rejects_metrics_outside_sel_lamax_without_database():
    model = PhysicsNPDModel()
    design = PhysicsDesign("CI", 2, 25000.0, 6.0, 150000.0)
    with pytest.raises(ValueError, match="supports only SEL, LAmax"):
        model.predict_table(design, "EPNL", "D", [20000.0])
