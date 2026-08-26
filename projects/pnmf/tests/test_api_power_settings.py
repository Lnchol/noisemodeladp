"""Focused contracts for selectable NPD row-power grids."""
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from pnmf.api import NoisePredictor, canonical_power_grid
from pnmf.core import NPDTable, ParametricAircraft


def _predictor():
    predictor = NoisePredictor.__new__(NoisePredictor)
    predictor.training_scope = "verified"
    predictor.training_metadata = {}
    predictor.input_envelope = {
        "per_type": {
            "Jet": {
                "thr": (20_000.0, 40_000.0, 10_000.0, 50_000.0),
                "mtow": (100_000.0, 300_000.0, 50_000.0, 400_000.0),
                "tw": (0.1, 0.8, 0.05, 1.0),
                "mlw_mtow": (0.6, 1.0, 0.5, 1.1),
                "n_set": [2, 4],
            }
        }
    }
    predictor._combos = [("SEL", "D"), ("SEL", "A"), ("LAmax", "D")]
    predictor._default_power = lambda aircraft, mode: (
        np.array([20000.0, 30000.0]) if mode == "D"
        else np.array([3000.0, 6000.0]))

    def predict_one(aircraft, metric, mode, powers):
        # Make row identity visible in std so sorting/alignment is testable.
        levels = np.tile(powers[:, None], (1, 10))
        std = np.tile((powers / 1000.0)[:, None], (1, 10))
        return NPDTable(powers, levels, metric, mode), std

    predictor._predict_one = predict_one
    return predictor


def _aircraft():
    return ParametricAircraft(name="TEST", n_engines=2,
                              max_static_thrust_lb=32000.0)


def test_default_power_grids_are_preserved():
    result = _predictor().predict(_aircraft())
    assert np.array_equal(result.tables[("SEL", "D")].P, [20000.0, 30000.0])
    assert np.array_equal(result.tables[("SEL", "A")].P, [3000.0, 6000.0])


def test_per_mode_mapping_and_missing_mode_default():
    result = _predictor().predict(
        _aircraft(), power_settings={"D": [26000.0, 18000.0], "A": None})
    assert np.array_equal(result.tables[("SEL", "D")].P, [18000.0, 26000.0])
    assert np.array_equal(result.tables[("LAmax", "D")].P, [18000.0, 26000.0])
    assert np.array_equal(result.tables[("SEL", "A")].P, [3000.0, 6000.0])


def test_shared_sequence_still_applies_to_every_mode():
    result = _predictor().predict(_aircraft(), power_settings=[9000.0, 5000.0])
    for table in result.tables.values():
        assert np.array_equal(table.P, [5000.0, 9000.0])


def test_sorted_power_rows_keep_uncertainty_aligned():
    result = _predictor().predict(_aircraft(), power_settings={"D": [30000, 20000]})
    table = result.tables[("SEL", "D")]
    std = result.uncertainty[("SEL", "D")]
    assert np.array_equal(table.P, [20000.0, 30000.0])
    assert np.array_equal(std[:, 0], table.P / 1000.0)


def test_prediction_progress_callback_reports_every_combo():
    events = []
    result = _predictor().predict(
        _aircraft(),
        progress_callback=lambda event, details: events.append(
            (event, details)))

    starts = [details for event, details in events
              if event == "combo_start"]
    done = [details for event, details in events if event == "combo_done"]
    assert len(starts) == len(done) == len(result.tables) == 3
    assert [(item["metric"], item["op_mode"]) for item in starts] == [
        ("SEL", "D"), ("SEL", "A"), ("LAmax", "D")]
    assert all(item["distances"] == 10 for item in done)
    assert events[-1] == (
        "prediction_done", {"tables": 3, "aircraft": "TEST"})


def test_prediction_rejects_physically_unsupported_aircraft_before_model_use():
    aircraft = ParametricAircraft(
        name="IMPOSSIBLE",
        n_engines=4,
        max_static_thrust_lb=200_000.0,
        mtow_lb=30_000.0,
        mlw_lb=25_000.0,
    )

    with pytest.raises(ValueError, match="supported Jet input envelope"):
        _predictor().predict(aircraft)


def test_prediction_metadata_records_non_blocking_support_warnings():
    aircraft = ParametricAircraft(name="UNUSUAL", n_engines=3)

    result = _predictor().predict(aircraft)

    assert result.metadata["input_findings"] == [
        {
            "level": "warning",
            "field": "n_engines",
            "message": "3 engines is not seen on any 'Jet' in the fleet "
            "(seen: [2, 4]).",
        }
    ]


@pytest.mark.parametrize("grid", [[], [0], [-1], [np.nan], [np.inf], [1, 1]])
def test_invalid_power_grids_are_rejected(grid):
    with pytest.raises(ValueError):
        canonical_power_grid(grid)


def test_cli_power_grid_parser_accepts_comma_separated_lbf_values():
    root = Path(__file__).resolve().parents[1]
    command = (
        "from pnmf_cli import parse_power_grid; "
        "print(parse_power_grid('18000, 24000,30000')); "
        "print(parse_power_grid('   '))"
    )
    result = subprocess.run([sys.executable, "-c", command], cwd=root,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["[18000.0, 24000.0, 30000.0]", "None"]
