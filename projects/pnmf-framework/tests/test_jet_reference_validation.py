import json

import numpy as np
import pandas as pd
import pytest

from pnmf.anp import ANPDatabase
from pnmf import jet_reference_validation as jetval
from pnmf.validation import COMBOS, TRUTH_COLUMNS, build_samples


@pytest.fixture(scope="module")
def samples():
    return build_samples(ANPDatabase())


def _reference_ids(selected):
    return {
        count: {"npd_id": value["npd_id"], "acft_id": value["acft_id"]}
        for count, value in selected.items()
    }


def test_v63_selection_is_target_blind_shuffle_stable_and_frozen(samples):
    selected, candidates = jetval.select_jet_references(samples)
    shuffled, shuffled_candidates = jetval.select_jet_references(
        samples.sample(frac=1, random_state=91)
    )
    assert _reference_ids(selected) == jetval.FROZEN_REFERENCES
    assert _reference_ids(shuffled) == jetval.FROZEN_REFERENCES
    assert len(candidates) == 11
    assert set(candidates["source_dataset"]) == {jetval.REFERENCE_SOURCE}
    assert set(candidates["engine_type"]) == {"Jet"}
    assert set(candidates["n_tasks"]) == {len(COMBOS)}
    assert candidates.groupby("engine_count").size().to_dict() == {2: 9, 3: 1, 4: 1}
    assert selected[2]["robust_distance"] == pytest.approx(0.216692, abs=5e-7)
    assert selected[3]["robust_distance"] == 0.0
    assert selected[4]["robust_distance"] == 0.0
    pd.testing.assert_frame_equal(
        candidates.reset_index(drop=True),
        shuffled_candidates.reset_index(drop=True),
    )


def test_release_split_has_exact_sources_purge_counts_and_no_overlap(samples):
    selected, _ = jetval.select_jet_references(samples)
    split = jetval.build_jet_reference_split(samples, selected)
    assert jetval.verify_jet_reference_contract(samples, split) == jetval.EXPECTED
    train = split[split["role"] == "train"]
    test = split[split["role"] == "test"]
    purged = split[split["role"] == "excluded_family_purge"]
    assert set(train["source_dataset"]) == {jetval.TRAIN_SOURCE}
    assert set(test["source_dataset"]) == {jetval.REFERENCE_SOURCE}
    assert set(test["npd_id"]) == {
        value["npd_id"] for value in jetval.FROZEN_REFERENCES.values()
    }
    assert set(purged["npd_id"]) == jetval.FAMILY_PURGE
    assert not (set(train["npd_id"]) & set(test["npd_id"]))
    assert not (
        set(train["aircraft_group_id"]) & set(test["aircraft_group_id"])
    )
    assert len(train) == 76
    assert len(test) == 3
    assert train.groupby("engine_count").size().to_dict() == {2: 57, 3: 9, 4: 10}


def test_no_v63_training_and_exact_test_cell_interpretation(samples):
    selected, _ = jetval.select_jet_references(samples)
    split = jetval.build_jet_reference_split(samples, selected)
    train_ids = set(split.loc[split["role"] == "train", "npd_id"])
    test_ids = set(split.loc[split["role"] == "test", "npd_id"])
    train = samples[samples["npd_id"].isin(train_ids)]
    test = samples[samples["npd_id"].isin(test_ids)]
    assert not (train["source_dataset"] == jetval.REFERENCE_SOURCE).any()
    assert set(test["source_dataset"]) == {jetval.REFERENCE_SOURCE}
    assert len(test) == 116
    assert len(test) * len(TRUTH_COLUMNS) == 1160
    assert (
        test.groupby(["metric", "op_mode"]).size().unstack().to_dict()
        == {
            "A": {"EPNL": 12, "LAmax": 12, "PNLTM": 12, "SEL": 12},
            "D": {"EPNL": 17, "LAmax": 17, "PNLTM": 17, "SEL": 17},
        }
    )
    fal = test[test["npd_id"] == "FAL900EX"]
    for metric, mode in COMBOS:
        observed = tuple(
            fal[(fal["metric"] == metric) & (fal["op_mode"] == mode)]
            .sort_values("power_setting")["power_setting"]
        )
        assert observed == jetval.EXPECTED_FAL_POWER_GRIDS[mode]


def test_metric_formulas_and_threshold_inclusivity():
    frame = pd.DataFrame(
        {
            "error_dB": [-3.0, 4.0, 6.0],
            "sample_id": ["a", "b", "c"],
            "npd_id": ["a", "b", "c"],
            "engine_count": [2, 3, 4],
        }
    )
    result = jetval._metrics(frame, balanced=False)
    errors = np.array([-3.0, 4.0, 6.0])
    assert result["rmse_dB"] == pytest.approx(np.sqrt(np.mean(errors ** 2)))
    assert result["mae_dB"] == pytest.approx(np.mean(np.abs(errors)))
    assert result["bias_dB"] == pytest.approx(np.mean(errors))
    assert result["p90_abs_error_dB"] == pytest.approx(
        np.percentile(np.abs(errors), 90)
    )
    assert result["pct_within_3_dB"] == pytest.approx(100 / 3)
    assert result["pct_within_5_dB"] == pytest.approx(200 / 3)


def test_category_balanced_rmse_is_root_mean_category_mse():
    frame = pd.DataFrame(
        {
            "error_dB": [0.0, 0.0, 6.0],
            "sample_id": ["a", "b", "c"],
            "npd_id": ["a", "a", "b"],
            "engine_count": [2, 2, 4],
        }
    )
    pooled = jetval._metrics(frame, balanced=False)
    balanced = jetval._metrics(frame, balanced=True)
    assert pooled["rmse_dB"] == pytest.approx(np.sqrt(12.0))
    assert balanced["rmse_dB"] == pytest.approx(np.sqrt(18.0))
    assert balanced["mae_dB"] == pytest.approx(3.0)


def test_all_task_model_category_results_and_versioned_artifacts(
    samples, tmp_path, monkeypatch
):
    def truth_predict(learner, seed, train, test):
        assert set(train["source_dataset"]) == {jetval.TRAIN_SOURCE}
        assert set(test["source_dataset"]) == {jetval.REFERENCE_SOURCE}
        assert not set(train["npd_id"]) & jetval.FAMILY_PURGE
        return test.loc[:, TRUTH_COLUMNS].to_numpy(float), 0.0

    monkeypatch.setattr(jetval, "_fit_predict", truth_predict)
    output = tmp_path / "jet_reference_v63"
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
    assert set(zip(detail["metric"], detail["op_mode"])) == set(COMBOS)
    assert set(detail["engine_count_category"].astype(str)) == {"2", "3", "4"}
    assert len(detail) == 2 * 8 * 3
    assert (detail["rmse_dB"] == 0).all()

    saved = json.loads((output / "run_manifest.json").read_text("utf-8"))
    assert saved["counts"] == jetval.EXPECTED
    assert saved["source_separation"]["v63_target_rows_in_training"] == 0
    assert saved["config"]["family_purge_npd_ids"] == sorted(jetval.FAMILY_PURGE)
    assert saved["official_conclusion"] == jetval.OFFICIAL_CONCLUSION
    assert set(saved["official_source_urls"]) == {
        "easa_anp_data", "easa_anp_legacy_data", "eu_regulation_598_2014"
    }
    assert len(saved["fit_runs"]) == 16
    assert report.is_file()
    report_text = report.read_text("utf-8")
    assert jetval.OFFICIAL_CONCLUSION in report_text
    assert "not general representatives" in report_text
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
