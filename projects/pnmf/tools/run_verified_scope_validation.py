from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from pnmf.anp import ANPDatabase, DIST_COLS, PROJECT_ROOT
from pnmf.core import ParametricAircraft
from pnmf.models import SurrogateNPDModel
from pnmf.physics import PhysicsDesign
from pnmf.physics_calibration import DEFAULT_ARTIFACT_PATH, load_calibrated_model
from pnmf.physics_presets import PHYSICS_PRESETS
from pnmf.verified_anp import (
    REGISTRY_VERSION,
    SOURCE_HASHES,
    TRAINABLE_NPD_IDS,
    VERIFIED_AIRCRAFT_REGISTRY,
)
from pnmf.validation import (
    COMBOS,
    FEATURES,
    TRUTH_COLUMNS,
    _fit_predict,
    _prediction_frame,
    _sha256_file,
    aircraft_group_map,
    build_samples,
    deterministic_group_folds,
    evaluate_temporal,
    summarize_predictions,
    temporal_split,
)


def _git_state() -> dict[str, object]:
    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT.parents[1],
            capture_output=True, text=True, check=False,
        )
        return result.stdout.strip()

    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD"),
        "dirty": bool(status),
        "status_sha256": hashlib.sha256(status.encode()).hexdigest(),
    }


def _descriptor_keys(frame: pd.DataFrame) -> pd.Series:
    columns = list(ParametricAircraft.feature_names())
    return frame.loc[:, columns].apply(
        lambda row: tuple(float(value) for value in row), axis=1)


def _metrics(frame: pd.DataFrame, unit: str | None = None) -> dict[str, float | int]:
    if frame.empty:
        return {"rmse_dB": None, "mae_dB": None, "bias_dB": None,
                "p90_abs_error_dB": None, "n_cells": 0,
                "n_power_samples": 0, "n_curves": 0,
                "n_aircraft_groups": 0}
    if unit is None:
        errors = frame["error_dB"].to_numpy(float)
        rmse = float(np.sqrt(np.mean(errors ** 2)))
        mae = float(np.mean(np.abs(errors)))
        bias = float(np.mean(errors))
        p90 = float(np.percentile(np.abs(errors), 90))
    else:
        values = frame.groupby(unit, sort=True)["error_dB"].agg(
            mse=lambda x: float(np.mean(np.asarray(x) ** 2)),
            mae=lambda x: float(np.mean(np.abs(np.asarray(x)))),
            bias="mean",
            p90=lambda x: float(np.percentile(np.abs(np.asarray(x)), 90)),
        )
        rmse = float(np.sqrt(values["mse"].mean()))
        mae = float(values["mae"].mean())
        bias = float(values["bias"].mean())
        p90 = float(values["p90"].mean())
    return {
        "rmse_dB": rmse,
        "mae_dB": mae,
        "bias_dB": bias,
        "p90_abs_error_dB": p90,
        "n_cells": int(len(frame)),
        "n_power_samples": int(frame["sample_id"].nunique()),
        "n_curves": int(frame["npd_id"].nunique()),
        "n_aircraft_groups": int(frame["aircraft_group_id"].nunique()),
    }


def _summary_rows(predictions: pd.DataFrame, protocol: str) -> list[dict]:
    rows = []
    for (variant, learner, metric, mode), frame in predictions[
            predictions["protocol"] == protocol].groupby(
                ["variant", "model", "metric", "op_mode"], sort=True):
        for aggregation, unit in (("cell_pooled", None),
                                  ("macro_aircraft", "aircraft_group_id")):
            row = {
                "protocol": protocol,
                "variant": variant,
                "model": learner,
                "metric": metric,
                "op_mode": mode,
                "aggregation": aggregation,
            }
            row.update(_metrics(frame, unit))
            rows.append(row)
    return rows


def _scoped_predictions(
    samples: pd.DataFrame,
    verified_samples: pd.DataFrame,
    splits: pd.DataFrame,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[pd.DataFrame] = []
    runs: list[dict] = []
    descriptor = _descriptor_keys(samples)
    all_samples = samples.copy()
    all_samples["descriptor_key"] = descriptor
    verified = verified_samples.copy()
    verified["descriptor_key"] = _descriptor_keys(verified)
    fold_map = splits.drop_duplicates("aircraft_group_id").set_index(
        "aircraft_group_id")["fold"]
    for metric, mode in COMBOS:
        verified_combo = verified[
            (verified.metric == metric) & (verified.op_mode == mode)
        ].copy()
        merged_combo = all_samples[
            (all_samples.metric == metric) & (all_samples.op_mode == mode)
        ].copy()
        verified_combo["fold"] = verified_combo.aircraft_group_id.map(fold_map)
        for fold in sorted(verified_combo["fold"].unique()):
            test = verified_combo[verified_combo.fold == fold].copy()
            held_groups = set(test.aircraft_group_id)
            held_descriptors = set(test.descriptor_key)
            train_verified = verified_combo[
                ~verified_combo.aircraft_group_id.isin(held_groups)
            ]
            train_merged = merged_combo[
                ~merged_combo.aircraft_group_id.isin(held_groups)
                & ~merged_combo.descriptor_key.isin(held_descriptors)
            ]
            if set(test.npd_id) & set(train_merged.npd_id):
                raise RuntimeError("held-out verified NPD ID leaked into merged training")
            for learner in ("et", "rf"):
                for scope, train in (("verified", train_verified),
                                     ("merged", train_merged)):
                    prediction, duration = _fit_predict(
                        learner, seed, train, test)
                    frame = _prediction_frame(
                        test, prediction,
                        protocol="verified_grouped_cv",
                        variant=scope,
                        learner=learner,
                        fold=fold,
                    )
                    rows.append(frame)
                    runs.append({
                        "protocol": "verified_grouped_cv",
                        "variant": scope,
                        "model": learner,
                        "metric": metric,
                        "op_mode": mode,
                        "fold": int(fold),
                        "train_samples": int(len(train)),
                        "train_curves": int(train.npd_id.nunique()),
                        "train_aircraft_groups": int(train.aircraft_group_id.nunique()),
                        "test_samples": int(len(test)),
                        "test_curves": int(test.npd_id.nunique()),
                        "test_aircraft_groups": int(test.aircraft_group_id.nunique()),
                        "fit_predict_seconds": float(duration),
                    })
    return pd.concat(rows, ignore_index=True), pd.DataFrame(runs)


def _frozen_jet_predictions(
    samples: pd.DataFrame,
    verified_samples: pd.DataFrame,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    references = ("A330-743L", "FAL900EX", "747400RN")
    test = verified_samples[verified_samples.npd_id.isin(references)].copy()
    if set(test.npd_id) != set(references):
        raise RuntimeError("frozen verified jet reference selection is incomplete")
    all_samples = samples.copy()
    descriptor = _descriptor_keys(all_samples)
    all_samples["descriptor_key"] = descriptor
    test["descriptor_key"] = _descriptor_keys(test)
    held_groups = set(test.aircraft_group_id)
    held_descriptors = set(test.descriptor_key)
    train_verified = verified_samples[
        ~verified_samples.aircraft_group_id.isin(held_groups)
    ]
    train_merged = all_samples[
        ~all_samples.aircraft_group_id.isin(held_groups)
        & ~all_samples.descriptor_key.isin(held_descriptors)
    ]
    rows: list[pd.DataFrame] = []
    runs: list[dict] = []
    for metric, mode in COMBOS:
        test_combo = test[(test.metric == metric) & (test.op_mode == mode)]
        for learner in ("et", "rf"):
            for scope, train_source in (("verified", train_verified),
                                        ("merged", train_merged)):
                train_combo = train_source[
                    (train_source.metric == metric)
                    & (train_source.op_mode == mode)
                ]
                prediction, duration = _fit_predict(
                    learner, seed, train_combo, test_combo)
                rows.append(_prediction_frame(
                    test_combo, prediction,
                    protocol="frozen_verified_jets",
                    variant=scope,
                    learner=learner,
                    fold="frozen",
                ))
                runs.append({
                    "protocol": "frozen_verified_jets",
                    "variant": scope,
                    "model": learner,
                    "metric": metric,
                    "op_mode": mode,
                    "train_curves": int(train_combo.npd_id.nunique()),
                    "test_curves": int(test_combo.npd_id.nunique()),
                    "fit_predict_seconds": float(duration),
                })
    return pd.concat(rows, ignore_index=True), pd.DataFrame(runs)


def _physics_validation(db: ANPDatabase) -> tuple[pd.DataFrame, dict]:
    model, artifact = load_calibrated_model()
    rows: list[dict] = []
    for key, preset in PHYSICS_PRESETS.items():
        if key == "A320-270N":
            continue
        aircraft = db.aircraft[db.aircraft["ACFT_ID"] == preset.anp_id]
        if aircraft.empty:
            raise RuntimeError(f"physics preset aircraft is missing: {preset.anp_id}")
        source = aircraft.iloc[0]
        design = PhysicsDesign(
            preset.anp_id, preset.n_engines, preset.max_thrust_lbf,
            preset.bpr, preset.mtow_lb,
            wing_area_m2=preset.estimated_wing_area_m2,
            span_m=preset.wing_span_m,
            fan_diameter_m=preset.fan_diameter_m,
            n_fan_blades=preset.fan_blades,
            n_wheels=preset.main_wheel_count,
            wheel_d_m=preset.main_wheel_diameter_m,
        )
        provenance = {record.field: record.status for record in preset.provenance}
        fallback = model.single_event_diagnostics(
            design, preset.max_thrust_lbf * 0.8, "D", 1000.0)
        for metric in ("SEL", "LAmax"):
            for mode in ("A", "D"):
                curve = db.curve(str(source.NPD_ID), metric, mode)
                powers = curve["Power Setting"].to_numpy(float)
                truth = curve[DIST_COLS].to_numpy(float)
                prediction = model.predict_table(design, metric, mode, powers).L
                error = (prediction - truth).reshape(-1)
                rows.append({
                    "aircraft_id": preset.anp_id,
                    "metric": metric,
                    "op_mode": mode,
                    "rmse_dB": float(np.sqrt(np.mean(error ** 2))),
                    "mae_dB": float(np.mean(np.abs(error))),
                    "bias_dB": float(np.mean(error)),
                    "p90_abs_error_dB": float(np.percentile(np.abs(error), 90)),
                    "n_cells": int(error.size),
                    "input_supplied": int(sum(status == "supplied" for status in provenance.values())),
                    "input_estimated": int(sum(status == "estimated" for status in provenance.values())),
                    "input_unavailable": int(sum(status == "unavailable" for status in provenance.values())),
                    "jet_source_status": fallback.source_status["jet"].source,
                    "fan_source_status": fallback.source_status["fan"].source,
                    "airframe_source_status": fallback.source_status["airframe"].source,
                    "fallback_used": int(fallback.source_status["jet"].source != "supplied"
                                          or fallback.source_status["fan"].source != "supplied"),
                })
    return pd.DataFrame(rows), artifact


def run(output_dir: Path, seed: int, folds: int) -> dict:
    started_utc = datetime.now(timezone.utc)
    started = time.perf_counter()
    db = ANPDatabase(".")
    samples = build_samples(db)
    verified = samples[
        samples.source_dataset.eq("supplement_v6.3")
        & samples.npd_id.isin(TRAINABLE_NPD_IDS)
    ].copy()
    if verified.npd_id.nunique() != 11:
        raise RuntimeError(f"verified sample support drifted: {verified.npd_id.nunique()}")
    splits = deterministic_group_folds(verified, folds, seed)
    grouped_predictions, grouped_runs = _scoped_predictions(
        samples, verified, splits, seed)
    frozen_predictions, frozen_runs = _frozen_jet_predictions(
        samples, verified, seed)
    temporal_splits = temporal_split(samples)
    temporal_predictions, temporal_runs = evaluate_temporal(samples, temporal_splits, seed)
    temporal_predictions["variant"] = "merged_" + temporal_predictions["variant"]
    predictions = pd.concat(
        [grouped_predictions, frozen_predictions, temporal_predictions],
        ignore_index=True,
    )
    summary = pd.DataFrame(
        _summary_rows(grouped_predictions, "verified_grouped_cv")
        + _summary_rows(frozen_predictions, "frozen_verified_jets")
        + _summary_rows(temporal_predictions, "temporal_release_holdout")
    )
    scope_delta = summary[
        (summary.protocol == "verified_grouped_cv")
        & (summary.aggregation == "macro_aircraft")
    ].pivot_table(
        index=["model", "metric", "op_mode", "aggregation"],
        columns="variant",
        values=["rmse_dB", "mae_dB", "bias_dB", "p90_abs_error_dB"],
    ).reset_index()
    scope_delta.columns = [
        "_".join(str(value) for value in column if str(value))
        if isinstance(column, tuple) else str(column)
        for column in scope_delta.columns
    ]
    physics, calibration = _physics_validation(db)
    output_dir.mkdir(parents=True, exist_ok=True)
    samples[samples.npd_id.isin(TRAINABLE_NPD_IDS)].to_csv(
        output_dir / "verified_samples.csv", index=False, lineterminator="\n")
    splits.to_csv(output_dir / "verified_group_splits.csv", index=False, lineterminator="\n")
    temporal_splits.to_csv(output_dir / "merged_temporal_splits.csv", index=False, lineterminator="\n")
    predictions.to_csv(output_dir / "predictions.csv", index=False, lineterminator="\n")
    summary.to_csv(output_dir / "summary.csv", index=False, lineterminator="\n")
    scope_delta.to_csv(output_dir / "verified_vs_merged_delta.csv", index=False,
                       lineterminator="\n")
    grouped_runs.to_csv(output_dir / "verified_group_runs.csv", index=False, lineterminator="\n")
    pd.concat([frozen_runs, pd.DataFrame(temporal_runs)], ignore_index=True).to_csv(
        output_dir / "holdout_runs.csv", index=False, lineterminator="\n")
    physics.to_csv(output_dir / "physics_validation.csv", index=False, lineterminator="\n")
    (output_dir / "physics_calibration_used.json").write_text(
        json.dumps(calibration, indent=2, sort_keys=True), encoding="utf-8")
    manifest_frame = db.dataset_manifest()
    manifest_frame.to_csv(output_dir / "source_manifest.csv", index=False, lineterminator="\n")
    datastore = PROJECT_ROOT / "anp_data.sqlite"
    manifest = {
        "run": {
            "started_utc": started_utc.isoformat(),
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": float(time.perf_counter() - started),
            "command": "pnmf/tools/run_verified_scope_validation.py",
            "seed": seed,
        },
        "git": _git_state(),
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "config": {
            "folds": folds,
            "training_scope": "verified",
            "verified_npd_ids": list(TRAINABLE_NPD_IDS),
            "verified_support_npd_ids": int(verified.npd_id.nunique()),
            "merged_support_npd_ids": int(samples.npd_id.nunique()),
            "frozen_jet_reference_ids": ["A330-743L", "FAL900EX", "747400RN"],
            "combos": [f"{metric}:{mode}" for metric, mode in COMBOS],
        },
        "registry": {
            "version": REGISTRY_VERSION,
            "entries": len(VERIFIED_AIRCRAFT_REGISTRY),
            "trainable": len(TRAINABLE_NPD_IDS),
            "metadata_only": len(VERIFIED_AIRCRAFT_REGISTRY) - len(TRAINABLE_NPD_IDS),
            "source_hashes": {
                "verified_workbook": SOURCE_HASHES.verified_workbook,
                "v63_aircraft": SOURCE_HASHES.v63_aircraft,
                "v63_npd": SOURCE_HASHES.v63_npd,
            },
        },
        "models": {
            "et": {"n_estimators": 500, "min_samples_leaf": 1,
                   "max_depth": 24, "max_features": 0.5},
            "rf": {"n_estimators": 200, "min_samples_leaf": 2,
                   "max_depth": None, "max_features": 1.0},
        },
        "inputs": {
            "datastore_sha256": _sha256_file(datastore),
            "source_manifest_sha256": hashlib.sha256(
                manifest_frame.to_csv(index=False).encode()).hexdigest(),
            "calibration_artifact_sha256": _sha256_file(DEFAULT_ARTIFACT_PATH),
        },
        "counts": {
            "sample_rows": int(len(samples)),
            "verified_sample_rows": int(len(verified)),
            "grouped_prediction_rows": int(len(grouped_predictions)),
            "frozen_prediction_rows": int(len(frozen_predictions)),
            "temporal_prediction_rows": int(len(temporal_predictions)),
            "physics_validation_rows": int(len(physics)),
        },
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=20260724)
    parser.add_argument("--folds", type=int, default=3)
    args = parser.parse_args(argv)
    manifest = run(Path(args.output_dir), args.seed, args.folds)
    print(json.dumps(manifest["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
