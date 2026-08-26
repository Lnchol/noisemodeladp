"""Feature contracts for the Jet-only learned prediction route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping

import numpy as np

JET_V2_SCHEMA_ID: Final = "jet-v2"
TOTAL_OPERATING_FEATURE: Final = "log_total_operating_cnt_lb"
SUPPORTED_JET_POWER_PARAMETERS: Final = frozenset(
    {"CNT (lb)", "CNT (% of Max Static Thrust)"}
)

_JET_STATIC_FEATURES: Final = (
    "n_engines",
    "log_mtow",
    "log_mlw",
    "mlw_mtow",
    "log_thrust_per_eng",
    "log_total_thrust",
    "noise_chapter",
)
_JET_POWER_FEATURES: Final = ("log_power_lb", "throttle")
_JET_COMPACT_FEATURES: Final = _JET_STATIC_FEATURES + _JET_POWER_FEATURES


class JetFeatureError(ValueError):
    """Raised when a Jet feature contract cannot be constructed safely."""


@dataclass(frozen=True, slots=True)
class JetFeatureSchema:
    """Immutable named feature schema used by training and prediction."""

    name: str
    feature_names: tuple[str, ...]
    uses_total_operating_cnt: bool


JET_SCHEMAS: Final = (
    JetFeatureSchema("jet_compact_v1", _JET_COMPACT_FEATURES, False),
    JetFeatureSchema(
        "jet_drop_count_v1",
        tuple(name for name in _JET_COMPACT_FEATURES if name != "n_engines"),
        False,
    ),
    JetFeatureSchema(
        "jet_replace_count_v1",
        tuple(name for name in _JET_COMPACT_FEATURES if name != "n_engines")
        + (TOTAL_OPERATING_FEATURE,),
        True,
    ),
    JetFeatureSchema(
        "jet_add_total_operating_v1",
        _JET_COMPACT_FEATURES + (TOTAL_OPERATING_FEATURE,),
        True,
    ),
)
JET_CANDIDATE_SCHEMA_IDS: Final = tuple(schema.name for schema in JET_SCHEMAS)
_JET_SCHEMA_BY_NAME: Final = {schema.name: schema for schema in JET_SCHEMAS}


def _production_schema() -> JetFeatureSchema:
    return JET_SCHEMAS[0]


def resolve_jet_schema(schema_id: str) -> JetFeatureSchema:
    """Resolve a candidate or frozen production Jet schema by stable ID."""
    if schema_id == JET_V2_SCHEMA_ID:
        return _production_schema()
    try:
        return _JET_SCHEMA_BY_NAME[schema_id]
    except KeyError as exc:
        raise JetFeatureError(f"unknown Jet feature schema {schema_id!r}") from exc


def jet_feature_names(schema_id: str) -> tuple[str, ...]:
    """Return the ordered model inputs for a Jet schema."""
    return resolve_jet_schema(schema_id).feature_names


def validate_jet_power_parameter(power_parameter: str) -> None:
    """Reject Jet power axes that cannot support corrected-CNT features."""
    if power_parameter not in SUPPORTED_JET_POWER_PARAMETERS:
        raise JetFeatureError(
            f"unsupported Jet power parameter {power_parameter!r}; "
            "expected CNT (lb) or CNT (% of Max Static Thrust)"
        )


def build_jet_feature_matrix(
    base_features: Mapping[str, float],
    log_power_lb: np.ndarray,
    throttle: np.ndarray,
    schema_id: str,
) -> np.ndarray:
    """Build a finite-row feature matrix from unit-normalized Jet inputs."""
    schema = resolve_jet_schema(schema_id)
    log_power = np.atleast_1d(np.asarray(log_power_lb, dtype=float))
    throttle_values = np.atleast_1d(np.asarray(throttle, dtype=float))
    if log_power.shape != throttle_values.shape:
        raise JetFeatureError("Jet power and throttle arrays must have equal shape")
    if "n_engines" not in base_features or float(base_features["n_engines"]) <= 0:
        raise JetFeatureError("Jet engine count must be positive")

    values = {
        name: np.full(log_power.shape, float(base_features[name]))
        for name in _JET_STATIC_FEATURES
    }
    values["log_power_lb"] = log_power
    values["throttle"] = throttle_values
    if schema.uses_total_operating_cnt:
        values[TOTAL_OPERATING_FEATURE] = log_power + np.log10(
            float(base_features["n_engines"])
        )
    matrix = np.column_stack([values[name] for name in schema.feature_names])
    if not np.isfinite(matrix).all():
        raise JetFeatureError("Jet model features must be finite")
    return matrix
