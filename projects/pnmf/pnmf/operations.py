"""Operational profiles: link flight trajectories to noise generation.

Loads the ANP default procedural steps (departure) and fixed-point profiles
(approach) and exposes a list of flight segments with (cumulative ground
distance, altitude AFE, speed, thrust setting). These feed the NPD power axis
(thrust -> source level) and the slant-distance lookup, i.e. the operational
half of the Doc 29 chain required by ADP task 5.

Scope note: this provides the trajectory + per-segment thrust/distance needed to
drive the generated NPD tables. Full Doc 29 ground-contour segmentation (energy
fraction, lateral attenuation) is the consumer tool's job (FSR/NIROS); here we
deliver the profile and a simple single-point flyover level as a sanity check.
"""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd


class OperationalProfile:
    def __init__(self, op_type, points: pd.DataFrame, acft_id="", profile_id=""):
        # points columns: distance_ft, altitude_ft, speed_kt, thrust
        self.op_type = op_type   # 'D' departure / 'A' approach
        self.points = points.reset_index(drop=True)
        self.acft_id = acft_id
        self.profile_id = profile_id

    # ---- constructors from ANP tables -----------------------------------
    @classmethod
    def from_fixed_point(cls, db, acft_id, op_type, profile_id=None, stage_length=None):
        """Approach/departure profile from the ANP fixed-point-profiles table."""
        fp = db.profiles
        if fp is None:
            raise RuntimeError("Fixed point profiles table not loaded")
        sub = fp[(fp['ACFT_ID'] == acft_id) & (fp['Op Type'] == op_type)].copy()
        if profile_id is not None:
            sub = sub[sub['Profile_ID'] == profile_id]
        if stage_length is not None and 'Stage Length' in sub:
            sub = sub[sub['Stage Length'] == stage_length]
        if sub.empty:
            raise ValueError(f"No fixed-point profile for {acft_id}/{op_type}")
        # pick the first available profile/stage
        keycols = [c for c in ['Profile_ID', 'Stage Length'] if c in sub]
        first = sub.drop_duplicates(keycols).iloc[0]
        for c in keycols:
            sub = sub[sub[c] == first[c]]
        sub = sub.sort_values('Point Number')
        pts = pd.DataFrame({
            'distance_ft': pd.to_numeric(sub['Distance (ft)'], errors='coerce'),
            'altitude_ft': pd.to_numeric(sub['Altitude AFE (ft)'], errors='coerce'),
            'speed_kt':    pd.to_numeric(sub['TAS (kt)'], errors='coerce'),
            'thrust':      pd.to_numeric(sub['Power Setting'], errors='coerce'),
        })
        return cls(op_type, pts, acft_id, str(first.get('Profile_ID', '')))

    # ---- geometry / segmentation ----------------------------------------
    def segments(self):
        """Return midpoint (x, altitude, speed, thrust, seg_length) per segment."""
        p = self.points
        x = p['distance_ft'].values
        z = p['altitude_ft'].values
        v = p['speed_kt'].values
        T = p['thrust'].values
        segs = []
        for i in range(len(p) - 1):
            xm = 0.5 * (x[i] + x[i + 1])
            zm = 0.5 * (z[i] + z[i + 1])
            vm = 0.5 * (v[i] + v[i + 1])
            Tm = 0.5 * (T[i] + T[i + 1])
            L = abs(x[i + 1] - x[i])
            segs.append(dict(x=xm, altitude=zm, speed=vm, thrust=Tm, length=L))
        return segs

    def flyover_level(self, npd_table, observer_x_ft, lateral_offset_ft=0.0):
        """Single-point L_max-style check: max over segments of the NPD level
        at the observer's CLOSEST slant distance to each segment (analytic
        point-to-segment minimum, not the segment midpoint - fault F3 fix:
        midpoints underestimate the close approach on long segments). Thrust
        is taken at the closest point by linear interpolation along the
        segment. Not a full Doc 29 contour - a sanity bridge between profile
        and generated NPD table; full segmentation (energy fraction, lateral
        attenuation) is the consumer tool's job.
        """
        p = self.points
        x = p['distance_ft'].values
        z = p['altitude_ft'].values
        T = p['thrust'].values
        best = -np.inf
        for i in range(len(p) - 1):
            # segment endpoints in the (along-track, height) plane
            ax, az = x[i] - observer_x_ft, z[i]
            bx, bz = x[i + 1] - observer_x_ft, z[i + 1]
            dx, dz = bx - ax, bz - az
            denom = dx * dx + dz * dz
            t = 0.0 if denom == 0 else np.clip(-(ax * dx + az * dz) / denom, 0.0, 1.0)
            cx, cz = ax + t * dx, az + t * dz
            slant = max(np.sqrt(cx**2 + cz**2 + lateral_offset_ft**2), 1.0)
            thrust_c = T[i] + t * (T[i + 1] - T[i])
            best = max(best, npd_table.level(thrust_c, slant))
        return best

    def __repr__(self):
        return (f"OperationalProfile({self.acft_id} {self.op_type} "
                f"{self.profile_id}, {len(self.points)} pts)")


# ===========================================================================
# section: synthesis (merged)
# ===========================================================================

"""Departure-profile synthesis from ANP procedural steps (SAE-AIR-1845 style).

The ANP fixed-point-profile table only covers ~20 legacy aircraft, but the
*procedural steps* table covers 142 - together with the jet-engine thrust
coefficients (Fn/delta = E + F*Vc + Ga*h + Gb*h^2 + H*Tc), the aerodynamic
coefficients (B, C, R per flap setting) and the stage-length weights, a full
departure trajectory (distance, altitude, speed, thrust) can be synthesized for
almost every aircraft in the database. This is the "integrate operational
profiles from performance models" task done properly, and it is also what lets
the framework attach a plausible trajectory to a *future* aircraft: borrow the
nearest neighbour's procedure and coefficients, rescale thrust.

Simplifications vs. the full ECAC Doc 29 Vol. 2 Appendix B method (documented,
deliberate for a conceptual-design tool):
- ISA sea-level airport, no wind, no runway gradient (theta ~ delta corrections
  at altitude are included in thrust via delta(h) and Tc(h)).
- CAS ~ TAS below 10,000 ft (error < ~5% at 250 kt / 10 kft, and NPD lookup
  depends on thrust and distance, not speed).
- Climb-angle factor K: 1.01 below 200 kt, 0.95 above (Doc 29 B-8 convention).
- Energy-share acceleration segments use the segment-mean thrust.
Outputs feed OperationalProfile directly.
"""
import numpy as np
import pandas as pd


G_FTS2 = 32.174          # gravity [ft/s^2]
KT2FTS = 1.68781         # knots -> ft/s
ISA_T0_C = 15.0
ISA_LAPSE_C_PER_FT = 0.0019812


def delta_pressure_ratio(h_ft):
    return (1.0 - 6.87535e-6 * h_ft) ** 5.2559


def isa_temp_c(h_ft):
    return ISA_T0_C - ISA_LAPSE_C_PER_FT * h_ft


class DepartureSynthesizer:
    """Builds a departure OperationalProfile from ANP procedural steps."""

    def __init__(self, db):
        self.db = db
        self.dep = db.dep_steps
        self.jets = db.jet_coeffs
        self.aero = db.aero
        self.weights = db.weights
        if any(t is None for t in (self.dep, self.jets, self.aero, self.weights)):
            raise RuntimeError("Synthesis needs departure steps, jet "
                               "coefficients, aero coefficients and weights tables")

    # ---- coefficient lookups --------------------------------------------
    def _thrust_coeffs(self, acft_id, rating):
        j = self.jets
        row = j[(j['ACFT_ID'] == acft_id) & (j['Thrust Rating'] == rating)]
        if not row.empty:
            r = row.iloc[0]
            out: dict[str, Any] = {k: (float(r[k]) if pd.notna(r[k]) else 0.0)
                                   for k in ('E', 'F', 'Ga', 'Gb', 'H')}
            out['_prop'] = None
            return out
        # propeller aircraft: SAE-AIR-1845 Fn = 325.87 * eta * hp / V_kt
        p = getattr(self.db, 'prop_coeffs', None)
        if p is not None:
            prow = p[(p['ACFT_ID'] == acft_id) & (p['Thrust Rating'] == rating)]
            if not prow.empty:
                r = prow.iloc[0]
                return {'_prop': (float(r['Propeller Efficiency']),
                                  float(r['Installed Net Propulsive Power (hp)']))}
        raise ValueError(f"No thrust coefficients for {acft_id}/{rating}")

    def corrected_net_thrust(self, coeffs, cas_kt, h_ft, thrust_scale=1.0):
        """Fn per engine [lb]. Jets: delta * (E + F*Vc + Ga*h + Gb*h^2 + H*Tc).
        Propellers (SAE-AIR-1845): Fn = 325.87 * eta * hp / V (V floored at
        40 kt to avoid the static singularity - the 1845 convention for the
        ground roll evaluates thrust at a representative roll speed anyway).
        thrust_scale supports borrowing a neighbour's engine deck for a future
        aircraft with different rated thrust."""
        if coeffs.get('_prop') is not None:
            eta, hp = coeffs['_prop']
            v = max(cas_kt, 40.0)
            return thrust_scale * 325.87 * eta * hp / v
        fn_over_delta = (coeffs['E'] + coeffs['F'] * cas_kt +
                         coeffs['Ga'] * h_ft + coeffs['Gb'] * h_ft**2 +
                         coeffs['H'] * isa_temp_c(h_ft))
        return thrust_scale * delta_pressure_ratio(h_ft) * fn_over_delta

    def _aero(self, acft_id, flap_id):
        a = self.aero
        row = a[(a['ACFT_ID'] == acft_id) & (a['Op Type'] == 'D') &
                (a['Flap_ID'] == flap_id)]
        if row.empty:
            raise ValueError(f"No D aero coefficients for {acft_id}/{flap_id}")
        r = row.iloc[0]
        return {k: (float(r[k]) if pd.notna(r[k]) else np.nan)
                for k in ('B', 'C', 'D', 'R')}

    def _weight(self, acft_id, stage_length):
        w = self.weights
        row = w[(w['ACFT_ID'] == acft_id) &
                (w['Stage Length'].astype(str) == str(stage_length))]
        if row.empty:
            raise ValueError(f"No default weight for {acft_id}/stage {stage_length}")
        return float(row['Weight (lb)'].iloc[0])

    # ---- main synthesis --------------------------------------------------
    def synthesize(self, acft_id, stage_length: "int | str" = 1,
                   profile_id="DEFAULT",
                   n_engines=None, weight_lb=None, thrust_scale=1.0,
                   out_name=None):
        """Synthesize the departure profile. Returns OperationalProfile.

        weight_lb / thrust_scale / n_engines overrides support the
        future-aircraft use case (borrowed procedure, rescaled engine deck).
        """
        d = self.dep
        steps = d[(d['ACFT_ID'] == acft_id) &
                  (d['Profile_ID'] == profile_id) &
                  (d['Stage Length'].astype(str) == str(stage_length))
                  ].sort_values('Step Number')
        if steps.empty and profile_id == "DEFAULT":
            # ANP v6.3 names its standard procedures ICAO_A/ICAO_B instead of
            # DEFAULT. Choose ICAO_A deterministically when present so the
            # public default remains usable across both source releases.
            candidates = d[
                (d['ACFT_ID'] == acft_id) &
                (d['Stage Length'].astype(str) == str(stage_length))]
            available = sorted(candidates['Profile_ID'].dropna().unique())
            fallback = "ICAO_A" if "ICAO_A" in available else (
                available[0] if available else None)
            if fallback is not None:
                steps = candidates[
                    candidates['Profile_ID'] == fallback
                ].sort_values('Step Number')
        if steps.empty:
            raise ValueError(f"No departure steps for {acft_id}/{profile_id}"
                             f"/stage {stage_length}")
        if n_engines is None:
            ap = self.db.aircraft
            n_engines = int(ap[ap['ACFT_ID'] == acft_id]
                            ['Number Of Engines'].iloc[0])
        W = weight_lb if weight_lb is not None else self._weight(acft_id, stage_length)

        pts = []      # (distance_ft, altitude_ft, speed_kt, thrust_lb_per_engine)
        x = h = 0.0
        v = 0.0       # current CAS [kt]

        for _, s in steps.iterrows():
            stype = str(s['Step Type'])
            rating = str(s['Thrust Rating'])
            coeffs = self._thrust_coeffs(acft_id, rating)
            flap = str(s['Flap_ID'])

            if stype == 'Takeoff':
                ae = self._aero(acft_id, flap)
                v_to = ae['C'] * np.sqrt(W)             # liftoff CAS [kt]
                fn_roll = self.corrected_net_thrust(coeffs, v_to / np.sqrt(2), 0.0,
                                                    thrust_scale)
                sg = ae['B'] * W**2 / (n_engines * max(fn_roll, 1.0))
                fn0 = self.corrected_net_thrust(coeffs, 0.0, 0.0, thrust_scale)
                pts.append((0.0, 0.0, 0.0, fn0))
                x = sg; v = v_to
                fn_lof = self.corrected_net_thrust(coeffs, v, 0.0, thrust_scale)
                pts.append((x, 0.0, v, fn_lof))

            elif stype == 'Climb':
                h_end = float(s['End Point Altitude (ft)'])
                if h_end <= h:          # already above target (guard)
                    continue
                ae = self._aero(acft_id, flap)
                R = ae['R']
                fn1 = self.corrected_net_thrust(coeffs, v, h, thrust_scale)
                fn2 = self.corrected_net_thrust(coeffs, v, h_end, thrust_scale)
                fn = 0.5 * (fn1 + fn2)
                K = 1.01 if v <= 200.0 else 0.95
                sin_g = np.clip(K * (n_engines * fn / W - R), 1e-3, 0.7)
                gamma = np.arcsin(sin_g)
                dx = (h_end - h) / np.tan(gamma)
                x += dx; h = h_end
                pts.append((x, h, v, fn2))

            elif stype == 'Accelerate':
                v2 = float(s['End Point CAS (kt)'])
                roc = float(s['Rate Of Climb (ft/min)']) if pd.notna(
                    s['Rate Of Climb (ft/min)']) else 0.0
                ae = self._aero(acft_id, flap)
                R = ae['R']
                fn = self.corrected_net_thrust(coeffs, 0.5 * (v + v2), h,
                                               thrust_scale)
                a_tot = max(G_FTS2 * (n_engines * fn / W - R), 1e-3)  # [ft/s^2]
                vz = roc / 60.0                                       # [ft/s]
                v_mean_fts = 0.5 * (v + v2) * KT2FTS
                sin_g = np.clip(vz / max(v_mean_fts, 1.0), 0.0, 0.5)
                # Energy budget guard: the tabulated ROC cannot consume more
                # than 80% of the available excess thrust during acceleration
                # (otherwise a_h -> 0 and the segment length diverges - this
                # is exactly what broke the 1900D/PA30 turboprop profiles).
                sin_g = min(sin_g, 0.8 * a_tot / G_FTS2)
                a_h = max(a_tot - G_FTS2 * sin_g, 0.2 * a_tot)
                dv2 = (v2 * KT2FTS)**2 - (v * KT2FTS)**2
                dx = max(dv2 / (2 * a_h), 0.0)
                dt = max(v2 - v, 0.0) * KT2FTS / a_h
                dh = vz * dt
                x += dx; h += dh; v = v2
                pts.append((x, h, v, fn))

            else:   # unknown step type: skip but keep going
                continue

        df = pd.DataFrame(pts, columns=['distance_ft', 'altitude_ft',
                                        'speed_kt', 'thrust'])
        return OperationalProfile('D', df, out_name or acft_id,
                                  f"SYNTH-{profile_id}-S{stage_length}")
