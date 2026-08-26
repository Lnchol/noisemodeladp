"""Select a Jet feature schema using the declared conservative gate."""

from __future__ import annotations

import pandas as pd  # noqa: PANDAS_OK - validation artifacts use the existing DataFrame contract.

from .jet_features import JET_CANDIDATE_SCHEMA_IDS, jet_feature_names
from .jet_model_artifacts import JSONValue, decision_payload
from .jet_model_gates import (
    SchemaEvaluation,
    evaluate_promotion_gate,
    VariantMetrics,
)
from .jet_model_validation import paired_group_bootstrap


def feature_evaluations(
    predictions: pd.DataFrame,
    *,
    bootstrap_resamples: int,
) -> tuple[list[SchemaEvaluation], dict[str, JSONValue], dict[str, JSONValue]]:
    """Score every non-baseline schema against the compact Jet baseline."""
    baseline_id = JET_CANDIDATE_SCHEMA_IDS[0]
    baseline_et = predictions.loc[
        (predictions["schema_id"] == baseline_id) & (predictions["model"] == "et")
    ]
    baseline = _metrics_for_baseline(predictions, baseline_id)
    evaluations: list[SchemaEvaluation] = []
    decisions: dict[str, JSONValue] = {}
    bootstrap: dict[str, JSONValue] = {}
    for order, schema_id in enumerate(JET_CANDIDATE_SCHEMA_IDS[1:], start=1):
        candidate_et = predictions.loc[
            (predictions["schema_id"] == schema_id) & (predictions["model"] == "et")
        ]
        interval = paired_group_bootstrap(
            candidate_et,
            baseline_et,
            resamples=bootstrap_resamples,
            seed=20260724,
        )
        metrics = _metrics_for_baseline(predictions, schema_id, interval)
        decision = evaluate_promotion_gate(metrics, baseline)
        evaluations.append(
            SchemaEvaluation(
                schema_id=schema_id,
                feature_count=len(jet_feature_names(schema_id)),
                metrics=metrics,
                candidate_order=order,
                passed=decision.passed,
            )
        )
        decisions[schema_id] = decision_payload(decision)
        bootstrap[schema_id] = {
            "seed": 20260724,
            "resamples": bootstrap_resamples,
            "delta_ci_rmse_dB": list(interval),
        }
    return evaluations, decisions, bootstrap


def _metrics_for_baseline(
    predictions: pd.DataFrame,
    schema_id: str,
    bootstrap: tuple[float, float] = (0.0, 0.0),
) -> VariantMetrics:
    from .jet_model_evaluation import metrics_for

    return metrics_for(predictions, schema_id, bootstrap=bootstrap)
