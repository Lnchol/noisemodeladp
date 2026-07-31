from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from openpyxl import Workbook

from pnmf.physics import THIRD_OCTAVE_HZ
from pnmf.serdp09_reference import Serdp09ReferenceError, load_case


def _write_archive(
    root: Path,
    *,
    rows: list[tuple[float, float, float]] | None = None,
    zone: str | None = None,
    header: str | None = None,
    workbook_rows: list[tuple[int, str]] | None = None,
) -> None:
    (root / "0SERDP09acousticREADME.txt").write_text(
        "SERDP09 archive; icrdg identifies each datapoint.", encoding="utf-8"
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "SERDP09_FF.db"
    sheet.append(("icrdg", "config"))
    for row in workbook_rows or [(844, "synthetic")]:
        sheet.append(row)
    workbook.save(root / "SERDP09acousticEscort.xlsx")
    data_dir = root / "844_nb"
    data_dir.mkdir()
    frequencies = np.linspace(20.0, 12000.0, 601)
    data = rows if rows is not None else [
        (float(frequency), angle, 80.0)
        for angle in (45.0, 90.0)
        for frequency in frequencies
    ]
    lines = [
        header or 'VARIABLES="Hz" "Polar angle" "PSD (dB)"',
        zone or 'ZONE T="844" I=601 J=2 F=POINT',
        *(f"{frequency}\t{angle}\t{psd}" for frequency, angle, psd in data),
    ]
    (data_dir / "844_nb.dat").write_text("\n".join(lines), encoding="utf-8")


def test_third_octave_band_centres_are_frozen_baseline():
    assert THIRD_OCTAVE_HZ.tolist() == [
        50.0, 63.0, 80.0, 100.0, 125.0, 160.0, 200.0, 250.0,
        315.0, 400.0, 500.0, 630.0, 800.0, 1000.0, 1250.0, 1600.0,
        2000.0, 2500.0, 3150.0, 4000.0, 5000.0, 6300.0, 8000.0,
        10000.0,
    ]


def test_load_case_integrates_constant_psd_in_linear_domain(tmp_path: Path):
    _write_archive(tmp_path)

    result = load_case(tmp_path, 844)

    lower = THIRD_OCTAVE_HZ / 2 ** (1 / 6)
    upper = THIRD_OCTAVE_HZ * 2 ** (1 / 6)
    expected = 80.0 + 10.0 * np.log10(upper - lower)
    assert result.record.icrdg == 844
    assert result.record.metadata == (("icrdg", "844"), ("config", "synthetic"))
    assert result.angles_deg == (45.0, 90.0)
    assert np.allclose(result.bands_db[45.0], expected)
    assert np.allclose(result.bands_db[90.0], expected)


@pytest.mark.parametrize(
    ("rows", "zone", "header", "match"),
    [
        (None, None, 'VARIABLES="Hz" "Angle" "PSD (dB)"', "columns"),
        (None, 'ZONE T="844" I=600 J=2 F=POINT', None, "row count"),
        ([(40.0, 45.0, 80.0), (20.0, 45.0, 80.0)], 'ZONE T="844" I=2 J=1 F=POINT', None, "frequency"),
        ([(20.0, 45.0, -999.0)], 'ZONE T="844" I=1 J=1 F=POINT', None, "-999"),
        ([(20.0, 45.0, float("nan"))], 'ZONE T="844" I=1 J=1 F=POINT', None, "non-finite"),
        ([(20.0, 45.0, 80.0), (40.0, 90.0, 80.0)], 'ZONE T="844" I=1 J=2 F=POINT', None, "overlap"),
    ],
)
def test_load_case_rejects_malformed_spectra(
    tmp_path: Path,
    rows: list[tuple[float, float, float]] | None,
    zone: str | None,
    header: str | None,
    match: str,
):
    _write_archive(tmp_path, rows=rows, zone=zone, header=header)

    with pytest.raises(Serdp09ReferenceError, match=match):
        load_case(tmp_path, 844)


def test_load_case_rejects_non_positive_zone_dimensions(tmp_path: Path):
    _write_archive(tmp_path, rows=[], zone='ZONE T="844" I=0 J=0 F=POINT')
    spectrum = tmp_path / "844_nb" / "844_nb.dat"
    spectrum.write_text(spectrum.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")

    with pytest.raises(Serdp09ReferenceError, match="dimensions"):
        load_case(tmp_path, 844)


def test_load_case_rejects_missing_or_duplicate_workbook_records(tmp_path: Path):
    _write_archive(tmp_path, workbook_rows=[(844, "one"), (844, "two")])

    with pytest.raises(Serdp09ReferenceError, match="duplicate"):
        load_case(tmp_path, 844)
    with pytest.raises(Serdp09ReferenceError, match="not found"):
        load_case(tmp_path, 845)


def test_load_case_rejects_duplicate_spectrum_rows(tmp_path: Path):
    _write_archive(
        tmp_path,
        rows=[(20.0, 45.0, 80.0), (20.0, 45.0, 80.0)],
        zone='ZONE T="844" I=2 J=1 F=POINT',
    )

    with pytest.raises(Serdp09ReferenceError, match="duplicate rows"):
        load_case(tmp_path, 844)


def test_load_case_rejects_duplicate_angles(tmp_path: Path):
    _write_archive(
        tmp_path,
        rows=[(20.0, 45.0, 80.0), (40.0, 45.0, 81.0)],
        zone='ZONE T="844" I=1 J=2 F=POINT',
    )

    with pytest.raises(Serdp09ReferenceError, match="duplicate angles"):
        load_case(tmp_path, 844)


@pytest.mark.parametrize("filename", ["0SERDP09acousticREADME.txt", "SERDP09acousticEscort.xlsx"])
def test_load_case_rejects_missing_required_archive_file(tmp_path: Path, filename: str):
    _write_archive(tmp_path)
    (tmp_path / filename).unlink()

    with pytest.raises(Serdp09ReferenceError, match="missing required archive file"):
        load_case(tmp_path, 844)


def test_load_case_treats_identifier_injection_as_data(tmp_path: Path):
    _write_archive(tmp_path)

    with pytest.raises(Serdp09ReferenceError, match="integer"):
        load_case(tmp_path, "844/../845")
