"""Production facade: one call from a parametric aircraft to NPD-equivalent
noise tables, uncertainty, an ANP-layout CSV, and an independent physics
cross-check.

    from pnmf import NoisePredictor
    pred = NoisePredictor(root=".")          # loads ANP db, fits the winner
    result = pred.predict(aircraft)          # ParametricAircraft or **kwargs
    result.tables[("SEL", "D")]              # NPDTable
    result.uncertainty[("SEL", "D")]         # (P,10) cross-tree std, or None
    result.to_anp_csv("out.csv")             # strict ANP layout
    result.crosscheck_physics(bpr=15.0)      # {metric: mean |delta| dB}

The winning predictor (see pnmf_cli.py compare) is fitted for every
metric/op-mode combination up front. crosscheck_physics runs the fully
independent PhysicsNPDModel route (calibrated once on the A320-211, exactly as
pnmf_cli.py physics) and compares OUTPUTS only - the two routes share no
fitting.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from .anp import ANPDatabase, DIST_COLS, qa_check
from .core import ParametricAircraft
from .core import NPDTable
from .models import SurrogateNPDModel
from .physics import PhysicsNPDModel, PhysicsDesign

# Winner of the 2026-07-15 legacy-corpus leave-one-aircraft-out bake-off:
# ET 2.99 dB vs RF 3.04 dB mean per-aircraft median RMSE. Expanded-corpus
# results are validation evidence, not a reason to change this default silently.
DEFAULT_MODEL = "et"
_CALIBRATION_ACFT = "A320-211"
_CALIBRATION_BPR = 6.0
_PHYSICS_METRICS = ("SEL", "LAmax")   # physics route scope (no EPNL/PNLTM)

_FACTORIES = {
    "rf":      lambda rs: SurrogateNPDModel("rf", random_state=rs),
    "et":      lambda rs: SurrogateNPDModel("et", random_state=rs),
}


@dataclass
class NoisePrediction:
    """Result of NoisePredictor.predict: NPD tables + optional uncertainty,
    with ANP-CSV export and an independent physics cross-check."""
    aircraft: ParametricAircraft
    tables: dict          # (metric, op_mode) -> NPDTable
    uncertainty: dict     # (metric, op_mode) -> (P,10) std array or None
    _predictor: "NoisePredictor | None" = field(repr=False, default=None)

    def to_anp_csv(self, path):
        """Write the strict ANP layout: NPD_ID, Noise Metric, Op Mode,
        Power Setting, then the ten standard-distance columns (rounded 0.1 dB)."""
        rows = []
        for (metric, om), tbl in self.tables.items():
            for i, P in enumerate(tbl.P):
                r = {"NPD_ID": self.aircraft.name, "Noise Metric": metric,
                     "Op Mode": om, "Power Setting": float(P)}
                r.update({c: round(float(tbl.L[i, j]), 1)
                          for j, c in enumerate(DIST_COLS)})
                rows.append(r)
        cols = ["NPD_ID", "Noise Metric", "Op Mode", "Power Setting"] + DIST_COLS
        df = pd.DataFrame(rows)[cols]
        df.to_csv(path, index=False)
        return df

    def crosscheck_physics(self, bpr=None):
        """Independent PhysicsNPDModel (pyNA-family) route vs the primary
        prediction. Returns {metric: mean |delta| in dB} over the shared cells
        for the physics-scope metrics (SEL, LAmax; EPNL is out of physics
        scope). bpr defaults to the aircraft's bypass_ratio (else 6.0)."""
        if bpr is None:
            bpr = self.aircraft.bypass_ratio or _CALIBRATION_BPR
        assert self._predictor is not None  # set by NoisePredictor.predict
        phys = self._predictor._calibrated_physics()
        ac = self.aircraft
        des = PhysicsDesign(ac.name, ac.n_engines, ac.max_static_thrust_lb,
                            bpr, ac.mtow_lb, wing_area_m2=ac.wing_area_m2,
                            span_m=ac.wing_span_m,
                            fan_diameter_m=ac.fan_diameter_m,
                            n_wheels=ac.n_main_gear_wheels)
        out = {}
        for metric in _PHYSICS_METRICS:
            deltas = []
            for (m, om), tbl in self.tables.items():
                if m != metric:
                    continue
                phys_L = phys.predict_table(des, metric, om, tbl.P).L
                deltas.append(np.abs(phys_L - tbl.L).ravel())
            if deltas:
                out[metric] = float(np.mean(np.concatenate(deltas)))
        return out


class NoisePredictor:
    """One-call NPD noise predictor. Fits the winning model for every
    metric/op-mode combination on construction."""

    def __init__(self, root=".", model=DEFAULT_MODEL,
                 metrics=("SEL", "LAmax", "EPNL", "PNLTM"),
                 op_modes=("A", "D"), random_state=0):
        if model not in _FACTORIES:
            raise ValueError(f"unknown model {model!r}; choose from "
                             f"{sorted(_FACTORIES)}. PhysicsNPDModel is a "
                             "separate component-physics cross-check.")
        self.db = ANPDatabase(root)
        self.model_name = model
        self.metrics = tuple(metrics)
        self.op_modes = tuple(op_modes)
        self.model = _FACTORIES[model](random_state)
        self.model.fit_all(self.db, metrics=self.metrics, op_modes=self.op_modes)
        self._combos = [(m, om) for m in self.metrics for om in self.op_modes
                        if self.db.list_curve_sets(m, om)]
        self._physics = None      # lazily calibrated on first cross-check

    # ---- default per-mode power grid (lb, per engine) -------------------
    def _default_power(self, aircraft, op_mode):
        T = aircraft.max_static_thrust_lb
        if op_mode == "D":
            return np.round(np.linspace(0.45 * T, 0.95 * T, 4))
        return np.round(np.linspace(0.07 * T, 0.35 * T, 3))

    def _predict_one(self, aircraft, metric, om, P):
        """Predict one table, capturing cross-tree std when the model exposes
        it (RF-based models); semi-empirical returns std=None."""
        try:
            out = self.model.predict_table(aircraft, metric, om, P,
                                           return_std=True,
                                           power_parameter="CNT (lb)")
        except TypeError:
            out = self.model.predict_table(aircraft, metric, om, P,
                                           power_parameter="CNT (lb)")
        if isinstance(out, tuple):
            return out[0], out[1]
        return out, None

    def predict(self, aircraft: ParametricAircraft | None = None,
                power_settings=None, **kwargs) -> NoisePrediction:
        """Predict NPD tables for all fitted metric/op combinations.

        aircraft: a ParametricAircraft, or pass its fields as **kwargs.
        power_settings: optional explicit thrust grid (lb/engine) applied to
        every combination; otherwise a per-mode default grid is derived from
        the aircraft's static thrust (departure high, approach low)."""
        if aircraft is None:
            aircraft = ParametricAircraft(**kwargs)
        tables, unc = {}, {}
        for metric, om in self._combos:
            P = (np.atleast_1d(np.asarray(power_settings, float))
                 if power_settings is not None
                 else self._default_power(aircraft, om))
            tbl, std = self._predict_one(aircraft, metric, om, P)
            tables[(metric, om)] = tbl
            unc[(metric, om)] = std
        return NoisePrediction(aircraft, tables, unc, _predictor=self)

    def _calibrated_physics(self):
        if self._physics is None:
            m = PhysicsNPDModel()
            m.calibrate(self.db, _CALIBRATION_ACFT, bpr=_CALIBRATION_BPR,
                        verbose=False)
            self._physics = m
        return self._physics


# ---------------------------------------------------------------------------
# real-vs-future comparison table (pure function: no plotting, no writes)
# ---------------------------------------------------------------------------

def real_vs_future_table(db, prediction, crosscheck=None, n_neighbors=3,
                         ref_distance_ft=1000.0):
    """Compare a NoisePrediction against its nearest real ANP aircraft.

    For every (metric, op_mode) table in `prediction`, evaluates the future
    aircraft and its n nearest NPD-curve neighbours at `ref_distance_ft`,
    each at its OWN representative power row (highest tabulated for "D",
    lowest for "A") - power parameters are not unit-comparable across
    aircraft (lbf vs %RPM ...), so raw settings are never compared directly.
    crosscheck: optional {metric: mean |delta| dB} from crosscheck_physics.
    Returns one DataFrame row per (metric:mode x neighbour)."""
    crosscheck = crosscheck or {}
    ac = prediction.aircraft
    neighbors = db.nearest_npd_ids(ac.mtow_lb, ac.engine_type, ac.n_engines,
                                   n=n_neighbors)
    rows = []
    for (metric, om), tbl in sorted(prediction.tables.items()):
        p_future = tbl.P[-1] if om == "D" else tbl.P[0]
        future_level = tbl.level(p_future, ref_distance_ft)
        std = prediction.uncertainty.get((metric, om))
        mean_sigma = float(np.mean(std)) if std is not None else float("nan")
        status, _ = qa_check(tbl.P, tbl.L, std,
                             crosscheck_db=crosscheck.get(metric))
        xcheck = float(crosscheck.get(metric, float("nan")))
        for acft_id, npd_id in neighbors:
            cv = db.curve(npd_id, metric, om)
            if cv.empty:
                continue
            nb = NPDTable(cv['Power Setting'].values.astype(float),
                          cv[DIST_COLS].values, metric, om, npd_id=npd_id)
            p_nb = nb.P[-1] if om == "D" else nb.P[0]
            nb_level = nb.level(p_nb, ref_distance_ft)
            rows.append({
                "metric": metric, "op_mode": om,
                "future_level_db": future_level,
                "mean_sigma_db": mean_sigma,
                "qa_status": status,
                "physics_crosscheck_db": xcheck,
                "neighbor_acft_id": acft_id,
                "neighbor_npd_id": npd_id,
                "neighbor_level_db": nb_level,
                "delta_db": future_level - nb_level,
            })
    cols = ["metric", "op_mode", "future_level_db", "mean_sigma_db",
            "qa_status", "physics_crosscheck_db", "neighbor_acft_id",
            "neighbor_npd_id", "neighbor_level_db", "delta_db"]
    return pd.DataFrame(rows, columns=cols)
