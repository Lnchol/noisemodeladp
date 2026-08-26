from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .core import NPDTable

ECAC_DOC29_VOLUME3_PART1_URL = (
    "https://www.ecac-ceac.org/images/documents/"
    "ECAC-Doc_29_4th_edition_Dec_2016_Volume_3_Part_1.pdf"
)
REFERENCE_SHEETS = ("JETF", "JETW")


class Doc29ReferenceError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _column(frame: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    names = {str(name).strip().lower(): str(name) for name in frame.columns}
    for alias in aliases:
        if alias in names:
            return names[alias]
    return None


def _sheet_check(frame: pd.DataFrame, sheet: str) -> dict[str, object]:
    power_column = _column(
        frame, ("power", "power_setting", "power_setting_lb", "jet_power")
    )
    distance_column = _column(
        frame, ("distance", "distance_ft", "slant_distance_ft")
    )
    expected_column = _column(
        frame,
        ("expected_level_db", "reference_level_db", "level_db", "output_db"),
    )
    if power_column is None or distance_column is None or expected_column is None:
        raise Doc29ReferenceError(
            f"{sheet} must contain power, distance_ft, and expected_level_db "
            "columns"
        )
    values = frame[[power_column, distance_column, expected_column]].apply(
        pd.to_numeric, errors="coerce"
    ).dropna()
    if len(values) < 4:
        raise Doc29ReferenceError(f"{sheet} has fewer than four numeric reference rows")
    if values[power_column].nunique() < 2 or values[distance_column].nunique() < 2:
        raise Doc29ReferenceError(f"{sheet} needs at least two powers and distances")
    checks = []
    for power, power_rows in values.groupby(power_column, sort=True):
        ordered = power_rows.sort_values(distance_column)
        if len(ordered) < 2:
            continue
        distances = ordered[distance_column].to_numpy(dtype=float)
        levels = ordered[expected_column].to_numpy(dtype=float)
        table = NPDTable(
            np.asarray([power], dtype=float),
            levels.reshape(1, -1),
            "DOC29",
            sheet,
            distances,
        )
        midpoint = float(np.mean(distances[:2]))
        expected = float(np.interp(np.log10(midpoint), np.log10(distances[:2]), levels[:2]))
        checks.append(abs(table.level(float(power), midpoint) - expected))
    if not checks or max(checks) > 1e-9:
        raise Doc29ReferenceError(f"{sheet} Doc 29 distance interpolation check failed")
    return {
        "sheet": sheet,
        "rows": int(len(values)),
        "powers": int(values[power_column].nunique()),
        "distances": int(values[distance_column].nunique()),
        "distance_interpolation_max_abs_error_db": float(max(checks)),
    }


def verify_doc29_workbook(
    workbook: str | Path,
    expected_sha256: str,
    output: str | Path | None = None,
) -> dict[str, object]:
    path = Path(workbook).expanduser().resolve()
    if not path.is_file():
        raise Doc29ReferenceError(f"official Doc 29 workbook not found: {path}")
    expected = expected_sha256.strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise Doc29ReferenceError("an exact 64-character workbook SHA-256 is required")
    actual = sha256_file(path)
    if actual != expected:
        raise Doc29ReferenceError(
            f"workbook SHA-256 mismatch: expected {expected}, got {actual}"
        )
    excel = pd.ExcelFile(path)
    by_upper = {str(sheet).upper(): str(sheet) for sheet in excel.sheet_names}
    missing = [sheet for sheet in REFERENCE_SHEETS if sheet not in by_upper]
    if missing:
        raise Doc29ReferenceError(
            "official workbook is missing fixed reference sheets: "
            + ", ".join(missing)
        )
    sheets = [
        _sheet_check(pd.read_excel(path, sheet_name=by_upper[sheet]), sheet)
        for sheet in REFERENCE_SHEETS
    ]
    manifest: dict[str, object] = {
        "status": "pass",
        "verification": "doc29_interpolation_reference_contract",
        "workbook": str(path),
        "sha256": actual,
        "source_url": ECAC_DOC29_VOLUME3_PART1_URL,
        "fixed_inputs": list(REFERENCE_SHEETS),
        "sheets": sheets,
        "learned_model_accuracy": False,
        "component_physics_validation": False,
    }
    if output is not None:
        destination = Path(output).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
