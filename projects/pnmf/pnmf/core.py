"""The parametric aircraft definition - the framework's input object.

This is the "parameterized aircraft" from the ADP brief: geometry, propulsion
and configuration descriptors that drive noise. It is deliberately aligned with
the parameters actually available in the ANP database so that the surrogate can
be trained and validated on real aircraft, while leaving room for the extra
geometric variables (span, wing area, fan diameter, BPR ...) that a future /
conceptual aircraft synthesis tool (PrADO, CPACS, RCAIDE) would supply.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import numpy as np

ENGINE_TYPES = ["Jet"]

# Canonical future-concept demo aircraft, used by pnmf_cli.py predict/physics/demo/report.
FUTURE_UHBR_TWIN = dict(
    name="FUTURE-UHBR-TWIN", n_engines=4,
    max_static_thrust_lb=75000.0, mtow_lb=370000.0, mlw_lb=445000.0,
    bypass_ratio=15.0, noise_chapter=4,
)


@dataclass
class ParametricAircraft:
    # --- identity ---
    name: str = "GENERIC"

    # --- propulsion (primary noise drivers, available in ANP) ---
    engine_type: str = field(default="Jet", init=False)
    n_engines: int = 2
    max_static_thrust_lb: float = 30000.0   # per-engine sea-level static thrust
    # optional richer propulsion params (used by semi-empirical layer if given;
    # a conceptual-design tool would populate these)
    bypass_ratio: Optional[float] = None
    fan_diameter_m: Optional[float] = None
    fan_tip_mach: Optional[float] = None

    # --- weights ---
    mtow_lb: float = 155000.0
    mlw_lb: float = 137000.0

    # --- airframe geometry (optional; future-concept extension) ---
    wing_area_m2: Optional[float] = None
    wing_span_m: Optional[float] = None
    n_main_gear_wheels: Optional[int] = None

    # --- certification / housekeeping ---
    noise_chapter: int = 4

    # -----------------------------------------------------------------
    def __post_init__(self) -> None:
        if int(self.n_engines) <= 0:
            raise ValueError("Jet engine count must be positive")
        if float(self.max_static_thrust_lb) <= 0:
            raise ValueError("Jet static thrust must be positive")

    def feature_vector(self) -> dict:
        """Numeric features consumed by the surrogate / semi-empirical models.

        Uses only quantities that exist for every ANP aircraft so the model can
        be validated leave-one-out on the real population.
        """
        mlw_mtow = self.mlw_lb / self.mtow_lb if self.mtow_lb else np.nan
        total_thrust = self.max_static_thrust_lb * self.n_engines
        return {
            "n_engines": float(self.n_engines),
            "log_mtow": np.log10(self.mtow_lb),
            "log_mlw": np.log10(self.mlw_lb),
            "mlw_mtow": mlw_mtow,
            "log_thrust_per_eng": np.log10(max(self.max_static_thrust_lb, 1.0)),
            "log_total_thrust": np.log10(max(total_thrust, 1.0)),
            "noise_chapter": float(self.noise_chapter),
        }

    @staticmethod
    def feature_names():
        return ["n_engines", "log_mtow", "log_mlw", "mlw_mtow",
                "log_thrust_per_eng", "log_total_thrust", "noise_chapter"]

    @classmethod
    def from_anp_row(cls, npd_id: str, row) -> "ParametricAircraft":
        """Build a ParametricAircraft from an ANP parametric-table row."""
        engine_type = str(row["Engine Type"])
        if engine_type != "Jet":
            raise ValueError(
                f"ParametricAircraft is Jet-only; {npd_id} has engine type "
                f"{engine_type!r}"
            )
        return cls(
            name=str(row.get("Description", npd_id)),
            n_engines=int(row["Number Of Engines"]),
            max_static_thrust_lb=float(row["Max Sea Level Static Thrust (lb)"]),
            mtow_lb=float(row["Max Gross Takeoff Weight (lb)"]),
            mlw_lb=float(row["Max Gross Landing Weight (lb)"]),
            noise_chapter=int(row["Noise Chapter"]) if not np_isnan(row["Noise Chapter"]) else 4,
        )

    def to_dict(self):
        return asdict(self)


def np_isnan(x):
    try:
        return np.isnan(x)
    except TypeError:
        return False


# ===========================================================================
# Input realism checker
# ===========================================================================
# The parametric inputs drive the whole prediction; values that individually
# pass the form's per-field bounds can still combine into something no real
# aircraft resembles (e.g. a huge thrust-to-weight ratio), which pushes the
# models far outside their ANP training range and makes the NPD graphs absurd.
# We derive a realistic envelope from the real ANP fleet (not hardcoded magic
# numbers) and flag inputs against it. Two severity levels drive handling:
# "error" = physically impossible / absurd, "warning" = unusual / extrapolating.
# Hard errors gate learned prediction; warnings still admit novel future concepts.

# ANP aircraft-table column names (as loaded by ANPDatabase).
_AC_ET = "Engine Type"
_AC_N = "Number Of Engines"
_AC_MTOW = "Max Gross Takeoff Weight (lb)"
_AC_MLW = "Max Gross Landing Weight (lb)"
_AC_THR = "Max Sea Level Static Thrust (lb)"


def _band(values):
    """(p1, p99, min, max) of a finite 1-D array; None if empty."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return None
    return (float(np.percentile(v, 1)), float(np.percentile(v, 99)),
            float(v.min()), float(v.max()))


def fleet_input_envelope(aircraft_df) -> dict:
    """Realistic-input envelope derived from the real ANP aircraft table.

    Returns per engine type: thrust-per-engine and MTOW bands (p1/p99/min/max),
    the thrust-to-weight and MLW/MTOW ratio bands, and the observed engine-count
    set. `evaluate_aircraft_inputs` scores a ParametricAircraft against this.
    Pass `ANPDatabase(root).aircraft`.
    """
    df = aircraft_df
    env: dict = {"per_type": {}}
    for et in ENGINE_TYPES:
        s = df[df[_AC_ET] == et]
        n = s[_AC_N].to_numpy(dtype=float)
        thr = s[_AC_THR].to_numpy(dtype=float)
        mtow = s[_AC_MTOW].to_numpy(dtype=float)
        mlw = s[_AC_MLW].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            tw = (n * thr) / mtow
            mm = mlw / mtow
        env["per_type"][et] = {
            "n_samples": int(len(s)),
            "thr": _band(thr),
            "mtow": _band(mtow),
            "tw": _band(tw),
            "mlw_mtow": _band(mm),
            "n_set": sorted({int(x) for x in n if np.isfinite(x)}),
        }
    return env


def evaluate_aircraft_inputs(aircraft, envelope) -> list:
    """Score a ParametricAircraft against the fleet `envelope`.

    Returns a list of findings, each {"level": "error"|"warning", "field": str,
    "message": str}, most-severe first. "error" means physically impossible or
    so far outside the fleet the prediction is meaningless; "warning" means
    unusual / extrapolating but plausible. Empty list == inputs look realistic.
    """
    ac = aircraft
    out = []

    def err(field, msg):
        out.append({"level": "error", "field": field, "message": msg})

    def warn(field, msg):
        out.append({"level": "warning", "field": field, "message": msg})

    thr = float(ac.max_static_thrust_lb)
    mtow = float(ac.mtow_lb)
    mlw = float(ac.mlw_lb)
    n_eng = int(ac.n_engines)
    et = ac.engine_type

    # --- hard physical impossibilities ------------------------------------
    if thr <= 0:
        err("thrust", "Static thrust must be positive.")
    if mtow <= 0:
        err("mtow", "MTOW must be positive.")
    if mlw <= 0:
        err("mlw", "MLW must be positive.")
    if thr <= 0 or mtow <= 0 or mlw <= 0:
        return out  # ratios below would be meaningless

    per_type = envelope.get("per_type", {})
    e = per_type.get(et) or {}

    # --- thrust per engine vs its engine type -----------------------------
    band = e.get("thr")
    if band:
        p1, p99, lo, hi = band
        if thr > 2.5 * hi or thr < 0.3 * lo:
            err("thrust", f"{thr:,.0f} lb/engine is far outside anything a "
                          f"'{et}' has in the ANP fleet "
                          f"({lo:,.0f} to {hi:,.0f} lb); likely the wrong engine "
                          f"type or a typo.")
        elif thr > p99 or thr < p1:
            warn("thrust", f"{thr:,.0f} lb/engine is unusual for a '{et}' "
                           f"(typical {p1:,.0f}–{p99:,.0f} lb).")

    # --- thrust-to-weight ratio -------------------------------------------
    tw = (n_eng * thr) / mtow
    twband = e.get("tw")
    if tw > 1.5 or tw < 0.05:
        err("thrust", f"Thrust-to-weight ratio {tw:.2f} is not physical for a "
                      f"transport aircraft; check thrust, engine count and "
                      f"MTOW.")
    elif twband and (tw > twband[1] or tw < twband[0]):
        warn("thrust", f"Thrust-to-weight ratio {tw:.2f} is outside the real "
                       f"fleet range ({twband[0]:.2f}–{twband[1]:.2f}); the "
                       f"prediction extrapolates.")

    # --- MLW vs MTOW ------------------------------------------------------
    ratio = mlw / mtow
    if ratio > 1.6 or ratio < 0.3:
        err("mlw", f"MLW is {ratio:.2f} times MTOW; outside anything physical; "
                   f"check both weights.")
    elif ratio > 1.0:
        warn("mlw", f"MLW exceeds MTOW ({ratio:.2f} times); allowed but unusual "
                    f"(the shipped preset is like this).")

    # --- MTOW vs its engine type ------------------------------------------
    mband = e.get("mtow")
    if mband:
        p1, p99, lo, hi = mband
        if mtow > 2.0 * hi or mtow < 0.3 * lo:
            err("mtow", f"MTOW {mtow:,.0f} lb is far outside the '{et}' fleet "
                        f"({lo:,.0f}–{hi:,.0f} lb).")
        elif mtow > p99 or mtow < p1:
            warn("mtow", f"MTOW {mtow:,.0f} lb is unusual for a '{et}' "
                         f"(typical {p1:,.0f}–{p99:,.0f} lb).")

    # --- engine count vs its engine type ----------------------------------
    n_set = e.get("n_set") or []
    if n_set and n_eng not in n_set:
        warn("n_engines", f"{n_eng} engines is not seen on any '{et}' in the "
                          f"fleet (seen: {n_set}).")

    # --- optional cycle sanity -------------------------------------------
    if ac.bypass_ratio is not None:
        if et != "Jet":
            warn("bypass_ratio", f"Bypass ratio is a turbofan parameter; '{et}' "
                                 f"is not a jet.")
        elif ac.bypass_ratio > 18:
            warn("bypass_ratio", f"Bypass ratio {ac.bypass_ratio:.0f} is beyond "
                                 f"even ultra-high-bypass designs (~15–18).")

    out.sort(key=lambda f: 0 if f["level"] == "error" else 1)
    return out


# ===========================================================================
# section: npd (merged)
# ===========================================================================

"""NPD table object - the framework OUTPUT, in ANP/Doc 29-equivalent form.

An NPD curve gives a single-event noise level (SEL, L_Amax, EPNL, PNLTM) versus
slant distance at a set of engine power (thrust) settings, for one operational
mode (Approach / Departure). This class stores that grid and implements the
Doc 29 lookup rule: linear interpolation/extrapolation on power (thrust),
logarithmic interpolation on distance.
"""
import numpy as np

STANDARD_DISTANCES_FT = np.array(
    [200, 400, 630, 1000, 2000, 4000, 6300, 10000, 16000, 25000], dtype=float)


class NPDTable:
    def __init__(self, power_settings, levels, metric, op_mode,
                 distances_ft=STANDARD_DISTANCES_FT, npd_id="", power_param="CNT (lb)"):
        """
        power_settings : (P,) array of thrust settings (per engine)
        levels         : (P, 10) array of dB at the standard distances
        """
        self.P = np.asarray(power_settings, float)
        self.L = np.asarray(levels, float)
        self.d = np.asarray(distances_ft, float)
        self.logd = np.log10(self.d)
        self.metric = metric
        self.op_mode = op_mode
        self.npd_id = npd_id
        self.power_param = power_param
        order = np.argsort(self.P)
        self.P, self.L = self.P[order], self.L[order]

    # ---- Doc 29 lookup --------------------------------------------------
    def level(self, power, distance_ft) -> float:
        """Interpolated level: linear on power, log on distance (Doc 29)."""
        power = float(power)
        ld = np.log10(float(distance_ft))
        # interpolate each power row in log-distance, then interpolate on power
        row_levels = np.array([np.interp(ld, self.logd, self.L[i],
                                         left=self._extrap_low(self.L[i], ld),
                                         right=self._extrap_high(self.L[i], ld))
                               for i in range(len(self.P))])
        if len(self.P) == 1:
            return float(row_levels[0])
        # linear in power, with linear extrapolation outside the tabulated range
        return float(_interp_extrap(power, self.P, row_levels))

    def _extrap_low(self, lvec, ld):
        # linear extrapolation in log-distance below 200 ft
        slope = (lvec[1] - lvec[0]) / (self.logd[1] - self.logd[0])
        return lvec[0] + slope * (ld - self.logd[0])

    def _extrap_high(self, lvec, ld):
        slope = (lvec[-1] - lvec[-2]) / (self.logd[-1] - self.logd[-2])
        return lvec[-1] + slope * (ld - self.logd[-1])

    def as_array(self):
        return self.P.copy(), self.L.copy()

    def __repr__(self):
        return (f"NPDTable({self.npd_id} {self.metric}/{self.op_mode}, "
                f"{len(self.P)} power settings, {self.L.shape[1]} distances)")


def _interp_extrap(x, xp, fp):
    """Linear interpolation with linear extrapolation at both ends."""
    if x <= xp[0]:
        slope = (fp[1] - fp[0]) / (xp[1] - xp[0])
        return fp[0] + slope * (x - xp[0])
    if x >= xp[-1]:
        slope = (fp[-1] - fp[-2]) / (xp[-1] - xp[-2])
        return fp[-1] + slope * (x - xp[-1])
    return np.interp(x, xp, fp)
