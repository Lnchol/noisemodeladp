"""Frozen production decision produced by the completed Jet feature gate."""

from __future__ import annotations

from typing import Final

from .verified_anp import TrainingScope

JET_V2_SELECTED_CANDIDATE: Final = "jet_compact_v1"
JET_V2_VALIDATION_REPORT_SHA256: Final = (
    "e45c8d9db915222477b1072cd0cc9ff58f1b9b1422e642ece126d3ae4a38e190"
)
JET_MERGED_PROMOTED: Final = True


def jet_merged_is_promoted() -> bool:
    """Return the audited production-scope decision without rerouting data."""
    return JET_MERGED_PROMOTED


def production_training_scope() -> TrainingScope:
    return "jet_merged"


def available_training_scopes() -> tuple[TrainingScope, ...]:
    return ("jet_merged",)
