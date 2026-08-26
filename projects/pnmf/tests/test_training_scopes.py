from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from pnmf.anp import ANPDatabase, PredictionStore
from pnmf.api import NoisePredictor, prediction_model_identity
from pnmf.core import NPDTable, ParametricAircraft, STANDARD_DISTANCES_FT
from pnmf.models import SurrogateNPDModel
from pnmf.verified_anp import (
    REGISTRY_VERSION,
    SOURCE_HASHES,
    TRAINABLE_NPD_IDS,
    resolve_training_scope,
)


def test_production_design_matrix_uses_complete_jet_population() -> None:
    db = ANPDatabase()
    model = SurrogateNPDModel()

    matrix, levels, groups = model._design_matrix(db, "SEL", "D")

    assert matrix.shape[1] == 9
    assert levels.shape[1] == 10
    assert tuple(sorted(set(groups))) == tuple(sorted(db.list_curve_sets("SEL", "D")))
    assert len(set(groups)) == 94


def test_verified_registry_remains_reference_only() -> None:
    db = ANPDatabase()
    assert len(TRAINABLE_NPD_IDS) == 11
    assert resolve_training_scope(db, "verified").selected_npd_ids == TRAINABLE_NPD_IDS


def test_prediction_result_exposes_scope_and_registry_metadata() -> None:
    predictor = NoisePredictor(metrics=("SEL",), op_modes=("D",))
    aircraft = ParametricAircraft(name="SCOPE-TEST", n_engines=2,
                                  max_static_thrust_lb=30000.0)

    result = predictor.predict(aircraft, power_settings=[20000.0])

    assert result.metadata["learner"] == "et"
    assert result.metadata["scope"] == "jet_merged"
    assert result.metadata["registry_version"] == REGISTRY_VERSION
    assert len(result.metadata["selected_npd_ids"]) == 94
    assert result.metadata["source_hashes"] == {
        "verified_workbook": SOURCE_HASHES.verified_workbook,
        "v63_aircraft": SOURCE_HASHES.v63_aircraft,
        "v63_npd": SOURCE_HASHES.v63_npd,
    }
    assert result.metadata["support_counts"] == {"SEL:D": 94}
    assert np.all(np.diff(result.tables[("SEL", "D")].L, axis=1) <= 1e-9)


def test_production_identity_is_fixed_and_historical_scopes_are_not_public() -> None:
    assert prediction_model_identity() == "et-jet_merged-jet-v2"
    for learner, scope in (("rf", "jet_merged"), ("et", "verified"),
                           ("et", "merged")):
        with pytest.raises(ValueError):
            prediction_model_identity(learner, scope)


def test_storage_keeps_verified_and_merged_rows_separate_without_migration(
    tmp_path,
) -> None:
    path = tmp_path / "predictions.sqlite"
    sqlite3.connect(path).close()
    aircraft = ParametricAircraft(name="SCOPE-STORE", n_engines=2,
                                  max_static_thrust_lb=30000.0)
    table = NPDTable(
        np.array([20000.0]),
        np.array([[100.0, 96.0, 93.0, 90.0, 84.0, 78.0, 74.0, 70.0, 65.0, 60.0]]),
        "SEL", "D", STANDARD_DISTANCES_FT,
    )
    store = PredictionStore(str(path))

    store.add(aircraft, {("SEL", "D"): table}, model="et-verified")
    store.add(aircraft, {("SEL", "D"): table}, model="et-merged")

    assert set(store.aircraft()["model"]) == {"et-verified", "et-merged"}
