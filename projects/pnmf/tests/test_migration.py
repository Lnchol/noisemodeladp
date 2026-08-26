"""Migration contracts: combined data, provenance, model surface, and paths."""
from pathlib import Path
import shutil
import subprocess

import pytest

from pnmf import ANPDatabase, NoisePredictor, SurrogateNPDModel
from pnmf.anp import (
    DataSourceError, PROJECT_ROOT, build_datastore,
)
from pnmf.api import DEFAULT_MODEL
from pnmf.models import SUPPORTED_LEARNERS


def test_combined_corpus_and_manifest():
    db = ANPDatabase()
    assert (len(db.aircraft), db.aircraft["ACFT_ID"].nunique()) == (136, 135)
    assert (db.npd["NPD_ID"].nunique(), len(db.npd)) == (94, 2664)
    assert db.npd["source_dataset"].value_counts().to_dict() == {
        "legacy_v2.3": 2244,
        "supplement_v6.3": 420,
    }
    manifest = db.dataset_manifest()
    assert set(manifest["source_dataset"].dropna()) == {
        "legacy_v2.3", "supplement_v6.3"}
    assert db.aircraft["Engine Type"].eq("Jet").all()


def test_v63_required_missing_table_fails_loudly(tmp_path):
    legacy = PROJECT_ROOT / "03_data" / "EASA_ANP_LEGACY_database_v2.3"
    target = tmp_path / "03_data"
    shutil.copytree(legacy, target / legacy.name)
    (target / "EASA_ANP_database_v6.3").mkdir()
    with pytest.raises(DataSourceError, match="required table missing"):
        build_datastore(tmp_path, tmp_path / "broken.sqlite")


def test_training_matrix_contains_v63_samples():
    db = ANPDatabase()
    model = SurrogateNPDModel().fit(db, "SEL", "D")
    assert model.training_provenance[("SEL", "D")] == {
        "legacy_v2.3": 327,
        "supplement_v6.3": 59,
    }


def test_default_training_scope_is_complete_jet_population():
    db = ANPDatabase()
    model = SurrogateNPDModel().fit(db, "SEL", "D")
    assert model.training_scope == "jet_merged"
    assert model.training_provenance[("SEL", "D")] == {
        "legacy_v2.3": 327,
        "supplement_v6.3": 59,
    }


def test_supported_learned_model_surface():
    assert DEFAULT_MODEL == "et"
    assert SUPPORTED_LEARNERS == ("et", "rf")
    SurrogateNPDModel()
    with pytest.raises(TypeError):
        SurrogateNPDModel("rf")
    with pytest.raises(TypeError):
        NoisePredictor(model="unsupported", metrics=())


def test_cli_is_caller_cwd_independent(tmp_path):
    result = subprocess.run(
        [str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
         str(PROJECT_ROOT / "pnmf_cli.py"), "manifest"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "'n_npd_sets': 94" in result.stdout
