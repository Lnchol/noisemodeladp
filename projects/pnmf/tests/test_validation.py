import json
from pathlib import Path

import numpy as np
import pandas as pd

from pnmf import validation
from pnmf.anp import ANPDatabase
from pnmf.models import SurrogateNPDModel


def test_aircraft_group_and_temporal_purge_control_7773er():
    db = ANPDatabase()
    npd_to_group, _, _ = validation.aircraft_group_map(db.aircraft)

    assert npd_to_group["GE9015"] == npd_to_group["7773ER"]

    samples = validation.build_samples(db)
    temporal = validation.temporal_split(samples)
    raw = temporal[
        (temporal["variant"] == "raw") & (temporal["npd_id"] == "7773ER")
    ]
    purged = temporal[
        (temporal["variant"] == "purged")
        & (temporal["npd_id"] == "7773ER")
    ]
    assert set(raw["role"]) == {"test"}
    assert set(purged["role"]) == {"excluded_test"}
    assert purged["exclusion_reason"].str.contains("7773ER").all()


def test_deterministic_group_split_never_splits_a_group():
    db = ANPDatabase()
    samples = validation.build_samples(db)
    first = validation.deterministic_group_folds(samples, 3, 17)
    shuffled = validation.deterministic_group_folds(
        samples.sample(frac=1, random_state=99), 3, 17
    )

    first_map = first.set_index("npd_id")["fold"].sort_index()
    shuffled_map = shuffled.set_index("npd_id")["fold"].sort_index()
    pd.testing.assert_series_equal(first_map, shuffled_map)
    assert first.groupby("aircraft_group_id")["fold"].nunique().max() == 1
    assert first.loc[first["npd_id"].isin(["GE9015", "7773ER"]), "fold"].nunique() == 1


def test_prediction_minus_truth_metric_formulas():
    predictions = pd.DataFrame(
        {
            "protocol": ["p"] * 4,
            "variant": ["v"] * 4,
            "model": ["et"] * 4,
            "metric": ["SEL"] * 4,
            "op_mode": ["D"] * 4,
            "source_dataset": ["s"] * 4,
            "engine_type": ["Jet"] * 4,
            "engine_count": [2] * 4,
            "sample_id": ["s1", "s1", "s2", "s2"],
            "npd_id": ["n1", "n1", "n2", "n2"],
            "aircraft_group_id": ["g1", "g1", "g2", "g2"],
            "error_dB": [1.0, -1.0, 3.0, -3.0],
        }
    )
    summary = validation.summarize_predictions(predictions)
    row = summary[
        (summary["dimension"] == "overall")
        & (summary["aggregation"] == "cell_pooled")
    ].iloc[0]

    assert np.isclose(row["rmse_dB"], np.sqrt(5.0))
    assert np.isclose(row["mae_dB"], 2.0)
    assert np.isclose(row["bias_dB"], 0.0)
    assert np.isclose(row["p90_abs_error_dB"], 3.0)
    assert row["n_cells"] == 4
    assert row["n_curves"] == 2
    assert row["n_aircraft_groups"] == 2


def test_exact_production_et_rf_surface():
    assert validation.SUPPORTED_LEARNERS == ("et", "rf")
    assert set(validation.MODEL_PARAMS) == {"et", "rf"}
    assert len(validation.COMBOS) == 8

    et = SurrogateNPDModel("et", random_state=23)._new_regressor()
    assert et.n_estimators == 500
    assert et.max_depth == 24
    assert et.max_features == 0.5
    assert et.min_samples_leaf == 1
    assert et.random_state == 23

    rf = SurrogateNPDModel("rf", random_state=23)._new_regressor()
    assert rf.n_estimators == 200
    assert rf.max_depth is None
    assert rf.max_features == 1.0
    assert rf.min_samples_leaf == 2
    assert rf.random_state == 23


def test_run_manifest_and_artifact_contract(tmp_path, monkeypatch):
    def truth_predict(learner, seed, train, test):
        return test.loc[:, validation.TRUTH_COLUMNS].to_numpy(float), 0.0

    monkeypatch.setattr(validation, "_fit_predict", truth_predict)
    output = tmp_path / "artifacts"
    report = tmp_path / "MODEL_TRAINING_REPORT.md"
    manifest = validation.run_validation(
        db_path=validation.PROJECT_ROOT / "anp_data.sqlite",
        output_dir=output,
        report_path=report,
        folds=3,
        seed=101,
    )

    saved = json.loads((output / "run_manifest.json").read_text("utf-8"))
    assert saved["config"]["models"] == ["et", "rf"]
    assert len(saved["config"]["metric_mode_combinations"]) == 8
    assert saved["inputs"]["datastore_sha256"] == manifest["inputs"]["datastore_sha256"]
    assert len(saved["inputs"]["source_manifest_sha256"]) == 64
    assert "not guaranteed byte-identical" in saved["reproducibility"]["model_results"]
    assert "run-specific integrity" in saved["reproducibility"]["artifact_hash_semantics"]
    assert saved["models"]["et"]["parameters"]["n_jobs"] == -1
    assert saved["models"]["rf"]["parameters"]["n_jobs"] == -1
    assert {
        "samples.csv",
        "splits_internal.csv",
        "splits_temporal.csv",
        "predictions.csv",
        "summary.csv",
        "summary.json",
        "engine_support_matrix.csv",
        "fit_runs.csv",
        "source_manifest.csv",
        "training_report",
    }.issubset(saved["artifacts"])
    assert report.is_file()
