"""Pure promotion gates for the Jet learned-model validation workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping, Sequence

DEFAULT_TASK_REGRESSION_DB: Final = 0.25
DEFAULT_SLICE_REGRESSION_DB: Final = 0.50
DEFAULT_RF_REGRESSION_FRACTION: Final = 0.01
DEFAULT_TIE_MARGIN_DB: Final = 0.05


@dataclass(frozen=True, slots=True)
class GateThresholds:
    """Fixed accuracy and regression limits for a promotion decision."""

    min_relative_improvement: float = 0.05
    max_task_regression_db: float = DEFAULT_TASK_REGRESSION_DB
    max_slice_regression_db: float = DEFAULT_SLICE_REGRESSION_DB
    max_rf_regression_fraction: float = DEFAULT_RF_REGRESSION_FRACTION
    tie_margin_db: float = DEFAULT_TIE_MARGIN_DB


@dataclass(frozen=True, slots=True)
class VariantMetrics:
    """Aggregate candidate metrics required by the promotion gate."""

    overall_rmse: float
    task_rmse: Mapping[str, float]
    slice_rmse: Mapping[str, float]
    bootstrap_delta_ci: tuple[float, float]
    rf_overall_rmse: float
    rf_task_rmse: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Explain whether a candidate satisfies every promotion check."""

    passed: bool
    relative_improvement: float
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SchemaEvaluation:
    """Candidate metrics and stable tie-breaking information."""

    schema_id: str
    feature_count: int
    metrics: VariantMetrics
    candidate_order: int
    passed: bool


def evaluate_promotion_gate(
    candidate: VariantMetrics,
    baseline: VariantMetrics,
    thresholds: GateThresholds = GateThresholds(),
) -> GateDecision:
    """Apply the conservative ET/RF, confidence, task, and slice checks."""
    if baseline.overall_rmse <= 0.0:
        relative_improvement = 0.0
    else:
        relative_improvement = (
            baseline.overall_rmse - candidate.overall_rmse
        ) / baseline.overall_rmse
    failures: list[str] = []
    if relative_improvement < thresholds.min_relative_improvement:
        failures.append("overall_improvement")
    if candidate.bootstrap_delta_ci[1] >= 0.0:
        failures.append("bootstrap_ci")
    if any(
        value > thresholds.max_task_regression_db
        for value in _deltas(candidate.task_rmse, baseline.task_rmse).values()
    ):
        failures.append("task_regression")
    if any(
        value > thresholds.max_slice_regression_db
        for value in _deltas(candidate.slice_rmse, baseline.slice_rmse).values()
    ):
        failures.append("slice_regression")
    rf_limit = baseline.rf_overall_rmse * (
        1.0 + thresholds.max_rf_regression_fraction
    )
    if candidate.rf_overall_rmse > rf_limit:
        failures.append("rf_regression")
    return GateDecision(
        passed=not failures,
        relative_improvement=float(relative_improvement),
        failures=tuple(failures),
    )


def _deltas(
    candidate: Mapping[str, float], baseline: Mapping[str, float]
) -> dict[str, float]:
    return {
        key: float(candidate[key] - baseline[key])
        for key in candidate.keys() & baseline.keys()
    }


def select_feature_schema(
    evaluations: Sequence[SchemaEvaluation], baseline_schema: str
) -> str:
    """Choose the best passing schema with deterministic tie-breaking."""
    passing = [evaluation for evaluation in evaluations if evaluation.passed]
    if not passing:
        return baseline_schema
    best_rmse = min(e.metrics.overall_rmse for e in passing)
    finalists = [
        evaluation
        for evaluation in passing
        if evaluation.metrics.overall_rmse - best_rmse <= DEFAULT_TIE_MARGIN_DB
    ]
    return min(
        finalists,
        key=lambda evaluation: (
            evaluation.feature_count,
            evaluation.candidate_order,
            evaluation.schema_id,
        ),
    ).schema_id
