from __future__ import annotations

import json
from pathlib import Path
import subprocess

import numpy as np
from openpyxl import Workbook

from pnmf.physics import THIRD_OCTAVE_HZ


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI = PROJECT_ROOT / "pnmf_cli.py"
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def _write_archive(root: Path, *, proven: bool = False, invalid: bool = False) -> None:
    (root / "0SERDP09acousticREADME.txt").write_text(
        "SERDP09 archive; icrdg identifies each datapoint.", encoding="utf-8"
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "SERDP09_FF.db"
    sheet.append(("icrdg", "stream_mapping_proof", "frequency_basis_proof"))
    proof = "proven" if proven else "unproven"
    sheet.append((844, proof, proof))
    workbook.save(root / "SERDP09acousticEscort.xlsx")
    (root / "SERDP09TestReqtsV3.8.doc").write_text(
        "local hardware provenance", encoding="utf-8"
    )
    data_dir = root / "844_nb"
    data_dir.mkdir()
    frequencies = np.linspace(20.0, 12000.0, 601)
    lines = [
        'VARIABLES="Hz" "Polar angle" "PSD (dB)"',
        'ZONE T="844" I=601 J=2 F=POINT',
        *(
            f"{frequency}\t{angle}\t{-999 if invalid and angle == 90.0 and frequency == 20.0 else 80}"
            for angle in (45.0, 90.0)
            for frequency in frequencies
        ),
    ]
    (data_dir / "844_nb.dat").write_text("\n".join(lines), encoding="utf-8")


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON), str(CLI), "validate-serdp09", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_validate_serdp09_reports_structured_reason_for_missing_data_root(tmp_path: Path):
    result = _run(tmp_path)

    report = json.loads(result.stdout)
    assert result.returncode != 0
    assert report["verdict"] == "incompatible"
    assert report["reasons"] == ["--data-root must be provided"]


def test_validate_serdp09_rejects_relative_data_root(tmp_path: Path):
    result = _run(tmp_path, "--data-root", "relative-archive")

    report = json.loads(result.stdout)
    assert result.returncode != 0
    assert report["reasons"] == ["--data-root must be an absolute path"]


def test_validate_serdp09_is_cwd_independent_and_incompatible_is_nonzero(tmp_path: Path):
    archive = tmp_path / "archive"
    archive.mkdir()
    _write_archive(archive)
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()

    result = _run(other_cwd, "--data-root", str(archive))

    report = json.loads(result.stdout)
    assert result.returncode != 0
    assert report["verdict"] == "incompatible"
    assert report["reasons"] == [
        "missing proven core/bypass-to-outer/merged mapping",
        "missing proven model-scale frequency basis",
    ]
    assert Path(report["report_path"]) == archive / "serdp09_case_844_report.json"
    assert Path(report["report_path"]).is_file()


def test_validate_serdp09_retains_provenance_when_spectrum_is_invalid(tmp_path: Path):
    archive = tmp_path / "archive"
    archive.mkdir()
    _write_archive(archive, invalid=True)

    result = _run(tmp_path, "--data-root", str(archive))

    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report["verdict"] == "incompatible"
    assert "spectrum contains -999 invalid data" in report["reasons"]
    assert "missing proven core/bypass-to-outer/merged mapping" in report["reasons"]
    assert "missing proven model-scale frequency basis" in report["reasons"]
    assert {source["name"] for source in report["sources"]} == {
        "SERDP09acousticEscort.xlsx",
        "844_nb/844_nb.dat",
        "SERDP09TestReqtsV3.8.doc",
    }
    assert all(len(source["sha256"]) == 64 for source in report["sources"])
    assert report["selected_workbook_fields"]["icrdg"] == "844"
    assert report["valid_angles_deg"] == []
    assert report["excluded_angles_deg"] == [45.0, 90.0]
    assert report["third_octave_bands_hz"]["status"] == "excluded"
    assert report["fixed_parameters"]
    assert report["normalization_order"]
    assert report["exclusions"]
    assert report["limitation"] == "Conceptual screening only; not certification."


def test_validate_serdp09_rejects_workbook_self_asserted_proof(tmp_path: Path):
    archive = tmp_path / "archive"
    archive.mkdir()
    _write_archive(archive, proven=True)

    result = _run(tmp_path, "--data-root", str(archive))

    report = json.loads(result.stdout)
    assert result.returncode == 1, result.stderr
    assert report["verdict"] == "incompatible"
    assert report["reasons"] == [
        "missing proven core/bypass-to-outer/merged mapping",
        "missing proven model-scale frequency basis",
    ]
