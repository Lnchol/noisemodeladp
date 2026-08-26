"""Immutable EASA verified-aircraft registry and fail-closed training scopes.

The registry describes workbook verification metadata; it does not alter ANP
truth rows or make PNMF output certification evidence.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, Protocol, TypeAlias

import pandas as pd  # noqa: PANDAS_OK - PNMF datastore contracts use pandas.

TrainingScope: TypeAlias = Literal["verified", "merged", "jet_merged"]
TrainingStatus: TypeAlias = Literal["trainable", "verified_metadata_only"]

EASA_ANP_SOURCE_URL: Final = (
    "https://www.easa.europa.eu/en/domains/environment/"
    "policy-support-and-research/aircraft-noise-and-performance-anp-data"
)
DEFAULT_METRICS: Final = ("SEL", "LAmax", "EPNL", "PNLTM")
DEFAULT_OP_MODES: Final = ("A", "D")
VERIFIED_REGISTRY_VERSION: Final = "easa-verified-14-family-v1"
REGISTRY_VERSION: Final = VERIFIED_REGISTRY_VERSION


@dataclass(frozen=True, slots=True)
class SourceHashes:
    verified_workbook: str
    v63_aircraft: str
    v63_npd: str


@dataclass(frozen=True, slots=True)
class VerifiedAircraftFamily:
    family_key: str
    npd_id: str
    engine_family: str
    variants: tuple[str, ...]
    engines: tuple[str, ...]
    verification_date: str
    training_status: TrainingStatus

    @property
    def official_source_url(self) -> str:
        return EASA_ANP_SOURCE_URL

    @property
    def source_url(self) -> str:
        return self.official_source_url

    @property
    def source_hashes(self) -> SourceHashes:
        return SOURCE_HASHES

    @property
    def source_hash(self) -> str:
        return SOURCE_HASHES.verified_workbook

    @property
    def expected_npd_identifier(self) -> str:
        return self.npd_id

    @property
    def expected_npd_id(self) -> str:
        return self.expected_npd_identifier

    @property
    def status(self) -> TrainingStatus:
        return self.training_status


@dataclass(frozen=True, slots=True)
class VerifiedANPIntegrityError(RuntimeError):
    scope: str
    issue: str

    def __str__(self) -> str:
        return f"verified ANP {self.scope} scope integrity error: {self.issue}"


@dataclass(frozen=True, slots=True)
class TrainingScopeResolution:
    scope: TrainingScope
    selected_npd_ids: tuple[str, ...]
    unavailable_registry_entries: tuple[str, ...]
    registry_version: str
    source_hashes: SourceHashes
    support_counts: Mapping[str, int]


class ANPTrainingData(Protocol):
    aircraft: pd.DataFrame
    npd: pd.DataFrame


SOURCE_HASHES: Final = SourceHashes(
    verified_workbook="26221b57fb56fdd90aad6798d8c0d6d12f309660f9445ef60d1c1d7cb3977adf",
    v63_aircraft="ea730a0d2940537ab0ea5e817dfbc80037b299fe763e20d8200af391baee81b8",
    v63_npd="77984a355fce073fd98fbd7bd52a36332e7a9a10d504adee1353b41780b4d4b2",
)

VERIFIED_AIRCRAFT_REGISTRY: Final = (
    VerifiedAircraftFamily("A320-270N", "A320-270N", "PW1100G-JM", ("A320-271N", "A320-272N", "A320-273N"), ("PW1127G-JM", "PW1124G-JM", "PW1129G-JM"), "2020-09-23", "trainable"),
    VerifiedAircraftFamily("A320-250N", "A320-250N", "LEAP-1A20", ("A320-251N", "A320-252N", "A320-253N"), ("LEAP-1A24", "LEAP-1A26", "LEAP-1A27"), "2025-12-12", "verified_metadata_only"),
    VerifiedAircraftFamily("A321-270N", "A321-270N", "PW1100G-JM", ("A321-271N", "A321-272N"), ("PW1133G-JM", "PW1130G-JM"), "2021-05-04", "trainable"),
    VerifiedAircraftFamily("A330-941", "A330-941", "Trent 7000", ("A330-941",), ("Trent 7000-72",), "2024-12-18", "verified_metadata_only"),
    VerifiedAircraftFamily("A330-743L", "A330-743L", "Trent 772B", ("A330-743L",), ("Trent 772B-60",), "2021-12-21", "trainable"),
    VerifiedAircraftFamily("A350-1041", "A350-1041", "Trent XWB-97", ("A350-1041",), ("Trent XWB-97",), "2022-08-17", "trainable"),
    VerifiedAircraftFamily("747400RN", "747400RN", "PW4062A", ("747-400F",), ("PW4062A",), "2022-06-03", "trainable"),
    VerifiedAircraftFamily("7673ER", "7673ER", "CF6-80C2B6F", ("767-300", "767-300F"), ("CF6-80C2B6F",), "2020-07-30", "trainable"),
    VerifiedAircraftFamily("7879", "7879", "GEnx-1B76A", ("787-9",), ("GEnx-1B76A",), "2022-06-03", "trainable"),
    VerifiedAircraftFamily("7773ER", "7773ER", "GE90-115B", ("777-300ER",), ("GE90-115B",), "2021-05-04", "trainable"),
    VerifiedAircraftFamily("ERJ190-300", "ERJ190-300", "PW1900G", ("ERJ 190-300",), ("PW1919G", "PW1922G"), "2022-08-17", "trainable"),
    VerifiedAircraftFamily("ERJ190-400", "ERJ190-400", "PW1900G", ("ERJ 190-400",), ("PW1921G", "PW1923G", "PW1923G-A"), "2022-08-17", "trainable"),
    VerifiedAircraftFamily("FAL900EX", "FAL900EX", "TFE731-60", ("Falcon 900EX", "Falcon 900LX"), ("TFE731-60(-1C)",), "2021-12-21", "trainable"),
    VerifiedAircraftFamily("G650ER", "G650ER", "BR-700-725A1-12", ("GVI",), ("BR-700-725A1-12",), "2024-04-01", "verified_metadata_only"),
)

TRAINABLE_NPD_IDS: Final = tuple(
    entry.npd_id
    for entry in VERIFIED_AIRCRAFT_REGISTRY
    if entry.training_status == "trainable"
)
METADATA_ONLY_FAMILY_KEYS: Final = tuple(
    entry.family_key
    for entry in VERIFIED_AIRCRAFT_REGISTRY
    if entry.training_status == "verified_metadata_only"
)


def resolve_training_scope(
    db: ANPTrainingData,
    scope: TrainingScope,
    *,
    metrics: Sequence[str] = DEFAULT_METRICS,
    op_modes: Sequence[str] = DEFAULT_OP_MODES,
    exclude_ids: Collection[str] = (),
) -> TrainingScopeResolution:
    """Resolve a complete, provenance-checked NPD ID set for model fitting."""
    metric_values = _normalise_dimension(metrics, "metrics", scope)
    op_mode_values = _normalise_dimension(op_modes, "op_modes", scope)
    _require_columns(db, scope)
    match scope:
        case "verified":
            _check_verified_provenance(db, scope)
            selected = tuple(
                npd_id for npd_id in TRAINABLE_NPD_IDS if npd_id not in exclude_ids
            )
        case "merged":
            selected = tuple(
                sorted(
                    set(db.npd["NPD_ID"].dropna().astype(str)) - set(exclude_ids)
                )
            )
        case "jet_merged":
            jet_ids = set(
                db.aircraft.loc[
                    db.aircraft["Engine Type"] == "Jet", "NPD_ID"
                ]
                .dropna()
                .astype(str)
            )
            selected = tuple(sorted(jet_ids - set(exclude_ids)))
        case invalid:
            raise VerifiedANPIntegrityError(str(invalid), "unknown training scope")
    if not selected:
        raise VerifiedANPIntegrityError(scope, "selection is empty after exclusions")
    support_counts = _check_task_completeness(
        db, scope, selected, metric_values, op_mode_values
    )
    return TrainingScopeResolution(
        scope=scope,
        selected_npd_ids=selected,
        unavailable_registry_entries=METADATA_ONLY_FAMILY_KEYS,
        registry_version=REGISTRY_VERSION,
        source_hashes=SOURCE_HASHES,
        support_counts=MappingProxyType(support_counts),
    )


def _normalise_dimension(
    values: Sequence[str], name: str, scope: str
) -> tuple[str, ...]:
    normalised = tuple(dict.fromkeys(str(value) for value in values))
    if not normalised:
        raise VerifiedANPIntegrityError(scope, f"{name} cannot be empty")
    return normalised


def _require_columns(db: ANPTrainingData, scope: str) -> None:
    aircraft_required = {"ACFT_ID", "NPD_ID", "source_dataset"}
    npd_required = {"NPD_ID", "Noise Metric", "Op Mode", "source_dataset"}
    missing_aircraft = sorted(aircraft_required - set(db.aircraft.columns))
    missing_npd = sorted(npd_required - set(db.npd.columns))
    if missing_aircraft or missing_npd:
        raise VerifiedANPIntegrityError(
            scope,
            f"provenance columns missing: aircraft={missing_aircraft}, npd={missing_npd}",
        )


def _check_verified_provenance(db: ANPTrainingData, scope: str) -> None:
    for entry in VERIFIED_AIRCRAFT_REGISTRY:
        match entry.training_status:
            case "trainable":
                aircraft_rows = db.aircraft.loc[
                    (db.aircraft["ACFT_ID"] == entry.family_key)
                    & (db.aircraft["NPD_ID"] == entry.npd_id)
                ]
                npd_rows = db.npd.loc[db.npd["NPD_ID"] == entry.npd_id]
                aircraft_sources = set(aircraft_rows["source_dataset"].dropna())
                npd_sources = set(npd_rows["source_dataset"].dropna())
                if aircraft_sources != {"supplement_v6.3"}:
                    raise VerifiedANPIntegrityError(
                        scope,
                        f"aircraft provenance for {entry.family_key} is {sorted(aircraft_sources)}",
                    )
                if npd_sources != {"supplement_v6.3"}:
                    raise VerifiedANPIntegrityError(
                        scope,
                        f"NPD provenance for {entry.npd_id} is {sorted(npd_sources)}",
                    )
            case "verified_metadata_only":
                continue
            case unreachable:
                raise VerifiedANPIntegrityError(scope, f"unknown registry status {unreachable}")


def _check_task_completeness(
    db: ANPTrainingData,
    scope: str,
    selected: tuple[str, ...],
    metrics: tuple[str, ...],
    op_modes: tuple[str, ...],
) -> dict[str, int]:
    support_counts: dict[str, int] = {}
    for metric in metrics:
        for op_mode in op_modes:
            task_key = f"{metric}:{op_mode}"
            available = set(
                db.npd.loc[
                    (db.npd["Noise Metric"] == metric)
                    & (db.npd["Op Mode"] == op_mode),
                    "NPD_ID",
                ]
                .dropna()
                .astype(str)
            )
            missing = tuple(npd_id for npd_id in selected if npd_id not in available)
            if missing:
                raise VerifiedANPIntegrityError(
                    scope, f"{task_key} lacks selected IDs {', '.join(missing)}"
                )
            support_counts[task_key] = len(selected)
    return support_counts
