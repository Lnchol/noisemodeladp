from __future__ import annotations

from typing import Literal, overload

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.isotonic import IsotonicRegression

from .anp import DIST_COLS
from .core import NPDTable, ParametricAircraft, STANDARD_DISTANCES_FT
from .jet_features import (
    JET_V2_SCHEMA_ID,
    build_jet_feature_matrix,
    jet_feature_names,
    validate_jet_power_parameter,
)
from .jet_v2_promotion import JET_V2_VALIDATION_REPORT_SHA256
from .verified_anp import REGISTRY_VERSION, resolve_training_scope

_LOGD = np.log10(STANDARD_DISTANCES_FT)
SUPPORTED_LEARNERS = ("et", "rf")
SUPPORTED_TRAINING_SCOPES = ("jet_merged",)


def power_features(P, power_parameter, static_thrust_lb):
    values = np.atleast_1d(np.asarray(P, dtype=float))
    parameter = str(power_parameter)
    static_thrust = max(float(static_thrust_lb), 1.0)
    if "%" in parameter:
        power_lb = values / 100.0 * static_thrust
        throttle = values / 100.0
    elif parameter == "CNT (lb)":
        power_lb = values
        throttle = values / static_thrust
    elif "RPM" in parameter or "rpm" in parameter:
        throttle = values / max(values.max(), 1.0)
        power_lb = throttle * static_thrust
    else:
        raise ValueError(
            f"unsupported Jet power parameter {parameter!r}; expected CNT (lb) "
            "or CNT (% of Max Static Thrust)"
        )
    return np.log10(np.maximum(power_lb, 1.0)), np.clip(throttle, 0.0, 2.0)


def enforce_distance_monotone(levels):
    result = np.array(levels, dtype=float, copy=True)
    for index in range(result.shape[0]):
        if (np.diff(result[index]) > 1e-9).any():
            result[index] = IsotonicRegression(increasing=False).fit_transform(
                _LOGD, result[index]
            )
    return result


def validation_regressor(learner: str, random_state: int):
    if learner == "et":
        return ExtraTreesRegressor(
            n_estimators=500,
            min_samples_leaf=1,
            max_depth=24,
            max_features=0.5,
            random_state=random_state,
            n_jobs=-1,
        )
    if learner == "rf":
        return RandomForestRegressor(
            n_estimators=200,
            min_samples_leaf=2,
            max_depth=None,
            max_features=1.0,
            random_state=random_state,
            n_jobs=-1,
        )
    raise ValueError(f"unsupported validation learner {learner!r}")


class SurrogateNPDModel:
    def __init__(self, random_state=0, monotone=True):
        if isinstance(random_state, str):
            raise TypeError("learner selection is validation-only")
        self.learner = "et"
        self.random_state = random_state
        self.monotone = monotone
        self.training_scope = "jet_merged"
        self.models = {}
        self.training_provenance = {}
        self.training_resolution = None
        self.training_metadata = {}
        self.feature_schema = JET_V2_SCHEMA_ID
        self.feat_names = list(jet_feature_names(JET_V2_SCHEMA_ID))

    def _new_regressor(self):
        return validation_regressor("et", self.random_state)

    def _feature_matrix(self, aircraft, power_settings, power_parameter):
        if aircraft.engine_type != "Jet":
            raise ValueError("Jet prediction accepts Jet aircraft only")
        validate_jet_power_parameter(str(power_parameter))
        power = np.atleast_1d(np.asarray(power_settings, dtype=float))
        log_power, throttle = power_features(
            power, power_parameter, aircraft.max_static_thrust_lb
        )
        return build_jet_feature_matrix(
            aircraft.feature_vector(), log_power, throttle, JET_V2_SCHEMA_ID
        )

    def _design_matrix(self, db, metric, op_mode, exclude_ids=(), resolution=None):
        if resolution is None:
            resolution = resolve_training_scope(
                db,
                "jet_merged",
                metrics=(metric,),
                op_modes=(op_mode,),
                exclude_ids=exclude_ids,
            )
        params = db.param_table()
        features = []
        truth = []
        groups = []
        for npd_id in resolution.selected_npd_ids:
            descriptor = params.loc[npd_id]
            aircraft = ParametricAircraft.from_anp_row(npd_id, descriptor)
            curve = db.curve(npd_id, metric, op_mode)
            matrix = self._feature_matrix(
                aircraft,
                curve["Power Setting"].to_numpy(dtype=float),
                descriptor["Power Parameter"],
            )
            curve_truth = curve[DIST_COLS].to_numpy(dtype=float)
            features.extend(matrix)
            truth.extend(curve_truth)
            groups.extend([npd_id] * len(curve_truth))
        return (
            np.asarray(features, dtype=float),
            np.asarray(truth, dtype=float),
            np.asarray(groups),
        )

    def fit(self, db, metric, op_mode, exclude_ids=()):
        resolution = resolve_training_scope(
            db,
            "jet_merged",
            metrics=(metric,),
            op_modes=(op_mode,),
            exclude_ids=exclude_ids,
        )
        features, truth, _ = self._design_matrix(
            db, metric, op_mode, exclude_ids, resolution
        )
        curves = db.npd.loc[
            db.npd["NPD_ID"].isin(resolution.selected_npd_ids)
            & db.npd["Noise Metric"].eq(metric)
            & db.npd["Op Mode"].eq(op_mode)
        ]
        if "source_dataset" not in curves:
            raise RuntimeError("training data has no source provenance")
        provenance = curves["source_dataset"].value_counts().sort_index().to_dict()
        if provenance.get("supplement_v6.3", 0) == 0:
            raise RuntimeError(f"{metric}/{op_mode} has no v6.3 samples")
        regressor = self._new_regressor()
        regressor.fit(features, truth)
        self.models[(metric, op_mode)] = regressor
        self.training_resolution = resolution
        self.training_provenance[(metric, op_mode)] = provenance
        if not self.training_metadata:
            self.training_metadata = {
                "learner": "et",
                "scope": "jet_merged",
                "feature_schema": self.feature_schema,
                "feature_names": list(self.feat_names),
                "training_population": "jet_merged",
                "registry_version": REGISTRY_VERSION,
                "source_hashes": {
                    "verified_workbook": resolution.source_hashes.verified_workbook,
                    "v63_aircraft": resolution.source_hashes.v63_aircraft,
                    "v63_npd": resolution.source_hashes.v63_npd,
                },
                "selected_npd_ids": resolution.selected_npd_ids,
                "support_counts": {},
                "validation_report_sha256": JET_V2_VALIDATION_REPORT_SHA256,
            }
        self.training_metadata["support_counts"].update(
            dict(resolution.support_counts)
        )
        return self

    def fit_all(
        self,
        db,
        metrics=("SEL", "LAmax", "EPNL", "PNLTM"),
        op_modes=("A", "D"),
    ):
        self.training_metadata = {}
        for metric in metrics:
            for op_mode in op_modes:
                if db.list_curve_sets(metric, op_mode):
                    self.fit(db, metric, op_mode)
        return self

    @overload
    def predict_table(
        self,
        aircraft: ParametricAircraft,
        metric,
        op_mode,
        power_settings,
        return_std: Literal[False] = ...,
        power_parameter: str = ...,
    ) -> NPDTable: ...

    @overload
    def predict_table(
        self,
        aircraft: ParametricAircraft,
        metric,
        op_mode,
        power_settings,
        return_std: Literal[True],
        power_parameter: str = ...,
    ) -> tuple[NPDTable, np.ndarray]: ...

    def predict_table(
        self,
        aircraft,
        metric,
        op_mode,
        power_settings,
        return_std=False,
        power_parameter="CNT (lb)",
    ):
        regressor = self.models[(metric, op_mode)]
        power = np.atleast_1d(np.asarray(power_settings, dtype=float))
        features = self._feature_matrix(aircraft, power, power_parameter)
        levels = np.asarray(regressor.predict(features), dtype=float)
        if levels.ndim == 1:
            levels = levels.reshape(1, -1)
        if self.monotone:
            levels = enforce_distance_monotone(levels)
        table = NPDTable(
            power,
            levels,
            metric,
            op_mode,
            STANDARD_DISTANCES_FT,
            npd_id=aircraft.name,
        )
        if not return_std:
            return table
        predictions = np.stack(
            [tree.predict(features) for tree in regressor.estimators_], axis=0
        )
        return table, predictions.std(axis=0)

    def generate_full(
        self,
        aircraft,
        power_settings=None,
        metrics=("SEL", "LAmax", "EPNL"),
        op_modes=("A", "D"),
        return_std=False,
    ):
        output = {}
        for op_mode in op_modes:
            powers = power_settings
            if powers is None:
                thrust = aircraft.max_static_thrust_lb
                powers = (
                    np.linspace(0.45 * thrust, 0.95 * thrust, 4)
                    if op_mode == "D"
                    else np.linspace(0.07 * thrust, 0.35 * thrust, 3)
                )
            for metric in metrics:
                if (metric, op_mode) in self.models:
                    output[(metric, op_mode)] = self.predict_table(
                        aircraft,
                        metric,
                        op_mode,
                        powers,
                        return_std=return_std,
                    )
        return output


def loo_validate(
    db, model_factory, metric, op_mode, verbose=False, return_cells=False
):
    params = db.param_table()
    ids = db.list_curve_sets(metric, op_mode)
    rows = []
    cells = []
    errors = []
    for npd_id in ids:
        model = model_factory()
        model.fit(db, metric, op_mode, exclude_ids=(npd_id,))
        descriptor = params.loc[npd_id]
        aircraft = ParametricAircraft.from_anp_row(npd_id, descriptor)
        curve = db.curve(npd_id, metric, op_mode)
        power = curve["Power Setting"].to_numpy(dtype=float)
        truth = curve[DIST_COLS].to_numpy(dtype=float)
        predicted = model.predict_table(
            aircraft,
            metric,
            op_mode,
            power,
            power_parameter=str(descriptor["Power Parameter"]),
        ).L
        error = predicted - truth
        errors.append(error.ravel())
        rows.append(
            {
                "npd_id": npd_id,
                "engine": "Jet",
                "rmse": float(np.sqrt(np.mean(error**2))),
                "mae": float(np.mean(np.abs(error))),
                "bias": float(np.mean(error)),
            }
        )
        if return_cells:
            for row_index, setting in enumerate(power):
                for distance_index, distance in enumerate(STANDARD_DISTANCES_FT):
                    cells.append(
                        {
                            "npd_id": npd_id,
                            "engine": "Jet",
                            "power_setting": float(setting),
                            "distance_ft": float(distance),
                            "truth_dB": float(truth[row_index, distance_index]),
                            "pred_dB": float(predicted[row_index, distance_index]),
                        }
                    )
        if verbose:
            print(f"  {npd_id:8s} Jet       RMSE={rows[-1]['rmse']:5.2f} dB")
    flat = np.concatenate(errors)
    summary = {
        "metric": metric,
        "op_mode": op_mode,
        "n_aircraft": len(ids),
        "rmse_dB": float(np.sqrt(np.mean(flat**2))),
        "mae_dB": float(np.mean(np.abs(flat))),
        "bias_dB": float(np.mean(flat)),
        "p90_abs_dB": float(np.percentile(np.abs(flat), 90)),
    }
    per_aircraft = pd.DataFrame(rows)
    if return_cells:
        return summary, per_aircraft, pd.DataFrame(cells)
    return summary, per_aircraft


def rank_models(comparison_df, score_suffix="_medRMSE"):
    from scipy.stats import friedmanchisquare, rankdata

    columns = [
        f"{learner}{score_suffix}"
        for learner in SUPPORTED_LEARNERS
        if f"{learner}{score_suffix}" in comparison_df.columns
    ]
    if len(columns) < 2:
        raise ValueError("need ET and RF validation scores")
    models = [column[: -len(score_suffix)] for column in columns]
    scores = comparison_df[columns].to_numpy(dtype=float)
    keep = ~np.isnan(scores).any(axis=0)
    if int(keep.sum()) < 2:
        raise ValueError("need >=2 complete validation learners")
    scores = scores[:, keep]
    models = [model for model, retained in zip(models, keep) if retained]
    ranks = np.vstack([rankdata(row) for row in scores])
    average = ranks.mean(axis=0)
    wins = (scores == scores.min(axis=1, keepdims=True)).sum(axis=0)
    ranking = pd.DataFrame(
        {
            "model": models,
            "avg_rank": np.round(average, 3),
            "wins": wins.astype(int),
            "mean_score": np.round(scores.mean(axis=0), 2),
        }
    ).sort_values(["avg_rank", "mean_score"], ignore_index=True)
    if scores.shape[0] >= 2 and scores.shape[1] >= 3:
        statistic, p_value = friedmanchisquare(
            *[scores[:, i] for i in range(scores.shape[1])]
        )
    else:
        statistic, p_value = float("nan"), float("nan")
    return ranking, {
        "n_combos": int(scores.shape[0]),
        "friedman_stat": float(statistic),
        "friedman_p": float(p_value),
        "recommended": str(ranking.iloc[0]["model"]),
        "dropped": [],
    }
