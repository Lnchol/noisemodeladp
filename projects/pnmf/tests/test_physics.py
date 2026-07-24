"""Unit tests for the physics-based (pyNA-family) model layer."""
import numpy as np
import pytest

from pnmf.physics import (a_weighting, atmospheric_absorption, band_sum_dba,
                          THIRD_OCTAVE_HZ)
from pnmf.physics import EngineState, JetSource, AirframeSource
from pnmf.physics import PhysicsNPDModel, PhysicsDesign


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

    for metric in ("EPNL", "PNLTM"):
        with pytest.raises(ValueError, match="supports only SEL, LAmax"):
            model.predict_table(design, metric, "D", [20000])
