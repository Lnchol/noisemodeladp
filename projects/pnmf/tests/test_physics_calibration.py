import pytest

from pnmf.physics import PhysicsNPDModel
from pnmf.physics_calibration import (
    ANCHOR_AIRCRAFT,
    DEFAULT_ARTIFACT_PATH,
    SCHEMA_VERSION,
    load_calibrated_model,
    load_calibration_artifact,
)


def test_release_calibration_artifact_is_a320_270n_and_hash_pinned():
    artifact = load_calibration_artifact(DEFAULT_ARTIFACT_PATH)
    assert artifact["schema_version"] == SCHEMA_VERSION
    assert artifact["anchor"]["aircraft_id"] == ANCHOR_AIRCRAFT
    assert artifact["anchor"]["npd_id"] == "A320-270N"
    assert artifact["metrics"]["cell_count"] == 180
    assert artifact["metrics"]["rmse_db"] < 10


def test_calibration_hash_mismatch_fails_closed():
    with pytest.raises(ValueError, match="source hash mismatch"):
        load_calibration_artifact(
            DEFAULT_ARTIFACT_PATH,
            expected_source_hashes={
                "verified_workbook": "wrong",
                "v63_aircraft": "wrong",
                "v63_npd": "wrong",
            },
        )


def test_runtime_load_applies_artifact_without_refitting(monkeypatch):
    def fail_refit(*args, **kwargs):
        raise AssertionError("runtime calibration refit is forbidden")

    monkeypatch.setattr(PhysicsNPDModel, "calibrate", fail_refit)
    model, artifact = load_calibrated_model(DEFAULT_ARTIFACT_PATH)
    assert model.calibration_parameters() == artifact["parameters"]
