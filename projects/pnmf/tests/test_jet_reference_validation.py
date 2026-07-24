import json

import numpy as np
import pandas as pd
import pytest

from pnmf.anp import ANPDatabase
from pnmf import jet_reference_validation as jetval
from pnmf.validation import TRUTH_COLUMNS, build_samples


@pytest.fixture(scope="module")
def samples():
    return build_samples(ANPDatabase())


def test_selection_is_shuffle_stable_and_matches_frozen_ids(samples):
    selected, _ = jetval.select_jet_references(samples)
    shuffled, _ = jetval.select_jet_references(
        samples.sample(frac=1, random_state=91)
    )
    actual = {
        count: {"npd_id": value["npd_id"], "acft_id": value["acft_id"]}
        for count, value in selected.items()
    }
    shuffled_actual = {
        count: {"npd_id": value["npd_id"], "acft_id": value["acft_id"]}
        for count, value in shuffled.items()
    }
    assert actual == jetval.FROZEN_REFERENCES
    assert shuffled_actual == actual


def test_exact_counts_no_group_overlap_and_jet_only_training(samples):
    selected, _ = jetval.select_jet_references(samples)
    split = jetval.build_jet_reference_split(samples, selected)
    assert jetval.verify_jet_reference_contract(samples, split) == jetval.EXPECTED
    train = split[split["role"] == "train"]
    test = split[split["role"] == "test"]
    assert set(train["engine_type"]) == {"Jet"}
    assert not (
        set(train["aircraft_group_id"]) & set(test["aircraft_group_id"])
    )
    assert set(test["npd_id"]) == {"BR715", "3JT8E5", "PW4056"}


def test_metric_success_percentages():
    frame = pd.DataFrame(
        {
            "error_dB": [-2.0, 4.0, 6.0],
            "sample_id": ["a", "b", "c"],
            "npd_id": ["a", "b", "c"],
            "engine_count": [2, 3, 4],
        }
    )
    result = jetval._metrics(frame, balanced=False)
    assert result["pct_within_3_dB"] == pytest.approx(100 / 3)
    assert result["pct_within_5_dB"] == pytest.approx(200 / 3)
    assert result["bias_dB"] == pytest.approx(8 / 3)


def test_all_task_model_category_results_and_artifacts(
    samples, tmp_path, monkeypatch
):
    def truth_predict(learner, seed, train, test):
        return test.loc[:, TRUTH_COLUMNS].to_numpy(float), 0.0

    monkeypatch.setattr(jetval, "_fit_predict", truth_predict)
    output = tmp_path / "output"
    report = tmp_path / "JET_REFERENCE_VALIDATION_REPORT.md"
    assets = tmp_path / "assets"
    manifest = jetval.run_jet_reference_validation(
        db_path=jetval.PROJECT_ROOT / "anp_data.sqlite",
        output_dir=output,
        report_path=report,
        assets_dir=assets,
        seed=13,
    )
    summary = pd.read_csv(output / "summary.csv")
    detail = summary[
        (summary["scope"] == "task_category")
        & (summary["aggregation"] == "cell_pooled")
    ]
    assert set(detail["model"]) == {"et", "rf"}
    assert set(zip(detail["metric"], detail["op_mode"])) == set(jetval.COMBOS)
    assert set(detail["engine_count_category"].astype(str)) == {"2", "3", "4"}
    assert len(detail) == 2 * 8 * 3
    assert (detail["rmse_dB"] == 0).all()

    saved = json.loads((output / "run_manifest.json").read_text("utf-8"))
    assert saved["counts"] == jetval.EXPECTED
    assert saved["config"]["frozen_references"] == {
        str(key): value for key, value in jetval.FROZEN_REFERENCES.items()
    }
    assert len(saved["fit_runs"]) == 16
    assert report.is_file()
    assert {
        "jet_reference_architecture.png",
        "jet_reference_metrics.png",
        "jet_reference_npd_comparison.png",
        "jet_reference_residual_heatmap.png",
    } == {path.name for path in assets.glob("*.png")}
    assert {
        "selection_candidates.csv", "split.csv", "predictions.csv",
        "fit_runs.csv", "summary.csv", "summary.json",
        "reference_metadata.csv", "reference_metadata.json",
        "source_manifest.csv",
    }.issubset(saved["artifacts"])
