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
from typing import Any, Generic, Literal, Mapping, Protocol, TypeVar, overload
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
from dataclasses import dataclass, field
import numpy as np


F_BANDS = THIRD_OCTAVE_HZ


@dataclass(frozen=True)
class InputStatus:
    """Declared origin and completeness of a physical input.

    ``source`` is deliberately a small, serialisable contract: values are
    ``supplied``, ``estimated`` or ``unavailable``. The component physics
    route never upgrades an estimated input to supplied.
    """
    source: Literal["supplied", "estimated", "unavailable"] = "unavailable"
    complete: bool = False
    note: str = ""


T = TypeVar("T")


@dataclass(frozen=True)
class PhysicalInput(Generic[T]):
    """A physical quantity together with its declared evidence status."""
    value: T | None
    status: Literal["supplied", "estimated", "unavailable"]
    note: str = ""

    @property
    def available(self) -> bool:
        return self.value is not None and self.status != "unavailable"

    def or_value(self, fallback: T) -> T:
        return self.value if self.available else fallback


@dataclass(frozen=True)
class JetStream:
    """One actual exhaust stream for the detailed Stone-style path."""
    velocity_ms: float
    mass_flow_kg_s: float
    diameter_m: float
    temperature_k: float = 450.0
    total_pressure_pa: float | None = None
    name: Literal["outer", "inner", "intermediate", "merged"] = "outer"
    status: Literal["supplied", "estimated"] = "supplied"


@dataclass(frozen=True)
class FanDeck:
    """Fan-map inputs required before the detailed Heidmann path is used."""
    mass_flow_kg_s: float
    tip_speed_ms: float
    blade_count: int
    rotor_diameter_m: float
    temperature_rise_k: float
    rpm: float | None = None
    n1_percent: float | None = None
    stator_count: int | None = None
    rotor_stator_spacing_m: float | None = None
    status: Literal["supplied", "estimated"] = "supplied"


@dataclass(frozen=True)
class CoreStream:
    """Optional core source; it is usable only with all fields populated."""
    velocity_ms: float
    mass_flow_kg_s: float
    diameter_m: float
    temperature_k: float
    combustor_exit_temperature_k: float | None = None
    total_pressure_pa: float | None = None
    turbine_attenuation_db: float | None = None
    status: Literal["supplied", "estimated"] = "supplied"


@dataclass(frozen=True)
class EnginePhysicalInputs:
    """Component-ready engine inputs; every field carries visible provenance."""
    thrust_n: PhysicalInput[float]
    bypass_ratio: PhysicalInput[float]
    mass_flow_kg_s: PhysicalInput[float]
    nozzle_exit_area_m2: PhysicalInput[float]
    nozzle_exit_velocity_ms: PhysicalInput[float]
    nozzle_exit_temperature_k: PhysicalInput[float]
    nozzle_exit_pressure_pa: PhysicalInput[float]
    fan_diameter_m: PhysicalInput[float]
    rpm: PhysicalInput[float]
    n1_percent: PhysicalInput[float]
    blade_count: PhysicalInput[int]
    stator_count: PhysicalInput[int]
    rotor_stator_spacing_m: PhysicalInput[float]
    fan_temperature_rise_k: PhysicalInput[float]
    core_mass_flow_kg_s: PhysicalInput[float]
    combustor_inlet_temperature_k: PhysicalInput[float]
    combustor_exit_temperature_k: PhysicalInput[float]
    turbine_attenuation_db: PhysicalInput[float]


@dataclass(frozen=True)
class AirframeGeometry:
    """Typed optional geometry/state contract for airframe component models."""
    wing_area_m2: float | None = None
    span_m: float | None = None
    flap_area_m2: float | None = None
    slat_area_m2: float | None = None
    slat_chord_m: float | None = None
    slat_deg: float | None = None
    wheel_diameter_m: float | None = None
    strut_diameter_m: float | None = None
    nose_wheel_count: int | None = None
    main_wheel_count: int | None = None
    flap_deg: float | None = None
    slats_out: bool | None = None
    gear_down: bool | None = None


@dataclass(frozen=True)
class AirframePhysicalInputs:
    """Airframe geometry/configuration contract with per-field evidence."""
    wing_area_m2: PhysicalInput[float]
    wing_span_m: PhysicalInput[float]
    flap_area_m2: PhysicalInput[float]
    flap_chord_m: PhysicalInput[float]
    flap_deflection_deg: PhysicalInput[float]
    slat_area_m2: PhysicalInput[float]
    slat_chord_m: PhysicalInput[float]
    slat_deflection_deg: PhysicalInput[float]
    nose_wheel_count: PhysicalInput[int]
    nose_wheel_diameter_m: PhysicalInput[float]
    nose_strut_diameter_m: PhysicalInput[float]
    main_wheel_count: PhysicalInput[int]
    main_wheel_diameter_m: PhysicalInput[float]
    main_strut_diameter_m: PhysicalInput[float]
    gear_down: PhysicalInput[bool]


@dataclass(frozen=True)
class Atmosphere:
    temperature_c: float = 15.0
    relative_humidity_percent: float = 70.0
    pressure_kpa: float = 101.325


@dataclass(frozen=True)
class AtmosphericPhysicalInputs:
    temperature_c: PhysicalInput[float]
    relative_humidity_percent: PhysicalInput[float]
    pressure_kpa: PhysicalInput[float]


@dataclass(frozen=True)
class TrajectoryState:
    """Full future trajectory contract; the adapter uses its NPD subset."""
    position_m: tuple[float, float, float]
    true_airspeed_ms: float
    mach: float | None = None
    altitude_m: float | None = None
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    yaw_deg: float = 0.0
    thrust_per_engine_n: float | None = None
    configuration: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FlightTrajectoryInputs:
    """Trajectory-ready state contract with explicit input provenance."""
    position_m: PhysicalInput[tuple[float, float, float]]
    true_airspeed_ms: PhysicalInput[float]
    mach: PhysicalInput[float]
    altitude_m: PhysicalInput[float]
    attitude_deg: PhysicalInput[tuple[float, float, float]]
    thrust_per_engine_n: PhysicalInput[float]
    configuration: PhysicalInput[Mapping[str, Any]]

    def to_flight_state(self, *, time_s: float,
                        emission_angle_deg: float,
                        atmosphere: Atmosphere | None = None) -> "FlightState":
        """Convert a complete trajectory sample to the source interface."""
        required = {
            "position_m": self.position_m,
            "true_airspeed_ms": self.true_airspeed_ms,
            "altitude_m": self.altitude_m,
            "thrust_per_engine_n": self.thrust_per_engine_n,
            "configuration": self.configuration,
        }
        missing = [name for name, value in required.items()
                   if not value.available]
        if missing:
            raise ValueError(
                "flight trajectory state unavailable: " + ", ".join(missing))
        position = self.position_m.value
        assert position is not None
        return FlightState(
            time_s=time_s, x_m=float(position[0]),
            altitude_m=float(self.altitude_m.value),
            true_airspeed_ms=float(self.true_airspeed_ms.value),
            emission_angle_deg=float(emission_angle_deg),
            position_m=position,
            mach=(float(self.mach.value) if self.mach.available else None),
            attitude_deg=(
                self.attitude_deg.value if self.attitude_deg.available
                else (0.0, 0.0, 0.0)),
            thrust_per_engine_n=float(self.thrust_per_engine_n.value),
            configuration=dict(self.configuration.value),
            atmosphere=atmosphere)


@dataclass(frozen=True)
class FlightState:
    """Instantaneous straight-flight state supplied to the event integrator."""
    time_s: float
    x_m: float
    altitude_m: float
    true_airspeed_ms: float
    emission_angle_deg: float
    position_m: tuple[float, float, float] | None = None
    mach: float | None = None
    attitude_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    thrust_per_engine_n: float | None = None
    configuration: Mapping[str, Any] = field(default_factory=dict)
    atmosphere: Atmosphere | None = None


class FlightStateSource(Protocol):
    """Extension point for installation/trajectory tools.

    It supplies instantaneous states; this module intentionally does not
    apply installation or propagation corrections beyond free-field loss.
    """
    def state(self, *, x_m: float, closest_distance_m: float,
              true_airspeed_ms: float,
              thrust_per_engine_n: float | None = None,
              configuration: Mapping[str, Any] | None = None,
              atmosphere: Atmosphere | None = None) -> FlightState: ...


@dataclass(frozen=True)
class Reference160KtFlightPath:
    """Doc-29 NPD adapter for a steady, level 160-kt flyover."""
    speed_ms: float = NPD_REF_SPEED_MS if 'NPD_REF_SPEED_MS' in globals() else 160.0 * KT2MS

    def state(self, *, x_m: float, closest_distance_m: float,
              true_airspeed_ms: float | None = None,
              thrust_per_engine_n: float | None = None,
              configuration: Mapping[str, Any] | None = None,
              atmosphere: Atmosphere | None = None) -> FlightState:
        speed = self.speed_ms if true_airspeed_ms is None else true_airspeed_ms
        theta = float(np.degrees(np.arctan2(closest_distance_m, -x_m)))
        return FlightState(
            x_m / speed, x_m, closest_distance_m, speed, theta,
            (x_m, 0.0, closest_distance_m), speed / C0, (0.0, 0.0, 0.0),
            thrust_per_engine_n, dict(configuration or {}), atmosphere)


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
    jet_streams: tuple[JetStream, ...] = ()
    fan_deck: FanDeck | None = None
    core_stream: CoreStream | None = None
    input_status: Mapping[str, InputStatus] = field(default_factory=dict)

    @classmethod
    def from_design(cls, thrust_per_engine_n, max_thrust_per_engine_n,
                    bpr, fan_diameter_m=None, n_blades=24,
                    jet_streams=(), fan_deck=None, core_stream=None,
                    physical_inputs: EnginePhysicalInputs | None = None):
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
        statuses = {}
        if physical_inputs is not None:
            v_j = float(physical_inputs.nozzle_exit_velocity_ms.or_value(v_j))
            mdot = float(physical_inputs.mass_flow_kg_s.or_value(mdot))
            a_jet = float(
                physical_inputs.nozzle_exit_area_m2.or_value(a_jet))
            d_jet = np.sqrt(4.0 * a_jet / np.pi)
            fan_diameter_m = float(
                physical_inputs.fan_diameter_m.or_value(fan_diameter_m))
            supplied_mixed = all(
                item.status == "supplied" and item.available for item in (
                    physical_inputs.nozzle_exit_velocity_ms,
                    physical_inputs.nozzle_exit_area_m2,
                    physical_inputs.nozzle_exit_temperature_k,
                    physical_inputs.nozzle_exit_pressure_pa,
                ))
            statuses["mixed_jet"] = InputStatus(
                "supplied" if supplied_mixed else "estimated",
                supplied_mixed,
                "typed nozzle inputs" if supplied_mixed
                else "typed/legacy mixed-nozzle estimates")
        bpf = m_tip * C0 / (np.pi * fan_diameter_m) * n_blades
        return cls(F, v_j, mdot, a_jet, d_jet, m_tip, bpf,
                   tuple(jet_streams), fan_deck, core_stream, statuses)


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

    STREAM_DIR_OFFSET = {
        "outer": -1.0, "inner": 1.5, "intermediate": 0.5, "merged": 0.0,
    }

    def component_spectra_with_diagnostics(self, st: EngineState, theta_deg):
        """Return independently inspectable Stone virtual-source spectra."""
        streams = tuple(s for s in st.jet_streams
                        if s.velocity_ms > 0 and s.mass_flow_kg_s > 0
                        and s.diameter_m > 0 and s.temperature_k > 0
                        and s.total_pressure_pa is not None
                        and s.total_pressure_pa > 0)
        names = {s.name for s in streams}
        if {"outer", "merged"}.issubset(names):
            pieces = {}
            for stream in streams:
                area = np.pi * (stream.diameter_m / 2.0) ** 2
                density_ratio = 288.15 / stream.temperature_k
                oaspl = (self.c + 80.0 * np.log10(stream.velocity_ms / C0)
                         + 10.0 * np.log10(area)
                         + 20.0 * np.log10(max(density_ratio, 0.05))
                         + _interp_dir(theta_deg, self.THETA, self.DIR)
                         + self.STREAM_DIR_OFFSET[stream.name])
                peak = self.f_scale * .25 * stream.velocity_ms / stream.diameter_m
                width = 1.45 if stream.name == "inner" else 1.7
                pieces[f"jet_{stream.name}"] = (
                    oaspl + _haystack(F_BANDS, peak, width=width))
            evidence = ("supplied"
                        if all(s.status == "supplied" for s in streams)
                        else "estimated")
            return pieces, InputStatus(
                evidence, evidence == "supplied",
                "Stone multi-stream: outer and merged required; "
                "inner/intermediate optional"
                + ("; contains estimated stream data"
                   if evidence == "estimated" else ""))
        return {}, InputStatus(
            "estimated", False,
            "Stone multi-stream unavailable: supplied outer and merged stream "
            "velocity, flow, diameter, temperature, and pressure required")

    def spectrum_with_diagnostics(self, st: EngineState, theta_deg):
        """Return spectrum and an explicit detailed/fallback source status."""
        pieces, status = self.component_spectra_with_diagnostics(st, theta_deg)
        if pieces:
            stack = np.stack(list(pieces.values()))
            spectrum = 10.0 * np.log10(
                np.sum(10.0 ** (stack / 10.0), axis=0))
            return spectrum, status
        oaspl = (self.c
                 + 80.0 * np.log10(st.v_jet / C0)
                 + 10.0 * np.log10(st.a_jet)
                 + _interp_dir(theta_deg, self.THETA, self.DIR))
        f_peak = self.f_scale * 0.25 * st.v_jet / max(st.d_jet, 0.05)  # St~0.25 x fitted shift
        mixed_status = st.input_status.get(
            "mixed_jet",
            InputStatus("estimated", False, "legacy thrust/BPR estimate"))
        return (oaspl + _haystack(F_BANDS, f_peak, width=1.6),
                InputStatus(
                    mixed_status.source, mixed_status.complete,
                    "simplified mixed-jet path; " + mixed_status.note))

    def band_spl_1m(self, st: EngineState, theta_deg):
        return self.spectrum_with_diagnostics(st, theta_deg)[0]

    def core_spectrum_1m(self, st: EngineState, theta_deg):
        """Optional core contribution; absent unless a complete core is given."""
        core = st.core_stream
        if (core is None
                or min(core.velocity_ms, core.mass_flow_kg_s,
                       core.diameter_m, core.temperature_k) <= 0
                or core.combustor_exit_temperature_k is None
                or core.total_pressure_pa is None
                or core.turbine_attenuation_db is None):
            return None, InputStatus(
                "unavailable", False,
                "core disabled: core flow, combustor state, pressure, and "
                "turbine attenuation are all required")
        area = np.pi * (core.diameter_m / 2.0) ** 2
        level = (self.c - 8.0 + 80.0 * np.log10(core.velocity_ms / C0)
                 + 10.0 * np.log10(area) + _interp_dir(theta_deg, self.THETA, self.DIR))
        peak = self.f_scale * .25 * core.velocity_ms / core.diameter_m
        level -= core.turbine_attenuation_db
        return (level + _haystack(F_BANDS, peak, width=1.7),
                InputStatus(
                    core.status, core.status == "supplied",
                    "optional combustor/core source"
                    + (" with estimated inputs"
                       if core.status == "estimated" else "")))


class FanSource:
    """Heidmann-form fan noise: 10log10(mdot) + 40log10(M_tip) (Euler work
    dTt ~ U_tip^2 => 20log10(dTt) = 40log10(M_tip) + const), haystack around
    BPF plus a +8 dB blade-passing tone; inlet + discharge lobes."""
    THETA = np.array([0, 30, 50, 70, 90, 110, 130, 150, 180.0])
    DIR = np.array([0.0, 2.5, 3.0, 0.5, -2.0, 0.5, 2.5, 1.0, -2.0])

    def __init__(self, c_fan=0.0, f_scale=1.0):
        self.c = c_fan
        self.f_scale = f_scale

    def component_spectra_with_diagnostics(self, st: EngineState, theta_deg):
        deck = st.fan_deck
        complete = (
            deck is not None
            and min(deck.mass_flow_kg_s, deck.tip_speed_ms,
                    deck.rotor_diameter_m, deck.temperature_rise_k) > 0
            and deck.blade_count > 0
            and deck.stator_count is not None and deck.stator_count > 0
            and deck.rotor_stator_spacing_m is not None
            and deck.rotor_stator_spacing_m > 0
            and (deck.rpm is not None or deck.n1_percent is not None))
        if complete:
            assert deck is not None
            bpf = deck.tip_speed_ms / (np.pi * deck.rotor_diameter_m) * deck.blade_count
            base = (self.c + 10.0 * np.log10(deck.mass_flow_kg_s)
                    + 20.0 * np.log10(deck.temperature_rise_k)
                    - 3.0 * np.log10(
                        1.0 + deck.rotor_stator_spacing_m / deck.rotor_diameter_m))
            spec = _haystack(F_BANDS, self.f_scale * bpf, width=1.2)
            tones = np.zeros_like(F_BANDS)
            for harmonic, gain in ((1, 8.0), (2, 5.0), (3, 3.0)):
                i = int(np.argmin(np.abs(np.log(
                    F_BANDS / max(harmonic * bpf, 50.0)))))
                tones[i] += gain
            tip_mach = deck.tip_speed_ms / C0
            buzz = np.zeros_like(F_BANDS)
            if tip_mach >= 1.0:
                buzz[F_BANDS < bpf] = 3.0 * min(tip_mach - 1.0, 0.5) / 0.5
            inlet_dir = _interp_dir(
                theta_deg, self.THETA,
                np.array([3., 4., 3., 0., -4., -7., -10., -12., -14.]))
            discharge_dir = _interp_dir(
                theta_deg, self.THETA,
                np.array([-14., -12., -9., -6., -3., 0., 3., 4., 3.]))
            return {
                "fan_inlet": base + inlet_dir + spec + tones + buzz,
                "fan_discharge": base - 2.0 + discharge_dir + spec + tones,
            }, InputStatus(
                deck.status, deck.status == "supplied",
                "Heidmann engine-deck path; BPF harmonics enabled"
                + ("; buzz-saw eligible" if tip_mach >= 1.0 else "")
                + ("; estimated inputs are not engine-deck-equivalent"
                   if deck.status == "estimated" else ""))
        return {}, InputStatus(
            "estimated", False,
            "Heidmann path unavailable: mass flow, temperature rise, tip "
            "speed/RPM or N1, blade/stator counts, and rotor-stator spacing required")

    def spectrum_with_diagnostics(self, st: EngineState, theta_deg):
        pieces, status = self.component_spectra_with_diagnostics(st, theta_deg)
        if pieces:
            stack = np.stack(list(pieces.values()))
            return (10.0 * np.log10(
                np.sum(10.0 ** (stack / 10.0), axis=0)), status)
        base = (self.c
                + 10.0 * np.log10(max(st.mdot, 1e-3))
                + 40.0 * np.log10(max(st.m_tip, 0.05))
                + _interp_dir(theta_deg, self.THETA, self.DIR))
        spec = _haystack(F_BANDS, self.f_scale * st.bpf_hz, width=1.2)
        tone = np.zeros_like(F_BANDS)
        i = int(np.argmin(np.abs(np.log(F_BANDS / max(st.bpf_hz, 50.0)))))
        tone[i] = 8.0
        return (base + spec + tone,
                InputStatus("estimated", False, "simplified fan-cycle fallback"))

    def band_spl_1m(self, st: EngineState, theta_deg):
        return self.spectrum_with_diagnostics(st, theta_deg)[0]


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

    def component_spectra_1m(self, v_ms, config, theta_deg):
        """Six separately inspectable Fink-style spectra.

        Missing/deployed components are represented by omission, rather than a
        fabricated silent spectrum; callers can therefore report unavailable
        inputs honestly.
        """
        """config: dict(wing_area_m2, span_m, flap_area_m2, flap_deg,
        gear_down, n_wheels, wheel_d_m, slats_out)."""
        V = max(v_ms, 20.0)
        S, b = config['wing_area_m2'], config['span_m']
        c_bar = S / b
        re = RHO0 * V * c_bar / 1.79e-5
        dstar = 0.37 * c_bar * re ** -0.2
        out = {}
        # wing (+ slat increment when deployed)
        lw = (self.cw + 50.0 * np.log10(V / C0)
              + 10.0 * np.log10(dstar * b) + self._dipole(theta_deg))
        f_w = self.f_scale * 0.1 * V / max(dstar, 1e-3)
        wing = lw + _haystack(F_BANDS, f_w, 1.5)
        out['wing_trailing_edge'] = wing
        if config.get('slats_out'):
            slat_chord = config.get('slat_chord_m', 0.12 * c_bar)
            f_s = self.f_scale * 0.2 * V / max(slat_chord, 0.05)
            out['slat'] = (lw + _haystack(F_BANDS, f_s, 1.35))
        # flap
        if config.get('flap_deg', 0.0) > 1.0:
            sf = config.get('flap_area_m2', 0.17 * S)
            lf = (self.cw + 3.0 + 50.0 * np.log10(V / C0)
                  + 10.0 * np.log10(sf * np.sin(np.radians(config['flap_deg'])) ** 2)
                  + self._dipole(theta_deg))
            f_f = self.f_scale * 0.6 * V / max(0.3 * c_bar, 0.2)
            flap_total = lf + _haystack(F_BANDS, f_f, 1.2)
            # Main-edge and two side-edge virtual sources split the legacy
            # flap intensity 75/25 while retaining distinct spectral peaks.
            out['flap_main_edge'] = flap_total + 10.0 * np.log10(.75)
            out['flap_side_edge'] = (
                lf + 10.0 * np.log10(.25)
                + _haystack(F_BANDS, 1.8 * f_f, 1.0))
        # landing gear
        if config.get('gear_down'):
            n, d = config.get('n_wheels', 8), config.get('wheel_d_m', 1.1)
            lg = self.cg + 60.0 * np.log10(V / C0)       # ~omnidirectional
            main_n = config.get('main_wheel_count', max(n - 2, 1))
            nose_n = config.get('nose_wheel_count', min(2, n))
            main_d = config.get('main_wheel_d_m', d)
            nose_d = config.get('nose_wheel_d_m', .7 * d)
            main_strut = config.get(
                'main_strut_d_m', config.get('strut_d_m', .12 * main_d))
            nose_strut = config.get(
                'nose_strut_d_m', config.get('strut_d_m', .12 * nose_d))
            main_gain = 10.0 * np.log10(
                1.0 + max(main_strut, 0.0) ** 2
                / max(main_d * main_d, 1e-6))
            nose_gain = 10.0 * np.log10(
                1.0 + max(nose_strut, 0.0) ** 2
                / max(nose_d * nose_d, 1e-6))
            out['main_landing_gear'] = (
                lg + 10.0 * np.log10(main_n * main_d * main_d)
                + main_gain
                + _haystack(F_BANDS, self.f_scale * .8 * V / main_d, 1.0))
            out['nose_landing_gear'] = (
                lg + 10.0 * np.log10(nose_n * nose_d * nose_d)
                + nose_gain
                + _haystack(
                    F_BANDS, 1.25 * self.f_scale * .8 * V / nose_d, 1.0))
        return out

    def band_spl_1m(self, v_ms, config, theta_deg):
        spectra = self.component_spectra_1m(v_ms, config, theta_deg)
        stack = np.stack(list(spectra.values()), axis=0)
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
                 n_wheels=None, wheel_d_m=1.1, *,
                 jet_streams: tuple[JetStream, ...] = (),
                 fan_deck: FanDeck | None = None,
                 core_stream: CoreStream | None = None,
                 airframe_geometry: AirframeGeometry | None = None,
                 engine_physical_inputs: EnginePhysicalInputs | None = None,
                 airframe_physical_inputs: AirframePhysicalInputs | None = None,
                 atmospheric_inputs: AtmosphericPhysicalInputs | None = None,
                 input_status: Mapping[str, InputStatus] | None = None):
        self.name = name
        self.n_engines = int(n_engines)
        self.fmax_n = max_thrust_per_engine_lbf * LBF2N
        self.engine_physical_inputs = engine_physical_inputs
        self.airframe_physical_inputs = airframe_physical_inputs
        self.atmospheric_inputs = atmospheric_inputs
        self.bpr = float(
            engine_physical_inputs.bypass_ratio.or_value(bpr)
            if engine_physical_inputs is not None else bpr)
        mtow_kg = mtow_lb * 0.453592
        # geometry defaults from weight when a synthesis tool hasn't
        # supplied them: wing loading ~600 kg/m^2, aspect ratio 9
        self.wing_area_m2 = wing_area_m2 or mtow_kg / 600.0
        self.span_m = span_m or np.sqrt(9.0 * self.wing_area_m2)
        self.fan_diameter_m = (
            engine_physical_inputs.fan_diameter_m.or_value(fan_diameter_m)
            if engine_physical_inputs is not None else fan_diameter_m)
        self.n_fan_blades = int(
            engine_physical_inputs.blade_count.or_value(n_fan_blades)
            if engine_physical_inputs is not None else n_fan_blades)
        self.n_wheels = n_wheels or (4 if mtow_kg < 5e4 else
                                     8 if mtow_kg < 2e5 else 12)
        self.wheel_d_m = wheel_d_m
        self.jet_streams = tuple(jet_streams)
        if fan_deck is None and engine_physical_inputs is not None:
            ep = engine_physical_inputs
            fan_fields = (
                ep.mass_flow_kg_s, ep.fan_diameter_m, ep.rpm,
                ep.blade_count, ep.stator_count, ep.rotor_stator_spacing_m,
                ep.fan_temperature_rise_k)
            if all(item.available for item in fan_fields):
                diameter = float(ep.fan_diameter_m.value)
                rpm = float(ep.rpm.value)
                fan_status = (
                    "supplied" if all(item.status == "supplied"
                                      for item in fan_fields)
                    else "estimated")
                fan_deck = FanDeck(
                    float(ep.mass_flow_kg_s.value),
                    np.pi * diameter * rpm / 60.0,
                    int(ep.blade_count.value), diameter,
                    float(ep.fan_temperature_rise_k.value), rpm= rpm,
                    n1_percent=(float(ep.n1_percent.value)
                                if ep.n1_percent.available else None),
                    stator_count=int(ep.stator_count.value),
                    rotor_stator_spacing_m=float(
                        ep.rotor_stator_spacing_m.value),
                    status=fan_status)
        self.fan_deck = fan_deck

        if core_stream is None and engine_physical_inputs is not None:
            ep = engine_physical_inputs
            core_fields = (
                ep.core_mass_flow_kg_s, ep.nozzle_exit_velocity_ms,
                ep.nozzle_exit_area_m2, ep.nozzle_exit_temperature_k,
                ep.nozzle_exit_pressure_pa,
                ep.combustor_exit_temperature_k,
                ep.turbine_attenuation_db)
            if all(item.available for item in core_fields):
                core_status = (
                    "supplied" if all(item.status == "supplied"
                                      for item in core_fields)
                    else "estimated")
                core_stream = CoreStream(
                    float(ep.nozzle_exit_velocity_ms.value),
                    float(ep.core_mass_flow_kg_s.value),
                    np.sqrt(4.0 * float(ep.nozzle_exit_area_m2.value) / np.pi),
                    float(ep.nozzle_exit_temperature_k.value),
                    combustor_exit_temperature_k=float(
                        ep.combustor_exit_temperature_k.value),
                    total_pressure_pa=float(ep.nozzle_exit_pressure_pa.value),
                    turbine_attenuation_db=float(
                        ep.turbine_attenuation_db.value),
                    status=core_status)
        self.core_stream = core_stream
        self.airframe_geometry = airframe_geometry
        core_complete = (
            core_stream is not None
            and core_stream.combustor_exit_temperature_k is not None
            and core_stream.total_pressure_pa is not None
            and core_stream.turbine_attenuation_db is not None
            and min(core_stream.velocity_ms, core_stream.mass_flow_kg_s,
                    core_stream.diameter_m, core_stream.temperature_k) > 0)
        defaults = {
            "thrust": InputStatus("supplied", True, "PhysicsDesign input"),
            "bypass_ratio": InputStatus("supplied", True, "PhysicsDesign input"),
            "wing_area_m2": InputStatus(
                "supplied" if wing_area_m2 is not None else "estimated",
                wing_area_m2 is not None,
                "supplied geometry" if wing_area_m2 is not None
                else "estimated from 600 kg/m2 wing loading"),
            "span_m": InputStatus(
                "supplied" if span_m is not None else "estimated",
                span_m is not None,
                "supplied geometry" if span_m is not None
                else "estimated with aspect ratio 9"),
            "jet_streams": InputStatus(
                "supplied" if jet_streams else "unavailable",
                bool(jet_streams), "engine-deck stream data"),
            "fan_deck": InputStatus(
                "supplied" if fan_deck is not None else "unavailable",
                fan_deck is not None, "engine-deck fan data"),
            "core_combustor": InputStatus(
                (core_stream.status if core_complete else "unavailable"),
                core_complete,
                "complete core source data" if core_complete
                else "core disabled until all required fields are available"),
        }
        if engine_physical_inputs is not None:
            for name, value in vars(engine_physical_inputs).items():
                defaults[name] = InputStatus(
                    value.status, value.available,
                    value.note or "typed engine physical input")
        if airframe_physical_inputs is not None:
            for name, value in vars(airframe_physical_inputs).items():
                defaults[f"airframe.{name}"] = InputStatus(
                    value.status, value.available,
                    value.note or "typed airframe physical input")
        if atmospheric_inputs is not None:
            for name, value in (
                    ("temperature_c", atmospheric_inputs.temperature_c),
                    ("relative_humidity_percent",
                     atmospheric_inputs.relative_humidity_percent),
                    ("pressure_kpa", atmospheric_inputs.pressure_kpa)):
                defaults[name] = InputStatus(
                    value.status, value.available,
                    value.note or "typed atmospheric input")
        defaults.update(input_status or {})
        self.input_status = defaults

    def config(self, op_mode):
        """Configuration state per operational mode (ANP convention:
        departure = gear up + takeoff flap; approach = landing flap + gear)."""
        if op_mode == 'D':
            base = dict(wing_area_m2=self.wing_area_m2, span_m=self.span_m,
                        flap_area_m2=0.17 * self.wing_area_m2, flap_deg=10.0,
                        gear_down=False, slats_out=True,
                        n_wheels=self.n_wheels, wheel_d_m=self.wheel_d_m)
        else:
            base = dict(wing_area_m2=self.wing_area_m2, span_m=self.span_m,
                    flap_area_m2=0.17 * self.wing_area_m2, flap_deg=30.0,
                    gear_down=True, slats_out=True,
                    n_wheels=self.n_wheels, wheel_d_m=self.wheel_d_m)
        geom = self.airframe_geometry
        if geom is not None:
            values = {"wing_area_m2": geom.wing_area_m2, "span_m": geom.span_m,
                      "flap_area_m2": geom.flap_area_m2, "flap_deg": geom.flap_deg,
                      "slats_out": geom.slats_out, "gear_down": geom.gear_down,
                      "slat_chord_m": geom.slat_chord_m,
                      "slat_deg": geom.slat_deg,
                      "wheel_d_m": geom.wheel_diameter_m,
                      "strut_d_m": geom.strut_diameter_m,
                      "nose_wheel_count": geom.nose_wheel_count,
                      "main_wheel_count": geom.main_wheel_count}
            base.update({k: v for k, v in values.items() if v is not None})
        physical = self.airframe_physical_inputs
        if physical is not None:
            typed_values = {
                "wing_area_m2": physical.wing_area_m2,
                "span_m": physical.wing_span_m,
                "flap_area_m2": physical.flap_area_m2,
                "flap_chord_m": physical.flap_chord_m,
                "flap_deg": physical.flap_deflection_deg,
                "slat_area_m2": physical.slat_area_m2,
                "slat_chord_m": physical.slat_chord_m,
                "slat_deg": physical.slat_deflection_deg,
                "nose_wheel_count": physical.nose_wheel_count,
                "nose_wheel_d_m": physical.nose_wheel_diameter_m,
                "nose_strut_d_m": physical.nose_strut_diameter_m,
                "main_wheel_count": physical.main_wheel_count,
                "main_wheel_d_m": physical.main_wheel_diameter_m,
                "main_strut_d_m": physical.main_strut_diameter_m,
                "gear_down": physical.gear_down,
            }
            base.update({
                key: value.value for key, value in typed_values.items()
                if value.available
            })
            # Legacy airframe formulas accept one representative wheel/strut
            # diameter; detailed nose/main values remain separately visible.
            if physical.main_wheel_diameter_m.available:
                base["wheel_d_m"] = physical.main_wheel_diameter_m.value
            if physical.main_strut_diameter_m.available:
                base["strut_d_m"] = physical.main_strut_diameter_m.value
        return base


@dataclass(frozen=True)
class EventDiagnostics:
    """Inspectability record for one event; levels are A-weighted dB."""
    lamax_db: float
    sel_db: float
    time_s: np.ndarray
    total_time_history_db: np.ndarray
    component_time_histories_db: Mapping[str, np.ndarray]
    component_metrics_db: Mapping[str, Mapping[str, float]]
    source_status: Mapping[str, InputStatus]
    input_status: Mapping[str, InputStatus]
    excluded_effects: tuple[str, ...] = (
        "installation_shielding", "nacelle_treatment", "ground_reflection",
        "lateral_attenuation", "terrain", "non_uniform_atmosphere",
    )
    uncertainty_note: str = (
        "Component anchor/model-form uncertainty is not a calibrated interval; "
        "learned-model tree dispersion is not physics uncertainty.")


class PhysicsNPDModel:
    SUPPORTED_METRICS = ("SEL", "LAmax")

    def __init__(self, c_jet=140.0, c_fan=55.0, c_wingflap=35.0, c_gear=25.0,
                 atmosphere: Atmosphere | None = None,
                 flight_path: FlightStateSource | None = None):
        self.jet = JetSource(c_jet)
        self.fan = FanSource(c_fan)
        self.airframe = AirframeSource(c_wingflap, c_gear)
        self._aw = a_weighting()
        self.atmosphere = atmosphere or Atmosphere()
        self._alpha = atmospheric_absorption(temp_c=self.atmosphere.temperature_c,
                                            rel_hum=self.atmosphere.relative_humidity_percent,
                                            pressure_kpa=self.atmosphere.pressure_kpa)
        self.flight_path = flight_path or Reference160KtFlightPath()
        self._theta = np.linspace(5.0, 175.0, 69)          # emission angles

    @staticmethod
    def _sum_spectra(spectra):
        stack = np.stack(list(spectra), axis=0)
        return 10.0 * np.log10(np.sum(10.0 ** (stack / 10.0), axis=0))

    def _atmosphere_for_design(self, design: PhysicsDesign) -> Atmosphere:
        inputs = design.atmospheric_inputs
        if inputs is None:
            return self.atmosphere
        return Atmosphere(
            float(inputs.temperature_c.or_value(
                self.atmosphere.temperature_c)),
            float(inputs.relative_humidity_percent.or_value(
                self.atmosphere.relative_humidity_percent)),
            float(inputs.pressure_kpa.or_value(
                self.atmosphere.pressure_kpa)))

    def evaluate_sources(self, design: PhysicsDesign, engine: EngineState,
                         config, state: FlightState):
        """Evaluate all enabled sources for one instantaneous flight state."""
        bands = {}
        statuses = {}

        jet_parts, jet_status = self.jet.component_spectra_with_diagnostics(
            engine, state.emission_angle_deg)
        if jet_parts:
            bands.update(jet_parts)
        else:
            bands["jet"], jet_status = self.jet.spectrum_with_diagnostics(
                engine, state.emission_angle_deg)
        statuses["jet"] = jet_status

        fan_parts, fan_status = self.fan.component_spectra_with_diagnostics(
            engine, state.emission_angle_deg)
        if fan_parts:
            bands.update(fan_parts)
        else:
            bands["fan"], fan_status = self.fan.spectrum_with_diagnostics(
                engine, state.emission_angle_deg)
        statuses["fan"] = fan_status

        core, core_status = self.jet.core_spectrum_1m(
            engine, state.emission_angle_deg)
        if core is not None:
            bands["core_combustor"] = core
        statuses["core_combustor"] = core_status

        bands.update(self.airframe.component_spectra_1m(
            state.true_airspeed_ms, config, state.emission_angle_deg))
        has_typed_airframe = design.airframe_physical_inputs is not None
        typed_airframe_supplied = (
            has_typed_airframe
            and all(value.available and value.status == "supplied"
                    for value in vars(design.airframe_physical_inputs).values())
        )
        explicit_airframe = (
            design.airframe_geometry is not None or has_typed_airframe)
        supplied_airframe = (
            typed_airframe_supplied or design.airframe_geometry is not None)
        statuses["airframe"] = InputStatus(
            "supplied" if supplied_airframe else "estimated",
            bool(supplied_airframe),
            ("typed supplied airframe geometry"
             if typed_airframe_supplied else
             "typed concept-stage geometry"
             if has_typed_airframe else
             "explicit airframe geometry"
             if explicit_airframe else
             "legacy weight/configuration geometry fallback"))
        return bands, statuses

    @staticmethod
    def _metric_pair(level_history, time_s):
        lamax = float(np.max(level_history))
        sel = float(10.0 * np.log10(np.trapezoid(
            10.0 ** (level_history / 10.0), time_s)))
        return {"LAmax": lamax, "SEL": sel}

    @staticmethod
    def _rollup_component_histories(component_histories):
        groups = {
            "jet": [k for k in component_histories if k.startswith("jet")],
            "fan": [k for k in component_histories if k.startswith("fan")],
            "airframe": [
                k for k in component_histories
                if k in {"wing_trailing_edge", "slat", "flap_main_edge",
                         "flap_side_edge", "nose_landing_gear",
                         "main_landing_gear"}],
        }
        out = {}
        for group, names in groups.items():
            if names:
                stack = np.stack([component_histories[n] for n in names])
                out[group] = 10.0 * np.log10(
                    np.sum(10.0 ** (stack / 10.0), axis=0))
        return out

    def single_event_diagnostics(self, design: PhysicsDesign,
                                 thrust_per_engine_lbf, op_mode,
                                 distance_ft) -> EventDiagnostics:
        """Simulate a reference event and retain source/time-history evidence."""
        d = float(distance_ft) * FT2M
        engine = EngineState.from_design(
            thrust_per_engine_lbf * LBF2N, design.fmax_n, design.bpr,
            design.fan_diameter_m, design.n_fan_blades,
            design.jet_streams, design.fan_deck, design.core_stream,
            design.engine_physical_inputs)
        config = design.config(op_mode)
        event_atmosphere = self._atmosphere_for_design(design)
        event_alpha = atmospheric_absorption(
            temp_c=event_atmosphere.temperature_c,
            rel_hum=event_atmosphere.relative_humidity_percent,
            pressure_kpa=event_atmosphere.pressure_kpa)
        theta = self._theta
        ranges = d / np.sin(np.radians(theta))
        x_positions = -d / np.tan(np.radians(theta))
        states = [
            self.flight_path.state(
                x_m=float(x), closest_distance_m=d,
                true_airspeed_ms=NPD_REF_SPEED_MS,
                thrust_per_engine_n=engine.thrust_n,
                configuration=config, atmosphere=event_atmosphere)
            for x in x_positions
        ]
        time_s = np.array([s.time_s for s in states])
        component_levels: dict[str, np.ndarray] = {}
        source_status = {}
        n_eng_db = 10.0 * np.log10(design.n_engines)

        for i, (state, distance_m) in enumerate(zip(states, ranges)):
            spectra, statuses = self.evaluate_sources(
                design, engine, config, state)
            source_status.update(statuses)
            propagation = (
                -20.0 * np.log10(distance_m)
                - event_alpha * distance_m + self._aw)
            for name, spectrum in spectra.items():
                engine_source = (
                    name.startswith("jet") or name.startswith("fan")
                    or name == "core_combustor")
                received = spectrum + propagation
                if engine_source:
                    received = received + n_eng_db
                level = 10.0 * np.log10(
                    np.sum(10.0 ** (received / 10.0)))
                if name not in component_levels:
                    component_levels[name] = np.full(len(states), -300.0)
                component_levels[name][i] = level

        stack = np.stack(list(component_levels.values()))
        total = 10.0 * np.log10(
            np.sum(10.0 ** (stack / 10.0), axis=0))
        total_metrics = self._metric_pair(total, time_s)
        metrics = {
            name: self._metric_pair(history, time_s)
            for name, history in component_levels.items()
        }
        rollups = self._rollup_component_histories(component_levels)
        for name, history in rollups.items():
            metrics[name] = self._metric_pair(history, time_s)
        return EventDiagnostics(
            total_metrics["LAmax"], total_metrics["SEL"], time_s, total,
            component_levels, metrics, dict(source_status),
            dict(design.input_status))

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
        diagnostics = self.single_event_diagnostics(
            design, thrust_per_engine_lbf, op_mode, distance_ft)
        if return_components:
            component_lamax = {
                name: values["LAmax"]
                for name, values in diagnostics.component_metrics_db.items()}
            return diagnostics.lamax_db, diagnostics.sel_db, component_lamax
        return diagnostics.lamax_db, diagnostics.sel_db

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
