from pnmf.jet_v2_promotion import (
    JET_V2_SELECTED_CANDIDATE,
    JET_V2_VALIDATION_REPORT_SHA256,
    available_training_scopes,
    jet_merged_is_promoted,
    production_training_scope,
)


def test_completed_route_gate_controls_public_jet_scope():
    assert jet_merged_is_promoted() is True
    assert production_training_scope() == "jet_merged"
    assert available_training_scopes() == ("jet_merged",)
    assert JET_V2_SELECTED_CANDIDATE == "jet_compact_v1"
    assert len(JET_V2_VALIDATION_REPORT_SHA256) == 64
