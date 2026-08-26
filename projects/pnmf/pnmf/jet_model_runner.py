"""Run the evidence-gated Jet model comparison and promotion check."""

from __future__ import annotations

import hashlib
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Sequence

import numpy as np
import pandas as pd  # noqa: PANDAS_OK - validation artifacts use the existing DataFrame contract.

from .anp import ANPDatabase, PROJECT_ROOT
from .jet_features import JET_CANDIDATE_SCHEMA_IDS, jet_feature_names
from .jet_model_artifacts import (
    ArtifactBundle,
    JSONValue,
    decision_payload,
    metrics_payload,
    write_artifacts,
    write_manifest,
    write_report,
    write_status,
)
from .jet_model_evaluation import evaluate_schema, evaluate_verified_route, metrics_for
from .jet_model_gates import GateThresholds, evaluate_promotion_gate, select_feature_schema
from .jet_model_validation import (
    JetValidationError,
    build_jet_group_folds,
    build_jet_samples,
    paired_group_bootstrap,
)
from .jet_reference_validation import EXPECTED as JET_REFERENCE_EXPECTED
from .jet_model_selection import feature_evaluations
from .models import SUPPORTED_LEARNERS
from .validation import COMBOS

JET_V2_SEEDS: Final = (13, 91, 20260724)
JET_V2_FOLDS: Final = 5
BOOTSTRAP_RESAMPLES: Final = 10_000
DEFAULT_OUTPUT_DIR: Final = PROJECT_ROOT / "outputs" / "jet_model_validation" / "current"
DEFAULT_REPORT_PATH: Final = PROJECT_ROOT.parents[1] / "docs" / "JET_MODEL_METHODOLOGY_AND_VALIDATION_REPORT.md"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_db_path(db_path: Path) -> Path:
    candidate = db_path.expanduser()
    if candidate.is_absolute() or candidate.exists():
        return candidate.resolve()
    return (PROJECT_ROOT / candidate).resolve()


def run_jet_model_validation(
    *,
    db_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_path: Path = DEFAULT_REPORT_PATH,
    folds: int = JET_V2_FOLDS,
    seeds: Sequence[int] = JET_V2_SEEDS,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict[str, JSONValue]:
    """Run all Jet candidates, compare the verified route, and write artifacts."""
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    seed_values = tuple(seeds)
    if not seed_values:
        raise JetValidationError("at least one Jet validation seed is required")
    resolved_db_path = _resolve_db_path(db_path)
    db = ANPDatabase(resolved_db_path)
    samples = build_jet_samples(db)
    split_frames = [
        build_jet_group_folds(samples, folds=folds, seed=seed)
        for seed in seed_values
    ]
    split_artifact = pd.concat(
        [frame.assign(seed=seed) for seed, frame in zip(seed_values, split_frames)],
        ignore_index=True,
    )
    candidate_frames: list[pd.DataFrame] = []
    run_records: list[dict[str, str | int | float]] = []
    for schema_id in JET_CANDIDATE_SCHEMA_IDS:
        frame, runs = evaluate_schema(
            samples,
            seeds=seed_values,
            folds=folds,
            schema_id=schema_id,
            split_frames=split_frames,
        )
        candidate_frames.append(frame)
        run_records.extend(runs)
    candidates = pd.concat(candidate_frames, ignore_index=True)
    evaluations, decisions, bootstrap = feature_evaluations(
        candidates, bootstrap_resamples=bootstrap_resamples
    )
    selected_schema = select_feature_schema(
        evaluations, baseline_schema=JET_CANDIDATE_SCHEMA_IDS[0]
    )
    selected_predictions = candidates.loc[
        candidates["schema_id"] == selected_schema
    ]
    et_rf_interval = paired_group_bootstrap(
        selected_predictions.loc[selected_predictions["model"] == "et"],
        selected_predictions.loc[selected_predictions["model"] == "rf"],
        resamples=bootstrap_resamples,
        seed=20260724,
    )
    route_predictions, route_runs, verified_ids = evaluate_verified_route(
        db,
        samples,
        seeds=seed_values,
        folds=folds,
        split_frames=split_frames,
    )
    run_records.extend(route_runs)
    all_predictions = pd.concat([candidates, route_predictions], ignore_index=True)
    route_interval = paired_group_bootstrap(
        selected_predictions.loc[selected_predictions["model"] == "et"],
        route_predictions.loc[route_predictions["model"] == "et"],
        resamples=bootstrap_resamples,
        seed=20260724,
    )
    route_candidate_metrics = metrics_for(
        selected_predictions, selected_schema, bootstrap=route_interval
    )
    verified_metrics = metrics_for(
        route_predictions, "verified_route", bootstrap=(0.0, 0.0)
    )
    route_decision = evaluate_promotion_gate(route_candidate_metrics, verified_metrics)
    promotion_passed = bool(route_decision.passed)
    bootstrap["route_vs_verified"] = {
        "seed": 20260724,
        "resamples": bootstrap_resamples,
        "delta_ci_rmse_dB": list(route_interval),
    }
    bootstrap["et_vs_rf"] = {
        "seed": 20260724,
        "resamples": bootstrap_resamples,
        "delta_ci_rmse_dB": list(et_rf_interval),
    }
    schema_metrics: dict[str, JSONValue] = {
        schema_id: metrics_payload(
            metrics_for(candidates, schema_id, bootstrap=(0.0, 0.0))
        )
        for schema_id in JET_CANDIDATE_SCHEMA_IDS
    }
    schema_metrics["verified_route"] = metrics_payload(verified_metrics)
    selected_metrics = schema_metrics[selected_schema]
    if isinstance(selected_metrics, dict):
        selected_metrics["route_gate_bootstrap_delta_ci"] = list(route_interval)
    gates: dict[str, JSONValue] = {
        "feature_candidates": decisions,
        "route": decision_payload(route_decision),
    }
    manifest: dict[str, JSONValue] = {
        "schema_version": 2,
        "run": {
            "started_utc": started.isoformat(),
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": time.perf_counter() - timer,
        },
        "config": {
            "folds": folds,
            "seeds": list(seed_values),
            "bootstrap_seed": 20260724,
            "bootstrap_resamples": bootstrap_resamples,
            "learners": list(SUPPORTED_LEARNERS),
            "tasks": [{"metric": metric, "op_mode": mode} for metric, mode in COMBOS],
        },
        "counts": {
            "samples": int(len(samples)),
            "curves": int(samples["npd_id"].nunique()),
            "aircraft_groups": int(samples["aircraft_group_id"].nunique()),
            "verified_curves": len(verified_ids),
        },
        "legacy_release_transfer": {
            "evidence_type": "descriptive_release_transfer",
            "counts": JET_REFERENCE_EXPECTED,
        },
        "features": {
            "schemas": {
                schema_id: list(jet_feature_names(schema_id))
                for schema_id in JET_CANDIDATE_SCHEMA_IDS
            },
            "production_schema": "jet-v2",
            "derived_formula": "log10(per_engine_CNT_lb * engine_count)",
            "derived_field": "log_total_operating_cnt_lb",
            "removed_constant_columns": ["is_jet", "is_turboprop", "is_piston"],
        },
        "feature_selection": {
            "selected_schema": selected_schema,
            "production_schema": "jet-v2",
            "candidate_order": list(JET_CANDIDATE_SCHEMA_IDS),
            "selected_metrics": metrics_payload(
                metrics_for(candidates, selected_schema, bootstrap=(0.0, 0.0))
            ),
            "evaluations": [
                {
                    "schema_id": evaluation.schema_id,
                    "feature_count": evaluation.feature_count,
                    "passed": evaluation.passed,
                    "metrics": metrics_payload(evaluation.metrics),
                }
                for evaluation in evaluations
            ],
        },
        "thresholds": {
            "min_relative_improvement": GateThresholds().min_relative_improvement,
            "max_task_regression_db": GateThresholds().max_task_regression_db,
            "max_slice_regression_db": GateThresholds().max_slice_regression_db,
            "max_rf_regression_fraction": GateThresholds().max_rf_regression_fraction,
            "tie_margin_db": GateThresholds().tie_margin_db,
        },
        "gates": gates,
        "promotion": {
            "passed": promotion_passed,
            "production_scope": "jet_merged" if promotion_passed else "verified",
            "model_identities": (
                [f"{learner}-jet_merged-jet-v2" for learner in SUPPORTED_LEARNERS]
                if promotion_passed
                else [f"{learner}-verified" for learner in SUPPORTED_LEARNERS]
            ),
            "verified_ids": list(verified_ids),
        },
        "model_comparison": {
            "production_learner": "et",
            "validation_challenger": "rf",
            "et_overall_rmse": float(selected_metrics["overall_rmse"]),
            "rf_overall_rmse": float(selected_metrics["rf_overall_rmse"]),
            "et_task_rmse": dict(selected_metrics["task_rmse"]),
            "rf_task_rmse": dict(selected_metrics["rf_task_rmse"]),
            "et_minus_rf_bootstrap_ci": list(et_rf_interval),
        },
        "inputs": {
            "datastore": str(resolved_db_path),
            "datastore_sha256": _sha256(resolved_db_path),
        },
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "platform": platform.platform(),
        },
        "artifacts": {},
    }
    manifest["artifacts"] = write_artifacts(
        output_dir,
        ArtifactBundle(
            samples=samples,
            splits=split_artifact,
            predictions=all_predictions,
            runs=tuple(run_records),
            schema_metrics=schema_metrics,
            gates=gates,
            bootstrap=bootstrap,
        ),
    )
    write_report(report_path, manifest)
    manifest["artifacts"]["validation_report"] = {
        "path": str(report_path.resolve()),
        "sha256": _sha256(report_path),
        "bytes": report_path.stat().st_size,
    }
    manifest["artifacts"]["promotion_status.json"] = write_status(
        output_dir, manifest
    )
    write_manifest(output_dir, manifest)
    return manifest
