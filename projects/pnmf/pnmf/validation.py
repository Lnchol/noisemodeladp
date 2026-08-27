"""Reproducible validation of the production ET/RF NPD regressors.

This module is intentionally separate from :mod:`pnmf.models`' historical
``loo_validate`` function.  It evaluates the exact production learners while
making release boundaries and aircraft-identity grouping explicit.  It never
writes to the ANP truth tables or the model registry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import sklearn

from .anp import ANPDatabase, DIST_COLS, PROJECT_ROOT
from .core import ParametricAircraft, STANDARD_DISTANCES_FT
from .models import (
    SUPPORTED_LEARNERS,
    enforce_distance_monotone,
    power_features,
    validation_regressor,
)

COMBOS = tuple(
    (metric, mode)
    for metric in ("SEL", "LAmax", "EPNL", "PNLTM")
    for mode in ("A", "D")
)
FEATURES = tuple(ParametricAircraft.feature_names()) + (
    "log_power_lb",
    "throttle",
)
TRUTH_COLUMNS = tuple(f"truth_{column}" for column in DIST_COLS)
MODEL_PARAMS = {
    "et": {
        "class": "sklearn.ensemble.ExtraTreesRegressor",
        "n_estimators": 500,
        "min_samples_leaf": 1,
        "max_depth": 24,
        "max_features": 0.5,
        "random_state": "run_seed",
        "n_jobs": -1,
    },
    "rf": {
        "class": "sklearn.ensemble.RandomForestRegressor",
        "n_estimators": 200,
        "min_samples_leaf": 2,
        "max_depth": None,
        "max_features": 1.0,
        "random_state": "run_seed",
        "n_jobs": -1,
    },
}
PROTOCOL_INTERNAL = "internal_aircraft_group_cv"
PROTOCOL_TEMPORAL = "temporal_release_holdout"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def exact_model_params(seed: int) -> dict[str, dict]:
    """Return every effective sklearn constructor parameter for this run."""
    result: dict[str, dict] = {}
    for learner in SUPPORTED_LEARNERS:
        regressor = validation_regressor(learner, seed)
        result[learner] = {
            "class": (
                f"{regressor.__class__.__module__}."
                f"{regressor.__class__.__name__}"
            ),
            "parameters": regressor.get_params(deep=True),
            "post_prediction_distance_monotone": True,
        }
    return result


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stable_token(parts: Iterable[object], length: int = 16) -> str:
    text = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def aircraft_group_map(
    aircraft: pd.DataFrame,
) -> tuple[dict[str, str], dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Return leakage-safe connected components for every NPD curve.

    Aircraft and NPD identifiers form a bipartite graph.  Connected components
    ensure that a shared NPD curve is never split and that an identical ACFT_ID
    appearing in two releases (notably ``7773ER``) remains in one fold.
    """
    uf = _UnionFind()
    direct_acft: dict[str, set[str]] = defaultdict(set)
    for row in aircraft.dropna(subset=["ACFT_ID", "NPD_ID"]).itertuples(
        index=False
    ):
        acft_id = str(getattr(row, "ACFT_ID")).strip()
        npd_id = str(getattr(row, "NPD_ID")).strip()
        uf.union(f"A:{acft_id}", f"N:{npd_id}")
        direct_acft[npd_id].add(acft_id)

    members: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"acft": set(), "npd": set()}
    )
    for node in tuple(uf.parent):
        root = uf.find(node)
        kind, value = node.split(":", 1)
        members[root]["acft" if kind == "A" else "npd"].add(value)

    npd_to_group: dict[str, str] = {}
    group_acft: dict[str, tuple[str, ...]] = {}
    for member in members.values():
        acft_ids = tuple(sorted(member["acft"]))
        npd_ids = tuple(sorted(member["npd"]))
        group_id = "ag_" + _stable_token((*acft_ids, "|", *npd_ids))
        group_acft[group_id] = acft_ids
        for npd_id in npd_ids:
            npd_to_group[npd_id] = group_id
    direct = {key: tuple(sorted(value)) for key, value in direct_acft.items()}
    return npd_to_group, group_acft, direct


def build_samples(db: ANPDatabase) -> pd.DataFrame:
    """Build the exact 12-input supervised surface and held-out truth grids."""
    params = db.param_table()
    npd_to_group, group_acft, direct_acft = aircraft_group_map(db.aircraft)
    rows: list[dict] = []
    for metric, mode in COMBOS:
        for npd_id in sorted(map(str, db.list_curve_sets(metric, mode))):
            descriptor = params.loc[npd_id]
            aircraft = ParametricAircraft.from_anp_row(npd_id, descriptor)
            feature_vector = aircraft.feature_vector()
            curve = db.curve(npd_id, metric, mode).reset_index(drop=True)
            power = curve["Power Setting"].to_numpy(dtype=float)
            log_power, throttle = power_features(
                power,
                descriptor["Power Parameter"],
                descriptor["Max Sea Level Static Thrust (lb)"],
            )
            group_id = npd_to_group[npd_id]
            acft_ids = direct_acft.get(npd_id, ())
            all_group_acft = group_acft[group_id]
            curve_powers = curve["Power Setting"].to_numpy(dtype=float)
            source_datasets = curve["source_dataset"].astype(str).to_numpy()
            source_files = curve["source_file"].astype(str).to_numpy()
            truth_mat = curve[DIST_COLS].to_numpy(dtype=float)
            rep_acft_id = str(descriptor.get("ACFT_ID", ""))
            desc_src = str(descriptor.get("source_dataset", ""))
            p_param = str(descriptor["Power Parameter"])
            acft_ids_str = "|".join(acft_ids)
            all_group_str = "|".join(all_group_acft)
            feat_dict = {name: float(feature_vector[name]) for name in ParametricAircraft.feature_names()}

            for power_index in range(len(curve)):
                src_ds = source_datasets[power_index]
                sample = {
                    "sample_id": f"{metric}:{mode}:{npd_id}:{src_ds}:{power_index}",
                    "metric": metric,
                    "op_mode": mode,
                    "npd_id": npd_id,
                    "aircraft_group_id": group_id,
                    "acft_ids": acft_ids_str,
                    "aircraft_group_acft_ids": all_group_str,
                    "representative_acft_id": rep_acft_id,
                    "source_dataset": src_ds,
                    "source_file": source_files[power_index],
                    "descriptor_source_dataset": desc_src,
                    "engine_type": aircraft.engine_type,
                    "engine_count": int(aircraft.n_engines),
                    "power_parameter": p_param,
                    "power_setting": float(curve_powers[power_index]),
                    **feat_dict,
                    "log_power_lb": float(log_power[power_index]),
                    "throttle": float(throttle[power_index]),
                }
                for t_idx, t_col in enumerate(TRUTH_COLUMNS):
                    sample[t_col] = float(truth_mat[power_index, t_idx])
                rows.append(sample)
    samples = pd.DataFrame(rows)
    return samples.sort_values(
        ["metric", "op_mode", "npd_id", "source_dataset", "power_setting"],
        kind="mergesort",
        ignore_index=True,
    )


def deterministic_group_folds(
    samples: pd.DataFrame, n_folds: int, seed: int
) -> pd.DataFrame:
    """Assign whole connected aircraft groups to balanced deterministic folds."""
    groups = (
        samples[["aircraft_group_id", "npd_id"]]
        .drop_duplicates()
        .groupby("aircraft_group_id", as_index=False)
        .agg(n_curves=("npd_id", "nunique"))
    )
    if n_folds < 2 or n_folds > len(groups):
        raise ValueError(
            f"folds must be in [2, {len(groups)}], received {n_folds}"
        )
    groups["tie"] = groups["aircraft_group_id"].map(
        lambda value: _stable_token((seed, value), length=64)
    )
    groups = groups.sort_values(
        ["n_curves", "tie", "aircraft_group_id"],
        ascending=[False, True, True],
        kind="mergesort",
    )
    load = [0] * n_folds
    assignment: dict[str, int] = {}
    for row in groups.itertuples(index=False):
        fold = min(range(n_folds), key=lambda value: (load[value], value))
        assignment[row.aircraft_group_id] = fold
        load[fold] += int(row.n_curves)
    curve_split = (
        samples[
            [
                "npd_id",
                "aircraft_group_id",
                "acft_ids",
                "aircraft_group_acft_ids",
                "source_dataset",
                "engine_type",
                "engine_count",
            ]
        ]
        .drop_duplicates()
        .sort_values(["npd_id", "source_dataset"], kind="mergesort")
    )
    curve_split.insert(0, "protocol", PROTOCOL_INTERNAL)
    curve_split.insert(1, "variant", "combined")
    curve_split["fold"] = curve_split["aircraft_group_id"].map(assignment)
    curve_split["role"] = "test_once"
    curve_split["seed"] = seed
    return curve_split.reset_index(drop=True)


def temporal_split(samples: pd.DataFrame) -> pd.DataFrame:
    """Describe raw and exact-ACFT-ID-purged release holdouts."""
    curves = samples[
        [
            "npd_id",
            "aircraft_group_id",
            "acft_ids",
            "source_dataset",
            "engine_type",
            "engine_count",
        ]
    ].drop_duplicates()
    legacy_acft = set(
        value
        for field in curves.loc[
            curves["source_dataset"] == "legacy_v2.3", "acft_ids"
        ]
        for value in str(field).split("|")
        if value
    )
    rows: list[dict] = []
    for variant in ("raw", "purged"):
        for row in curves.itertuples(index=False):
            acft_ids = {value for value in str(row.acft_ids).split("|") if value}
            shared = sorted(acft_ids & legacy_acft)
            if row.source_dataset == "legacy_v2.3":
                role = "train"
                exclusion = ""
            elif variant == "purged" and shared:
                role = "excluded_test"
                exclusion = "exact_ACFT_ID_shared_with_legacy:" + "|".join(shared)
            else:
                role = "test"
                exclusion = ""
            rows.append(
                {
                    "protocol": PROTOCOL_TEMPORAL,
                    "variant": variant,
                    "fold": "release_holdout",
                    "npd_id": row.npd_id,
                    "aircraft_group_id": row.aircraft_group_id,
                    "acft_ids": row.acft_ids,
                    "source_dataset": row.source_dataset,
                    "engine_type": row.engine_type,
                    "engine_count": int(row.engine_count),
                    "role": role,
                    "exclusion_reason": exclusion,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["variant", "role", "npd_id"], kind="mergesort", ignore_index=True
    )


def _fit_predict(
    learner: str, seed: int, train: pd.DataFrame, test: pd.DataFrame
) -> tuple[np.ndarray, float]:
    if learner not in SUPPORTED_LEARNERS:
        raise ValueError(f"unsupported learner {learner!r}")
    regressor = validation_regressor(learner, seed)
    start = time.perf_counter()
    regressor.fit(
        train.loc[:, FEATURES].to_numpy(dtype=float),
        train.loc[:, TRUTH_COLUMNS].to_numpy(dtype=float),
    )
    prediction = regressor.predict(
        test.loc[:, FEATURES].to_numpy(dtype=float)
    )
    prediction = enforce_distance_monotone(np.asarray(prediction, dtype=float))
    return prediction, time.perf_counter() - start


def _prediction_frame(
    test: pd.DataFrame,
    prediction: np.ndarray,
    *,
    protocol: str,
    variant: str,
    learner: str,
    fold: object,
) -> pd.DataFrame:
    identity_columns = [
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
    ]
    identity = test.loc[:, identity_columns].reset_index(drop=True)
    frames: list[pd.DataFrame] = []
    truth = test.loc[:, TRUTH_COLUMNS].to_numpy(dtype=float)
    for distance_index, distance_ft in enumerate(STANDARD_DISTANCES_FT):
        frame = identity.copy()
        frame["distance_ft"] = float(distance_ft)
        frame["truth_dB"] = truth[:, distance_index]
        frame["prediction_dB"] = prediction[:, distance_index]
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    result["error_dB"] = result["prediction_dB"] - result["truth_dB"]
    result.insert(0, "fold", fold)
    result.insert(0, "model", learner)
    result.insert(0, "variant", variant)
    result.insert(0, "protocol", protocol)
    return result


def evaluate_internal(
    samples: pd.DataFrame, splits: pd.DataFrame, seed: int
) -> tuple[pd.DataFrame, list[dict]]:
    fold_by_group = (
        splits[["aircraft_group_id", "fold"]]
        .drop_duplicates()
        .set_index("aircraft_group_id")["fold"]
    )
    predictions: list[pd.DataFrame] = []
    runs: list[dict] = []
    n_folds = int(splits["fold"].nunique())
    for metric, mode in COMBOS:
        combo = samples[
            (samples["metric"] == metric) & (samples["op_mode"] == mode)
        ].copy()
        combo["fold"] = combo["aircraft_group_id"].map(fold_by_group)
        for learner in SUPPORTED_LEARNERS:
            for fold in range(n_folds):
                train = combo[combo["fold"] != fold]
                test = combo[combo["fold"] == fold]
                prediction, duration = _fit_predict(
                    learner, seed, train, test
                )
                predictions.append(
                    _prediction_frame(
                        test,
                        prediction,
                        protocol=PROTOCOL_INTERNAL,
                        variant="combined",
                        learner=learner,
                        fold=fold,
                    )
                )
                runs.append(
                    _run_record(
                        PROTOCOL_INTERNAL,
                        "combined",
                        learner,
                        metric,
                        mode,
                        fold,
                        train,
                        test,
                        duration,
                    )
                )
    return pd.concat(predictions, ignore_index=True), runs


def evaluate_temporal(
    samples: pd.DataFrame, split: pd.DataFrame, seed: int
) -> tuple[pd.DataFrame, list[dict]]:
    predictions: list[pd.DataFrame] = []
    runs: list[dict] = []
    raw_test_ids = set(
        split.loc[
            (split["variant"] == "raw") & (split["role"] == "test"), "npd_id"
        ]
    )
    purged_test_ids = set(
        split.loc[
            (split["variant"] == "purged") & (split["role"] == "test"),
            "npd_id",
        ]
    )
    for metric, mode in COMBOS:
        combo = samples[
            (samples["metric"] == metric) & (samples["op_mode"] == mode)
        ]
        train = combo[combo["source_dataset"] == "legacy_v2.3"]
        raw_test = combo[combo["npd_id"].isin(raw_test_ids)]
        purged_test = combo[combo["npd_id"].isin(purged_test_ids)]
        for learner in SUPPORTED_LEARNERS:
            prediction, duration = _fit_predict(
                learner, seed, train, raw_test
            )
            raw_frame = _prediction_frame(
                raw_test,
                prediction,
                protocol=PROTOCOL_TEMPORAL,
                variant="raw",
                learner=learner,
                fold="release_holdout",
            )
            predictions.append(raw_frame)
            keep = raw_frame["npd_id"].isin(purged_test_ids)
            predictions.append(
                raw_frame.loc[keep].assign(variant="purged").reset_index(drop=True)
            )
            runs.append(
                _run_record(
                    PROTOCOL_TEMPORAL,
                    "raw",
                    learner,
                    metric,
                    mode,
                    "release_holdout",
                    train,
                    raw_test,
                    duration,
                )
            )
            purged_record = _run_record(
                PROTOCOL_TEMPORAL,
                "purged",
                learner,
                metric,
                mode,
                "release_holdout",
                train,
                purged_test,
                0.0,
            )
            purged_record["fit_reused_from_variant"] = "raw"
            runs.append(purged_record)
    return pd.concat(predictions, ignore_index=True), runs


def _run_record(
    protocol: str,
    variant: str,
    learner: str,
    metric: str,
    mode: str,
    fold: object,
    train: pd.DataFrame,
    test: pd.DataFrame,
    duration: float,
) -> dict:
    return {
        "protocol": protocol,
        "variant": variant,
        "model": learner,
        "metric": metric,
        "op_mode": mode,
        "fold": fold,
        "train_samples": int(len(train)),
        "train_curves": int(train["npd_id"].nunique()),
        "train_aircraft_groups": int(train["aircraft_group_id"].nunique()),
        "test_samples": int(len(test)),
        "test_curves": int(test["npd_id"].nunique()),
        "test_aircraft_groups": int(test["aircraft_group_id"].nunique()),
        "fit_predict_seconds": float(duration),
    }


def _metrics(frame: pd.DataFrame, balance_unit: str | None) -> dict:
    if balance_unit is None:
        errors = frame["error_dB"].to_numpy(dtype=float)
        rmse = np.sqrt(np.mean(errors ** 2))
        mae = np.mean(np.abs(errors))
        bias = np.mean(errors)
        p90 = np.percentile(np.abs(errors), 90)
    else:
        unit_stats = frame.groupby(balance_unit, sort=True)["error_dB"].agg(
            mse=lambda value: float(np.mean(np.asarray(value) ** 2)),
            mae=lambda value: float(np.mean(np.abs(np.asarray(value)))),
            bias="mean",
            p90=lambda value: float(
                np.percentile(np.abs(np.asarray(value)), 90)
            ),
        )
        rmse = np.sqrt(unit_stats["mse"].mean())
        mae = unit_stats["mae"].mean()
        bias = unit_stats["bias"].mean()
        p90 = unit_stats["p90"].mean()
    return {
        "rmse_dB": float(rmse),
        "mae_dB": float(mae),
        "bias_dB": float(bias),
        "p90_abs_error_dB": float(p90),
        "n_cells": int(len(frame)),
        "n_power_samples": int(frame["sample_id"].nunique()),
        "n_curves": int(frame["npd_id"].nunique()),
        "n_aircraft_groups": int(frame["aircraft_group_id"].nunique()),
    }


def summarize_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    """Compute prediction-minus-truth pooled and equal-unit summaries."""
    base_columns = [
        "protocol",
        "variant",
        "model",
        "metric",
        "op_mode",
    ]
    balance_modes = {
        "cell_pooled": None,
        "curve_balanced": "npd_id",
        "aircraft_group_balanced": "aircraft_group_id",
    }
    rows: list[dict] = []
    for keys, frame in predictions.groupby(base_columns, sort=True):
        slices: list[tuple[str, str, pd.DataFrame]] = [("overall", "all", frame)]
        for column, label in (
            ("source_dataset", "source_dataset"),
            ("engine_type", "engine_type"),
            ("engine_count", "engine_count"),
        ):
            for value, subset in frame.groupby(column, sort=True):
                slices.append((label, str(value), subset))
        for (engine_type, engine_count), subset in frame.groupby(
            ["engine_type", "engine_count"], sort=True
        ):
            slices.append(
                (
                    "engine_type_count",
                    f"{engine_type}/{int(engine_count)}",
                    subset,
                )
            )
        for dimension, value, subset in slices:
            for aggregation, balance_unit in balance_modes.items():
                result = dict(zip(base_columns, keys))
                result.update(
                    {
                        "dimension": dimension,
                        "dimension_value": value,
                        "aggregation": aggregation,
                    }
                )
                result.update(_metrics(subset, balance_unit))
                rows.append(result)
    return pd.DataFrame(rows).sort_values(
        base_columns + ["dimension", "dimension_value", "aggregation"],
        kind="mergesort",
        ignore_index=True,
    )


def support_matrix(
    samples: pd.DataFrame,
    internal_splits: pd.DataFrame,
    temporal_splits: pd.DataFrame,
) -> pd.DataFrame:
    """Report exact engine-type/count support for every evaluated test slice."""
    rows: list[dict] = []
    fold_by_group = (
        internal_splits[["aircraft_group_id", "fold"]]
        .drop_duplicates()
        .set_index("aircraft_group_id")["fold"]
    )
    for metric, mode in COMBOS:
        combo = samples[
            (samples["metric"] == metric) & (samples["op_mode"] == mode)
        ].copy()
        combo["fold"] = combo["aircraft_group_id"].map(fold_by_group)
        for fold in sorted(combo["fold"].unique()):
            rows.extend(
                _support_rows(
                    combo[combo["fold"] != fold],
                    combo[combo["fold"] == fold],
                    PROTOCOL_INTERNAL,
                    "combined",
                    fold,
                    metric,
                    mode,
                )
            )
        train = combo[combo["source_dataset"] == "legacy_v2.3"]
        for variant in ("raw", "purged"):
            test_ids = set(
                temporal_splits.loc[
                    (temporal_splits["variant"] == variant)
                    & (temporal_splits["role"] == "test"),
                    "npd_id",
                ]
            )
            rows.extend(
                _support_rows(
                    train,
                    combo[combo["npd_id"].isin(test_ids)],
                    PROTOCOL_TEMPORAL,
                    variant,
                    "release_holdout",
                    metric,
                    mode,
                )
            )
    return pd.DataFrame(rows).sort_values(
        [
            "protocol",
            "variant",
            "metric",
            "op_mode",
            "fold",
            "engine_type",
            "engine_count",
        ],
        kind="mergesort",
        ignore_index=True,
    )


def _support_rows(
    train: pd.DataFrame,
    test: pd.DataFrame,
    protocol: str,
    variant: str,
    fold: object,
    metric: str,
    mode: str,
) -> list[dict]:
    rows: list[dict] = []
    test_curves = test[
        ["engine_type", "engine_count", "npd_id", "aircraft_group_id"]
    ].drop_duplicates()
    train_curves = train[
        ["engine_type", "engine_count", "npd_id", "aircraft_group_id"]
    ].drop_duplicates()
    for (engine_type, count), subset in test_curves.groupby(
        ["engine_type", "engine_count"], sort=True
    ):
        exact = train_curves[
            (train_curves["engine_type"] == engine_type)
            & (train_curves["engine_count"] == count)
        ]
        type_only = train_curves[train_curves["engine_type"] == engine_type]
        n_exact_groups = int(exact["aircraft_group_id"].nunique())
        if n_exact_groups == 0:
            status = "impossible_exact_cell"
        elif n_exact_groups < 3:
            status = "sparse_exact_cell"
        else:
            status = "feasible_exact_cell"
        rows.append(
            {
                "protocol": protocol,
                "variant": variant,
                "fold": fold,
                "metric": metric,
                "op_mode": mode,
                "engine_type": engine_type,
                "engine_count": int(count),
                "status": status,
                "evaluated": True,
                "train_exact_curves": int(exact["npd_id"].nunique()),
                "train_exact_aircraft_groups": n_exact_groups,
                "train_engine_type_curves": int(type_only["npd_id"].nunique()),
                "train_engine_type_aircraft_groups": int(
                    type_only["aircraft_group_id"].nunique()
                ),
                "test_curves": int(subset["npd_id"].nunique()),
                "test_aircraft_groups": int(
                    subset["aircraft_group_id"].nunique()
                ),
            }
        )
    return rows


def _git_state(repo_root: Path) -> dict:
    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD") or None,
        "dirty": bool(status),
        "status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
    }


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    values = frame.loc[:, columns].copy()
    for column in values.select_dtypes(include=[np.number]).columns:
        if column.startswith("n_"):
            values[column] = values[column].map(lambda value: f"{int(value)}")
        else:
            values[column] = values[column].map(lambda value: f"{value:.3f}")
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in values.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *body])


def write_report(
    report_path: Path,
    summary: pd.DataFrame,
    support: pd.DataFrame,
    temporal_splits: pd.DataFrame,
    manifest: dict,
) -> None:
    headline = summary[
        (summary["dimension"] == "overall")
        & (summary["aggregation"] == "cell_pooled")
    ].copy()
    internal = headline[headline["protocol"] == PROTOCOL_INTERNAL]
    temporal = headline[headline["protocol"] == PROTOCOL_TEMPORAL]
    report_columns = [
        "model",
        "metric",
        "op_mode",
        "rmse_dB",
        "mae_dB",
        "bias_dB",
        "p90_abs_error_dB",
        "n_curves",
        "n_aircraft_groups",
    ]
    excluded = temporal_splits[
        (temporal_splits["variant"] == "purged")
        & (temporal_splits["role"] == "excluded_test")
    ]
    status_counts = (
        support.groupby(["protocol", "variant", "status"], sort=True)
        .size()
        .reset_index(name="n_slices")
    )
    lines = [
        "# PNMF Model Training and Validation Report",
        "",
        f"> Generated {manifest['run']['finished_utc']} by "
        "`pnmf_cli.py validate-model`. This is the current learned-model "
        "evidence report; `FINAL_REPORT.md` is historical.",
        "",
        "## Scope and conclusion",
        "",
        "This run evaluates exactly the production Extra Trees (`et`) and "
        "Random Forest (`rf`) regressors for all eight SEL/LAmax/EPNL/PNLTM "
        "times approach/departure tasks. It is evidence for interpolation "
        "within the available aircraft population and for a release-ordered "
        "legacy-to-supplement transfer. It is not certification evidence and "
        "does not establish performance on unseen aircraft families because "
        "the datastore has no curated family labels.",
        "",
        "**Maturity: 2/5 - reproducible retrospective validation.** Split "
        "leakage by exact aircraft identity is controlled and release holdout "
        "is reported, but family-level, prospective and genuinely external "
        "confirmation remain missing.",
        "",
        "## Exact prediction task",
        "",
        "Each power row is one supervised sample with 12 inputs:",
        "",
        "`[is_jet, is_turboprop, is_piston, n_engines, log10(MTOW_lb), "
        "log10(MLW_lb), MLW/MTOW, log10(static_thrust_lb_per_engine), "
        "log10(total_static_thrust_lb), noise_chapter, log10(power_lb), "
        "throttle]`.",
        "",
        "Engine type is a three-column one-hot encoding and engine count is a "
        "separate numeric feature. The ten targets are the truth levels at "
        "200, 400, 630, 1,000, 2,000, 4,000, 6,300, 10,000, 16,000 and "
        "25,000 ft. For `CNT (lb)`, `power_lb=P` and `throttle=P/T_static`; "
        "for percent CNT, `power_lb=P/100*T_static` and `throttle=P/100`; "
        "for RPM, `throttle=P/max(P_grid)` and "
        "`power_lb=throttle*T_static`. MTOW and MLW are required positive "
        "and transformed directly with `log10(value)`. Static thrust per "
        "engine, total static thrust, and converted row power use "
        "`log10(max(value, 1))`; throttle is clipped to [0, 2].",
        "",
        "The held-out aircraft descriptor and held-out power grid are inputs "
        "to the prediction task; held-out noise levels are used only after "
        "prediction for scoring. In particular, the temporal model is fit "
        "from legacy targets only. Conditioning on the requested power grid "
        "is part of producing an NPD table, not target leakage.",
        "",
        "Production hyperparameters were not tuned in this run:",
        "",
        f"- ET: `{json.dumps(MODEL_PARAMS['et'], sort_keys=True)}`",
        f"- RF: `{json.dumps(MODEL_PARAMS['rf'], sort_keys=True)}`",
        "",
        "Every effective scikit-learn constructor parameter, including "
        "defaults, is captured under `models` in `run_manifest.json`.",
        "",
        "Both produce ten outputs jointly. The normal production monotonic "
        "projection is applied after prediction. Cross-tree dispersion is an "
        "ensemble disagreement heuristic; it is not calibrated uncertainty "
        "and this validation does not turn it into a confidence interval.",
        "",
        "## Protocol 1 - internal aircraft-grouped CV",
        "",
        f"{manifest['config']['folds']} deterministic folds are built from "
        "connected components of the bipartite `ACFT_ID`--`NPD_ID` graph. "
        "Consequently no NPD curve is split, aircraft sharing a curve stay "
        "together, and identical IDs across releases (including `7773ER`) "
        "stay together. This is honestly labelled aircraft-grouped CV, not "
        "unseen-family CV.",
        "",
        _markdown_table(internal, report_columns),
        "",
        "## Protocol 2 - temporal release holdout",
        "",
        "The model is trained on `legacy_v2.3` and evaluated on "
        "`supplement_v6.3`. The raw result includes exact identity overlap. "
        "The purged result removes supplement test curves whose exact "
        "`ACFT_ID` occurs in legacy training; training itself is unchanged.",
        "",
        "Purged exclusions:",
        "",
    ]
    if excluded.empty:
        lines.append("- None.")
    else:
        for row in excluded.itertuples(index=False):
            lines.append(
                f"- `{row.npd_id}` ({row.exclusion_reason})."
            )
    for variant in ("raw", "purged"):
        lines.extend(
            [
                "",
                f"### Temporal {variant}",
                "",
                _markdown_table(
                    temporal[temporal["variant"] == variant], report_columns
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            "All errors are `prediction - truth`. Cell-pooled metrics are "
            "`RMSE=sqrt(mean(e^2))`, `MAE=mean(|e|)`, `bias=mean(e)`, and "
            "`p90=percentile90(|e|)`. Curve-balanced and aircraft-group-"
            "balanced RMSE are `sqrt(mean_u(mean_cells_in_u(e^2)))`; their "
            "MAE, bias and p90 are the arithmetic means of the corresponding "
            "per-unit statistic. The machine-readable summary also reports "
            "source-, engine-type-, engine-count- and joint type/count slices "
            "with cell, curve and group counts.",
            "",
            "## Engine support and stress interpretation",
            "",
            "Every evaluated fold/test slice is classified on exact "
            "engine-type/count training support: zero training groups is "
            "`impossible_exact_cell`, one or two is `sparse_exact_cell`, and "
            "three or more is `feasible_exact_cell`. A model can still emit "
            "a prediction for an impossible exact cell by borrowing across "
            "other counts/types; that is extrapolation, not evidence of "
            "supported generalisation.",
            "",
            _markdown_table(
                status_counts,
                ["protocol", "variant", "status", "n_slices"],
            ),
            "",
            "## What the evidence does and does not prove",
            "",
            "- Internal CV tests transfer to held-out aircraft-identity "
            "components in the combined corpus. It does not test curated "
            "families or novel architectures.",
            "- Temporal raw tests release transfer but contains exact "
            "identity overlap; temporal purged removes that known overlap. "
            "Only 11 supplement aircraft exist, so both are small tests.",
            "- The independent frozen physics route is valid as a separate "
            "mechanistic cross-check for SEL/LAmax only. It was not fit or "
            "evaluated by this command and cannot validate EPNL/PNLTM.",
            "- A genuinely external confirmation set must not have supplied "
            "training targets or model selection feedback. The substitution "
            "workbook is useful contextual evidence, but its curated proxy "
            "assignments and coverage are not direct measured NPD truth for "
            "the conceptual aircraft task, so correlations against it are "
            "not an absolute accuracy claim.",
            "",
            "## Reproducibility record",
            "",
            f"- Seed: `{manifest['config']['seed']}`; folds: "
            f"`{manifest['config']['folds']}`.",
            f"- Git commit: `{manifest['git']['commit']}`; dirty: "
            f"`{manifest['git']['dirty']}`.",
            f"- Datastore SHA-256: `{manifest['inputs']['datastore_sha256']}`.",
            f"- Source-manifest SHA-256: "
            f"`{manifest['inputs']['source_manifest_sha256']}`.",
            f"- Python `{manifest['software']['python']}`, numpy "
            f"`{manifest['software']['numpy']}`, pandas "
            f"`{manifest['software']['pandas']}`, scikit-learn "
            f"`{manifest['software']['scikit_learn']}`.",
            f"- Run duration: `{manifest['run']['duration_seconds']:.3f}` s.",
            "",
            "Fixed seeds make the multi-threaded scikit-learn fits "
            "numerically reproducible to the observed approximately "
            "`1e-13` level, not guaranteed byte-identical. Samples, split "
            "definitions, source manifest, and support matrix are byte-stable "
            "for an unchanged datastore/configuration. Prediction and summary "
            "files can differ in last-bit formatting, and timestamps, "
            "durations, Git state and the run manifest necessarily vary.",
            "",
            "Every SHA-256 in `run_manifest.json` is a run-specific integrity "
            "hash for that emitted artifact, not a claim that independently "
            "executed model outputs must have identical bytes. Deterministic "
            "splits, samples, cell predictions, balanced summaries, support "
            "matrix, and per-fit records are all listed beside the manifest.",
            "",
            "## Next experiments",
            "",
            "1. Curate manufacturer/platform/engine-family labels, freeze "
            "them, then run true leave-family-out validation.",
            "2. Add a prospectively frozen external NPD dataset with no "
            "training or model-selection use.",
            "3. Expand rare turboprop/piston and engine-count cells before "
            "drawing conclusions from sparse/impossible support slices.",
            "4. Calibrate predictive intervals on held-out groups; keep them "
            "distinct from raw tree dispersion.",
            "5. Repeat the temporal holdout when a later ANP release provides "
            "a larger, genuinely new test population.",
            "",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def run_validation(
    *,
    db_path: Path,
    output_dir: Path,
    report_path: Path,
    folds: int = 3,
    seed: int = 20260724,
) -> dict:
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    db = ANPDatabase(db_path)
    manifest_frame = db.dataset_manifest()
    samples = build_samples(db)
    internal_splits = deterministic_group_folds(samples, folds, seed)
    temporal_splits = temporal_split(samples)

    internal_predictions, internal_runs = evaluate_internal(
        samples, internal_splits, seed
    )
    temporal_predictions, temporal_runs = evaluate_temporal(
        samples, temporal_splits, seed
    )
    predictions = pd.concat(
        [internal_predictions, temporal_predictions], ignore_index=True
    )
    summary = summarize_predictions(predictions)
    support = support_matrix(samples, internal_splits, temporal_splits)
    run_records = pd.DataFrame([*internal_runs, *temporal_runs])

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_frames = {
        "samples.csv": samples,
        "splits_internal.csv": internal_splits,
        "splits_temporal.csv": temporal_splits,
        "predictions.csv": predictions,
        "summary.csv": summary,
        "engine_support_matrix.csv": support,
        "fit_runs.csv": run_records,
        "source_manifest.csv": manifest_frame,
    }
    for name, frame in artifact_frames.items():
        frame.to_csv(output_dir / name, index=False, lineterminator="\n")
    (output_dir / "summary.json").write_text(
        json.dumps(summary.to_dict(orient="records"), indent=2),
        encoding="utf-8",
    )

    repo_root = PROJECT_ROOT.parents[1]
    db_file = db_path if db_path.is_file() else db_path / "anp_data.sqlite"
    finished = datetime.now(timezone.utc)
    manifest = {
        "schema_version": 1,
        "run": {
            "started_utc": started.isoformat(),
            "finished_utc": finished.isoformat(),
            "duration_seconds": time.perf_counter() - timer,
        },
        "config": {
            "seed": seed,
            "folds": folds,
            "models": list(SUPPORTED_LEARNERS),
            "metric_mode_combinations": [
                {"metric": metric, "op_mode": mode}
                for metric, mode in COMBOS
            ],
        },
        "features": list(FEATURES),
        "targets": list(DIST_COLS),
        "models": exact_model_params(seed),
        "protocols": {
            PROTOCOL_INTERNAL: {
                "label": "aircraft-grouped CV",
                "family_claim": False,
                "group_definition": "connected components of ACFT_ID--NPD_ID",
            },
            PROTOCOL_TEMPORAL: {
                "train_source": "legacy_v2.3",
                "test_source": "supplement_v6.3",
                "variants": ["raw", "purged_exact_ACFT_ID"],
            },
        },
        "inputs": {
            "datastore": str(db_file.resolve()),
            "datastore_sha256": _sha256_file(db_file),
            "source_manifest_sha256": _sha256_json(
                manifest_frame.to_dict(orient="records")
            ),
            "sample_rows": int(len(samples)),
            "curve_ids": int(samples["npd_id"].nunique()),
            "aircraft_groups": int(
                samples["aircraft_group_id"].nunique()
            ),
            "source_counts": {
                str(key): int(value)
                for key, value in samples.groupby("source_dataset").size().items()
            },
        },
        "exclusions": temporal_splits[
            temporal_splits["role"] == "excluded_test"
        ].to_dict(orient="records"),
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
            "platform": platform.platform(),
        },
        "git": _git_state(repo_root),
        "reproducibility": {
            "model_results": (
                "fixed-seed multi-threaded sklearn; numerically reproducible "
                "to observed approximately 1e-13, not guaranteed byte-identical"
            ),
            "byte_stable_for_unchanged_input_and_config": [
                "samples.csv",
                "splits_internal.csv",
                "splits_temporal.csv",
                "engine_support_matrix.csv",
                "source_manifest.csv",
            ],
            "artifact_hash_semantics": (
                "run-specific integrity hashes of emitted files; not a "
                "cross-run byte-identity guarantee"
            ),
        },
        "fit_runs": [*internal_runs, *temporal_runs],
        "artifacts": {},
    }
    write_report(report_path, summary, support, temporal_splits, manifest)
    all_artifacts = [
        *artifact_frames.keys(),
        "summary.json",
    ]
    for name in all_artifacts:
        path = output_dir / name
        manifest["artifacts"][name] = {
            "path": str(path.resolve()),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }
    manifest["artifacts"]["training_report"] = {
        "path": str(report_path.resolve()),
        "sha256": _sha256_file(report_path),
        "bytes": report_path.stat().st_size,
    }
    manifest_path = output_dir / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return manifest


def _project_relative(path_text: str, default: Path) -> Path:
    path = Path(path_text) if path_text else default
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run reproducible ET/RF aircraft-grouped and temporal validation."
    )
    parser.add_argument(
        "--db",
        default=str(PROJECT_ROOT / "anp_data.sqlite"),
        help="canonical datastore path (relative paths resolve from PNMF root)",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/model_validation/current",
        help="artifact directory (relative paths resolve from PNMF root)",
    )
    parser.add_argument(
        "--report",
        default="docs/MODEL_TRAINING_REPORT.md",
        help="generated Markdown report path",
    )
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260724)
    args = parser.parse_args(argv)
    manifest = run_validation(
        db_path=_project_relative(args.db, PROJECT_ROOT / "anp_data.sqlite"),
        output_dir=_project_relative(
            args.output_dir, PROJECT_ROOT / "outputs/model_validation/current"
        ),
        report_path=_project_relative(
            args.report, PROJECT_ROOT / "docs/MODEL_TRAINING_REPORT.md"
        ),
        folds=args.folds,
        seed=args.seed,
    )
    print(
        "model validation complete: "
        f"{manifest['inputs']['sample_rows']} samples, "
        f"{manifest['config']['folds']} folds, "
        f"{manifest['run']['duration_seconds']:.1f} s"
    )
    print(
        "artifacts: "
        + str(
            _project_relative(
                args.output_dir, PROJECT_ROOT / "outputs/model_validation/current"
            )
        )
    )
    print(
        "report: "
        + str(
            _project_relative(
                args.report, PROJECT_ROOT / "docs/MODEL_TRAINING_REPORT.md"
            )
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
