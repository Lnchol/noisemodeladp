from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from pnmf.doc29_reference import Doc29ReferenceError, verify_doc29_workbook


def _write_workbook(path) -> None:
    frame = pd.DataFrame(
        {
            "power_setting": [80, 80, 90, 90],
            "distance_ft": [100, 1000, 100, 1000],
            "expected_level_db": [90, 80, 91, 81],
        }
    )
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(writer, sheet_name="JETF", index=False)
        frame.assign(expected_level_db=frame["expected_level_db"] - 2).to_excel(
            writer, sheet_name="JETW", index=False
        )


def test_doc29_reference_workbook_hash_and_interpolation(tmp_path) -> None:
    workbook = tmp_path / "official-doc29.xlsx"
    _write_workbook(workbook)
    digest = hashlib.sha256(workbook.read_bytes()).hexdigest()

    manifest = verify_doc29_workbook(workbook, digest)

    assert manifest["status"] == "pass"
    assert manifest["fixed_inputs"] == ["JETF", "JETW"]
    assert manifest["learned_model_accuracy"] is False
    assert manifest["component_physics_validation"] is False


def test_doc29_reference_rejects_wrong_hash_and_missing_sheet(tmp_path) -> None:
    workbook = tmp_path / "wrong.xlsx"
    _write_workbook(workbook)
    digest = hashlib.sha256(workbook.read_bytes()).hexdigest()

    with pytest.raises(Doc29ReferenceError, match="SHA-256 mismatch"):
        verify_doc29_workbook(workbook, "0" * 64)

    invalid = tmp_path / "invalid.xlsx"
    with pd.ExcelWriter(invalid) as writer:
        pd.DataFrame({"power": [80, 80], "distance_ft": [100, 1000], "level_db": [90, 80]}).to_excel(
            writer, sheet_name="OTHER", index=False
        )
    invalid_digest = hashlib.sha256(invalid.read_bytes()).hexdigest()
    with pytest.raises(Doc29ReferenceError, match="missing fixed reference sheets"):
        verify_doc29_workbook(invalid, invalid_digest)
