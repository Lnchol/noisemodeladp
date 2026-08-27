"""Complete accuracy validation dataset and per-aircraft training vs validation role analysis."""

from __future__ import annotations

import os
from typing import Literal
import numpy as np
import pandas as pd

from .anp import ANPDatabase, DIST_COLS
from .core import STANDARD_DISTANCES_FT, ParametricAircraft
from .models import (
    SUPPORTED_LEARNERS,
    enforce_distance_monotone,
    validation_regressor,
)
from .validation import (
    COMBOS,
    FEATURES,
    TRUTH_COLUMNS,
    build_samples,
    exact_model_params,
    deterministic_group_folds,
)
from .jet_reference_validation import (
    PROTOCOL as HOLDOUT_PROTOCOL,
    TRAIN_SOURCE,
    REFERENCE_SOURCE,
    FROZEN_REFERENCES,
    EXPECTED_REFERENCE_DESCRIPTIONS,
    FAMILY_PURGE,
    FAMILY_PURGE_REASON,
    _complete_curve_table,
    build_jet_reference_split,
)
from .jet_model_validation import (
    build_jet_samples,
    build_jet_group_folds,
    jet_feature_names,
)
from .jet_features import JET_V2_SCHEMA_ID
from .verified_anp import (
    VERIFIED_AIRCRAFT_REGISTRY,
    TRAINABLE_NPD_IDS,
)

VERIFIED_METADATA_MAP = {
    entry.npd_id: {
        "engine_family": entry.engine_family,
        "variants": ", ".join(entry.variants),
        "engines": ", ".join(entry.engines),
        "verification_date": entry.verification_date,
        "training_status": entry.training_status,
    }
    for entry in VERIFIED_AIRCRAFT_REGISTRY
}


def _calculate_row_metrics(errors: np.ndarray) -> dict[str, float]:
    """Calculate RMSE, MAE, Max Error, and Bias from an error array."""
    if errors.size == 0 or np.all(np.isnan(errors)):
        return {
            "rmse_dB": np.nan,
            "mae_dB": np.nan,
            "max_error_dB": np.nan,
            "bias_dB": np.nan,
        }
    valid_errors = errors[~np.isnan(errors)]
    if valid_errors.size == 0:
        return {
            "rmse_dB": np.nan,
            "mae_dB": np.nan,
            "max_error_dB": np.nan,
            "bias_dB": np.nan,
        }
    return {
        "rmse_dB": float(np.sqrt(np.mean(valid_errors ** 2))),
        "mae_dB": float(np.mean(np.abs(valid_errors))),
        "max_error_dB": float(np.max(np.abs(valid_errors))),
        "bias_dB": float(np.mean(valid_errors)),
    }


def build_accuracy_validation_dataset(
    db: ANPDatabase,
    protocol: Literal["verified_5fold", "group_cv", "holdout"] = "verified_5fold",
    learner: str = "et",
    seed: int = 20260724,
) -> dict:
    """Build a complete per-aircraft accuracy validation table and predictions.

    Parameters
    ----------
    db : ANPDatabase
        Database instance.
    protocol : {'verified_5fold', 'group_cv', 'holdout'}
        'verified_5fold' for 5-fold CV evaluated strictly on the 11 EASA-verified v6.3 aircraft.
        'group_cv' for 5-fold stratified group CV across all 94 Jet fleet curves.
        'holdout' for the frozen v6.3 release holdout (legacy v2.3 train vs v6.3 test).
    learner : {'et', 'rf'}, default 'et'
        Surrogate regressor architecture.
    seed : int, default 20260724
        Deterministic random seed.

    Returns
    -------
    dict
        Contains:
        - 'summary_table': pd.DataFrame with per-aircraft accuracy & role tags.
        - 'predictions': pd.DataFrame with point-by-point truth vs prediction curves.
        - 'kpis': dict of aggregate performance metrics.
        - 'protocol': str protocol name.
    """
    if learner not in SUPPORTED_LEARNERS:
        raise ValueError(f"Unsupported learner: {learner}")

    samples = build_samples(db)
    jet_samples = build_jet_samples(db)
    aircraft_df = db.aircraft.copy()

    if protocol == "verified_5fold":
        # 1. EASA VERIFIED AIRCRAFT 5-FOLD CROSS-VALIDATION
        # Filter strictly to the 11 verified trainable aircraft types from easa_verified_anp_aircraft_types.csv
        verified_samples = jet_samples[jet_samples["npd_id"].isin(TRAINABLE_NPD_IDS)].copy()
        if verified_samples.empty:
            raise RuntimeError("No verified EASA aircraft samples found in database")

        splits = deterministic_group_folds(verified_samples, 5, seed)
        fold_map = dict(zip(splits["npd_id"], splits["fold"]))
        verified_samples["fold"] = verified_samples["npd_id"].map(fold_map)

        feature_names = jet_feature_names(JET_V2_SCHEMA_ID)
        predictions_list = []

        for metric, mode in COMBOS:
            v_combo = verified_samples[
                (verified_samples["metric"] == metric) & (verified_samples["op_mode"] == mode)
            ].copy()
            all_combo = jet_samples[
                (jet_samples["metric"] == metric) & (jet_samples["op_mode"] == mode)
            ].copy()

            for fold in sorted(v_combo["fold"].unique()):
                test = v_combo[v_combo["fold"] == fold].copy()
                held_groups = set(test["aircraft_group_id"])
                held_npds = set(test["npd_id"])

                # Train on the rest of the fleet excluding held-out groups
                train = all_combo[
                    ~all_combo["aircraft_group_id"].isin(held_groups)
                    & ~all_combo["npd_id"].isin(held_npds)
                ]

                if test.empty or train.empty:
                    continue

                regressor = validation_regressor(learner, seed)
                regressor.fit(
                    train.loc[:, feature_names].to_numpy(dtype=float),
                    train.loc[:, TRUTH_COLUMNS].to_numpy(dtype=float),
                )
                pred_oof = enforce_distance_monotone(
                    regressor.predict(test.loc[:, feature_names].to_numpy(dtype=float))
                )
                _accumulate_prediction_rows(
                    predictions_list, test, pred_oof, metric, mode, f"VERIFIED_FOLD_{fold+1}_TEST", learner, protocol
                )

        pred_df = pd.DataFrame(predictions_list) if predictions_list else pd.DataFrame()

        # Build summary table for the 11 verified aircraft
        rows = []
        for npd_id in sorted(TRAINABLE_NPD_IDS):
            fold_idx = fold_map.get(npd_id, -1)
            meta = VERIFIED_METADATA_MAP.get(npd_id, {})
            acft_matches = aircraft_df[aircraft_df["NPD_ID"] == npd_id]
            if not acft_matches.empty:
                desc = str(acft_matches.iloc[0]["Description"])
                acft_id = str(acft_matches.iloc[0]["ACFT_ID"])
                engine_count = int(acft_matches.iloc[0]["Number Of Engines"])
                mtow_lb = float(acft_matches.iloc[0]["Max Gross Takeoff Weight (lb)"])
                thrust_lb = float(acft_matches.iloc[0]["Max Sea Level Static Thrust (lb)"])
            else:
                desc = npd_id
                acft_id = npd_id
                engine_count = 2
                mtow_lb = 0.0
                thrust_lb = 0.0

            if not pred_df.empty:
                acft_preds = pred_df[pred_df["npd_id"] == npd_id]
            else:
                acft_preds = pd.DataFrame()

            if not acft_preds.empty:
                m_all = _calculate_row_metrics(acft_preds["error_dB"].to_numpy(float))
                rmse = m_all["rmse_dB"]
                mae = m_all["mae_dB"]
                max_err = m_all["max_error_dB"]
                bias = m_all["bias_dB"]
                n_points = len(acft_preds)
            else:
                rmse = np.nan
                mae = np.nan
                max_err = np.nan
                bias = np.nan
                n_points = 0

            # Per-metric breakdowns
            metric_cols = {}
            for metric, mode in COMBOS:
                col_name = f"RMSE_{metric}_{mode}"
                if not acft_preds.empty:
                    sub = acft_preds[(acft_preds["metric"] == metric) & (acft_preds["op_mode"] == mode)]
                    if not sub.empty:
                        metric_cols[col_name] = round(float(np.sqrt(np.mean(sub["error_dB"].to_numpy(float) ** 2))), 3)
                    else:
                        metric_cols[col_name] = np.nan
                else:
                    metric_cols[col_name] = np.nan

            rows.append({
                "NPD_ID": npd_id,
                "ACFT_ID": acft_id,
                "Description": desc,
                "EASA Status": "✅ Verified (v6.3)",
                "Verification Date": meta.get("verification_date", "EASA v6.3"),
                "Engine Family": meta.get("engine_family", "Certified"),
                "Role": "VERIFIED_OUT_OF_FOLD",
                "Role Description": f"Fold {fold_idx + 1} Verified Out-of-Fold Test",
                "Fold": fold_idx + 1,
                "Engine Count": engine_count,
                "MTOW [lb]": mtow_lb,
                "Thrust [lb]": thrust_lb,
                "Overall RMSE [dB]": round(rmse, 3) if not np.isnan(rmse) else np.nan,
                "MAE [dB]": round(mae, 3) if not np.isnan(mae) else np.nan,
                "Max Error [dB]": round(max_err, 3) if not np.isnan(max_err) else np.nan,
                "Bias [dB]": round(bias, 3) if not np.isnan(bias) else np.nan,
                "Points Evaluated": n_points,
                **metric_cols,
            })

        summary_df = pd.DataFrame(rows)

        kpis = {
            "protocol_name": "EASA Verified 5-Fold Cross-Validation",
            "total_aircraft_count": len(summary_df),
            "validation_aircraft_count": len(summary_df),
            "training_aircraft_count": len(jet_samples["npd_id"].unique()) - len(summary_df),
            "purged_aircraft_count": 0,
            "overall_validation_rmse_dB": round(float(summary_df["Overall RMSE [dB]"].dropna().mean()), 3),
            "overall_training_rmse_dB": round(float(summary_df["Overall RMSE [dB]"].dropna().mean()), 3),
            "n_folds": 5,
            "verified_source": "easa_verified_anp_aircraft_types.csv (11 Types)",
        }

        return {
            "summary_table": summary_df,
            "predictions": pred_df,
            "kpis": kpis,
            "protocol": protocol,
        }

    elif protocol == "holdout":
        # 2. FROZEN V6.3 RELEASE-HOLDOUT PROTOCOL
        selected_refs = {
            count: {"npd_id": item["npd_id"], "acft_id": item["acft_id"]}
            for count, item in FROZEN_REFERENCES.items()
        }
        split = build_jet_reference_split(samples, selected_refs)

        train_ids = set(split.loc[split["role"] == "train", "npd_id"])
        test_ids = set(split.loc[split["role"] == "test", "npd_id"])
        purged_ids = set(split.loc[split["role"] == "excluded_family_purge", "npd_id"])

        predictions_list = []

        for metric, mode in COMBOS:
            combo = jet_samples[
                (jet_samples["metric"] == metric) & (jet_samples["op_mode"] == mode)
            ]
            train = combo[
                combo["npd_id"].isin(train_ids)
                & (combo["source_dataset"] == TRAIN_SOURCE)
            ]
            test = combo[
                combo["npd_id"].isin(test_ids)
                & (combo["source_dataset"] == REFERENCE_SOURCE)
            ]

            if train.empty:
                continue

            regressor = validation_regressor(learner, seed)
            regressor.fit(
                train.loc[:, FEATURES].to_numpy(dtype=float),
                train.loc[:, TRUTH_COLUMNS].to_numpy(dtype=float),
            )

            # Predict on test holdout
            if not test.empty:
                pred_test = enforce_distance_monotone(
                    regressor.predict(test.loc[:, FEATURES].to_numpy(dtype=float))
                )
                _accumulate_prediction_rows(
                    predictions_list, test, pred_test, metric, mode, "VALIDATION_ONLY", learner, protocol
                )

            # Predict on train set
            pred_train = enforce_distance_monotone(
                regressor.predict(train.loc[:, FEATURES].to_numpy(dtype=float))
            )
            _accumulate_prediction_rows(
                predictions_list, train, pred_train, metric, mode, "TRAIN", learner, protocol
            )

        pred_df = pd.DataFrame(predictions_list) if predictions_list else pd.DataFrame()

        rows = []
        for _, curve_row in split.iterrows():
            npd_id = curve_row["npd_id"]
            raw_role = curve_row["role"]
            source = curve_row["source_dataset"]

            if raw_role == "test":
                ui_role = "VALIDATION_ONLY"
                role_desc = "Frozen v6.3 Release Holdout"
            elif raw_role == "train":
                ui_role = "TRAIN"
                role_desc = "Legacy v2.3 Training Set"
            elif raw_role == "excluded_family_purge":
                ui_role = "PURGED"
                reason = FAMILY_PURGE_REASON.get(npd_id, "family_leakage_guard")
                role_desc = f"Purged ({reason})"
            else:
                ui_role = "EXCLUDED"
                role_desc = "Excluded Candidate"

            acft_matches = aircraft_df[aircraft_df["NPD_ID"] == npd_id]
            if not acft_matches.empty:
                desc = str(acft_matches.iloc[0]["Description"])
                acft_id = str(acft_matches.iloc[0]["ACFT_ID"])
                engine_type = str(acft_matches.iloc[0]["Engine Type"])
                engine_count = int(acft_matches.iloc[0]["Number Of Engines"])
                mtow_lb = float(acft_matches.iloc[0]["Max Gross Takeoff Weight (lb)"])
                thrust_lb = float(acft_matches.iloc[0]["Max Sea Level Static Thrust (lb)"])
            else:
                desc = EXPECTED_REFERENCE_DESCRIPTIONS.get(npd_id, npd_id)
                acft_id = npd_id
                engine_type = "Jet"
                engine_count = int(curve_row["engine_count"])
                mtow_lb = 0.0
                thrust_lb = 0.0

            if not pred_df.empty:
                acft_preds = pred_df[pred_df["npd_id"] == npd_id]
            else:
                acft_preds = pd.DataFrame()

            if not acft_preds.empty:
                m_all = _calculate_row_metrics(acft_preds["error_dB"].to_numpy(float))
                rmse = m_all["rmse_dB"]
                mae = m_all["mae_dB"]
                max_err = m_all["max_error_dB"]
                bias = m_all["bias_dB"]
                n_points = len(acft_preds)
            else:
                rmse = np.nan
                mae = np.nan
                max_err = np.nan
                bias = np.nan
                n_points = 0

            metric_cols = {}
            for metric, mode in COMBOS:
                col_name = f"RMSE_{metric}_{mode}"
                if not acft_preds.empty:
                    sub = acft_preds[(acft_preds["metric"] == metric) & (acft_preds["op_mode"] == mode)]
                    if not sub.empty:
                        metric_cols[col_name] = round(float(np.sqrt(np.mean(sub["error_dB"].to_numpy(float) ** 2))), 3)
                    else:
                        metric_cols[col_name] = np.nan
                else:
                    metric_cols[col_name] = np.nan

            is_verified = "✅ Verified (v6.3)" if npd_id in TRAINABLE_NPD_IDS else "Legacy (v2.3)"

            rows.append({
                "NPD_ID": npd_id,
                "ACFT_ID": acft_id,
                "Description": desc,
                "EASA Status": is_verified,
                "Role": ui_role,
                "Role Description": role_desc,
                "Dataset Source": source,
                "Engine Count": engine_count,
                "MTOW [lb]": mtow_lb,
                "Thrust [lb]": thrust_lb,
                "Overall RMSE [dB]": round(rmse, 3) if not np.isnan(rmse) else np.nan,
                "MAE [dB]": round(mae, 3) if not np.isnan(mae) else np.nan,
                "Max Error [dB]": round(max_err, 3) if not np.isnan(max_err) else np.nan,
                "Bias [dB]": round(bias, 3) if not np.isnan(bias) else np.nan,
                "Points Evaluated": n_points,
                **metric_cols,
            })

        summary_df = pd.DataFrame(rows)

        val_sub = summary_df[summary_df["Role"] == "VALIDATION_ONLY"]
        train_sub = summary_df[summary_df["Role"] == "TRAIN"]
        purged_sub = summary_df[summary_df["Role"] == "PURGED"]

        kpis = {
            "protocol_name": "Frozen v6.3 Release-Holdout",
            "total_aircraft_count": len(summary_df),
            "training_aircraft_count": len(train_sub),
            "validation_aircraft_count": len(val_sub),
            "purged_aircraft_count": len(purged_sub),
            "overall_validation_rmse_dB": round(float(val_sub["Overall RMSE [dB]"].mean()), 3) if not val_sub.empty else 0.0,
            "overall_training_rmse_dB": round(float(train_sub["Overall RMSE [dB]"].mean()), 3) if not train_sub.empty else 0.0,
            "holdout_references": list(test_ids),
            "purged_family_guards": list(purged_ids),
        }

        return {
            "summary_table": summary_df,
            "predictions": pred_df,
            "kpis": kpis,
            "protocol": protocol,
        }

    elif protocol == "group_cv":
        # 3. COMPLETE 5-FOLD STRATIFIED GROUP CROSS-VALIDATION (ALL 94 JETS)
        folds_df = build_jet_group_folds(jet_samples, folds=5, seed=seed)
        fold_map = dict(zip(folds_df["npd_id"], folds_df["fold"]))
        jet_samples["fold"] = jet_samples["npd_id"].map(fold_map)

        feature_names = jet_feature_names(JET_V2_SCHEMA_ID)
        predictions_list = []

        for fold in range(5):
            train = jet_samples[jet_samples["fold"] != fold]
            test = jet_samples[jet_samples["fold"] == fold]

            for metric, mode in COMBOS:
                sub_train = train[(train["metric"] == metric) & (train["op_mode"] == mode)]
                sub_test = test[(test["metric"] == metric) & (test["op_mode"] == mode)]

                if sub_train.empty or sub_test.empty:
                    continue

                regressor = validation_regressor(learner, seed)
                regressor.fit(
                    sub_train.loc[:, feature_names].to_numpy(dtype=float),
                    sub_train.loc[:, TRUTH_COLUMNS].to_numpy(dtype=float),
                )
                pred_oof = enforce_distance_monotone(
                    regressor.predict(sub_test.loc[:, feature_names].to_numpy(dtype=float))
                )
                _accumulate_prediction_rows(
                    predictions_list, sub_test, pred_oof, metric, mode, f"CV_FOLD_{fold+1}_TEST", learner, protocol
                )

        pred_df = pd.DataFrame(predictions_list) if predictions_list else pd.DataFrame()

        rows = []
        unique_npds = jet_samples["npd_id"].unique()
        for npd_id in sorted(unique_npds):
            fold_idx = fold_map.get(npd_id, -1)
            ui_role = "OUT_OF_FOLD_VALIDATION"
            role_desc = f"Fold {fold_idx + 1} Out-of-Fold Validation"

            acft_matches = aircraft_df[aircraft_df["NPD_ID"] == npd_id]
            if not acft_matches.empty:
                desc = str(acft_matches.iloc[0]["Description"])
                acft_id = str(acft_matches.iloc[0]["ACFT_ID"])
                engine_count = int(acft_matches.iloc[0]["Number Of Engines"])
                mtow_lb = float(acft_matches.iloc[0]["Max Gross Takeoff Weight (lb)"])
                thrust_lb = float(acft_matches.iloc[0]["Max Sea Level Static Thrust (lb)"])
            else:
                desc = npd_id
                acft_id = npd_id
                engine_count = 2
                mtow_lb = 0.0
                thrust_lb = 0.0

            if not pred_df.empty:
                acft_preds = pred_df[pred_df["npd_id"] == npd_id]
            else:
                acft_preds = pd.DataFrame()

            if not acft_preds.empty:
                m_all = _calculate_row_metrics(acft_preds["error_dB"].to_numpy(float))
                rmse = m_all["rmse_dB"]
                mae = m_all["mae_dB"]
                max_err = m_all["max_error_dB"]
                bias = m_all["bias_dB"]
                n_points = len(acft_preds)
            else:
                rmse = np.nan
                mae = np.nan
                max_err = np.nan
                bias = np.nan
                n_points = 0

            metric_cols = {}
            for metric, mode in COMBOS:
                col_name = f"RMSE_{metric}_{mode}"
                if not acft_preds.empty:
                    sub = acft_preds[(acft_preds["metric"] == metric) & (acft_preds["op_mode"] == mode)]
                    if not sub.empty:
                        metric_cols[col_name] = round(float(np.sqrt(np.mean(sub["error_dB"].to_numpy(float) ** 2))), 3)
                    else:
                        metric_cols[col_name] = np.nan
                else:
                    metric_cols[col_name] = np.nan

            is_verified = "✅ Verified (v6.3)" if npd_id in TRAINABLE_NPD_IDS else "Legacy (v2.3)"

            rows.append({
                "NPD_ID": npd_id,
                "ACFT_ID": acft_id,
                "Description": desc,
                "EASA Status": is_verified,
                "Role": ui_role,
                "Role Description": role_desc,
                "Fold": fold_idx + 1,
                "Engine Count": engine_count,
                "MTOW [lb]": mtow_lb,
                "Thrust [lb]": thrust_lb,
                "Overall RMSE [dB]": round(rmse, 3) if not np.isnan(rmse) else np.nan,
                "MAE [dB]": round(mae, 3) if not np.isnan(mae) else np.nan,
                "Max Error [dB]": round(max_err, 3) if not np.isnan(max_err) else np.nan,
                "Bias [dB]": round(bias, 3) if not np.isnan(bias) else np.nan,
                "Points Evaluated": n_points,
                **metric_cols,
            })

        summary_df = pd.DataFrame(rows)

        kpis = {
            "protocol_name": "5-Fold Stratified Group Cross-Validation",
            "total_aircraft_count": len(summary_df),
            "training_aircraft_count": len(summary_df),
            "validation_aircraft_count": len(summary_df),
            "purged_aircraft_count": 0,
            "overall_validation_rmse_dB": round(float(summary_df["Overall RMSE [dB]"].dropna().mean()), 3),
            "overall_training_rmse_dB": round(float(summary_df["Overall RMSE [dB]"].dropna().mean()), 3),
            "n_folds": 5,
        }

        return {
            "summary_table": summary_df,
            "predictions": pred_df,
            "kpis": kpis,
            "protocol": protocol,
        }

    else:
        raise ValueError(f"Unknown validation protocol: {protocol}")


def _accumulate_prediction_rows(
    out_list: list,
    samples_subset: pd.DataFrame,
    predictions: np.ndarray,
    metric: str,
    mode: str,
    role: str,
    learner: str,
    protocol: str,
) -> None:
    """Accumulate point-by-point truth vs prediction values across all 10 distances."""
    truth_matrix = samples_subset.loc[:, TRUTH_COLUMNS].to_numpy(dtype=float)
    npd_ids = samples_subset["npd_id"].to_numpy()
    power_settings = samples_subset["power_setting"].to_numpy(dtype=float)
    source_datasets = (
        samples_subset["source_dataset"].to_numpy()
        if "source_dataset" in samples_subset
        else np.array(["unknown"] * len(samples_subset))
    )

    for row_idx in range(len(samples_subset)):
        npd_id = str(npd_ids[row_idx])
        p_val = float(power_settings[row_idx])
        src = str(source_datasets[row_idx])

        for dist_idx, dist_ft in enumerate(STANDARD_DISTANCES_FT):
            t_val = float(truth_matrix[row_idx, dist_idx])
            p_pred = float(predictions[row_idx, dist_idx])
            err = p_pred - t_val

            out_list.append({
                "protocol": protocol,
                "model": learner,
                "role": role,
                "npd_id": npd_id,
                "source_dataset": src,
                "metric": metric,
                "op_mode": mode,
                "power_setting": p_val,
                "distance_ft": float(dist_ft),
                "truth_dB": t_val,
                "prediction_dB": p_pred,
                "error_dB": err,
            })


def load_or_build_accuracy_dataset(
    db: ANPDatabase,
    protocol: Literal["verified_5fold", "group_cv", "holdout"] = "verified_5fold",
    learner: str = "et",
    seed: int = 20260724,
    force_recompute: bool = False,
) -> dict:
    """Load precomputed accuracy validation dataset from disk in milliseconds, or build and cache it.

    Parameters
    ----------
    db : ANPDatabase
        Database instance.
    protocol : {'verified_5fold', 'group_cv', 'holdout'}
        Validation protocol.
    learner : str, default 'et'
        Surrogate regressor.
    seed : int, default 20260724
        Random seed.
    force_recompute : bool, default False
        If True, ignore disk cache and recompute from scratch.

    Returns
    -------
    dict
        Accuracy dataset dict with summary_table, predictions, kpis, protocol.
    """
    import json
    from pathlib import Path

    root = getattr(db, "root", ".")
    cache_dir = Path(root).resolve() / "outputs" / "accuracy_validation"
    summary_path = cache_dir / f"{protocol}_summary.parquet"
    preds_path = cache_dir / f"{protocol}_predictions.parquet"
    kpis_path = cache_dir / f"{protocol}_kpis.json"

    if (
        not force_recompute
        and summary_path.exists()
        and preds_path.exists()
        and kpis_path.exists()
    ):
        try:
            summary_df = pd.read_parquet(summary_path)
            pred_df = pd.read_parquet(preds_path)
            with open(kpis_path, "r", encoding="utf-8") as f:
                kpis = json.load(f)
            return {
                "summary_table": summary_df,
                "predictions": pred_df,
                "kpis": kpis,
                "protocol": protocol,
            }
        except Exception:
            pass  # Fall back to rebuilding

    ds = build_accuracy_validation_dataset(
        db, protocol=protocol, learner=learner, seed=seed
    )

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        ds["summary_table"].to_parquet(summary_path, index=False)
        ds["predictions"].to_parquet(preds_path, index=False)
        with open(kpis_path, "w", encoding="utf-8") as f:
            json.dump(ds["kpis"], f, indent=2)
    except Exception:
        pass

    return ds

