"""Fit Jet feature candidates and calculate comparable validation metrics."""

from __future__ import annotations

import time
from collections.abc import Sequence

import numpy as np
import pandas as pd  # noqa: PANDAS_OK - validation artifacts use the existing DataFrame contract.

from .anp import ANPDatabase
from .jet_model_gates import VariantMetrics
from .jet_model_validation import (
    OPERATING_CNT_BAND,
    balanced_task_metrics,
    fit_jet_variant,
    jet_prediction_frame,
    slice_rmse,
)
from .models import SUPPORTED_LEARNERS, enforce_distance_monotone, validation_regressor
from .validation import COMBOS, FEATURES, TRUTH_COLUMNS
from .verified_anp import resolve_training_scope

RunRecord = dict[str, str | int | float]


def fit_verified_variant(
    learner: str, seed: int, train: pd.DataFrame, test: pd.DataFrame
) -> tuple[np.ndarray, float]:
    """Fit the frozen legacy feature contract for route comparison."""
    regressor = validation_regressor(learner, seed)
    started = time.perf_counter()
    regressor.fit(
        train.loc[:, FEATURES].to_numpy(dtype=float),
        train.loc[:, TRUTH_COLUMNS].to_numpy(dtype=float),
    )
    prediction = regressor.predict(test.loc[:, FEATURES].to_numpy(dtype=float))
    return (
        enforce_distance_monotone(np.asarray(prediction, dtype=float)),
        time.perf_counter() - started,
    )


def evaluate_schema(
    samples: pd.DataFrame,
    *,
    seeds: Sequence[int],
    folds: int,
    schema_id: str,
    split_frames: Sequence[pd.DataFrame],
) -> tuple[pd.DataFrame, list[RunRecord]]:
    """Evaluate one Jet schema for every learner, task, seed, and fold."""
    predictions: list[pd.DataFrame] = []
    runs: list[RunRecord] = []
    for seed, split in zip(seeds, split_frames):
        group_split = split.drop_duplicates("aircraft_group_id").set_index(
            "aircraft_group_id"
        )
        for metric, mode in COMBOS:
            combo = samples.loc[
                (samples["metric"] == metric) & (samples["op_mode"] == mode)
            ].copy()
            combo["_fold"] = combo["aircraft_group_id"].map(group_split["fold"])
            combo["static_thrust_band"] = combo["aircraft_group_id"].map(
                group_split["static_thrust_band"]
            )
            for learner in SUPPORTED_LEARNERS:
                for fold in range(folds):
                    train = combo.loc[combo["_fold"] != fold]
                    test = combo.loc[combo["_fold"] == fold]
                    prediction, duration = fit_jet_variant(
                        learner, seed, train, test, schema_id
                    )
                    predictions.append(
                        jet_prediction_frame(
                            test,
                            prediction,
                            learner=learner,
                            schema_id=schema_id,
                            seed=seed,
                            fold=fold,
                        )
                    )
                    runs.append(
                        {
                            "schema_id": schema_id,
                            "seed": seed,
                            "learner": learner,
                            "metric": metric,
                            "op_mode": mode,
                            "fold": fold,
                            "train_samples": len(train),
                            "train_curves": train["npd_id"].nunique(),
                            "test_samples": len(test),
                            "test_curves": test["npd_id"].nunique(),
                            "fit_predict_seconds": duration,
                        }
                    )
    return pd.concat(predictions, ignore_index=True), runs


def evaluate_verified_route(
    db: ANPDatabase,
    samples: pd.DataFrame,
    *,
    seeds: Sequence[int],
    folds: int,
    split_frames: Sequence[pd.DataFrame],
) -> tuple[pd.DataFrame, list[RunRecord], tuple[str, ...]]:
    """Evaluate the current 11-curve verified route on identical Jet folds."""
    verified_ids = resolve_training_scope(db, "verified").selected_npd_ids
    predictions: list[pd.DataFrame] = []
    runs: list[RunRecord] = []
    for seed, split in zip(seeds, split_frames):
        group_split = split.drop_duplicates("aircraft_group_id").set_index(
            "aircraft_group_id"
        )
        for metric, mode in COMBOS:
            combo = samples.loc[
                (samples["metric"] == metric) & (samples["op_mode"] == mode)
            ].copy()
            combo["_fold"] = combo["aircraft_group_id"].map(group_split["fold"])
            combo["static_thrust_band"] = combo["aircraft_group_id"].map(
                group_split["static_thrust_band"]
            )
            for learner in SUPPORTED_LEARNERS:
                for fold in range(folds):
                    test = combo.loc[combo["_fold"] == fold]
                    train = combo.loc[
                        (combo["_fold"] != fold)
                        & combo["npd_id"].isin(verified_ids)
                    ]
                    prediction, duration = fit_verified_variant(
                        learner, seed, train, test
                    )
                    predictions.append(
                        jet_prediction_frame(
                            test,
                            prediction,
                            learner=learner,
                            schema_id="verified_route",
                            seed=seed,
                            fold=fold,
                        )
                    )
                    runs.append(
                        {
                            "schema_id": "verified_route",
                            "seed": seed,
                            "learner": learner,
                            "metric": metric,
                            "op_mode": mode,
                            "fold": fold,
                            "train_samples": len(train),
                            "train_curves": train["npd_id"].nunique(),
                            "test_samples": len(test),
                            "test_curves": len(test["npd_id"].unique()),
                            "fit_predict_seconds": duration,
                        }
                    )
    return pd.concat(predictions, ignore_index=True), runs, verified_ids


def metrics_for(
    predictions: pd.DataFrame, schema_id: str, *, bootstrap: tuple[float, float]
) -> VariantMetrics:
    """Summarize a schema with task/group-balanced ET and overall RF RMSE."""
    et = predictions.loc[
        (predictions["schema_id"] == schema_id) & (predictions["model"] == "et")
    ]
    rf = predictions.loc[
        (predictions["schema_id"] == schema_id) & (predictions["model"] == "rf")
    ]
    overall, task = balanced_task_metrics(et)
    slices: dict[str, float] = {}
    for column in ("engine_count", "static_thrust_band", OPERATING_CNT_BAND):
        slices.update(
            {f"{column}={key}": value for key, value in slice_rmse(et, column).items()}
        )
    rf_overall, rf_task = balanced_task_metrics(rf)
    return VariantMetrics(
        overall_rmse=overall,
        task_rmse=task,
        slice_rmse=slices,
        bootstrap_delta_ci=bootstrap,
        rf_overall_rmse=rf_overall,
        rf_task_rmse=rf_task,
    )
