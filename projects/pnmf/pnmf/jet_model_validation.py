"""Jet samples, grouped folds, predictions, and balanced metrics."""

from __future__ import annotations

import time
from collections.abc import Mapping

import numpy as np
import pandas as pd  # noqa: PANDAS_OK - validation artifacts use the existing DataFrame contract.
from sklearn.model_selection import StratifiedGroupKFold

from .anp import ANPDatabase
from .jet_features import (
    TOTAL_OPERATING_FEATURE,
    validate_jet_power_parameter,
    jet_feature_names,
)
from .models import (
    SUPPORTED_LEARNERS,
    enforce_distance_monotone,
    validation_regressor,
)
from .core import STANDARD_DISTANCES_FT
from .validation import COMBOS, TRUTH_COLUMNS, build_samples

JET_SAMPLE_COUNT = 2664
JET_CURVE_COUNT = 94
JET_GROUP_COUNT = 93
OPERATING_CNT_BAND = "operating_cnt_band"


class JetValidationError(ValueError):
    pass


def build_jet_samples(db: ANPDatabase) -> pd.DataFrame:
    """Build the complete Jet population and its derived CNT fields."""
    samples = build_samples(db)
    jet = samples.loc[samples["engine_type"] == "Jet"].copy()
    if jet.empty:
        raise JetValidationError("Jet validation population is empty")
    for parameter in sorted(jet["power_parameter"].unique()):
        validate_jet_power_parameter(str(parameter))
    jet[TOTAL_OPERATING_FEATURE] = jet["log_power_lb"] + np.log10(
        jet["engine_count"].to_numpy(dtype=float)
    )
    jet[OPERATING_CNT_BAND] = pd.qcut(
        jet[TOTAL_OPERATING_FEATURE], q=3, labels=False, duplicates="drop"
    ).astype(int)
    _check_jet_population(jet)
    return jet.sort_values(
        ["metric", "op_mode", "npd_id", "source_dataset", "power_setting"],
        kind="mergesort",
        ignore_index=True,
    )


def build_jet_group_folds(
    samples: pd.DataFrame, *, folds: int, seed: int
) -> pd.DataFrame:
    """Create deterministic five-fold splits stratified by count and thrust."""
    _check_jet_population(samples)
    curves = samples[
        ["npd_id", "aircraft_group_id", "engine_count", "log_total_thrust"]
    ].drop_duplicates()
    group_counts = curves.groupby("aircraft_group_id")["engine_count"].nunique()
    if int(group_counts.max()) != 1:
        raise JetValidationError("Jet aircraft groups contain mixed engine counts")
    group_thrust = curves.groupby("aircraft_group_id")["log_total_thrust"].nunique()
    if int(group_thrust.max()) != 1:
        raise JetValidationError("Jet aircraft groups contain mixed static thrust")
    groups = (
        curves.groupby("aircraft_group_id", as_index=False)
        .agg(
            engine_count=("engine_count", "first"),
            log_total_static_thrust=("log_total_thrust", "first"),
        )
        .sort_values("aircraft_group_id", kind="mergesort")
    )
    groups["static_thrust_band"] = pd.qcut(
        groups["log_total_static_thrust"],
        q=3,
        labels=False,
        duplicates="drop",
    ).astype(int)
    groups["stratum"] = (
        groups["engine_count"].astype(str)
        + ":"
        + groups["static_thrust_band"].astype(str)
    )
    if folds < 2 or folds > len(groups):
        raise JetValidationError(f"folds must be in [2, {len(groups)}]")
    import warnings
    splitter = StratifiedGroupKFold(
        n_splits=folds, shuffle=True, random_state=seed
    )
    x = np.zeros((len(groups), 1), dtype=float)
    assignment: dict[str, int] = {}
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="The least populated class in y has only 1 members")
        for fold, (_, test_index) in enumerate(
            splitter.split(x, groups["stratum"], groups["aircraft_group_id"])
        ):
            for index in test_index:
                assignment[str(groups.iloc[index]["aircraft_group_id"])] = fold
    groups["fold"] = groups["aircraft_group_id"].map(assignment).astype(int)
    result = curves.merge(
        groups[
            [
                "aircraft_group_id",
                "static_thrust_band",
                "stratum",
                "fold",
            ]
        ],
        on="aircraft_group_id",
        how="left",
        validate="many_to_one",
    )
    return result.sort_values("npd_id", kind="mergesort").reset_index(drop=True)


def fit_jet_variant(
    learner: str,
    seed: int,
    train: pd.DataFrame,
    test: pd.DataFrame,
    schema_id: str,
) -> tuple[np.ndarray, float]:
    """Fit one frozen learner/schema pair and return projected predictions."""
    if learner not in SUPPORTED_LEARNERS:
        raise JetValidationError(f"unsupported learner {learner!r}")
    names = jet_feature_names(schema_id)
    regressor = validation_regressor(learner, seed)
    started = time.perf_counter()
    regressor.fit(
        train.loc[:, names].to_numpy(dtype=float),
        train.loc[:, TRUTH_COLUMNS].to_numpy(dtype=float),
    )
    prediction = regressor.predict(test.loc[:, names].to_numpy(dtype=float))
    return (
        enforce_distance_monotone(np.asarray(prediction, dtype=float)),
        time.perf_counter() - started,
    )


def jet_prediction_frame(
    test: pd.DataFrame,
    prediction: np.ndarray,
    *,
    learner: str,
    schema_id: str,
    seed: int,
    fold: int,
) -> pd.DataFrame:
    """Expand ten-distance predictions into an auditable long-form frame."""
    columns = [
        "sample_id",
        "metric",
        "op_mode",
        "npd_id",
        "aircraft_group_id",
        "acft_ids",
        "source_dataset",
        "engine_type",
        "engine_count",
        "power_parameter",
        "power_setting",
        "static_thrust_band",
        OPERATING_CNT_BAND,
    ]
    identity = test.loc[:, columns].reset_index(drop=True)
    truth = test.loc[:, TRUTH_COLUMNS].to_numpy(dtype=float)
    frames: list[pd.DataFrame] = []
    for distance_index, distance_ft in enumerate(STANDARD_DISTANCES_FT):
        frame = identity.copy()
        frame["distance_ft"] = float(distance_ft)
        frame["truth_dB"] = truth[:, distance_index]
        frame["prediction_dB"] = prediction[:, distance_index]
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    result["error_dB"] = result["prediction_dB"] - result["truth_dB"]
    result.insert(0, "fold", fold)
    result.insert(0, "seed", seed)
    result.insert(0, "schema_id", schema_id)
    result.insert(0, "model", learner)
    return result


def balanced_task_metrics(frame: pd.DataFrame) -> tuple[float, dict[str, float]]:
    """Return task/group-balanced RMSE and one RMSE per metric/mode task."""
    grouped = (
        frame.assign(squared_error=frame["error_dB"] ** 2)
        .groupby(["aircraft_group_id", "metric", "op_mode"], sort=True)[
            "squared_error"
        ]
        .mean()
        .reset_index()
    )
    task_mse = grouped.groupby(["metric", "op_mode"], sort=True)[
        "squared_error"
    ].mean()
    overall = float(np.sqrt(task_mse.mean()))
    task = {
        f"{metric}/{mode}": float(np.sqrt(value))
        for (metric, mode), value in task_mse.items()
    }
    return overall, task


def slice_rmse(frame: pd.DataFrame, column: str) -> dict[str, float]:
    """Return group-balanced RMSE for each requested validation slice."""
    result: dict[str, float] = {}
    for value, subset in frame.groupby(column, sort=True):
        result[str(value)] = balanced_task_metrics(subset)[0]
    return result


def paired_group_bootstrap(
    candidate: pd.DataFrame,
    baseline: pd.DataFrame,
    *,
    resamples: int = 10_000,
    seed: int = 20260724,
) -> tuple[float, float]:
    """Estimate a paired aircraft-group RMSE-delta confidence interval."""
    keys = ["aircraft_group_id", "metric", "op_mode"]
    def group_mse(frame: pd.DataFrame) -> pd.DataFrame:
        return (
            frame.assign(squared_error=frame["error_dB"] ** 2)
            .groupby(keys, sort=True)["squared_error"]
            .mean()
            .reset_index()
        )
    left = group_mse(candidate).rename(columns={"squared_error": "candidate"})
    right = group_mse(baseline).rename(columns={"squared_error": "baseline"})
    paired = left.merge(right, on=keys, how="inner", validate="one_to_one")
    groups = np.array(sorted(paired["aircraft_group_id"].unique()), dtype=object)
    if len(groups) < 2:
        raise JetValidationError("paired bootstrap requires at least two aircraft groups")
    tasks = sorted(set(zip(paired["metric"], paired["op_mode"])))
    index = pd.MultiIndex.from_tuples(
        [(group, metric, mode) for group in groups for metric, mode in tasks],
        names=keys,
    )
    paired = paired.set_index(keys).reindex(index)
    candidate_mse = paired["candidate"].to_numpy().reshape(len(groups), len(tasks))
    baseline_mse = paired["baseline"].to_numpy().reshape(len(groups), len(tasks))
    rng = np.random.default_rng(seed)
    sampled = rng.integers(0, len(groups), size=(resamples, len(groups)))
    candidate_rmse = np.sqrt(candidate_mse[sampled].mean(axis=(1, 2)))
    baseline_rmse = np.sqrt(baseline_mse[sampled].mean(axis=(1, 2)))
    delta = candidate_rmse - baseline_rmse
    return float(np.percentile(delta, 2.5)), float(np.percentile(delta, 97.5))


def _check_jet_population(samples: pd.DataFrame) -> None:
    if len(samples) != JET_SAMPLE_COUNT:
        raise JetValidationError(f"Jet population has {len(samples)} rows, expected {JET_SAMPLE_COUNT}")
    if samples["npd_id"].nunique() != JET_CURVE_COUNT:
        raise JetValidationError("Jet population must contain exactly 94 curves")
    if samples["aircraft_group_id"].nunique() != JET_GROUP_COUNT:
        raise JetValidationError("Jet population must contain exactly 93 aircraft groups")
    support = samples.groupby(["metric", "op_mode"])["npd_id"].nunique()
    if set(support) != {JET_CURVE_COUNT} or len(support) != len(COMBOS):
        raise JetValidationError("every Jet metric/mode task must contain all 94 curves")
