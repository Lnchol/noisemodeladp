from __future__ import annotations

import inspect
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pandas as pd
import pytest

from pnmf.anp import ANPDatabase, DataIntegrityError, build_datastore
from pnmf.api import NoisePredictor, prediction_model_identity
from pnmf.core import ParametricAircraft


def test_parametric_aircraft_is_jet_only_and_exposes_compatibility_metadata() -> None:
    aircraft = ParametricAircraft(name="JET", n_engines=2)

    assert aircraft.engine_type == "Jet"
    assert aircraft.to_dict()["engine_type"] == "Jet"
    assert "engine_type" not in inspect.signature(ParametricAircraft).parameters


def test_noise_predictor_has_no_public_model_or_scope_selection() -> None:
    parameters = inspect.signature(NoisePredictor.__init__).parameters

    assert "model" not in parameters
    assert "training_scope" not in parameters


def test_production_identity_is_fixed_to_et_jet_v2() -> None:
    assert prediction_model_identity() == "et-jet_merged-jet-v2"
    with pytest.raises(ValueError, match="production identity"):
        prediction_model_identity("rf", "verified")


def test_mixed_datastore_fails_closed(tmp_path) -> None:
    db_path = tmp_path / "mixed.sqlite"
    with sqlite3.connect(db_path) as connection:
        pd.DataFrame(
            [{"Engine Type": "Turboprop", "NPD_ID": "P1"}]
        ).to_sql("anp_aircraft", connection, index=False)
        pd.DataFrame(
            [{"NPD_ID": "P1", "Noise Metric": "SEL", "Op Mode": "A"}]
        ).to_sql("anp_npd_data", connection, index=False)
        pd.DataFrame(
            [{"population_scope": "mixed", "schema_version": 1}]
        ).to_sql("anp_meta", connection, index=False)

    with pytest.raises(DataIntegrityError, match="Jet-only"):
        ANPDatabase(db_path)


def test_stale_jet_datastore_schema_fails_closed(tmp_path) -> None:
    source = Path(__file__).resolve().parents[1] / "anp_data.sqlite"
    db_path = tmp_path / "stale.sqlite"
    shutil.copyfile(source, db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE anp_meta SET schema_version = -1")

    with pytest.raises(DataIntegrityError, match="stale datastore schema"):
        ANPDatabase(db_path)


@pytest.mark.parametrize("command", ["predict", "validate-jet-model"])
def test_cli_help_hides_internal_prediction_version_names(command) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "pnmf_cli.py", command, "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Jet-v2" not in result.stdout
    assert "et-jet_merged-jet-v2" not in result.stdout


def test_jet_datastore_builder_reports_population_contract(tmp_path) -> None:
    target = tmp_path / "jet.sqlite"

    build_datastore(root=".", db_path=target)

    with sqlite3.connect(target) as connection:
        meta = pd.read_sql_query("SELECT * FROM anp_meta", connection).iloc[0]
        aircraft = pd.read_sql_query("SELECT * FROM anp_aircraft", connection)
        npd = pd.read_sql_query("SELECT * FROM anp_npd_data", connection)

    assert meta["population_scope"] == "jet_only"
    assert len(aircraft) == 136
    assert aircraft["ACFT_ID"].nunique() == 135
    assert len(npd) == 2664
    assert set(aircraft["Engine Type"]) == {"Jet"}
