from dataclasses import dataclass

import pandas as pd
import pytest

from pnmf.anp import ANPDatabase
from pnmf.verified_anp import (
    SOURCE_HASHES,
    TRAINABLE_NPD_IDS,
    VERIFIED_AIRCRAFT_REGISTRY,
    VerifiedANPIntegrityError,
    resolve_training_scope,
)


@dataclass(frozen=True, slots=True)
class _RegistryDatabase:
    aircraft: pd.DataFrame
    npd: pd.DataFrame


@pytest.fixture(scope="module")
def anp_database() -> ANPDatabase:
    return ANPDatabase()


def test_verified_scope_selects_exact_trainable_ids_for_all_tasks(
    anp_database: ANPDatabase,
) -> None:
    # Given: the canonical datastore with all verified v6.3 records.
    # When: resolving the constrained verified scope.
    resolution = resolve_training_scope(anp_database, "verified")
    # Then: exactly the 11 declared trainable NPD IDs support every task.
    assert resolution.selected_npd_ids == TRAINABLE_NPD_IDS
    assert len(resolution.support_counts) == 8
    assert set(resolution.support_counts.values()) == {11}


def test_registry_keeps_three_workbook_entries_metadata_only() -> None:
    # Given: the immutable workbook-derived registry.
    # When: inspecting its non-trainable entries.
    metadata_only = tuple(
        entry.family_key
        for entry in VERIFIED_AIRCRAFT_REGISTRY
        if entry.training_status == "verified_metadata_only"
    )
    # Then: only workbook entries without trainable ANP curves are excluded.
    assert metadata_only == ("A320-250N", "A330-941", "G650ER")


def test_verified_scope_rejects_missing_metric_mode_support(
    anp_database: ANPDatabase,
) -> None:
    # Given: a verified NPD ID with one required task removed.
    incomplete = anp_database.npd.loc[
        ~(
            (anp_database.npd["NPD_ID"] == "A320-270N")
            & (anp_database.npd["Noise Metric"] == "SEL")
            & (anp_database.npd["Op Mode"] == "D")
        )
    ].copy()
    db = _RegistryDatabase(anp_database.aircraft.copy(), incomplete)
    # When / Then: scope resolution fails closed instead of silently shrinking.
    with pytest.raises(VerifiedANPIntegrityError, match="SEL:D"):
        resolve_training_scope(db, "verified")


def test_verified_scope_rejects_unproven_aircraft_provenance(
    anp_database: ANPDatabase,
) -> None:
    # Given: an otherwise intact registry record labelled as legacy data.
    aircraft = anp_database.aircraft.copy()
    aircraft.loc[aircraft["ACFT_ID"] == "A320-270N", "source_dataset"] = "legacy_v2.3"
    db = _RegistryDatabase(aircraft, anp_database.npd.copy())
    # When / Then: the v6.3 provenance contract rejects the record.
    with pytest.raises(VerifiedANPIntegrityError, match="provenance"):
        resolve_training_scope(db, "verified")


def test_excluded_verified_id_is_removed_from_each_task_count(
    anp_database: ANPDatabase,
) -> None:
    # Given: the verified scope and one declared holdout.
    # When: resolving with that holdout excluded.
    resolution = resolve_training_scope(
        anp_database, "verified", exclude_ids=("FAL900EX",)
    )
    # Then: the holdout is absent and each remaining task has ten IDs.
    assert "FAL900EX" not in resolution.selected_npd_ids
    assert set(resolution.support_counts.values()) == {10}


def test_source_hashes_are_pinned_to_the_approved_inputs() -> None:
    # Given: the provenance contract constants.
    # When: reading their declared source hashes.
    # Then: they remain pinned to the approved workbook and v6.3 inputs.
    assert SOURCE_HASHES.verified_workbook == (
        "26221b57fb56fdd90aad6798d8c0d6d12f309660f9445ef60d1c1d7cb3977adf"
    )
    assert SOURCE_HASHES.v63_aircraft == (
        "ea730a0d2940537ab0ea5e817dfbc80037b299fe763e20d8200af391baee81b8"
    )
    assert SOURCE_HASHES.v63_npd == (
        "77984a355fce073fd98fbd7bd52a36332e7a9a10d504adee1353b41780b4d4b2"
    )
