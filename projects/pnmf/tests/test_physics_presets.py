"""Source and corpus checks for component-physics aircraft presets."""
import pytest

from pnmf.anp import ANPDatabase
from pnmf.physics_presets import PHYSICS_PRESETS


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
