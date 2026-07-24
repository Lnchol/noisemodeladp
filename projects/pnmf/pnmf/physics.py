"""Acoustics foundation for the physics-based (pyNA-family) noise model.

Provides the three ingredients every component source shares:
  1. The 24 standard 1/3-octave bands, 50 Hz - 10 kHz (deliberately identical
     to the ANP spectral-class bands so outputs are directly comparable).
  2. A-weighting per IEC 61672 (exact analytic form; A(1 kHz) = 0 dB).
  3. Atmospheric absorption alpha(f) per ISO 9613-1 (the physics behind
     SAE ARP 866A), evaluated at ANP reference conditions 15 degC / 70% RH.

Propagation model used throughout: free field spherical spreading
(-20 log10 r) + molecular absorption (-alpha(f) * r). Ground effects, lateral
attenuation and engine installation are deliberately excluded - in the
NPD/Doc-29 world those are applied by the CONSUMER tool (SAE-AIR-5662 etc.),
and NPD tables themselves are defined for this idealised geometry.
"""
from __future__ import annotations
from typing import Literal, overload
import numpy as np

# 1/3-octave band CENTRE frequencies [Hz] - same 24 bands as the ANP
# spectral classes (50 Hz ... 10 kHz).
THIRD_OCTAVE_HZ = np.array([50, 63, 80, 100, 125, 160, 200, 250, 315, 400,
                            500, 630, 800, 1000, 1250, 1600, 2000, 2500,
                            3150, 4000, 5000, 6300, 8000, 10000], dtype=float)

RHO0 = 1.225          # ISA sea-level density [kg/m^3]
C0 = 340.29           # ISA sea-level speed of sound [m/s]
P_REF = 2.0e-5        # acoustic reference pressure [Pa]
KT2MS = 0.514444


def a_weighting(f=THIRD_OCTAVE_HZ):
    """A-weighting in dB per IEC 61672. Zero at 1 kHz by construction."""
    f = np.asarray(f, float)
    f2 = f ** 2
    ra = (12194.0**2 * f2**2) / ((f2 + 20.6**2) *
                                 np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) *
                                 (f2 + 12194.0**2))
    return 20.0 * np.log10(ra) + 2.00


def atmospheric_absorption(f=THIRD_OCTAVE_HZ, temp_c=15.0, rel_hum=70.0,
                           pressure_kpa=101.325):
    """Absorption coefficient alpha [dB/m] per ISO 9613-1.

    Defaults are the ANP/Doc-29 reference atmosphere (15 degC, 70 % RH).
    """
    f = np.asarray(f, float)
    T = temp_c + 273.15
    T0 = 293.15                      # ISO reference temperature [K]
    T01 = 273.16                     # triple point [K]
    p = pressure_kpa
    p0 = 101.325
    # molar concentration of water vapour [%]
    psat_over_p0 = 10.0 ** (-6.8346 * (T01 / T) ** 1.261 + 4.6151)
    h = rel_hum * psat_over_p0 * (p0 / p)
    # relaxation frequencies of O2 and N2 [Hz]
    fr_o = (p / p0) * (24.0 + 4.04e4 * h * (0.02 + h) / (0.391 + h))
    fr_n = (p / p0) * (T / T0) ** (-0.5) * (
        9.0 + 280.0 * h * np.exp(-4.170 * ((T / T0) ** (-1.0 / 3.0) - 1.0)))
    alpha = 8.686 * f**2 * (
        1.84e-11 * (p0 / p) * (T / T0) ** 0.5 +
        (T / T0) ** (-2.5) * (
            0.01275 * np.exp(-2239.1 / T) / (fr_o + f**2 / fr_o) +
            0.1068 * np.exp(-3352.0 / T) / (fr_n + f**2 / fr_n)))
    return alpha                     # [dB/m]


def band_sum_dba(band_spl, f=THIRD_OCTAVE_HZ):
    """Energetic sum of 1/3-octave band SPLs into one A-weighted level."""
    la = np.asarray(band_spl, float) + a_weighting(f)
    return 10.0 * np.log10(np.sum(10.0 ** (la / 10.0), axis=-1))


def propagate(band_spl_1m, r_m, alpha=None):
    """Free-field propagation from the 1 m reference to distance r [m]:
    spherical spreading + atmospheric absorption per band."""
    if alpha is None:
        alpha = atmospheric_absorption()
    return band_spl_1m - 20.0 * np.log10(r_m) - alpha * r_m


# ===========================================================================
# section: components (merged)
# ===========================================================================

"""Component noise sources - the pyNA/ANOPP model family, implemented natively.

Every conceptual-design noise tool (NASA ANOPP, DLR PANAM, Chalmers CHOICE,
MIT pyNA) is built from the same semi-empirical component set; this module
implements their published SCALING LAWS with free additive anchor constants:

  Jet mixing  (Stone / Lighthill) : intensity ~ rho_j^2 A_j V_j^8, peak
                                    Strouhal ~ 0.25, aft-dominant directivity
  Fan         (Heidmann form)     : level ~ 10log10(mdot) + 20log10(dTt),
                                    dTt ~ U_tip^2 (Euler work), haystack
                                    spectrum around the blade-passing
                                    frequency + BPF tone, two-lobe directivity
  Airframe    (Fink FAA-RD-77-29) : clean wing/slat trailing edge ~ V^5 *
                                    delta*(Re) * span; flaps ~ V^5 * S_f *
                                    sin^2(deflection); landing gear ~ V^6 *
                                    n_wheels * d^2, dipole directivity

Design philosophy (state this in the thesis): the EXPONENTS and spectral/
directivity shapes come from the literature and give correct sensitivities to
design changes; the four additive constants (C_jet, C_fan, C_wingflap,
C_gear) are calibrated ONCE against a single reference aircraft's ANP NPD
curves, then held fixed for every other aircraft and every future design.
This "anchored scaling-law" approach is standard conceptual-design practice
(same family as DLR's certified-EPNL correlations) and keeps the model honest:
absolute constants we could not re-verify from the primary reports are never
silently trusted - they are fitted and reported.

Engine-cycle state from (thrust setting, design): a deliberately simple,
documented mapping - see EngineState. All engine sources scale with the
per-engine corrected net thrust that the NPD power axis uses.
"""
from dataclasses import dataclass
import numpy as np


F_BANDS = THIRD_OCTAVE_HZ


def _interp_dir(theta_deg, table_theta, table_db):
    return np.interp(theta_deg, table_theta, table_db)


def _haystack(f, f_peak, width=2.0, floor=-40.0):
    """Smooth spectral hump: 0 dB at f_peak, parabolic in log2(f/f_peak)."""
    x = np.log2(np.maximum(f, 1.0) / max(f_peak, 1.0))
    return np.maximum(-width * x**2, floor)


# ---------------------------------------------------------------------------
# Engine cycle state
# ---------------------------------------------------------------------------
@dataclass
class EngineState:
    """Per-engine gas-path state at a given thrust setting.

    Derivation (documented approximations, all overridable):
      v_jet_max  = 700 / (1+BPR)^0.44  [m/s]   mixed-jet velocity anchored on
                   JT8D (BPR 1.7, ~450 m/s) and CFM56 (BPR 6, ~296 m/s);
                   reproduces GE90 (BPR 8.4) ~ 260 m/s.
      fixed nozzle: F = mdot*v_j and mdot ~ v_j  =>  v_j = v_max*sqrt(F/Fmax)
      mdot       = F / v_j
      A_jet      = mdot / (rho_j v_j),  rho_j ~ 0.64 rho0 (Tj ~ 450 K mixed)
      M_tip_max  = 1.6 / (1+BPR)^0.15   (1.38 @ BPR1.7, 1.20 @ BPR6,
                   1.13 @ BPR9.6, 1.06 @ BPR15)
      M_tip      = M_tip_max * (F/Fmax)^0.45   (N1-thrust lapse)
      BPF        = M_tip*c0/(pi*D_fan) * n_blades   (blade passing frequency)
      D_fan      : from mdot_max at a Mach-0.45 fan face unless given.
    """
    thrust_n: float
    v_jet: float
    mdot: float
    a_jet: float
    d_jet: float
    m_tip: float
    bpf_hz: float

    @classmethod
    def from_design(cls, thrust_per_engine_n, max_thrust_per_engine_n,
                    bpr, fan_diameter_m=None, n_blades=24):
        F = max(float(thrust_per_engine_n), 1.0)
        Fmax = max(float(max_thrust_per_engine_n), F)
        v_max = 700.0 / (1.0 + bpr) ** 0.44
        v_j = v_max * np.sqrt(F / Fmax)
        mdot = F / v_j
        rho_j = 0.64 * RHO0
        a_jet = mdot / (rho_j * v_j)
        d_jet = np.sqrt(4.0 * a_jet / np.pi)
        m_tip_max = 1.6 / (1.0 + bpr) ** 0.15
        m_tip = m_tip_max * (F / Fmax) ** 0.45
        if fan_diameter_m is None:
            mdot_max = Fmax / v_max
            a_fan = mdot_max / (RHO0 * 0.45 * C0)
            fan_diameter_m = np.sqrt(4.0 * a_fan / np.pi)
        bpf = m_tip * C0 / (np.pi * fan_diameter_m) * n_blades
        return cls(F, v_j, mdot, a_jet, d_jet, m_tip, bpf)


# ---------------------------------------------------------------------------
# Sources: each returns 1/3-octave SPL at 1 m reference radius, free field,
# for ONE engine (engine sources) or the whole airframe.
# ---------------------------------------------------------------------------
class JetSource:
    """Stone/Lighthill jet mixing noise: I ~ rho_j^2 A_j V_j^8 / (rho0 c0^5)."""
    THETA = np.array([0, 30, 60, 90, 120, 150, 165, 180.0])
    DIR = np.array([-3.0, -2.5, -1.5, 0.0, 2.0, 5.0, 3.0, 0.0])   # aft-dominant

    def __init__(self, c_jet=0.0, f_scale=1.0):
        self.c = c_jet
        self.f_scale = f_scale   # spectral placement calibration (see physicsmodel)

    def band_spl_1m(self, st: EngineState, theta_deg):
        oaspl = (self.c
                 + 80.0 * np.log10(st.v_jet / C0)
                 + 10.0 * np.log10(st.a_jet)
                 + _interp_dir(theta_deg, self.THETA, self.DIR))
        f_peak = self.f_scale * 0.25 * st.v_jet / max(st.d_jet, 0.05)  # St~0.25 x fitted shift
        return oaspl + _haystack(F_BANDS, f_peak, width=1.6)


class FanSource:
    """Heidmann-form fan noise: 10log10(mdot) + 40log10(M_tip) (Euler work
    dTt ~ U_tip^2 => 20log10(dTt) = 40log10(M_tip) + const), haystack around
    BPF plus a +8 dB blade-passing tone; inlet + discharge lobes."""
    THETA = np.array([0, 30, 50, 70, 90, 110, 130, 150, 180.0])
    DIR = np.array([0.0, 2.5, 3.0, 0.5, -2.0, 0.5, 2.5, 1.0, -2.0])

    def __init__(self, c_fan=0.0, f_scale=1.0):
        self.c = c_fan
        self.f_scale = f_scale

    def band_spl_1m(self, st: EngineState, theta_deg):
        base = (self.c
                + 10.0 * np.log10(max(st.mdot, 1e-3))
                + 40.0 * np.log10(max(st.m_tip, 0.05))
                + _interp_dir(theta_deg, self.THETA, self.DIR))
        spec = _haystack(F_BANDS, self.f_scale * st.bpf_hz, width=1.2)
        tone = np.zeros_like(F_BANDS)
        i = int(np.argmin(np.abs(np.log(F_BANDS / max(st.bpf_hz, 50.0)))))
        tone[i] = 8.0
        return base + spec + tone


class AirframeSource:
    """Fink airframe noise, three groups with their own scaling:
       wing/slat TE ~ 50log10(V) + 10log10(delta* b),  delta* = 0.37 c Re^-0.2
       flap         ~ 50log10(V) + 10log10(S_f sin^2(delta_f))
       gear         ~ 60log10(V) + 10log10(n_wheels d_w^2)
    Dipole-like directivity (max broadside, min fore/aft)."""

    def __init__(self, c_wingflap=0.0, c_gear=0.0, f_scale=1.0):
        self.cw = c_wingflap
        self.cg = c_gear
        self.f_scale = f_scale

    @staticmethod
    def _dipole(theta_deg):
        s = np.sin(np.radians(theta_deg))
        return 10.0 * np.log10(s * s + 0.05)

    def band_spl_1m(self, v_ms, config, theta_deg):
        """config: dict(wing_area_m2, span_m, flap_area_m2, flap_deg,
        gear_down, n_wheels, wheel_d_m, slats_out)."""
        V = max(v_ms, 20.0)
        S, b = config['wing_area_m2'], config['span_m']
        c_bar = S / b
        re = RHO0 * V * c_bar / 1.79e-5
        dstar = 0.37 * c_bar * re ** -0.2
        out = []
        # wing (+ slat increment when deployed)
        lw = (self.cw + 50.0 * np.log10(V / C0)
              + 10.0 * np.log10(dstar * b) + self._dipole(theta_deg))
        f_w = self.f_scale * 0.1 * V / max(dstar, 1e-3)
        wing = lw + _haystack(F_BANDS, f_w, 1.5) + (3.0 if config.get('slats_out') else 0.0)
        out.append(wing)
        # flap
        if config.get('flap_deg', 0.0) > 1.0:
            sf = config.get('flap_area_m2', 0.17 * S)
            lf = (self.cw + 3.0 + 50.0 * np.log10(V / C0)
                  + 10.0 * np.log10(sf * np.sin(np.radians(config['flap_deg'])) ** 2)
                  + self._dipole(theta_deg))
            f_f = self.f_scale * 0.6 * V / max(0.3 * c_bar, 0.2)
            out.append(lf + _haystack(F_BANDS, f_f, 1.2))
        # landing gear
        if config.get('gear_down'):
            n, d = config.get('n_wheels', 8), config.get('wheel_d_m', 1.1)
            lg = (self.cg + 60.0 * np.log10(V / C0)
                  + 10.0 * np.log10(n * d * d))          # ~omnidirectional
            f_g = self.f_scale * 0.8 * V / d
            out.append(lg + _haystack(F_BANDS, f_g, 1.0))
        # energetic sum of the airframe groups
        stack = np.stack(out, axis=0)
        return 10.0 * np.log10(np.sum(10.0 ** (stack / 10.0), axis=0))


# ===========================================================================
# section: physicsmodel (merged)
# ===========================================================================

"""Physics-based NPD generator + one-shot calibration against ANP truth.

How an NPD point is DEFINED (ECAC Doc 29 / ANP): a single aircraft in steady
level flight at the reference speed (160 kt), at a fixed engine power setting,
passing an observer whose closest-approach (slant) distance is d; the table
stores the observer's LAmax and SEL (and EPNL) for the ten standard distances.

This module simulates exactly that definition:
  1. EngineState from (thrust setting, design)     [components section above]
  2. For emission angles theta = 5..175 deg along the straight path:
       position x = -d*cot(theta), range r = d/sin(theta)
  3. Per component: 1/3-octave SPL at 1 m -> propagate (spherical spreading +
     ISO 9613-1 absorption) -> A-weight -> energetic sum -> L_A(t)
     (engine sources x N_engines: +10 log10 N)
  4. LAmax = max_t L_A(t);  SEL = 10 log10( int 10^{L_A/10} dt / 1 s )
     - the SEL duration effect (slower decay with distance than LAmax)
     emerges naturally from the integration, nothing is bolted on.
  5. Repeat over the requested thrust settings and the 10 ANP distances ->
     NPDTable, identical format to the data-driven surrogate's output.

EPNL is intentionally out of scope (needs PNLT tone-correction machinery);
SEL + LAmax are what the ANP validation uses.

Calibration: the four anchor constants (C_jet, C_fan, C_wingflap, C_gear) are
fitted by least squares to ONE reference aircraft's ANP SEL+LAmax curves
(departure = jet+fan separable via their different throttle scalings V_j^8 vs
M_tip^4; approach = airframe-dominated). They are then FROZEN for every other
aircraft and every future design - so all cross-fleet validation is genuinely
out-of-sample.
"""
import numpy as np
from scipy.optimize import least_squares

from .core import NPDTable, STANDARD_DISTANCES_FT
from .anp import DIST_COLS

FT2M = 0.3048
LBF2N = 4.44822
NPD_REF_SPEED_MS = 160.0 * KT2MS          # ANP NPD reference airspeed


class PhysicsDesign:
    """Design/configuration container for the physics model."""

    def __init__(self, name, n_engines, max_thrust_per_engine_lbf, bpr,
                 mtow_lb, wing_area_m2=None, span_m=None,
                 fan_diameter_m=None, n_fan_blades=24,
                 n_wheels=None, wheel_d_m=1.1):
        self.name = name
        self.n_engines = int(n_engines)
        self.fmax_n = max_thrust_per_engine_lbf * LBF2N
        self.bpr = float(bpr)
        mtow_kg = mtow_lb * 0.453592
        # geometry defaults from weight when a synthesis tool hasn't
        # supplied them: wing loading ~600 kg/m^2, aspect ratio 9
        self.wing_area_m2 = wing_area_m2 or mtow_kg / 600.0
        self.span_m = span_m or np.sqrt(9.0 * self.wing_area_m2)
        self.fan_diameter_m = fan_diameter_m
        self.n_fan_blades = n_fan_blades
        self.n_wheels = n_wheels or (4 if mtow_kg < 5e4 else
                                     8 if mtow_kg < 2e5 else 12)
        self.wheel_d_m = wheel_d_m

    def config(self, op_mode):
        """Configuration state per operational mode (ANP convention:
        departure = gear up + takeoff flap; approach = landing flap + gear)."""
        if op_mode == 'D':
            return dict(wing_area_m2=self.wing_area_m2, span_m=self.span_m,
                        flap_area_m2=0.17 * self.wing_area_m2, flap_deg=10.0,
                        gear_down=False, slats_out=True,
                        n_wheels=self.n_wheels, wheel_d_m=self.wheel_d_m)
        return dict(wing_area_m2=self.wing_area_m2, span_m=self.span_m,
                    flap_area_m2=0.17 * self.wing_area_m2, flap_deg=30.0,
                    gear_down=True, slats_out=True,
                    n_wheels=self.n_wheels, wheel_d_m=self.wheel_d_m)


class PhysicsNPDModel:
    SUPPORTED_METRICS = ("SEL", "LAmax")

    def __init__(self, c_jet=140.0, c_fan=55.0, c_wingflap=35.0, c_gear=25.0):
        self.jet = JetSource(c_jet)
        self.fan = FanSource(c_fan)
        self.airframe = AirframeSource(c_wingflap, c_gear)
        self._aw = a_weighting()
        self._alpha = atmospheric_absorption()
        self._theta = np.linspace(5.0, 175.0, 69)          # emission angles

    # ---- single flyover event -------------------------------------------
    @overload
    def single_event(self, design: PhysicsDesign, thrust_per_engine_lbf,
                     op_mode, distance_ft,
                     return_components: Literal[False] = ...,
                     ) -> tuple[float, float]: ...
    @overload
    def single_event(self, design: PhysicsDesign, thrust_per_engine_lbf,
                     op_mode, distance_ft, return_components: Literal[True],
                     ) -> tuple[float, float, dict[str, float]]: ...

    def single_event(self, design: PhysicsDesign, thrust_per_engine_lbf,
                     op_mode, distance_ft, return_components=False):
        """Returns (LAmax, SEL) for one level flyover at closest distance d."""
        d = distance_ft * FT2M
        st = EngineState.from_design(thrust_per_engine_lbf * LBF2N,
                                     design.fmax_n, design.bpr,
                                     design.fan_diameter_m,
                                     design.n_fan_blades)
        cfg = design.config(op_mode)
        v = NPD_REF_SPEED_MS
        th = self._theta
        r = d / np.sin(np.radians(th))                     # slant range [m]
        x = -d / np.tan(np.radians(th))                    # along-track pos
        t = x / v                                          # time [s]
        n_eng_db = 10.0 * np.log10(design.n_engines)
        la = np.empty_like(th)
        comp_max = {}
        for i, (ti, ri) in enumerate(zip(th, r)):
            prop = -20.0 * np.log10(ri) - self._alpha * ri + self._aw
            bands = {
                'jet': self.jet.band_spl_1m(st, ti) + n_eng_db + prop,
                'fan': self.fan.band_spl_1m(st, ti) + n_eng_db + prop,
                'airframe': self.airframe.band_spl_1m(v, cfg, ti) + prop,
            }
            tot = 0.0
            for k, b in bands.items():
                lk = 10.0 * np.log10(np.sum(10.0 ** (b / 10.0)))
                comp_max[k] = max(comp_max.get(k, -300.0), lk)
                tot += 10.0 ** (lk / 10.0)
            la[i] = 10.0 * np.log10(tot)
        lamax = float(la.max())
        sel = float(10.0 * np.log10(np.trapezoid(10.0 ** (la / 10.0), t)))
        if return_components:
            return lamax, sel, comp_max
        return lamax, sel

    # ---- NPD table emission ---------------------------------------------
    def predict_table(self, design: PhysicsDesign, metric, op_mode,
                      power_settings_lbf) -> NPDTable:
        if metric not in self.SUPPORTED_METRICS:
            raise ValueError(
                f"PhysicsNPDModel supports only "
                f"{', '.join(self.SUPPORTED_METRICS)}; got {metric!r}. "
                "EPNL/PNLTM require tone-correction machinery that is not "
                "implemented in the component-physics route.")
        P = np.atleast_1d(np.asarray(power_settings_lbf, float))
        L = np.empty((len(P), len(STANDARD_DISTANCES_FT)))
        for i, p in enumerate(P):
            for j, dft in enumerate(STANDARD_DISTANCES_FT):
                lamax, sel = self.single_event(design, p, op_mode, dft)
                L[i, j] = lamax if metric == 'LAmax' else sel
        return NPDTable(P, L, metric, op_mode, npd_id=design.name)

    # ---- one-shot calibration against ANP truth --------------------------
    def calibrate(self, db, acft_id, bpr, verbose=True):
        """Fit (C_jet, C_fan, C_wingflap, C_gear) to one reference aircraft's
        ANP SEL + LAmax curves (both op modes), then freeze them."""
        row = db.aircraft[db.aircraft['ACFT_ID'] == acft_id].iloc[0]
        design = PhysicsDesign(acft_id, row['Number Of Engines'],
                               row['Max Sea Level Static Thrust (lb)'], bpr,
                               row['Max Gross Takeoff Weight (lb)'])
        npd_id = str(row['NPD_ID'])
        targets = []
        for metric in self.SUPPORTED_METRICS:
            for om in ('D', 'A'):
                cv = db.curve(npd_id, metric, om)
                if not cv.empty:
                    targets.append((metric, om,
                                    cv['Power Setting'].values.astype(float),
                                    cv[DIST_COLS].values))

        def set_params(c):
            self.jet.c, self.fan.c = c[0], c[1]
            self.airframe.cw, self.airframe.cg = c[2], c[3]
            fs = 2.0 ** c[4]
            self.jet.f_scale = self.fan.f_scale = self.airframe.f_scale = fs

        def residual(c):
            set_params(c)
            res = []
            for metric, om, P, truth in targets:
                pred = self.predict_table(design, metric, om, P).L
                res.append((pred - truth).ravel())
            return np.concatenate(res)

        # Stage 1: coarse grid on the spectral placement (the one strongly
        # non-convex parameter), fitting the four level constants at each
        # node. Starting levels are physically scaled so every component is
        # audible (a jet constant ~140 puts jet OASPL(1 m) near 110-140 dB;
        # airframe needs ~100+ to be comparable at approach speed).
        lo = np.array([110.0, 30.0, 70.0, 60.0])
        hi = np.array([180.0, 100.0, 145.0, 135.0])
        x_lvl0 = np.array([140.0, 60.0, 105.0, 95.0])
        best = None
        for lf in (0.0, 0.7, 1.3, 2.0, 2.6):              # f_scale x1..x6
            sol = least_squares(lambda c: residual(np.r_[c, lf]),
                                x_lvl0, bounds=(lo, hi),
                                diff_step=1.0, xtol=1e-2, max_nfev=40)
            cost = float(np.sqrt(np.mean(sol.fun ** 2)))
            if best is None or cost < best[0]:
                best = (cost, np.r_[sol.x, lf])
        # Stage 2: joint bounded refinement around the best grid node.
        assert best is not None  # the grid loop always evaluates >= 1 node
        sol = least_squares(residual, best[1],
                            bounds=(np.r_[lo, 0.0], np.r_[hi, 3.0]),
                            diff_step=0.3, xtol=1e-3, max_nfev=60)
        set_params(sol.x)
        rmse = float(np.sqrt(np.mean(sol.fun ** 2)))
        if verbose:
            print(f"  calibrated on {acft_id}: C_jet={sol.x[0]:.1f} "
                  f"C_fan={sol.x[1]:.1f} C_wingflap={sol.x[2]:.1f} "
                  f"C_gear={sol.x[3]:.1f} f_scale=x{2**sol.x[4]:.2f}  "
                  f"(in-sample RMSE {rmse:.2f} dB)")
        return rmse
