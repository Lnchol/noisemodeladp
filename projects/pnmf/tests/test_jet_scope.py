import pytest

from pnmf.anp import ANPDatabase
from pnmf.api import NoisePredictor, prediction_model_identity
from pnmf.core import ParametricAircraft
from pnmf.jet_features import jet_feature_names
from pnmf.jet_v2_promotion import JET_V2_VALIDATION_REPORT_SHA256
from pnmf.models import SurrogateNPDModel
from pnmf.verified_anp import resolve_training_scope


def test_jet_merged_scope_selects_all_complete_jet_curves():
    db = ANPDatabase()
    resolution = resolve_training_scope(db, "jet_merged")
    params = db.param_table().loc[list(resolution.selected_npd_ids)]
    assert len(resolution.selected_npd_ids) == 94
    assert params["Engine Type"].eq("Jet").all()
    assert len(resolution.support_counts) == 8
    assert set(resolution.support_counts.values()) == {94}


def test_jet_merged_design_matrix_uses_frozen_jet_schema():
    model = SurrogateNPDModel()
    matrix, _levels, groups = model._design_matrix(ANPDatabase(), "SEL", "D")
    assert matrix.shape[1] == len(jet_feature_names("jet-v2"))
    assert len(set(groups)) == 94


def test_jet_merged_prediction_rejects_non_jet_aircraft():
    predictor = NoisePredictor(metrics=("SEL",), op_modes=("D",))
    for engine_type in ("Turboprop", "Piston"):
        with pytest.raises(ValueError, match="Jet-only"):
            predictor.predict(
                name="NON-JET", engine_type=engine_type, n_engines=2,
                max_static_thrust_lb=8000.0, mtow_lb=30000.0,
                mlw_lb=25000.0, power_settings=[4000.0]
            )


def test_jet_model_identity_and_metadata_are_versioned():
    assert prediction_model_identity("et", "jet_merged") == (
        "et-jet_merged-jet-v2"
    )
    predictor = NoisePredictor(metrics=("SEL",), op_modes=("D",))
    metadata = predictor.training_metadata
    assert metadata["feature_schema"] == "jet-v2"
    assert metadata["training_population"] == "jet_merged"
    assert metadata["feature_names"] == list(jet_feature_names("jet-v2"))
    assert metadata["validation_report_sha256"] == JET_V2_VALIDATION_REPORT_SHA256
