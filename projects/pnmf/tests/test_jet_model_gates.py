from pnmf.jet_model_gates import (
    GateThresholds,
    SchemaEvaluation,
    VariantMetrics,
    evaluate_promotion_gate,
    select_feature_schema,
)


def _metrics(
    overall: float,
    task_delta: float = 0.0,
    slice_delta: float = 0.0,
    ci: tuple[float, float] = (-0.3, -0.1),
    rf_overall: float = 4.0,
) -> VariantMetrics:
    return VariantMetrics(
        overall_rmse=overall,
        task_rmse={"SEL:D": 3.0 + task_delta},
        slice_rmse={"engine_count:2": 3.0 + slice_delta},
        bootstrap_delta_ci=ci,
        rf_overall_rmse=rf_overall,
        rf_task_rmse={"SEL:D": 3.0},
    )


def test_gate_passes_only_when_all_conservative_checks_pass():
    baseline = _metrics(5.0, rf_overall=4.0)
    candidate = _metrics(4.7, rf_overall=3.95)
    decision = evaluate_promotion_gate(
        candidate,
        baseline,
        GateThresholds(min_relative_improvement=0.05),
    )
    assert decision.passed
    assert decision.failures == ()


def test_gate_reports_statistical_and_slice_failures():
    baseline = _metrics(5.0, rf_overall=4.0)
    candidate = _metrics(
        4.7,
        task_delta=0.3,
        slice_delta=0.6,
        ci=(-0.2, 0.01),
        rf_overall=4.2,
    )
    decision = evaluate_promotion_gate(candidate, baseline)
    assert not decision.passed
    assert {
        "bootstrap_ci",
        "task_regression",
        "slice_regression",
        "rf_regression",
    }.issubset(decision.failures)


def test_schema_selection_uses_fewer_features_when_rmse_is_within_tie_margin():
    baseline = _metrics(5.0)
    evaluations = (
        SchemaEvaluation("wide", 10, _metrics(4.70), 0, True),
        SchemaEvaluation("compact", 9, _metrics(4.73), 1, True),
        SchemaEvaluation("worse", 8, _metrics(4.95), 2, False),
    )
    assert select_feature_schema(evaluations, baseline_schema="compact") == "compact"
