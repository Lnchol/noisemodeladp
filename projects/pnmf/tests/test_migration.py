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
    assert (len(db.aircraft), db.aircraft["ACFT_ID"].nunique()) == (166, 165)
    assert (db.npd["NPD_ID"].nunique(), len(db.npd)) == (122, 3196)
    assert db.npd["source_dataset"].value_counts().to_dict() == {
        "legacy_v2.3": 2776,
        "supplement_v6.3": 420,
    }
    manifest = db.dataset_manifest()
    assert set(manifest["source_dataset"]) == {
        "legacy_v2.3", "supplement_v6.3"}
    assert set(db.aircraft.loc[
        db.aircraft["ACFT_ID"] == "7773ER", "NPD_ID"]) == {
        "GE9015", "7773ER"}


def test_v63_required_missing_table_fails_loudly(tmp_path):
    legacy = PROJECT_ROOT / "03_data" / "EASA_ANP_LEGACY_database_v2.3"
    target = tmp_path / "03_data"
    shutil.copytree(legacy, target / legacy.name)
    (target / "EASA_ANP_database_v6.3").mkdir()
    with pytest.raises(DataSourceError, match="required table missing"):
        build_datastore(tmp_path, tmp_path / "broken.sqlite")


def test_training_matrix_contains_v63_samples():
    db = ANPDatabase()
    model = SurrogateNPDModel("et").fit(db, "SEL", "D")
    assert model.training_provenance[("SEL", "D")] == {
        "legacy_v2.3": 398,
        "supplement_v6.3": 59,
    }


def test_supported_learned_model_surface():
    assert DEFAULT_MODEL == "et"
    assert SUPPORTED_LEARNERS == ("et", "rf")
    for learner in SUPPORTED_LEARNERS:
        SurrogateNPDModel(learner)
        NoisePredictor(model=learner, metrics=())
    with pytest.raises(ValueError, match="unsupported learned model"):
        SurrogateNPDModel("gbr")
    with pytest.raises(ValueError, match="unknown model"):
        NoisePredictor(model="unsupported", metrics=())


def test_cli_is_caller_cwd_independent(tmp_path):
    result = subprocess.run(
        [str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
         str(PROJECT_ROOT / "pnmf_cli.py"), "manifest"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "'n_npd_sets': 122" in result.stdout
