import json

import pandas as pd

from pnmf import jet_model_runner as runner
from pnmf import jet_model_evaluation as evaluation
from pnmf.jet_model_artifacts import metrics_payload
from pnmf.jet_model_validation import OPERATING_CNT_BAND
from pnmf.validation import TRUTH_COLUMNS


def test_jet_runner_writes_gate_artifacts_with_truth_stub(tmp_path, monkeypatch):
    def truth_jet(learner, seed, train, test, schema_id):
        return test.loc[:, TRUTH_COLUMNS].to_numpy(float), 0.0

    def truth_verified(learner, seed, train, test):
        return test.loc[:, TRUTH_COLUMNS].to_numpy(float), 0.0

    monkeypatch.setattr(evaluation, "fit_jet_variant", truth_jet)
    monkeypatch.setattr(evaluation, "fit_verified_variant", truth_verified)
    output = tmp_path / "jet_validation"
    report = tmp_path / "JET_MODEL_V2_VALIDATION_REPORT.md"
    manifest = runner.run_jet_model_validation(
        db_path=runner.PROJECT_ROOT / "anp_data.sqlite",
        output_dir=output,
        report_path=report,
        folds=5,
        seeds=(13,),
        bootstrap_resamples=100,
    )
    assert manifest["counts"] == {
        "samples": 2664,
        "curves": 94,
        "aircraft_groups": 93,
        "verified_curves": 11,
    }
    assert manifest["promotion"]["production_scope"] == "verified"
    assert report.is_file()
    assert {
        "samples.csv",
        "splits.csv",
        "predictions.csv",
        "fit_runs.csv",
        "schema_metrics.json",
        "gate_decisions.json",
        "bootstrap_results.json",
        "promotion_status.json",
        "run_manifest.json",
    }.issubset(path.name for path in output.iterdir())
    saved = json.loads((output / "run_manifest.json").read_text("utf-8"))
    assert saved["features"]["derived_field"] == "log_total_operating_cnt_lb"
    assert saved["gates"]["route"]["passed"] is False


def test_metrics_payload_preserves_balanced_task_rmse_for_both_learners():
    tasks = (
        ("SEL", "A"),
        ("SEL", "D"),
        ("LAmax", "A"),
        ("LAmax", "D"),
        ("EPNL", "A"),
        ("EPNL", "D"),
        ("PNLTM", "A"),
        ("PNLTM", "D"),
    )
    rows = []
    for model, error in (("et", 1.0), ("rf", 2.0)):
        for index, (metric, op_mode) in enumerate(tasks):
            rows.append(
                {
                    "schema_id": "jet_compact_v1",
                    "model": model,
                    "error_dB": error,
                    "aircraft_group_id": f"group-{index}",
                    "metric": metric,
                    "op_mode": op_mode,
                    "engine_count": 2,
                    "static_thrust_band": "middle",
                    OPERATING_CNT_BAND: "middle",
                }
            )
    metrics = evaluation.metrics_for(
        pd.DataFrame(rows), "jet_compact_v1", bootstrap=(0.0, 0.0)
    )
    payload = metrics_payload(metrics)
    assert set(payload["rf_task_rmse"]) == {
        f"{metric}/{op_mode}" for metric, op_mode in tasks
    }
    assert all(
        metrics.task_rmse[task] < metrics.rf_task_rmse[task]
        for task in metrics.task_rmse
    )
