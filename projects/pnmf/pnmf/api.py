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

The Jet-only Extra Trees predictor is fitted for every metric/op-mode
combination up front. crosscheck_physics runs the fully
independent PhysicsNPDModel route (calibrated once on the A320-211, exactly as
pnmf_cli.py physics) and compares OUTPUTS only - the two routes share no
fitting.
"""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from .anp import ANPDatabase, DIST_COLS, qa_check
from .core import (
    NPDTable,
    ParametricAircraft,
    evaluate_aircraft_inputs,
    fleet_input_envelope,
)
from .models import SurrogateNPDModel
from .physics_calibration import load_calibrated_model
from .physics import PhysicsDesign
from .accuracy_validation import (
    build_accuracy_validation_dataset,
    load_or_build_accuracy_dataset,
)

DEFAULT_MODEL = "et"
_PHYSICS_METRICS = ("SEL", "LAmax")   # physics route scope (no EPNL/PNLTM)

def prediction_model_identity(
    model: str = DEFAULT_MODEL, training_scope: str = "jet_merged"
) -> str:
    if training_scope != "jet_merged" or model not in ("et", "svr", "spline_ridge"):
        raise ValueError("production identity is fixed and cannot be selected")
    return f"{model}-jet_merged-jet-v2"


def canonical_power_grid(power_settings):
    """Return a validated ascending NPD power grid in lb/engine.

    NPD rows need a finite, positive and unique power coordinate. Sorting
    before learned prediction keeps the returned table and its row-wise
    uncertainty array in the same canonical order.
    """
    try:
        grid = np.asarray(power_settings, dtype=float).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise ValueError("power settings must be numeric lb/engine values") from exc
    if grid.size == 0:
        raise ValueError("power settings must contain at least one value")
    if not np.all(np.isfinite(grid)):
        raise ValueError("power settings must be finite")
    if np.any(grid <= 0):
        raise ValueError("power settings must be positive")
    grid = np.sort(grid)
    if np.any(np.diff(grid) == 0):
        raise ValueError("power settings must be unique")
    return grid


@dataclass
class NoisePrediction:
    """Result of NoisePredictor.predict: NPD tables + optional uncertainty,
    with ANP-CSV export and an independent physics cross-check."""
    aircraft: ParametricAircraft
    tables: dict          # (metric, op_mode) -> NPDTable
    uncertainty: dict     # (metric, op_mode) -> (P,10) std array or None
    metadata: dict = field(default_factory=dict)
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
        """Run the independent calibrated PhysicsNPDModel on this aircraft
        and return the mean absolute difference in dB for SEL and LAmax.

        The physics model is calibrated once on the A320-211 and frozen; it
        uses no machine learning and shares no weights with the predictor.
        """
        phys = self._calibrated_physics()
        des = PhysicsDesign(
            self.aircraft.name,
            self.aircraft.n_engines,
            self.aircraft.max_static_thrust_lb,
            float(bpr or self.aircraft.bypass_ratio or 11.0),
            self.aircraft.mtow_lb,
            wing_area_m2=self.aircraft.wing_area_m2,
            span_m=self.aircraft.wing_span_m,
            fan_diameter_m=self.aircraft.fan_diameter_m,
            n_wheels=self.aircraft.n_main_gear_wheels,
        )
        out = {}
        for metric in _PHYSICS_METRICS:
            deltas = []
            for om in ("A", "D"):
                tbl = self.tables.get((metric, om))
                if tbl is None:
                    continue
                phys_L = phys.predict_table(des, metric, om, tbl.P).L
                deltas.append(np.abs(phys_L - tbl.L).ravel())
            if deltas:
                out[metric] = float(np.mean(np.concatenate(deltas)))
        return out

    def _calibrated_physics(self):
        if self._predictor is not None:
            return self._predictor._calibrated_physics()
        return load_calibrated_model()

    def physics_diagnostics(self, design, thrust_per_engine_lbf, op_mode,
                            distance_ft):
        """Run one inspectable event through the independently calibrated
        component-physics route.

        ``design`` is a :class:`PhysicsDesign`; learned-model tables are not
        used as inputs. They may be compared with the returned diagnostics by
        a caller, but the two prediction routes remain independently fitted.
        """
        if self._predictor is None:
            raise RuntimeError(
                "physics diagnostics require a prediction created by "
                "NoisePredictor")
        return self._predictor._calibrated_physics().single_event_diagnostics(
            design, thrust_per_engine_lbf, op_mode, distance_ft)

    def physics_table(self, design, metric, op_mode, power_settings_lbf):
        """Emit a component-physics NPD table using the frozen calibration."""
        if self._predictor is None:
            raise RuntimeError(
                "physics tables require a prediction created by NoisePredictor")
        return self._predictor._calibrated_physics().predict_table(
            design, metric, op_mode, power_settings_lbf)


from .jet_features import JET_V2_SCHEMA_ID, JET_V3_SCHEMA_ID

class NoisePredictor:
    def __init__(self, root=".",
                 metrics=("SEL", "LAmax", "EPNL", "PNLTM"),
                 op_modes=("A", "D"), random_state=0,
                 *, learner=DEFAULT_MODEL, scope="jet_merged",
                 prioritize_verified=True,
                 schema_id=JET_V2_SCHEMA_ID):
        self.db = ANPDatabase(root)
        self.input_envelope = fleet_input_envelope(self.db.aircraft)
        self.model_name = learner
        self.training_scope = scope
        self.prioritize_verified = bool(prioritize_verified)
        self.schema_id = schema_id
        self.metrics = tuple(metrics)
        self.op_modes = tuple(op_modes)
        self.model = SurrogateNPDModel(
            random_state=random_state,
            learner=learner,
            training_scope=scope,
            prioritize_verified=prioritize_verified,
            schema_id=schema_id,
        )
        self.model.fit_all(self.db, metrics=self.metrics, op_modes=self.op_modes)
        self.training_metadata = dict(self.model.training_metadata)
        if (learner in ("et", "svr", "spline_ridge")) and scope == "jet_merged":
            self.training_metadata["model_identity"] = prediction_model_identity(
                learner, scope
            )
        else:
            self.training_metadata["model_identity"] = f"{learner}-{scope}-custom"
        self._combos = [(m, om) for m in self.metrics for om in self.op_modes
                        if self.db.list_curve_sets(m, om)]
        self._physics = None
        self.physics_calibration_artifact = None

    # ---- default per-mode power grid (lb, per engine) -------------------
    def _default_power(self, aircraft, op_mode):
        T = aircraft.max_static_thrust_lb
        if op_mode == "D":
            return np.round(np.linspace(0.45 * T, 0.95 * T, 4))
        return np.round(np.linspace(0.07 * T, 0.35 * T, 3))

    def _predict_one(self, aircraft, metric, om, P):
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
                power_settings=None, progress_callback=None,
                **kwargs) -> NoisePrediction:
        """Predict NPD tables for all fitted metric/op combinations.

        aircraft: a ParametricAircraft, or pass its fields as **kwargs.
        power_settings: optional explicit NPD row powers in lb/engine. A
        sequence is applied to every mode for backward compatibility; a
        mapping such as ``{"D": [18000, 24000], "A": [3000, 6000]}``
        supplies separate departure/approach grids. Missing mapping entries
        use that mode's existing default grid. Every selected grid is
        canonicalized to finite, positive, unique ascending floats before
        learned prediction.

        ``progress_callback`` is an optional read-only UI/CLI hook receiving
        ``(event_name, details_dict)`` before and after each metric/operation
        table. It does not affect model inputs or results."""
        if aircraft is None:
            supplied_engine_type = kwargs.pop("engine_type", "Jet")
            if supplied_engine_type != "Jet":
                raise ValueError(
                    "Jet-only production prediction accepts Jet aircraft only"
                )
            aircraft = ParametricAircraft(**kwargs)
        if aircraft.engine_type != "Jet":
            raise ValueError("Jet-only production prediction accepts Jet aircraft only")
        input_findings = evaluate_aircraft_inputs(aircraft, self.input_envelope)
        input_errors = [
            finding["message"] for finding in input_findings
            if finding["level"] == "error"
        ]
        if input_errors:
            raise ValueError(
                "aircraft is outside the supported Jet input envelope: "
                + " ".join(input_errors)
            )
        tables, unc = {}, {}
        total = len(self._combos)
        for index, (metric, om) in enumerate(self._combos, start=1):
            requested = (power_settings.get(om)
                         if isinstance(power_settings, Mapping)
                         else power_settings)
            P = canonical_power_grid(
                self._default_power(aircraft, om)
                if requested is None else requested)
            details = {
                "index": index, "total": total, "metric": metric,
                "op_mode": om, "powers_lbf": P.tolist(),
            }
            if progress_callback is not None:
                progress_callback("combo_start", details)
            tbl, std = self._predict_one(aircraft, metric, om, P)
            tables[(metric, om)] = tbl
            unc[(metric, om)] = std
            if progress_callback is not None:
                progress_callback("combo_done", {
                    **details,
                    "rows": int(len(tbl.P)),
                    "distances": int(tbl.L.shape[1]),
                    "uncertainty": std is not None,
                })
        if progress_callback is not None:
            progress_callback(
                "prediction_done",
                {"tables": len(tables), "aircraft": aircraft.name})
        metadata = dict(getattr(self, "training_metadata", {}))
        metadata["input_findings"] = input_findings
        return NoisePrediction(
            aircraft, tables, unc, metadata=metadata, _predictor=self)

    def _calibrated_physics(self):
        if self._physics is None:
            self._physics, self.physics_calibration_artifact = \
                load_calibrated_model()
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
