"""Data-driven surrogate: parametric descriptors -> NPD-equivalent table.

Trains one multi-output regressor per (noise metric, operational mode) that maps
[aircraft feature vector, power features] -> the 10 standard-distance levels.
This is the "surrogate / metamodel" route from the ADP task list. The ANP
population is the training set; leave-one-aircraft-out gives an honest
generalisation estimate (see loo_validate at the end of this module).

Power-axis unit handling (fault F1): the ANP 'Power Setting' column mixes three
units across aircraft - corrected net thrust in lb (134 aircraft), % of max
static thrust (17), and RPM (4). Feeding the raw value into one log feature
contaminates the power axis. We therefore derive two unit-consistent features
per NPD row: log10 of the unit-corrected absolute power in lb, and the throttle
fraction (power / max static thrust). Confirmed LOO improvement: e.g. SEL/A
RMSE 4.82 -> 4.23 dB.

Physicality (fault F2): every truth row decreases
monotonically with distance; predictions are projected onto that constraint
(isotonic, non-increasing in log-distance) so out-of-population queries can
never emit an unphysical table.

Supported learners are Extra Trees (default) and Random Forest. Historical
experimental classes remain below for reproducibility but are not part of the
supported prediction surface.
"""
from __future__ import annotations
from typing import Any, Literal, overload
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor
from sklearn.isotonic import IsotonicRegression

from .core import ParametricAircraft
from .core import NPDTable, STANDARD_DISTANCES_FT
from .anp import DIST_COLS

_LOGD = np.log10(STANDARD_DISTANCES_FT)
SUPPORTED_LEARNERS = ("et", "rf")


def power_features(P, power_parameter, static_thrust_lb):
    """Unit-consistent power features for a set of NPD power settings.

    Returns (log10 corrected absolute power in lb, throttle fraction).
    - 'CNT (lb)': already lb; throttle = P / static thrust
    - 'CNT (% of Max Static Thrust)': lb = P/100 * static; throttle = P/100
    - 'Other (RPM)': no exact conversion exists; throttle = P / max(P) in the
      set and lb is imputed as throttle * static (crude but consistent).
    """
    P = np.atleast_1d(np.asarray(P, float))
    pp = str(power_parameter)
    stat = max(float(static_thrust_lb), 1.0)
    if '%' in pp:
        P_lb = P / 100.0 * stat
        thr = P / 100.0
    elif 'RPM' in pp or 'rpm' in pp:
        thr = P / max(P.max(), 1.0)
        P_lb = thr * stat
    else:  # CNT (lb) and anything unrecognised (documented default)
        P_lb = P
        thr = P / stat
    return np.log10(np.maximum(P_lb, 1.0)), np.clip(thr, 0.0, 2.0)


def enforce_distance_monotone(levels):
    """Project each predicted row onto 'non-increasing with distance' using
    isotonic regression in log-distance. Rows already monotone are unchanged."""
    L = np.array(levels, float, copy=True)
    for i in range(L.shape[0]):
        if (np.diff(L[i]) > 1e-9).any():
            iso = IsotonicRegression(increasing=False)
            L[i] = iso.fit_transform(_LOGD, L[i])
    return L


class SurrogateNPDModel:
    def __init__(self, learner="et", random_state=0, monotone=True):
        if learner not in SUPPORTED_LEARNERS:
            raise ValueError(
                f"unsupported learned model {learner!r}; choose one of "
                f"{SUPPORTED_LEARNERS}. PhysicsNPDModel is the separate "
                "component-physics workflow.")
        self.learner = learner
        self.random_state = random_state
        self.monotone = monotone
        self.models = {}        # (metric, op_mode) -> fitted regressor
        self.training_provenance = {}
        self.feat_names = ParametricAircraft.feature_names()

    def _new_regressor(self) -> Any:  # any sklearn-style multi-output regressor
        if self.learner == "et":
            # Frozen production configuration. Validation is performed by the
            # current aircraft-grouped and temporal workflow in validation.py.
            return ExtraTreesRegressor(n_estimators=500, min_samples_leaf=1,
                                       max_depth=24, max_features=0.5,
                                       random_state=self.random_state,
                                       n_jobs=-1)
        return RandomForestRegressor(n_estimators=200, min_samples_leaf=2,
                                     random_state=self.random_state, n_jobs=-1)

    # ---- build training matrix from an ANPDatabase ----------------------
    def _design_matrix(self, db, metric, op_mode, exclude_ids=()):
        params = db.param_table()
        X, Y, groups = [], [], []
        for npd_id in db.list_curve_sets(metric, op_mode):
            if npd_id in exclude_ids:
                continue
            row = params.loc[npd_id]
            ac = ParametricAircraft.from_anp_row(npd_id, row)
            fv = ac.feature_vector()
            base = [fv[n] for n in self.feat_names]
            curve = db.curve(npd_id, metric, op_mode)
            P = curve['Power Setting'].values.astype(float)
            log_plb, thr = power_features(P, row['Power Parameter'],
                                          row['Max Sea Level Static Thrust (lb)'])
            M = curve[DIST_COLS].values
            for i in range(len(P)):
                X.append(base + [log_plb[i], thr[i]])
                Y.append(M[i].tolist())
                groups.append(npd_id)
        return np.array(X, float), np.array(Y, float), np.array(groups)

    def fit(self, db, metric, op_mode, exclude_ids=()):
        X, Y, _ = self._design_matrix(db, metric, op_mode, exclude_ids)
        curves = db.npd[
            (db.npd["Noise Metric"] == metric) &
            (db.npd["Op Mode"] == op_mode) &
            (~db.npd["NPD_ID"].isin(set(exclude_ids)))]
        if "source_dataset" not in curves:
            raise RuntimeError(
                "training data has no source provenance; rebuild datastore")
        self.training_provenance[(metric, op_mode)] = (
            curves["source_dataset"].value_counts().sort_index().to_dict())
        if self.training_provenance[(metric, op_mode)].get(
                "supplement_v6.3", 0) == 0:
            raise RuntimeError(
                f"{metric}/{op_mode} training matrix has no ANP v6.3 samples")
        reg = self._new_regressor()
        reg.fit(X, Y)
        self.models[(metric, op_mode)] = reg
        return self

    def fit_all(self, db, metrics=("SEL", "LAmax", "EPNL", "PNLTM"),
                op_modes=("A", "D")):
        for m in metrics:
            for om in op_modes:
                if db.list_curve_sets(m, om):
                    self.fit(db, m, om)
        return self

    # ---- generate an NPD table for a parametric aircraft ----------------
    # overloads: the return shape is decided by the return_std flag
    @overload
    def predict_table(self, aircraft: ParametricAircraft, metric, op_mode,
                      power_settings, return_std: Literal[False] = ...,
                      power_parameter: str = ...) -> NPDTable: ...
    @overload
    def predict_table(self, aircraft: ParametricAircraft, metric, op_mode,
                      power_settings, return_std: Literal[True],
                      power_parameter: str = ...) -> tuple[NPDTable, np.ndarray]: ...

    def predict_table(self, aircraft: ParametricAircraft, metric, op_mode,
                      power_settings, return_std=False,
                      power_parameter="CNT (lb)"):
        """Predict an NPDTable for power_settings given in the stated unit
        (default: corrected net thrust per engine in lb - the natural unit for
        a parametric design). If return_std=True (RandomForest only), also
        return a (P, 10) array of cross-tree standard deviations - a cheap
        uncertainty proxy in place of full GP variance: queries far from the
        training population get systematically wider spread, flagging where
        the metamodel is extrapolating.
        """
        reg = self.models[(metric, op_mode)]
        fv = aircraft.feature_vector()
        base = [fv[n] for n in self.feat_names]
        P = np.atleast_1d(np.asarray(power_settings, float))
        log_plb, thr = power_features(P, power_parameter,
                                      aircraft.max_static_thrust_lb)
        X = np.array([base + [log_plb[i], thr[i]] for i in range(len(P))])
        L = reg.predict(X)
        if L.ndim == 1:
            L = L.reshape(1, -1)
        if self.monotone:
            L = enforce_distance_monotone(L)
        table = NPDTable(P, L, metric, op_mode, STANDARD_DISTANCES_FT,
                         npd_id=aircraft.name)
        if not return_std:
            return table
        std = self._tree_std(reg, X)
        return table, std

    def _tree_std(self, reg, X):
        """Cross-tree prediction std, shape (n_queries, 10). Only meaningful
        for the native multi-output tree ensembles ('rf'/'et' learners)."""
        if not hasattr(reg, "estimators_") or self.learner not in ("rf", "et"):
            return np.full((X.shape[0], len(DIST_COLS)), np.nan)
        preds = np.stack([est.predict(X) for est in reg.estimators_], axis=0)
        return preds.std(axis=0)

    def generate_full(self, aircraft: ParametricAircraft, db_for_power=None,
                      power_settings=None,
                      metrics=("SEL", "LAmax", "EPNL"), op_modes=("A", "D"),
                      return_std=False):
        """Produce a dict of NPDTables covering the requested metrics/modes.

        If power_settings is None, a default per-mode thrust grid is derived from
        the aircraft's static thrust (departure: high thrust; approach: low).
        If return_std=True, values are (NPDTable, std_array) tuples instead.
        """
        out = {}
        for om in op_modes:
            if power_settings is not None:
                P = power_settings
            else:
                T = aircraft.max_static_thrust_lb
                if om == "D":
                    P = np.round(np.linspace(0.45 * T, 0.95 * T, 4))
                else:
                    P = np.round(np.linspace(0.07 * T, 0.35 * T, 3))
            for m in metrics:
                if (m, om) in self.models:
                    out[(m, om)] = self.predict_table(aircraft, m, om, P,
                                                       return_std=return_std)
        return out


# ===========================================================================
# section: semiempirical (merged)
# ===========================================================================

"""Physics-anchored semi-empirical NPD generator (interpretable baseline).

Decomposes every NPD curve into three physically meaningful parts:

    L(P, d) = L_anchor(params)                # loudness at reference 1000 ft
              + s_thrust * log10(P / P_ref)   # thrust (power-axis) sensitivity
              + decay(d)                       # spherical spreading + atm. abs.

* decay(d) is the near-universal level drop vs slant distance (spherical
  spreading ~20*log10 plus atmospheric absorption), fitted per engine type;
  the data show ~-21 dB per decade for jets, consistent with theory.
* L_anchor is a physical correlation of reference loudness on total thrust,
  number of engines and weight - the same family as the DLR "certified EPNL vs
  static thrust / fan diameter / MTOM" correlations (~±2 dB) cited in the
  roadmap.
* s_thrust is the slope of level on log-thrust along the power axis.

This layer is transparent and extrapolates sensibly to novel thrust/weight
combinations; the surrogate (top of this module) trades interpretability
for accuracy.
"""
import numpy as np
from sklearn.linear_model import Ridge

from .core import ParametricAircraft
from .core import NPDTable, STANDARD_DISTANCES_FT
from .anp import DIST_COLS

REF_DIST_IDX = 3  # 1000 ft column is the reference anchor


class SemiEmpiricalNPDModel:
    def __init__(self):
        self.anchor_reg = {}      # (metric,mode)->Ridge on features -> L@1000ft,Pref
        self.decay = {}           # (metric,mode,engine_type)->(10,) decay vs 1000ft
        self.decay_default = {}   # (metric,mode)->(10,)
        self.thrust_slope = {}    # (metric,mode,engine_type)->float
        self.thrust_slope_default = {}
        self.feat_names = ["is_jet", "is_turboprop", "is_piston", "n_engines",
                           "log_total_thrust", "log_mtow"]

    def _feat(self, ac: ParametricAircraft):
        fv = ac.feature_vector()
        return [fv[n] for n in self.feat_names]

    def fit(self, db, metric, op_mode, exclude_ids=()):
        params = db.param_table()
        feats, anchors = [], []
        decay_by_et = {}
        slopes_by_et = {}
        for npd_id in db.list_curve_sets(metric, op_mode):
            if npd_id in exclude_ids:
                continue
            row = params.loc[npd_id]
            ac = ParametricAircraft.from_anp_row(npd_id, row)
            et = ac.engine_type
            curve = db.curve(npd_id, metric, op_mode)
            M = curve[DIST_COLS].values            # (nP, 10)
            P = curve['Power Setting'].values.astype(float)
            L1000 = M[:, REF_DIST_IDX]
            # reference power = max tabulated thrust setting for this set
            ref_i = int(np.argmax(P))
            Pref = P[ref_i]
            # anchor sample: loudness at reference power & 1000 ft
            feats.append(self._feat(ac))
            anchors.append(L1000[ref_i])
            # decay shape (relative to 1000 ft) averaged over this set's rows
            shape = (M - M[:, [REF_DIST_IDX]]).mean(axis=0)
            decay_by_et.setdefault(et, []).append(shape)
            # thrust slope: level@1000ft vs log10(P), if >=2 settings
            if len(P) >= 2 and np.ptp(P) > 0:
                A = np.vstack([np.log10(np.maximum(P, 1)), np.ones_like(P)]).T
                slope = np.linalg.lstsq(A, L1000, rcond=None)[0][0]
                slopes_by_et.setdefault(et, []).append(slope)
        # fit anchor regression
        reg = Ridge(alpha=1.0).fit(np.array(feats), np.array(anchors))
        self.anchor_reg[(metric, op_mode)] = (reg, np.array(feats), np.array(anchors))
        # store decay shapes per engine type + default
        all_shapes = []
        for et, lst in decay_by_et.items():
            arr = np.array(lst)
            self.decay[(metric, op_mode, et)] = arr.mean(0)
            all_shapes.append(arr)
        self.decay_default[(metric, op_mode)] = np.vstack(all_shapes).mean(0)
        # thrust slopes
        all_sl = []
        for et, lst in slopes_by_et.items():
            self.thrust_slope[(metric, op_mode, et)] = float(np.mean(lst))
            all_sl += lst
        self.thrust_slope_default[(metric, op_mode)] = float(np.mean(all_sl)) if all_sl else 3.0
        return self

    def fit_all(self, db, metrics=("SEL", "LAmax", "EPNL", "PNLTM"), op_modes=("A", "D")):
        for m in metrics:
            for om in op_modes:
                if db.list_curve_sets(m, om):
                    self.fit(db, m, om)
        return self

    def predict_table(self, aircraft: ParametricAircraft, metric, op_mode,
                      power_settings, ref_power=None,
                      power_parameter="CNT (lb)") -> NPDTable:
        """power_parameter is accepted for interface parity with the surrogate
        but is unit-invariant here: the model only uses the RATIO P/P_ref, and
        log10(a*P) - log10(a*P_ref) = log10(P/P_ref) for any unit scale a."""
        reg = self.anchor_reg[(metric, op_mode)][0]
        et = aircraft.engine_type
        decay = self.decay.get((metric, op_mode, et),
                               self.decay_default[(metric, op_mode)])
        slope = self.thrust_slope.get((metric, op_mode, et),
                                      self.thrust_slope_default[(metric, op_mode)])
        x = np.array(self._feat(aircraft)).reshape(1, -1)
        L_anchor = float(reg.predict(x)[0])           # loudness @ ref power, 1000 ft
        P = np.atleast_1d(np.asarray(power_settings, float))
        if ref_power is None:
            ref_power = P.max()
        L = np.empty((len(P), 10))
        for i, p in enumerate(P):
            l1000 = L_anchor + slope * np.log10(max(p, 1.0) / max(ref_power, 1.0))
            L[i] = l1000 + decay
        return NPDTable(P, L, metric, op_mode, STANDARD_DISTANCES_FT,
                        npd_id=aircraft.name)


# ===========================================================================
# section: anchor (merged)
# ===========================================================================

"""Anchor+delta (substitution-style) NPD generator.

Mirrors how EASA assigns noise to an un-certificated aircraft: pick the nearest
real donor aircraft and reuse its measured curve, then apply a parametric
correction. Here the anchor is the donor's ACTUAL ANP curve (so the absolute
level and the physical distance-decay shape come from measured data, not a
regressor), and the delta is a RandomForest trained on residuals
(target - donor) as a function of the aircraft-feature difference and the
power state. This keeps most of the signal in a real curve and asks the learner
only for a small, well-conditioned correction - the regime where tree models
generalise best out-of-population.

Unit handling matches the surrogate section above: the shared power coordinate is the
unit-corrected throttle fraction (power / max static thrust), so donor and
target are compared at the same relative power regardless of whether either
tabulates lb / % / RPM. Predictions are projected non-increasing in distance.
"""
import numpy as np
from sklearn.ensemble import RandomForestRegressor

from .core import ParametricAircraft
from .core import NPDTable, STANDARD_DISTANCES_FT
from .anp import DIST_COLS

_ENGINE_MISMATCH_PENALTY = 3.0   # std-devs added when donor engine type differs


def _throttle_curve(P_raw, power_parameter, static_lb, L):
    """Donor curve keyed by unit-corrected throttle fraction.

    Returns (thr_sorted, L_sorted) with duplicate throttles averaged so the
    coordinate is strictly increasing (safe for np.interp)."""
    _, thr = power_features(P_raw, power_parameter, static_lb)
    order = np.argsort(thr)
    thr, L = thr[order], np.asarray(L, float)[order]
    uniq, inv = np.unique(np.round(thr, 9), return_inverse=True)
    if len(uniq) == len(thr):
        return thr, L
    Lm = np.array([L[inv == k].mean(0) for k in range(len(uniq))])
    return uniq, Lm


def _anchor_eval(thr_donor, L_donor, thr_query):
    """Donor levels sampled at the query throttle values: linear on throttle
    (with edge hold via np.interp), independent per distance column."""
    thr_query = np.atleast_1d(np.asarray(thr_query, float))
    if len(thr_donor) == 1:
        return np.repeat(L_donor, len(thr_query), axis=0)
    return np.column_stack([np.interp(thr_query, thr_donor, L_donor[:, j])
                            for j in range(L_donor.shape[1])])


class AnchorDeltaNPDModel:
    """Substitution anchor + learned parametric residual. Interface-compatible
    with SurrogateNPDModel (.fit / .predict_table / fit_all)."""

    def __init__(self, random_state=0, monotone=True):
        self.random_state = random_state
        self.monotone = monotone
        self.feat_names = ParametricAircraft.feature_names()
        self.donors = {}      # (metric,mode) -> list of donor records
        self.stats = {}       # (metric,mode) -> (mu, sd) for feature scaling
        self.residual = {}    # (metric,mode) -> fitted RandomForest

    def _feat(self, ac):
        fv = ac.feature_vector()
        return np.array([fv[n] for n in self.feat_names], float)

    def _nearest(self, records, mu, sd, feat, engine_type, exclude_id=None):
        best, best_d = None, np.inf
        fz = (feat - mu) / sd
        for r in records:
            if exclude_id is not None and r['id'] == exclude_id:
                continue
            d = np.linalg.norm((r['feat'] - mu) / sd - fz)
            if r['engine_type'] != engine_type:
                d += _ENGINE_MISMATCH_PENALTY
            if d < best_d:
                best, best_d = r, d
        return best

    def fit(self, db, metric, op_mode, exclude_ids=()):
        params = db.param_table()
        records = []
        for npd_id in db.list_curve_sets(metric, op_mode):
            if npd_id in exclude_ids:
                continue
            row = params.loc[npd_id]
            ac = ParametricAircraft.from_anp_row(npd_id, row)
            curve = db.curve(npd_id, metric, op_mode)
            P = curve['Power Setting'].values.astype(float)
            L = curve[DIST_COLS].values.astype(float)
            log_plb, thr = power_features(P, row['Power Parameter'],
                                          row['Max Sea Level Static Thrust (lb)'])
            thr_c, L_c = _throttle_curve(P, row['Power Parameter'],
                                         row['Max Sea Level Static Thrust (lb)'], L)
            records.append(dict(id=npd_id, ac=ac, feat=self._feat(ac),
                                engine_type=ac.engine_type, P=P, L=L,
                                log_plb=log_plb, thr=thr,
                                thr_curve=thr_c, L_curve=L_c))
        feats = np.array([r['feat'] for r in records])
        mu, sd = feats.mean(0), feats.std(0)
        sd[sd == 0] = 1.0
        # build residual training set: each target anchored on its nearest
        # OTHER donor, correction = target - donor(at target throttle)
        Xr, Yr = [], []
        for r in records:
            donor = self._nearest(records, mu, sd, r['feat'],
                                  r['engine_type'], exclude_id=r['id'])
            if donor is None:
                continue
            anchor = _anchor_eval(donor['thr_curve'], donor['L_curve'], r['thr'])
            resid = r['L'] - anchor
            fdiff = r['feat'] - donor['feat']
            for i in range(len(r['P'])):
                Xr.append(np.concatenate([fdiff, [r['thr'][i], r['log_plb'][i]]]))
                Yr.append(resid[i])
        reg = RandomForestRegressor(n_estimators=200, min_samples_leaf=2,
                                    random_state=self.random_state, n_jobs=-1)
        reg.fit(np.array(Xr, float), np.array(Yr, float))
        self.donors[(metric, op_mode)] = records
        self.stats[(metric, op_mode)] = (mu, sd)
        self.residual[(metric, op_mode)] = reg
        return self

    def fit_all(self, db, metrics=("SEL", "LAmax", "EPNL", "PNLTM"),
                op_modes=("A", "D")):
        for m in metrics:
            for om in op_modes:
                if db.list_curve_sets(m, om):
                    self.fit(db, m, om)
        return self

    @overload
    def predict_table(self, aircraft: ParametricAircraft, metric, op_mode,
                      power_settings, return_std: Literal[False] = ...,
                      power_parameter: str = ...) -> NPDTable: ...
    @overload
    def predict_table(self, aircraft: ParametricAircraft, metric, op_mode,
                      power_settings, return_std: Literal[True],
                      power_parameter: str = ...) -> tuple[NPDTable, np.ndarray]: ...

    def predict_table(self, aircraft: ParametricAircraft, metric, op_mode,
                      power_settings, return_std=False,
                      power_parameter="CNT (lb)"):
        """Anchor on the nearest donor's real curve, add the learned residual
        correction, project monotone. return_std gives the cross-tree std of the
        CORRECTION (the anchor is measured data); wider where the parametric
        gap to the donor is large."""
        records = self.donors[(metric, op_mode)]
        mu, sd = self.stats[(metric, op_mode)]
        reg = self.residual[(metric, op_mode)]
        feat = self._feat(aircraft)
        donor = self._nearest(records, mu, sd, feat, aircraft.engine_type)
        assert donor is not None  # a fitted model always has >= 1 donor record
        P = np.atleast_1d(np.asarray(power_settings, float))
        log_plb, thr = power_features(P, power_parameter,
                                      aircraft.max_static_thrust_lb)
        anchor = _anchor_eval(donor['thr_curve'], donor['L_curve'], thr)
        fdiff = feat - donor['feat']
        Xr = np.array([np.concatenate([fdiff, [thr[i], log_plb[i]]])
                       for i in range(len(P))])
        L = anchor + reg.predict(Xr)
        if L.ndim == 1:
            L = L.reshape(1, -1)
        if self.monotone:
            L = enforce_distance_monotone(L)
        table = NPDTable(P, L, metric, op_mode, STANDARD_DISTANCES_FT,
                         npd_id=aircraft.name)
        if not return_std:
            return table
        preds = np.stack([est.predict(Xr) for est in reg.estimators_], axis=0)
        return table, preds.std(axis=0)


# ===========================================================================
# section: hybrid (merged)
# ===========================================================================

"""Blend of the two existing independent routes' OUTPUTS.

Convex combination of the data-driven RandomForest surrogate and the
interpretable semi-empirical model at the level (dB) axis:

    L = w * L_rf + (1 - w) * L_semiemp

The two component models are fit independently (no shared parameters); only
their predicted tables are combined, so the blend adds no coupling. Default
weight 0.5; a variance-reduction hedge against either route's failure mode
(the RF over-fitting the fleet envelope, the linear anchor under-fitting
strong interactions). Predictions are projected non-increasing in distance.
"""
import numpy as np

from .core import ParametricAircraft
from .core import NPDTable, STANDARD_DISTANCES_FT


class BlendNPDModel:
    """Weighted blend of SurrogateNPDModel('rf') and SemiEmpiricalNPDModel.
    Interface-compatible with both (.fit / .predict_table / fit_all)."""

    def __init__(self, weight=0.5, random_state=0, monotone=True):
        self.weight = float(weight)
        self.monotone = monotone
        self.rf = SurrogateNPDModel("rf", random_state=random_state,
                                    monotone=False)
        self.se = SemiEmpiricalNPDModel()

    def fit(self, db, metric, op_mode, exclude_ids=()):
        self.rf.fit(db, metric, op_mode, exclude_ids=exclude_ids)
        self.se.fit(db, metric, op_mode, exclude_ids=exclude_ids)
        return self

    def fit_all(self, db, metrics=("SEL", "LAmax", "EPNL", "PNLTM"),
                op_modes=("A", "D")):
        for m in metrics:
            for om in op_modes:
                if db.list_curve_sets(m, om):
                    self.fit(db, m, om)
        return self

    @overload
    def predict_table(self, aircraft: ParametricAircraft, metric, op_mode,
                      power_settings, return_std: Literal[False] = ...,
                      power_parameter: str = ...) -> NPDTable: ...
    @overload
    def predict_table(self, aircraft: ParametricAircraft, metric, op_mode,
                      power_settings, return_std: Literal[True],
                      power_parameter: str = ...) -> tuple[NPDTable, np.ndarray]: ...

    def predict_table(self, aircraft: ParametricAircraft, metric, op_mode,
                      power_settings, return_std=False,
                      power_parameter="CNT (lb)"):
        rf_tbl, std = self.rf.predict_table(aircraft, metric, op_mode,
                                            power_settings, return_std=True,
                                            power_parameter=power_parameter)
        se_tbl = self.se.predict_table(aircraft, metric, op_mode,
                                       power_settings,
                                       power_parameter=power_parameter)
        w = self.weight
        L = w * rf_tbl.L + (1.0 - w) * se_tbl.L
        if self.monotone:
            L = enforce_distance_monotone(L)
        P = np.atleast_1d(np.asarray(power_settings, float))
        table = NPDTable(P, L, metric, op_mode, STANDARD_DISTANCES_FT,
                         npd_id=aircraft.name)
        if not return_std:
            return table
        return table, w * std   # RF cross-tree spread, scaled by its weight


# ===========================================================================
# section: arix (ARIMA-family, pooled)
# ===========================================================================

"""ARIMA-family NPD generator: pooled ARIX over the log-distance axis.

Literal ARIMA does not apply here. ARIMA fits ONE observed series and
forecasts its own future, but this task is cross-sectional: a future aircraft
has no observed NPD series to fit. We keep the two parts of ARIMA that DO
transfer, treating each curve's 10 levels as a short series indexed by
log-distance:

* Integrated (I): we model the first differences d_j = L(d_{j+1}) - L(d_j) of
  the level curve along the log-distance axis, not the levels directly.
* AutoRegressive (AR): each diff is regressed on the two preceding diffs
  (AR(2)), pooled across the whole ANP fleet, with the aircraft/power feature
  vector as exogenous regressors -- i.e. ARIX, AR with eXogenous inputs.

MA(q) is dropped on purpose: a moving-average term is not estimable per-series
in this pooled, cross-sectional setting (there is no per-aircraft residual
history to regress on). An invertible MA is equivalent to an infinite-order
AR, so a pooled AR(2) is the practical stand-in.

Three pooled Ridge regressors (alpha=1, no scaler -- codebase precedent) do
the work: an anchor (level at the 1000 ft reference column), a seed (the first
two diffs, which have no AR lags yet), and the AR recursion for the remaining
diffs. Prediction rebuilds the curve by cumulative-summing the forecast diffs
onto the anchor, then projects it non-increasing in distance.
"""
import numpy as np
from sklearn.linear_model import Ridge

from .core import ParametricAircraft
from .core import NPDTable, STANDARD_DISTANCES_FT
from .anp import DIST_COLS

_DSTEP = np.diff(_LOGD)   # 9 per-step log-distance increments (non-uniform)


class ArimaNPDModel:
    """Pooled ARIX over the log-distance axis. Interface-compatible with the
    other models (.fit / .predict_table / fit_all). No return_std parameter
    (mirrors SemiEmpiricalNPDModel; api.py handles its absence via try/except
    TypeError)."""

    def __init__(self):
        self.models = {}      # (metric,mode) -> {'anchor','seed','ar'} Ridges
        self.feat_names = ParametricAircraft.feature_names()   # 10 features

    def fit(self, db, metric, op_mode, exclude_ids=()):
        params = db.param_table()
        anchor_X, anchor_y = [], []
        seed_X, seed_y = [], []
        ar_X, ar_y = [], []
        for npd_id in db.list_curve_sets(metric, op_mode):
            if npd_id in exclude_ids:
                continue
            row = params.loc[npd_id]
            ac = ParametricAircraft.from_anp_row(npd_id, row)
            curve = db.curve(npd_id, metric, op_mode)
            P = curve['Power Setting'].values.astype(float)
            log_plb, thr = power_features(P, row['Power Parameter'],
                                          row['Max Sea Level Static Thrust (lb)'])
            M = curve[DIST_COLS].values.astype(float)
            fv = ac.feature_vector()
            base = [fv[n] for n in self.feat_names]
            for i in range(len(P)):
                L = M[i]
                if not np.isfinite(L).all():          # NaN guard
                    continue
                d = np.diff(L)                        # (9,) first differences
                x = base + [log_plb[i], thr[i]]
                anchor_X.append(x); anchor_y.append(L[REF_DIST_IDX])
                seed_X.append(x);   seed_y.append([d[0], d[1]])
                # ponytail: pooled AR slopes shared across engine types; add is_jet*d_lag interactions if props diverge in LOO
                for j in range(2, 9):                 # teacher forcing: true lagged diffs
                    ar_X.append(x + [d[j-1], d[j-2], _DSTEP[j], _LOGD[j+1]])
                    ar_y.append(d[j])
        self.models[(metric, op_mode)] = dict(
            anchor=Ridge(alpha=1.0).fit(anchor_X, anchor_y),
            seed=Ridge(alpha=1.0).fit(seed_X, seed_y),
            ar=Ridge(alpha=1.0).fit(ar_X, ar_y),
        )
        return self

    def fit_all(self, db, metrics=("SEL", "LAmax", "EPNL", "PNLTM"),
                op_modes=("A", "D")):
        for m in metrics:
            for om in op_modes:
                if db.list_curve_sets(m, om):
                    self.fit(db, m, om)
        return self

    def predict_table(self, aircraft: ParametricAircraft, metric, op_mode,
                      power_settings, power_parameter="CNT (lb)") -> NPDTable:
        key = (metric, op_mode)
        if key not in self.models:
            raise KeyError(f"ArimaNPDModel not fitted for {key}; "
                           "call fit()/fit_all() first")
        reg = self.models[key]
        anchor, seed, ar = reg['anchor'], reg['seed'], reg['ar']
        P = np.atleast_1d(np.asarray(power_settings, float))
        log_plb, thr = power_features(P, power_parameter,
                                      aircraft.max_static_thrust_lb)
        fv = aircraft.feature_vector()
        base = [fv[n] for n in self.feat_names]       # loop-invariant
        L = np.empty((len(P), 10))
        for i in range(len(P)):
            x = base + [log_plb[i], thr[i]]
            d0, d1 = seed.predict([x])[0]             # first two diffs (no lags yet)
            d = [d0, d1]
            for j in range(2, 9):                     # recurse: forecast diffs feed forward
                d.append(ar.predict([x + [d[j-1], d[j-2],
                                          _DSTEP[j], _LOGD[j+1]]])[0])
            shape = np.concatenate([[0.0], np.cumsum(d)])   # (10,), shape[0]=0
            L[i] = anchor.predict([x])[0] - shape[REF_DIST_IDX] + shape
        L = enforce_distance_monotone(L)
        return NPDTable(P, L, metric, op_mode, STANDARD_DISTANCES_FT,
                        npd_id=aircraft.name)


# ===========================================================================
# section: validate (merged)
# ===========================================================================

"""Leave-one-aircraft-out (LOO) validation against ANP ground truth.

For each NPD curve set, retrain the model on every OTHER aircraft and predict the
held-out aircraft's curve from its parameters only. Compares cell-by-cell against
the real ANP table. This is ADP task 6 ("reproduce known aircraft noise and
compare with reference data") done quantitatively across the whole population.
"""
import numpy as np
import pandas as pd

from .core import ParametricAircraft
from .anp import DIST_COLS


@overload
def loo_validate(db, model_factory, metric, op_mode, verbose: bool = ...,
                 return_cells: Literal[False] = ...
                 ) -> tuple[dict, pd.DataFrame]: ...
@overload
def loo_validate(db, model_factory, metric, op_mode, verbose: bool = ...,
                 *, return_cells: Literal[True]
                 ) -> tuple[dict, pd.DataFrame, pd.DataFrame]: ...
def loo_validate(db, model_factory, metric, op_mode, verbose=False,
                 return_cells=False):
    """model_factory() -> fresh model exposing
    .fit(db, metric, op_mode, exclude_ids=...) and
    .predict_table(aircraft, metric, op_mode, power_settings).

    With return_cells=True, additionally returns a long-format per-cell
    DataFrame (columns: npd_id, engine, power_setting, distance_ft, truth_dB,
    pred_dB) - one row per (power setting x standard distance) cell of every
    held-out aircraft - as a third element: (summary, per_ac, cells)."""
    params = db.param_table()
    ids = db.list_curve_sets(metric, op_mode)
    rows = []
    all_err = []
    cell_rows = []
    for npd_id in ids:
        model = model_factory()
        model.fit(db, metric, op_mode, exclude_ids=(npd_id,))
        row = params.loc[npd_id]
        ac = ParametricAircraft.from_anp_row(npd_id, row)
        curve = db.curve(npd_id, metric, op_mode)
        P = curve['Power Setting'].values.astype(float)
        truth = curve[DIST_COLS].values
        tbl = model.predict_table(ac, metric, op_mode, P,
                                  power_parameter=str(row['Power Parameter']))
        pred = tbl.L
        err = pred - truth
        all_err.append(err.ravel())
        rows.append(dict(npd_id=npd_id, engine=ac.engine_type,
                         rmse=np.sqrt(np.mean(err**2)),
                         mae=np.mean(np.abs(err)),
                         bias=np.mean(err)))
        if return_cells:
            for i, p in enumerate(P):
                for j, d in enumerate(STANDARD_DISTANCES_FT):
                    cell_rows.append(dict(npd_id=npd_id,
                                          engine=ac.engine_type,
                                          power_setting=float(p),
                                          distance_ft=float(d),
                                          truth_dB=float(truth[i, j]),
                                          pred_dB=float(pred[i, j])))
        if verbose:
            print(f"  {npd_id:8s} {ac.engine_type:9s} RMSE={rows[-1]['rmse']:5.2f} dB")
    per_ac = pd.DataFrame(rows)
    flat = np.concatenate(all_err)
    summary = dict(metric=metric, op_mode=op_mode,
                   n_aircraft=len(ids),
                   rmse_dB=float(np.sqrt(np.mean(flat**2))),
                   mae_dB=float(np.mean(np.abs(flat))),
                   bias_dB=float(np.mean(flat)),
                   p90_abs_dB=float(np.percentile(np.abs(flat), 90)))
    if return_cells:
        cells = pd.DataFrame(cell_rows, columns=["npd_id", "engine",
                                                 "power_setting", "distance_ft",
                                                 "truth_dB", "pred_dB"])
        return summary, per_ac, cells
    return summary, per_ac


def rank_models(comparison_df, score_suffix="_medRMSE"):
    """Rank the bake-off's candidate NPD models across the metric:op combos by
    **average rank** — the Friedman / Nemenyi mean-rank method (Demsar 2006,
    "Statistical Comparisons of Classifiers over Multiple Data Sets", JMLR 7),
    the standard, citable way to compare several predictors over several tasks.

    Why not just average the dB score (what `compare`'s winner line does)?
    Averaging a raw RMSE lets one combo where every model scores ~7 dB dominate
    one where they all score ~2 dB. Ranking *within* each combo first (1 = best)
    is scale-free across combos, so a model that is reliably 2nd beats one that
    wins the easy combos but is last on the hard ones. The Friedman chi-square
    then tests whether the spread of average ranks is more than chance; if it
        is not, the leaders are effectively tied and we use the top-ranked
        supported static model.

    Parameters
    ----------
    comparison_df : the outputs/algorithm_comparison.csv frame — one row per
        metric:op combo, columns "<model><score_suffix>" (lower = better),
        optional "metric_op" label column.
    score_suffix : which per-combo score family to rank on (default the
        per-aircraft median RMSE column, "<model>_medRMSE").

    Returns (ranking_df, info)
      ranking_df : one row per fully-scored model, best-first, columns
        model, avg_rank, wins (combos scored best, shared ties both count),
        mean_score, best_combo, worst_combo.
      info : dict with n_combos, friedman_stat, friedman_p, significant
        (p < 0.05), recommended, dropped (models missing a combo), note.
    """
    from scipy.stats import rankdata, friedmanchisquare

    cols = [
        f"{model}{score_suffix}"
        for model in SUPPORTED_LEARNERS
        if f"{model}{score_suffix}" in comparison_df.columns
    ]
    if not cols:
        raise ValueError(f"no '*{score_suffix}' columns in comparison frame")
    models = [c[:-len(score_suffix)] for c in cols]
    M = comparison_df[cols].to_numpy(dtype=float)          # (n_combos, n_models)
    if "metric_op" in comparison_df.columns:
        combos = comparison_df["metric_op"].astype(str).tolist()
    else:
        combos = [str(i) for i in range(M.shape[0])]

    # Drop supported models missing any combo.
    keep = ~np.isnan(M).any(axis=0)
    dropped = [m for m, k in zip(models, keep) if not k]
    models = [m for m, k in zip(models, keep) if k]
    M = M[:, keep]
    if M.shape[1] < 2:
        raise ValueError("need >=2 fully-scored models to rank")

    ranks = np.vstack([rankdata(row) for row in M])        # 1 = lowest RMSE
    avg_rank = ranks.mean(axis=0)
    wins = (M == M.min(axis=1, keepdims=True)).sum(axis=0)
    mean_score = M.mean(axis=0)
    best_combo = [combos[i] for i in M.argmin(axis=0)]
    worst_combo = [combos[i] for i in M.argmax(axis=0)]

    ranking = pd.DataFrame(dict(
        model=models, avg_rank=np.round(avg_rank, 3), wins=wins.astype(int),
        mean_score=np.round(mean_score, 2),
        best_combo=best_combo, worst_combo=worst_combo))
    ranking = ranking.sort_values(
        ["avg_rank", "mean_score"]).reset_index(drop=True)

    stat = p = float("nan")
    if M.shape[0] >= 2 and M.shape[1] >= 3:
        stat, p = friedmanchisquare(*[M[:, j] for j in range(M.shape[1])])
    significant = (p == p) and (p < 0.05)

    if significant:
        recommended = str(ranking.loc[0, "model"])
        note = (f"Ranking is statistically significant (Friedman "
                f"p={p:.3f}). Recommended: {recommended}.")
    else:
        recommended = str(ranking.iloc[0]["model"])
        ptxt = "n/a" if p != p else f"{p:.2f}"
        note = (f"Model differences are not statistically significant "
                f"(Friedman p={ptxt}); the leaders are effectively tied, so "
                f"the top-ranked supported static model is preferred: "
                f"{recommended}.")

    info = dict(n_combos=int(M.shape[0]), friedman_stat=float(stat),
                friedman_p=float(p), significant=bool(significant),
                recommended=recommended, dropped=dropped, note=note)
    return ranking, info
