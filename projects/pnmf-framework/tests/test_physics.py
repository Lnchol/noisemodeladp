"""Unit tests for the physics-based (pyNA-family) model layer."""
import numpy as np
import pytest

from pnmf.physics import (a_weighting, atmospheric_absorption, band_sum_dba,
                          THIRD_OCTAVE_HZ)
from pnmf.physics import EngineState, JetSource, AirframeSource
from pnmf.physics import PhysicsNPDModel, PhysicsDesign
from pnmf.physics import (AirframeGeometry, AirframePhysicalInputs,
                          AtmosphericPhysicalInputs, CoreStream,
                          EnginePhysicalInputs, FanDeck, FanSource,
                          FlightTrajectoryInputs, JetStream, PhysicalInput,
                          Reference160KtFlightPath)


def test_a_weighting_reference_points():
    assert abs(a_weighting(np.array([1000.0]))[0]) < 0.02       # 0 dB @ 1 kHz
    assert a_weighting(np.array([100.0]))[0] < -15.0            # LF suppressed
    assert -2.0 < a_weighting(np.array([4000.0]))[0] < 2.0


def test_absorption_monotone_in_frequency():
    a = atmospheric_absorption()
    assert (np.diff(a) > 0).all()                # rises with f
    assert a[-1] * 304.8 > 5.0                   # 10 kHz over 1000 ft: strong
    assert a[0] * 304.8 < 0.2                    # 50 Hz: negligible


def test_jet_v8_scaling():
    """Doubling jet velocity at fixed area: +80log10(2) = 24.1 dB from the
    V^8 law PLUS an A-weighted gain because the Strouhal peak doubles too
    (44 -> 88 Hz here, escaping the A-weighting's LF suppression). The
    coupled effect lands between the pure V^8 delta and ~ +32 dB."""
    js = JetSource(140.0, f_scale=1.0)
    st1 = EngineState(1, 200.0, 100.0, 1.0, 1.13, 1.0, 2000.0)
    st2 = EngineState(1, 400.0, 100.0, 1.0, 1.13, 1.0, 2000.0)
    l1 = band_sum_dba(js.band_spl_1m(st1, 90.0))
    l2 = band_sum_dba(js.band_spl_1m(st2, 90.0))
    assert 23.0 < (l2 - l1) < 32.0


def test_gear_dominates_v6_growth():
    af = AirframeSource(100.0, 100.0)
    cfg = dict(wing_area_m2=120, span_m=33, flap_deg=0.0, gear_down=True,
               slats_out=False, n_wheels=8, wheel_d_m=1.1)
    l1 = band_sum_dba(af.band_spl_1m(60.0, cfg, 90.0))
    l2 = band_sum_dba(af.band_spl_1m(120.0, cfg, 90.0))
    assert 14.0 < (l2 - l1) < 21.0               # between V^5 and V^6 growth


def test_flyover_duration_effect():
    """SEL must decay ~10 dB/decade slower than LAmax (exposure duration
    grows linearly with distance for a level flyover)."""
    m = PhysicsNPDModel()
    d = PhysicsDesign("T", 2, 25000, 6.0, 150000)
    la1, se1 = m.single_event(d, 20000, 'D', 1000)
    la2, se2 = m.single_event(d, 20000, 'D', 10000)
    dla, dse = la1 - la2, se1 - se2
    assert 7.0 < (dla - dse) < 12.0


def test_higher_bpr_is_quieter_on_departure():
    m = PhysicsNPDModel()
    lo = PhysicsDesign("lo", 2, 27000, 3.0, 160000)
    hi = PhysicsDesign("hi", 2, 27000, 12.0, 160000)
    _, s_lo = m.single_event(lo, 24000, 'D', 1000)
    _, s_hi = m.single_event(hi, 24000, 'D', 1000)
    assert s_lo - s_hi > 3.0


def test_gear_adds_noise_on_approach():
    m = PhysicsNPDModel(c_wingflap=139.0, c_gear=134.0)
    d = PhysicsDesign("T", 2, 27000, 6.0, 160000)
    la_dn, _ = m.single_event(d, 4000, 'A', 1000)
    d2 = PhysicsDesign("T", 2, 27000, 6.0, 160000)
    d2.config = lambda op_mode: dict(wing_area_m2=d.wing_area_m2, span_m=d.span_m,
                                     flap_area_m2=.17*d.wing_area_m2, flap_deg=30.,
                                     gear_down=False, slats_out=True,
                                     n_wheels=d.n_wheels, wheel_d_m=d.wheel_d_m)
    la_up, _ = m.single_event(d2, 4000, 'A', 1000)
    assert la_dn > la_up


def test_physics_table_metric_contract():
    model = PhysicsNPDModel()
    design = PhysicsDesign("T", 2, 25000, 6.0, 150000)

    for metric in ("SEL", "LAmax"):
        table = model.predict_table(design, metric, "D", [20000])
        assert table.metric == metric
        assert table.L.shape == (1, 10)
        assert (np.diff(table.L, axis=1) <= 0).all()

    for metric in ("EPNL", "PNLTM"):
        with pytest.raises(ValueError, match="supports only SEL, LAmax"):
            model.predict_table(design, metric, "D", [20000])


def test_physical_input_and_legacy_design_provenance():
    supplied = PhysicalInput(6.0, "supplied", "engine deck")
    missing = PhysicalInput(None, "unavailable")
    assert supplied.available
    assert not missing.available

    design = PhysicsDesign("T", 2, 25000, 6.0, 150000)
    assert design.input_status["thrust"].source == "supplied"
    assert design.input_status["wing_area_m2"].source == "estimated"
    assert design.input_status["jet_streams"].source == "unavailable"


def _engine_inputs(nozzle_velocity=360.0):
    supplied = lambda value: PhysicalInput(value, "supplied")
    unavailable = PhysicalInput(None, "unavailable")
    return EnginePhysicalInputs(
        thrust_n=supplied(90000), bypass_ratio=supplied(6.2),
        mass_flow_kg_s=supplied(320),
        nozzle_exit_area_m2=supplied(1.8),
        nozzle_exit_velocity_ms=supplied(nozzle_velocity),
        nozzle_exit_temperature_k=supplied(470),
        nozzle_exit_pressure_pa=supplied(175000),
        fan_diameter_m=supplied(1.8), rpm=supplied(4000),
        n1_percent=supplied(92), blade_count=supplied(24),
        stator_count=supplied(38), rotor_stator_spacing_m=supplied(.11),
        fan_temperature_rise_k=supplied(45),
        core_mass_flow_kg_s=unavailable,
        combustor_inlet_temperature_k=unavailable,
        combustor_exit_temperature_k=unavailable,
        turbine_attenuation_db=unavailable)


def test_typed_engine_inputs_feed_sources_and_diagnostics():
    typed = PhysicsDesign(
        "typed", 2, 25000, 6.0, 150000,
        engine_physical_inputs=_engine_inputs())
    legacy = PhysicsDesign("legacy", 2, 25000, 6.0, 150000)
    model = PhysicsNPDModel()
    typed_result = model.single_event_diagnostics(typed, 20000, "D", 1000)
    legacy_result = model.single_event_diagnostics(legacy, 20000, "D", 1000)
    assert typed_result.lamax_db != pytest.approx(legacy_result.lamax_db)
    assert typed_result.source_status["jet"].source == "supplied"
    assert typed_result.source_status["fan"].source == "supplied"
    assert {"fan_inlet", "fan_discharge"}.issubset(
        typed_result.component_time_histories_db)
    assert typed_result.input_status["nozzle_exit_velocity_ms"].source == "supplied"


def test_typed_airframe_and_atmosphere_inputs_are_consumed():
    supplied = lambda value: PhysicalInput(value, "supplied")
    airframe = AirframePhysicalInputs(
        wing_area_m2=supplied(130), wing_span_m=supplied(36),
        flap_area_m2=supplied(24), flap_chord_m=supplied(1.7),
        flap_deflection_deg=supplied(35), slat_area_m2=supplied(12),
        slat_chord_m=supplied(.55), slat_deflection_deg=supplied(20),
        nose_wheel_count=supplied(2), nose_wheel_diameter_m=supplied(.75),
        nose_strut_diameter_m=supplied(.09), main_wheel_count=supplied(8),
        main_wheel_diameter_m=supplied(1.15),
        main_strut_diameter_m=supplied(.16), gear_down=supplied(True))
    atmosphere = AtmosphericPhysicalInputs(
        supplied(30), supplied(35), supplied(95))
    design = PhysicsDesign(
        "typed", 2, 25000, 6, 150000,
        airframe_physical_inputs=airframe,
        atmospheric_inputs=atmosphere)
    assert design.config("A")["nose_wheel_d_m"] == .75
    model = PhysicsNPDModel()
    typed = model.single_event_diagnostics(design, 4000, "A", 10000)
    reference = model.single_event_diagnostics(
        PhysicsDesign("ref", 2, 25000, 6, 150000),
        4000, "A", 10000)
    assert typed.sel_db != pytest.approx(reference.sel_db)
    assert typed.input_status["temperature_c"].source == "supplied"


def test_stone_multistream_gate_and_virtual_sources():
    source = JetSource(140.0)
    legacy = EngineState.from_design(80000, 100000, 6.0)
    pieces, status = source.component_spectra_with_diagnostics(legacy, 120.0)
    assert pieces == {}
    assert status.source == "estimated"
    assert "required" in status.note

    streams = (
        JetStream(290, 250, 1.5, 340, 160000, "outer"),
        JetStream(430, 70, .75, 700, 240000, "inner"),
        JetStream(330, 320, 1.7, 430, 175000, "merged"),
    )
    detailed = EngineState.from_design(
        80000, 100000, 6.0, jet_streams=streams)
    pieces, status = source.component_spectra_with_diagnostics(
        detailed, 120.0)
    assert set(pieces) == {"jet_outer", "jet_inner", "jet_merged"}
    assert all(v.shape == THIRD_OCTAVE_HZ.shape for v in pieces.values())
    assert status.source == "supplied" and status.complete


def test_heidmann_engine_deck_gate_harmonics_and_lobes():
    source = FanSource(55.0)
    legacy = EngineState.from_design(80000, 100000, 6.0)
    pieces, status = source.component_spectra_with_diagnostics(legacy, 60.0)
    assert pieces == {}
    assert status.source == "estimated"

    deck = FanDeck(310, 380, 24, 1.8, 45, rpm=4032,
                   stator_count=38, rotor_stator_spacing_m=.11)
    detailed = EngineState.from_design(
        80000, 100000, 6.0, fan_deck=deck)
    forward, status = source.component_spectra_with_diagnostics(
        detailed, 30.0)
    aft, _ = source.component_spectra_with_diagnostics(detailed, 150.0)
    assert set(forward) == {"fan_inlet", "fan_discharge"}
    assert band_sum_dba(forward["fan_inlet"]) > band_sum_dba(
        forward["fan_discharge"])
    assert band_sum_dba(aft["fan_discharge"]) > band_sum_dba(
        aft["fan_inlet"])
    assert status.source == "supplied" and "harmonics" in status.note


def test_airframe_six_component_decomposition():
    source = AirframeSource(100.0, 100.0)
    config = {
        "wing_area_m2": 120, "span_m": 33, "flap_area_m2": 20,
        "flap_deg": 30, "gear_down": True, "slats_out": True,
        "n_wheels": 10, "wheel_d_m": 1.1,
    }
    spectra = source.component_spectra_1m(80.0, config, 90.0)
    assert set(spectra) == {
        "wing_trailing_edge", "slat", "flap_main_edge", "flap_side_edge",
        "nose_landing_gear", "main_landing_gear",
    }
    total = source.band_spl_1m(80.0, config, 90.0)
    expected = 10 * np.log10(np.sum(
        10 ** (np.stack(list(spectra.values())) / 10), axis=0))
    assert np.allclose(total, expected)


def test_event_diagnostics_preserve_time_history_and_energy():
    model = PhysicsNPDModel()
    design = PhysicsDesign(
        "T", 2, 25000, 6.0, 150000,
        airframe_geometry=AirframeGeometry(
            wing_area_m2=115, span_m=34, flap_area_m2=20,
            flap_deg=30, slats_out=True, gear_down=True,
            wheel_diameter_m=1.05, nose_wheel_count=2,
            main_wheel_count=8))
    result = model.single_event_diagnostics(design, 4000, "A", 1000)
    assert len(result.time_s) == len(result.total_time_history_db) == 69
    assert np.all(np.diff(result.time_s) > 0)
    assert {"wing_trailing_edge", "slat", "flap_main_edge",
            "flap_side_edge", "nose_landing_gear",
            "main_landing_gear"}.issubset(result.component_metrics_db)
    stack = np.stack(list(result.component_time_histories_db.values()))
    energetic = 10 * np.log10(np.sum(10 ** (stack / 10), axis=0))
    assert np.allclose(energetic, result.total_time_history_db)
    assert result.source_status["jet"].source == "estimated"
    assert "ground_reflection" in result.excluded_effects


def test_optional_core_is_absent_without_complete_inputs():
    result = PhysicsNPDModel().single_event_diagnostics(
        PhysicsDesign("T", 2, 25000, 6.0, 150000), 4000, "A", 1000)
    assert "core_combustor" not in result.component_time_histories_db
    assert result.source_status["core_combustor"].source == "unavailable"


def test_incomplete_core_has_consistent_unavailable_status():
    core = CoreStream(
        310, 45, .55, 780, combustor_exit_temperature_k=1350,
        total_pressure_pa=260000)
    result = PhysicsNPDModel().single_event_diagnostics(
        PhysicsDesign("T", 2, 25000, 6.0, 150000, core_stream=core),
        4000, "A", 1000)
    assert result.input_status["core_combustor"].source == "unavailable"
    assert result.source_status["core_combustor"].source == "unavailable"


def test_optional_core_enables_only_with_complete_state():
    core = CoreStream(
        310, 45, .55, 780, combustor_exit_temperature_k=1350,
        total_pressure_pa=260000, turbine_attenuation_db=18)
    result = PhysicsNPDModel().single_event_diagnostics(
        PhysicsDesign("T", 2, 25000, 6.0, 150000, core_stream=core),
        4000, "A", 1000)
    assert "core_combustor" in result.component_time_histories_db
    assert result.source_status["core_combustor"].source == "supplied"


def test_reference_flight_path_state_contract():
    state = Reference160KtFlightPath().state(
        x_m=0.0, closest_distance_m=304.8,
        thrust_per_engine_n=80000, configuration={"gear_down": True})
    assert state.emission_angle_deg == pytest.approx(90.0)
    assert state.altitude_m == pytest.approx(304.8)
    assert state.true_airspeed_ms == pytest.approx(160 * 0.514444)
    assert state.position_m == (0.0, 0.0, 304.8)
    assert state.mach == pytest.approx(state.true_airspeed_ms / 340.29)
    assert state.thrust_per_engine_n == 80000
    assert state.configuration["gear_down"]


def test_typed_trajectory_converts_to_instantaneous_state():
    supplied = lambda value: PhysicalInput(value, "supplied")
    inputs = FlightTrajectoryInputs(
        position_m=supplied((100.0, 0.0, 800.0)),
        true_airspeed_ms=supplied(95.0), mach=supplied(.28),
        altitude_m=supplied(800.0), attitude_deg=supplied((4.0, 0.0, 2.0)),
        thrust_per_engine_n=supplied(70000.0),
        configuration=supplied({"flap_deg": 10.0}))
    state = inputs.to_flight_state(time_s=2.0, emission_angle_deg=100.0)
    assert state.position_m == (100.0, 0.0, 800.0)
    assert state.mach == .28
    assert state.configuration["flap_deg"] == 10.0
