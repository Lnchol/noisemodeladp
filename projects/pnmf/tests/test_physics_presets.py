"""Source and corpus checks for component-physics aircraft presets."""
import pytest

from pnmf.anp import ANPDatabase
from pnmf.physics_presets import PHYSICS_PRESETS


_TRAINABLE_PRESET_KEYS = {
    "A320-270N",
    "A321-270N",
    "A330-743L",
    "A350-1041",
    "747400RN",
    "7673ER",
    "7879",
    "7773ER",
    "ERJ190-300",
    "ERJ190-400",
    "FAL900EX",
}

_INPUT_FIELDS = {
    "n_engines",
    "max_thrust_lbf",
    "mtow_lb",
    "mlw_lb",
    "noise_chapter",
    "bpr",
    "wing_span_m",
    "fan_diameter_m",
    "fan_blades",
    "nose_wheel_count",
    "main_wheel_count",
    "nose_wheel_diameter_m",
    "main_wheel_diameter_m",
}


def test_trainable_physics_presets_match_verified_registry_keys() -> None:
    # Given: the physics preset registry.
    # When: its keys are compared with the approved trainable scope.
    # Then: all and only the eleven verified aircraft are available.
    assert set(PHYSICS_PRESETS) == _TRAINABLE_PRESET_KEYS
    assert PHYSICS_PRESETS["A320-270N"].label.endswith("PW1100G-JM")


@pytest.mark.parametrize("preset", PHYSICS_PRESETS.values(), ids=PHYSICS_PRESETS)
def test_preset_provenance_labels_every_input_and_missing_component_decks(preset) -> None:
    # Given: a trainable aircraft's component-physics defaults.
    # When: its provenance records are indexed by field.
    # Then: every input is labelled and unsupported component decks stay explicit.
    provenance = {record.field: record for record in preset.provenance}
    assert _INPUT_FIELDS <= set(provenance)
    assert {record.status for record in provenance.values()} == {
        "supplied",
        "estimated",
        "unavailable",
    }
    assert provenance["engine_component_deck"].status == "unavailable"
    assert provenance["high_lift_geometry"].status == "unavailable"
    supplied_fields = {
        record.field for record in provenance.values() if record.status == "supplied"
    }
    source_fields = {field for source in preset.sources for field in source.fields}
    assert supplied_fields <= source_fields


def test_physics_presets_are_present_in_local_v63_corpus():
    params = ANPDatabase(".").param_table()
    v63_ids = set(params.loc[
        params["source_dataset"] == "supplement_v6.3", "ACFT_ID"])

    assert {preset.anp_id for preset in PHYSICS_PRESETS.values()} <= v63_ids


@pytest.mark.parametrize("preset", PHYSICS_PRESETS.values(),
                         ids=PHYSICS_PRESETS)
def test_physics_presets_have_sane_values_and_first_party_sources(preset):
    assert preset.n_engines > 0
    assert preset.max_thrust_lbf > 0
    assert preset.mtow_lb > preset.mlw_lb > 0
    assert preset.bpr > 0
    assert preset.wing_span_m > 0
    assert preset.fan_diameter_m > 0
    assert preset.fan_blades > 0
    assert preset.nose_wheel_count > 0
    assert preset.main_wheel_count > 0
    assert preset.sources
    assert all(source.url.startswith("https://")
               for source in preset.sources)
    assert all(source.fields for source in preset.sources)


def test_wing_area_is_an_explicit_aspect_ratio_estimate():
    for preset in PHYSICS_PRESETS.values():
        assert preset.estimated_wing_area_m2 == pytest.approx(
            preset.wing_span_m ** 2 / 9.0)
