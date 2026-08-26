from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import numpy as np

from .anp import ANPDatabase, DIST_COLS
from .physics import PhysicsNPDModel, PhysicsDesign
from .physics_presets import PHYSICS_PRESETS
from .verified_anp import REGISTRY_VERSION, SOURCE_HASHES

SCHEMA_VERSION = "pnmf.physics-calibration/v1"
ANCHOR_AIRCRAFT = "A320-270N"
ANCHOR_NPD_ID = "A320-270N"
ANCHOR_PRESET = "A320-270N"
DEFAULT_ARTIFACT_PATH = Path(__file__).with_name(
    "physics_calibration_A320-270N_v1.json")
DEFAULT_OPTIMIZER_CONFIG = {
    "spectral_grid": (0.0, 0.7, 1.3, 2.0, 2.6),
    "stage1_max_nfev": 40,
    "joint_max_nfev": 60,
    "stage1_diff_step": 1.0,
    "joint_diff_step": 0.3,
    "stage1_xtol": 1e-2,
    "joint_xtol": 1e-3,
}


def _hash_dict() -> dict[str, str]:
    return {
        "verified_workbook": SOURCE_HASHES.verified_workbook,
        "v63_aircraft": SOURCE_HASHES.v63_aircraft,
        "v63_npd": SOURCE_HASHES.v63_npd,
    }


def _git_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def _anchor_design(db: ANPDatabase) -> tuple[PhysicsDesign, str]:
    rows = db.aircraft[db.aircraft["ACFT_ID"] == ANCHOR_AIRCRAFT]
    if len(rows) != 1:
        raise ValueError(
            f"expected one {ANCHOR_AIRCRAFT} aircraft row, found {len(rows)}")
    row = rows.iloc[0]
    preset = PHYSICS_PRESETS[ANCHOR_PRESET]
    return PhysicsDesign(
        ANCHOR_AIRCRAFT,
        row["Number Of Engines"],
        row["Max Sea Level Static Thrust (lb)"],
        preset.bpr,
        row["Max Gross Takeoff Weight (lb)"],
        wing_area_m2=preset.estimated_wing_area_m2,
        span_m=preset.wing_span_m,
        fan_diameter_m=preset.fan_diameter_m,
        n_fan_blades=preset.fan_blades,
        n_wheels=preset.main_wheel_count,
        wheel_d_m=preset.main_wheel_diameter_m,
    ), str(row["NPD_ID"])


def _metrics(db: ANPDatabase, model: PhysicsNPDModel) -> dict[str, float | int]:
    design, npd_id = _anchor_design(db)
    errors: list[np.ndarray] = []
    for metric in model.SUPPORTED_METRICS:
        for op_mode in ("A", "D"):
            curve = db.curve(npd_id, metric, op_mode)
            if curve.empty:
                continue
            powers = curve["Power Setting"].to_numpy(dtype=float)
            truth = curve[DIST_COLS].to_numpy(dtype=float)
            prediction = model.predict_table(
                design, metric, op_mode, powers).L
            errors.append((prediction - truth).reshape(-1))
    if not errors:
        raise ValueError("A320-270N has no SEL/LAmax calibration cells")
    flat = np.concatenate(errors)
    absolute = np.abs(flat)
    return {
        "cell_count": int(flat.size),
        "rmse_db": float(np.sqrt(np.mean(flat ** 2))),
        "mae_db": float(np.mean(absolute)),
        "bias_db": float(np.mean(flat)),
        "p90_absolute_error_db": float(np.percentile(absolute, 90)),
    }


def build_calibration_artifact(
    db: ANPDatabase,
    output_path: str | Path,
    *,
    optimizer_config: Mapping[str, object] | None = None,
    generated_utc: str | None = None,
) -> dict:
    config = dict(DEFAULT_OPTIMIZER_CONFIG)
    if optimizer_config:
        config.update(optimizer_config)
    model = PhysicsNPDModel()
    model.calibrate(
        db,
        ANCHOR_AIRCRAFT,
        bpr=PHYSICS_PRESETS[ANCHOR_PRESET].bpr,
        verbose=False,
        optimizer_config=config,
    )
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "registry_version": REGISTRY_VERSION,
        "anchor": {
            "aircraft_id": ANCHOR_AIRCRAFT,
            "npd_id": ANCHOR_NPD_ID,
            "preset_id": ANCHOR_PRESET,
        },
        "parameters": model.calibration_parameters(),
        "optimizer": {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in config.items()
        },
        "metrics": _metrics(db, model),
        "source_hashes": _hash_dict(),
        "code_revision": _git_revision(),
        "generated_utc": generated_utc or datetime.now(timezone.utc).isoformat(),
        "generation_command": "pnmf_cli.py build-physics-calibration",
        "validation_scope": "A320-270N in-sample SEL/LAmax A/D",
    }
    validate_calibration_artifact(artifact)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return artifact


def validate_calibration_artifact(
    artifact: Mapping[str, object],
    *,
    expected_source_hashes: Mapping[str, str] | None = None,
) -> dict:
    if artifact.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported physics calibration schema")
    if artifact.get("registry_version") != REGISTRY_VERSION:
        raise ValueError("physics calibration registry version mismatch")
    anchor = artifact.get("anchor")
    if not isinstance(anchor, Mapping) or anchor != {
        "aircraft_id": ANCHOR_AIRCRAFT,
        "npd_id": ANCHOR_NPD_ID,
        "preset_id": ANCHOR_PRESET,
    }:
        raise ValueError("physics calibration anchor mismatch")
    hashes = artifact.get("source_hashes")
    expected = dict(expected_source_hashes or _hash_dict())
    if not isinstance(hashes, Mapping) or dict(hashes) != expected:
        raise ValueError("physics calibration source hash mismatch")
    parameters = artifact.get("parameters")
    required = ("C_jet", "C_fan", "C_wingflap", "C_gear",
                "spectral_scale")
    if not isinstance(parameters, Mapping) or any(
            key not in parameters for key in required):
        raise ValueError("physics calibration parameter schema mismatch")
    if not all(np.isfinite(float(parameters[key])) for key in required):
        raise ValueError("physics calibration parameters must be finite")
    if float(parameters["spectral_scale"]) <= 0:
        raise ValueError("physics calibration spectral scale must be positive")
    metrics = artifact.get("metrics")
    if not isinstance(metrics, Mapping) or int(metrics.get("cell_count", 0)) <= 0:
        raise ValueError("physics calibration metrics are incomplete")
    return dict(artifact)


def load_calibration_artifact(
    path: str | Path | None = None,
    *,
    expected_source_hashes: Mapping[str, str] | None = None,
) -> dict:
    artifact_path = Path(path) if path is not None else DEFAULT_ARTIFACT_PATH
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"physics calibration artifact not found: {artifact_path}") from exc
    if not isinstance(artifact, Mapping):
        raise ValueError("physics calibration artifact must be an object")
    return validate_calibration_artifact(
        artifact, expected_source_hashes=expected_source_hashes)


def load_calibrated_model(
    path: str | Path | None = None,
    *,
    expected_source_hashes: Mapping[str, str] | None = None,
) -> tuple[PhysicsNPDModel, dict]:
    artifact = load_calibration_artifact(
        path, expected_source_hashes=expected_source_hashes)
    model = PhysicsNPDModel().apply_calibration(artifact["parameters"])
    return model, artifact
