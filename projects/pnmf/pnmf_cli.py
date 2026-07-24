"""PNMF command-line interface - all framework entry points in one file.

Usage:  .venv\\Scripts\\python.exe pnmf_cli.py <command> [args...]

Commands:
  datastore build anp_data.sqlite from raw v2.3 + v6.3 CSV sources
  manifest  inspect the combined training-corpus provenance
  predict   predict + QA-gate + store NPD tables for a future aircraft
  validate  LOO validation of the supported ET and RF learned models
  validate-model reproducible aircraft-grouped + temporal ET/RF validation
  validate-jet-reference frozen representative Jet ET/RF holdout
  physics   physics-route calibration + fleet validation + BPR sweep
  demo      end-to-end demo: generate NPD, validate, synthesize, sideline
  compare   LOO bake-off of Extra Trees and Random Forest
  subs      external check vs the 19.5k-aircraft substitution xlsx

See each command's docstring for flags and output artifacts.
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)

def cmd_datastore():
    """Build the single-file SQLite datastore from the staged ANP CSVs.

    Usage (formerly build_datastore.py):
        .venv\\Scripts\\python.exe pnmf_cli.py datastore [root]

    Reads the raw v2.3 semicolon CSVs and v6.3 comma CSVs under 03_data,
    merges them with source provenance, and writes canonical truth tables.
    """
    import sys

    from pnmf.anp import ANPDatabase
    from pnmf.anp import build_datastore


    def main(root="."):
        db_path = build_datastore(root)
        print(f"built {db_path}")
        db = ANPDatabase(db_path)
        print(db.dataset_manifest().to_string(index=False))
        print("combined summary:", db.summary())


    if True:
        main(sys.argv[1] if len(sys.argv) > 1 else ".")


def cmd_manifest():
    """Print the canonical dataset manifest and combined corpus summary."""
    from pnmf import ANPDatabase
    db = ANPDatabase()
    print(db.dataset_manifest().to_string(index=False))
    print("\ncombined summary:", db.summary())



def cmd_predict():
    """Predict the NPD noise table for a future aircraft and store it in the
    datastore - gated so no unphysical or low-confidence data enters silently.

    Usage (defaults reproduce the FUTURE-UHBR-TWIN demo concept; formerly
    predict_future.py):
        .venv\\Scripts\\python.exe pnmf_cli.py predict
        .venv\\Scripts\\python.exe pnmf_cli.py predict --name MY-CONCEPT ^
            --thrust-lb 32000 --n-engines 2 --mtow-lb 180000 --mlw-lb 152000 ^
            --bpr 12 --noise-chapter 14
        .venv\\Scripts\\python.exe pnmf_cli.py predict --dry-run   (predict + QA only)

    Pipeline:
      1. learn      - NoisePredictor fits the LOO-winning model on the ANP fleet
                      (loaded from anp_data.sqlite; run pnmf_cli.py datastore once).
      2. predict    - full NPD tables (SEL/LAmax/EPNL/PNLTM x A/D) + cross-tree
                      uncertainty per cell.
      3. cross-check- the independent physics route (calibrated once on the
                      A320-211, frozen) re-predicts SEL/LAmax; mean |delta| is
                      recorded as evidence.
      4. QA gate    - unphysical tables are REJECTED (never stored); high
                      uncertainty or physics disagreement stores them flagged
                      'caution'. Real ANP tables are never touched.
      5. store      - accepted tables land in predicted_npd / predicted_aircraft
                      inside anp_data.sqlite, tagged with model + timestamp.
    """
    import argparse
    import os
    import sys

    from pnmf.core import ParametricAircraft, FUTURE_UHBR_TWIN
    from pnmf.api import NoisePredictor, DEFAULT_MODEL
    from pnmf.anp import DB_FILENAME, PredictionStore


    def parse_args():
        ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
        ap.add_argument("--name", default=FUTURE_UHBR_TWIN["name"])
        ap.add_argument("--engine-type", default=FUTURE_UHBR_TWIN["engine_type"],
                        choices=["Jet", "Turboprop", "Piston"])
        ap.add_argument("--n-engines", type=int,
                        default=FUTURE_UHBR_TWIN["n_engines"])
        ap.add_argument("--thrust-lb", type=float,
                        default=FUTURE_UHBR_TWIN["max_static_thrust_lb"],
                        help="max sea-level static thrust per engine [lbf]")
        ap.add_argument("--mtow-lb", type=float,
                        default=FUTURE_UHBR_TWIN["mtow_lb"])
        ap.add_argument("--mlw-lb", type=float,
                        default=FUTURE_UHBR_TWIN["mlw_lb"])
        ap.add_argument("--bpr", type=float,
                        default=FUTURE_UHBR_TWIN["bypass_ratio"],
                        help="bypass ratio (used by the physics cross-check)")
        ap.add_argument("--noise-chapter", type=int,
                        default=FUTURE_UHBR_TWIN["noise_chapter"])
        ap.add_argument("--model", default=DEFAULT_MODEL)
        ap.add_argument("--db", default=DB_FILENAME)
        ap.add_argument("--dry-run", action="store_true",
                        help="predict and QA-check but do not write to the database")
        return ap.parse_args()


    def main():
        args = parse_args()
        if not os.path.exists(args.db):
            sys.exit(f"{args.db} not found - run: pnmf_cli.py datastore first")

        aircraft = ParametricAircraft(
            name=args.name, engine_type=args.engine_type,
            n_engines=args.n_engines, max_static_thrust_lb=args.thrust_lb,
            mtow_lb=args.mtow_lb, mlw_lb=args.mlw_lb,
            bypass_ratio=args.bpr, noise_chapter=args.noise_chapter)

        print(f"[1/4] fitting '{args.model}' model on the ANP fleet ...")
        pred = NoisePredictor(root=".", model=args.model)

        print(f"[2/4] predicting NPD tables for {aircraft.name} ...")
        result = pred.predict(aircraft)

        print("[3/4] independent physics cross-check (SEL/LAmax) ...")
        crosscheck = result.crosscheck_physics(bpr=args.bpr)
        for metric, delta in crosscheck.items():
            print(f"      {metric}: mean |physics - {args.model}| = {delta:.2f} dB")

        print("[4/4] QA gate + store ...")
        store = PredictionStore(args.db)
        if args.dry_run:
            from pnmf.anp import qa_check
            results = {}
            for (metric, om), tbl in result.tables.items():
                std = result.uncertainty.get((metric, om))
                results[(metric, om)] = qa_check(
                    tbl.P, tbl.L, std, crosscheck_db=crosscheck.get(metric))
        else:
            results = store.add(aircraft, result.tables, result.uncertainty,
                                model=args.model, crosscheck=crosscheck)

        n_ok = n_caution = n_rejected = 0
        for (metric, om), (status, reasons) in sorted(results.items()):
            mark = {"ok": "stored", "caution": "stored [CAUTION]",
                    "rejected": "REJECTED"}[status]
            if args.dry_run:
                mark = {"ok": "would store", "caution": "would store [CAUTION]",
                        "rejected": "would REJECT"}[status]
            note = f"  ({'; '.join(reasons)})" if reasons else ""
            print(f"      {metric:6s}/{om}  {mark}{note}")
            n_ok += status == "ok"
            n_caution += status == "caution"
            n_rejected += status == "rejected"

        print(f"\nsummary: {n_ok} ok, {n_caution} caution, {n_rejected} rejected"
              + (" (dry run - nothing written)" if args.dry_run else
                 f" -> {args.db} [predicted_npd / predicted_aircraft]"))
        if not args.dry_run and (n_ok + n_caution):
            df = store.npd(name=aircraft.name)
            print(f"database now holds {len(df)} predicted NPD rows for "
                  f"{aircraft.name}. The anp_* truth tables are untouched.")


    if True:
        main()



def cmd_validate():
    """Run LOO validation for one or more (metric, mode) pairs; merge into the
    summary CSV (one row per metric:mode - rerunning a combo replaces its row).
    Usage: .venv\\Scripts\\python.exe pnmf_cli.py validate SEL:D SEL:A EPNL:D EPNL:A
    (formerly run_validation.py)
    """
    import sys, os
    import pandas as pd
    from pnmf import ANPDatabase, SurrogateNPDModel
    from pnmf.models import loo_validate

    db = ANPDatabase('.')
    OUT = os.path.join('.', 'outputs'); os.makedirs(OUT, exist_ok=True)
    csv_path = os.path.join(OUT, 'validation_summary.csv')
    fields = ['metric', 'mode', 'n', 'et_RMSE', 'et_MAE', 'et_bias',
              'et_p90', 'rf_RMSE', 'rf_MAE', 'rf_bias', 'rf_p90']

    new_rows = []
    for arg in sys.argv[1:]:
        metric, om = arg.split(':')
        et, et_per = loo_validate(
            db, lambda: SurrogateNPDModel("et"), metric, om)
        rf, rf_per = loo_validate(
            db, lambda: SurrogateNPDModel("rf"), metric, om)
        new_rows.append(dict(
            metric=metric, mode=om, n=et['n_aircraft'],
            et_RMSE=round(et['rmse_dB'], 2), et_MAE=round(et['mae_dB'], 2),
            et_bias=round(et['bias_dB'], 2), et_p90=round(et['p90_abs_dB'], 2),
            rf_RMSE=round(rf['rmse_dB'], 2), rf_MAE=round(rf['mae_dB'], 2),
            rf_bias=round(rf['bias_dB'], 2), rf_p90=round(rf['p90_abs_dB'], 2)))
        et_per.to_csv(os.path.join(
            OUT, f'per_aircraft_et_{metric}_{om}.csv'), index=False)
        rf_per.to_csv(os.path.join(
            OUT, f'per_aircraft_rf_{metric}_{om}.csv'), index=False)
        print(f"{metric}/{om}: ET RMSE={et['rmse_dB']:.2f}; "
              f"RF RMSE={rf['rmse_dB']:.2f} (n={et['n_aircraft']})")

    new = pd.DataFrame(new_rows, columns=fields)
    if os.path.exists(csv_path):
        old = pd.read_csv(csv_path)
        # clean legacy duplicates: keep only the last row per (metric, mode)
        old = old.drop_duplicates(subset=['metric', 'mode'], keep='last')
        # drop combos being rewritten by this run
        rewritten = set(zip(new['metric'], new['mode']))
        keep = [(m, om) not in rewritten
                for m, om in zip(old['metric'], old['mode'])]
        new = pd.concat([old[keep], new], ignore_index=True)
    new = new.sort_values(['metric', 'mode'], kind='mergesort',
                          ignore_index=True)
    new[fields].to_csv(csv_path, index=False)


def cmd_validate_model():
    """Run the current reproducible ET/RF model-validation workflow.

    This is separate from the historical ``validate`` command. It writes
    deterministic samples/splits/predictions/summaries and the current
    ``docs/MODEL_TRAINING_REPORT.md`` without modifying truth or registry
    tables.
    """
    from pnmf.validation import main

    raise SystemExit(main(sys.argv[1:]))


def cmd_validate_jet_reference():
    """Run the frozen representative-jet ET/RF holdout experiment."""
    from pnmf.jet_reference_validation import main

    raise SystemExit(main(sys.argv[1:]))



def cmd_physics():
    """Physics-based (pyNA-family) model: calibrate once, validate across the
    fleet, demonstrate design sensitivities, and compare the physics route against
    the data-driven surrogate for a future design.

    Outputs (./outputs):
      physics_calibration_A320.png     truth vs physics for the calibration aircraft
      physics_fleet_validation.csv/png out-of-sample fleet RMSE (frozen constants)
      physics_bpr_sweep.png            SEL vs bypass ratio at constant thrust
      physics_component_split.png      approach/departure source breakdown
      physics_vs_surrogate_future.png  two independent routes for the future design
    """
    import os
    import numpy as np
    import pandas as pd
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from pnmf import (ANPDatabase, ParametricAircraft, SurrogateNPDModel,
                      PhysicsNPDModel, STANDARD_DISTANCES_FT)
    from pnmf.core import FUTURE_UHBR_TWIN
    from pnmf.physics import PhysicsDesign
    from pnmf.anp import DIST_COLS

    db = ANPDatabase('.')
    OUT = './outputs'; os.makedirs(OUT, exist_ok=True)

    # public bypass ratios for well-known ANP aircraft (ACFT_ID -> BPR)
    FLEET_BPR = {
        'A320-211': 6.0,     # CFM56-5A1  (CALIBRATION aircraft)
        '737800':   5.1,     # CFM56-7B
        '737300':   5.0,     # CFM56-3
        'A320-232': 4.8,     # V2527-A5
        '757PW':    4.8,     # PW2037   (if present)
        '757RR':    4.3,     # RB211-535E4
        '767300':   4.85,    # PW4056
        'A330-343': 5.0,     # Trent 772
        '777300':   8.4,     # GE90
        'A350-941': 9.6,     # Trent XWB-84
        'MD82':     1.7,     # JT8D-217
        '727EM2':   1.0,     # JT8D-15
        '747200':   5.0,     # JT9D-7
    }

    # ---------------------------------------------------------------------------
    # STEP A: calibrate the four anchor constants + spectral placement on ONE
    # aircraft (A320-211), then freeze them.
    # ---------------------------------------------------------------------------
    model = PhysicsNPDModel()
    print("[A] calibration:")
    model.calibrate(db, 'A320-211', bpr=FLEET_BPR['A320-211'])


    def design_from_anp(acft_id, bpr):
        row = db.aircraft[db.aircraft['ACFT_ID'] == acft_id]
        if row.empty:
            return None, None
        r = row.iloc[0]
        return PhysicsDesign(acft_id, r['Number Of Engines'],
                             r['Max Sea Level Static Thrust (lb)'], bpr,
                             r['Max Gross Takeoff Weight (lb)']), str(r['NPD_ID'])


    def aircraft_rmse(acft_id, bpr):
        """RMSE of the frozen physics model against this aircraft's ANP truth
        over SEL+LAmax x both modes x all tabulated power settings/distances.
        Skips aircraft whose NPD power axis is not in lb (units incompatible
        with a thrust-parameterised physics model)."""
        des, npd_id = design_from_anp(acft_id, bpr)
        if des is None or npd_id is None:
            return None
        r = db.aircraft[db.aircraft['ACFT_ID'] == acft_id].iloc[0]
        if 'lb' not in str(r['Power Parameter']):
            return None
        errs = []
        for metric in ('SEL', 'LAmax'):
            for om in ('D', 'A'):
                cv = db.curve(npd_id, metric, om)
                if cv.empty:
                    continue
                P = cv['Power Setting'].values.astype(float)
                truth = cv[DIST_COLS].values
                pred = model.predict_table(des, metric, om, P).L
                errs.append((pred - truth).ravel())
        if not errs:
            return None
        e = np.concatenate(errs)
        return float(np.sqrt(np.mean(e ** 2))), float(np.mean(e))


    # ---------------------------------------------------------------------------
    # STEP B: calibration-quality figure (A320, SEL both modes)
    # ---------------------------------------------------------------------------
    des_cal, npd_cal = design_from_anp('A320-211', FLEET_BPR['A320-211'])
    assert des_cal is not None and npd_cal is not None  # calibration aircraft is always in the fleet
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.5))
    for ax, om, title in zip(axes, ('D', 'A'), ('Departure', 'Approach')):
        cv = db.curve(npd_cal, 'SEL', om)
        P = cv['Power Setting'].values.astype(float)
        truth = cv[DIST_COLS].values
        pred = model.predict_table(des_cal, 'SEL', om, P).L
        cmap = plt.cm.viridis(np.linspace(0, .8, len(P)))
        for i in range(len(P)):
            ax.semilogx(STANDARD_DISTANCES_FT, truth[i], 'o-', color=cmap[i],
                        lw=1.6, label='ANP truth' if i == 0 else None)
            ax.semilogx(STANDARD_DISTANCES_FT, pred[i], 's--', color=cmap[i],
                        lw=1.1, label='physics model' if i == 0 else None)
        ax.set_title(f"A320-211 SEL / {title} (calibration aircraft)", fontsize=10)
        ax.set_xlabel("slant distance [ft]"); ax.set_ylabel("SEL [dB]")
        ax.grid(True, which='both', alpha=.25); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(f"{OUT}/physics_calibration_A320.png", dpi=130)
    plt.close(fig)
    print("[B] calibration figure saved")

    # ---------------------------------------------------------------------------
    # STEP C: OUT-OF-SAMPLE fleet validation with frozen constants
    # ---------------------------------------------------------------------------
    rows = []
    for acid, bpr in FLEET_BPR.items():
        res = aircraft_rmse(acid, bpr)
        if res is None:
            continue
        rmse, bias = res
        rows.append(dict(acft_id=acid, bpr=bpr, rmse_dB=round(rmse, 2),
                         bias_dB=round(bias, 2),
                         role='calibration' if acid == 'A320-211' else 'out-of-sample'))
        print(f"[C] {acid:10s} BPR {bpr:4.1f}  RMSE {rmse:5.2f} dB  "
              f"bias {bias:+5.2f} dB  ({rows[-1]['role']})")
    fleet = pd.DataFrame(rows)
    fleet.to_csv(f"{OUT}/physics_fleet_validation.csv", index=False)
    oos = fleet[fleet.role == 'out-of-sample']
    print(f"[C] out-of-sample fleet: median RMSE {oos.rmse_dB.median():.2f} dB, "
          f"mean {oos.rmse_dB.mean():.2f} dB over {len(oos)} aircraft")

    fig, ax = plt.subplots(figsize=(8, 4.3))
    colors = ['#2b6cb0' if r == 'out-of-sample' else '#c53030' for r in fleet.role]
    ax.bar(fleet.acft_id, fleet.rmse_dB, color=colors)
    ax.axhline(oos.rmse_dB.median(), ls='--', c='k', lw=1,
               label=f"out-of-sample median {oos.rmse_dB.median():.1f} dB")
    ax.set_ylabel("RMSE vs ANP truth [dB]")
    ax.set_title("Physics model, constants frozen after A320 calibration (red)")
    ax.legend(fontsize=8); plt.xticks(rotation=45, ha='right', fontsize=8)
    fig.tight_layout(); fig.savefig(f"{OUT}/physics_fleet_validation.png", dpi=130)
    plt.close(fig)

    # ---------------------------------------------------------------------------
    # STEP D: design sensitivity - BPR sweep at constant thrust & weight
    # ---------------------------------------------------------------------------
    bprs = np.linspace(2, 16, 8)
    sel_dep, sel_app = [], []
    for b in bprs:
        d = PhysicsDesign(f"BPR{b:.0f}", 2, 27000, b, 160000)
        sel_dep.append(model.single_event(d, 24000, 'D', 1000)[1])
        sel_app.append(model.single_event(d, 4000, 'A', 1000)[1])
    fig, ax = plt.subplots(figsize=(6.4, 4.3))
    ax.plot(bprs, sel_dep, 'o-', color='#c53030', label='departure (24 klbf/eng)')
    ax.plot(bprs, sel_app, 's-', color='#2b6cb0', label='approach (4 klbf/eng)')
    ax.set_xlabel("bypass ratio"); ax.set_ylabel("SEL @ 1000 ft [dB]")
    ax.set_title("Design sensitivity: same thrust, quieter cycle")
    ax.grid(alpha=.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(f"{OUT}/physics_bpr_sweep.png", dpi=130)
    plt.close(fig)
    print(f"[D] BPR sweep: departure SEL falls {sel_dep[0]-sel_dep[-1]:.1f} dB "
          f"from BPR 2 -> 16; approach only {sel_app[0]-sel_app[-1]:.1f} dB "
          f"(airframe floor)")

    # ---------------------------------------------------------------------------
    # STEP E: component split (why approach is airframe-limited)
    # ---------------------------------------------------------------------------
    d = PhysicsDesign("SPLIT", 2, 27000, 6.0, 160000)
    cases = [('Departure, 24 klbf', 24000, 'D'), ('Approach, 4 klbf', 4000, 'A')]
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    width = 0.35
    ks = ['jet', 'fan', 'airframe']
    for k, (lab, thr, om) in enumerate(cases):
        _, _, comp = model.single_event(d, thr, om, 1000,
                                        return_components=True)
        ax.bar(np.arange(3) + k * width, [comp[c] for c in ks], width, label=lab)
    ax.set_xticks(np.arange(3) + width / 2); ax.set_xticklabels(ks)
    ax.set_ylabel("component LAmax @ 1000 ft [dB]")
    ax.set_title("Source balance shifts along the mission")
    ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(f"{OUT}/physics_component_split.png", dpi=130); plt.close(fig)
    print("[E] component split figure saved")

    # ---------------------------------------------------------------------------
    # STEP F: FUTURE DESIGN - physics route vs data-driven surrogate route
    # ---------------------------------------------------------------------------
    F: dict = FUTURE_UHBR_TWIN   # plain dict: values are per-field, not a union
    future_phys = PhysicsDesign(F["name"], F["n_engines"],
                                F["max_static_thrust_lb"], F["bypass_ratio"],
                                F["mtow_lb"])
    future_par = ParametricAircraft(**F)
    sur = SurrogateNPDModel("rf").fit(db, 'SEL', 'D')
    P = np.array([13500., 19500., 25500., 28500.])
    tbl_phys = model.predict_table(future_phys, 'SEL', 'D', P)
    tbl_sur, std = sur.predict_table(future_par, 'SEL', 'D', P, return_std=True)
    fig, ax = plt.subplots(figsize=(6.6, 4.6))
    cmap = plt.cm.viridis(np.linspace(0, .8, len(P)))
    for i in range(len(P)):
        ax.semilogx(STANDARD_DISTANCES_FT, tbl_phys.L[i], 'o-', color=cmap[i],
                    lw=1.6, label='physics (pyNA-family)' if i == 0 else None)
        ax.semilogx(STANDARD_DISTANCES_FT, tbl_sur.L[i], 's--', color=cmap[i],
                    lw=1.2, label='data-driven surrogate' if i == 0 else None)
        ax.fill_between(STANDARD_DISTANCES_FT, tbl_sur.L[i] - std[i],
                        tbl_sur.L[i] + std[i], color=cmap[i], alpha=.10)
    gap = float(np.mean(tbl_phys.L - tbl_sur.L))
    ax.set_xlabel("slant distance [ft]"); ax.set_ylabel("SEL [dB]")
    ax.set_title(f"FUTURE-UHBR-TWIN SEL/Departure: two independent routes "
                 f"(mean gap {gap:+.1f} dB)", fontsize=9.5)
    ax.grid(True, which='both', alpha=.25); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(f"{OUT}/physics_vs_surrogate_future.png", dpi=130)
    plt.close(fig)
    print(f"[F] future design: physics vs surrogate mean gap {gap:+.1f} dB "
          f"(surrogate extrapolates the fleet trend; physics extrapolates the "
          f"V_jet^8 cycle physics)")
    print("\nDone. Outputs in", OUT)



def cmd_demo():
    """Demonstration + figures (fast; only the small held-out set refits models).

    Produces:
      A. NPD-equivalent table for a future/parametric aircraft - strict ANP layout
         (generated_NPD_FUTURE.csv, directly consumable by an ANP/Doc-29 tool) plus
         a companion file with per-cell ET tree dispersion.
      B. Held-out reproduction plots for real, recognizable aircraft.
      C. Grouped 5-fold validation scatter + error histogram (SEL/Departure).
      D. Surrogate feature importance.
      E. END-TO-END CLOSURE: parametric aircraft -> generated NPD table ->
         synthesized departure trajectory (borrowed nearest-neighbour procedure,
         rescaled engine deck) -> single-event LAmax along a runway sideline,
         compared against a real reference aircraft (A320) computed the same way
         from its own ANP truth table + synthesized profile.

    Run: .venv\\Scripts\\python.exe pnmf_cli.py demo   (after pnmf_cli.py validate;
    formerly make_demo.py)
    """
    import os
    import numpy as np
    import pandas as pd
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.model_selection import GroupKFold

    from pnmf import (ANPDatabase, ParametricAircraft, SurrogateNPDModel,
                      DepartureSynthesizer, NPDTable, STANDARD_DISTANCES_FT)
    from pnmf.core import FUTURE_UHBR_TWIN
    from pnmf.anp import DIST_COLS
    from pnmf.validation import aircraft_group_map

    db = ANPDatabase('.')
    OUT = './outputs'; os.makedirs(OUT, exist_ok=True)
    params = db.param_table()
    npd_to_group, _, _ = aircraft_group_map(db.aircraft)
    curves_by_group = {}
    for curve_id, group_id in npd_to_group.items():
        curves_by_group.setdefault(group_id, []).append(curve_id)
    sur = SurrogateNPDModel("et").fit_all(db)

    # ---- (A) generate NPD-equivalent table + uncertainty for a future aircraft -
    future_spec: dict = FUTURE_UHBR_TWIN
    future = ParametricAircraft(**future_spec)
    tables = sur.generate_full(future, metrics=("SEL", "LAmax", "EPNL"),
                               op_modes=("A", "D"), return_std=True)
    strict_rows, dispersion_rows = [], []
    for (metric, om), (tbl, std) in tables.items():
        for i, P in enumerate(tbl.P):
            base = {"NPD_ID": future.name, "Noise Metric": metric, "Op Mode": om,
                    "Power Setting": P}
            strict = dict(base); strict.update(
                {c: round(tbl.L[i, j], 1) for j, c in enumerate(DIST_COLS)})
            strict_rows.append(strict)
            dispersion = dict(base); dispersion.update(
                {c: round(tbl.L[i, j], 1) for j, c in enumerate(DIST_COLS)})
            dispersion.update({f"{c}_tree_std": round(std[i, j], 2)
                               for j, c in enumerate(DIST_COLS)})
            dispersion_rows.append(dispersion)
    pd.DataFrame(strict_rows).to_csv(f"{OUT}/generated_NPD_FUTURE.csv", index=False)
    pd.DataFrame(dispersion_rows).to_csv(
        f"{OUT}/generated_NPD_FUTURE_with_tree_dispersion.csv", index=False)
    mean_std = np.mean([std.mean() for _, std in tables.values()])
    print(f"[A] generated {len(strict_rows)} NPD rows for {future.name} "
          f"(strict ANP layout + uncalibrated tree-dispersion companion; "
          f"mean cross-tree std {mean_std:.2f} dB)")

    # ---- (B) held-out reproduction plots for real, recognizable aircraft -------
    CANDIDATES = ["A350-941", "GE90", "TRENT7", "V2527A", "PW4056", "CF567B"]

    def reproduce(npd_id, metric="SEL", om="D"):
        if npd_id not in params.index:
            print(f"[B] skip {npd_id}: no NPD/{metric}/{om} curve set"); return None
        et = SurrogateNPDModel("et")
        rf = SurrogateNPDModel("rf")
        excluded = tuple(curves_by_group[npd_to_group[npd_id]])
        et.fit(db, metric, om, exclude_ids=excluded)
        rf.fit(db, metric, om, exclude_ids=excluded)
        row = params.loc[npd_id]
        ac = ParametricAircraft.from_anp_row(npd_id, row)
        cv = db.curve(npd_id, metric, om); P = cv['Power Setting'].values.astype(float)
        truth = cv[DIST_COLS].values
        pp = str(row['Power Parameter'])
        tbl, std = et.predict_table(ac, metric, om, P, return_std=True,
                                    power_parameter=pp)
        rf_levels = rf.predict_table(
            ac, metric, om, P, power_parameter=pp).L
        fig, ax = plt.subplots(figsize=(6.4, 4.6))
        cmap = plt.cm.viridis(np.linspace(0, .82, len(P)))
        for i in range(len(P)):
            ax.semilogx(STANDARD_DISTANCES_FT, truth[i], 'o-', color=cmap[i], lw=1.7,
                        label=("ANP truth" if i == 0 else None))
            ax.semilogx(STANDARD_DISTANCES_FT, tbl.L[i], 's--', color=cmap[i], lw=1.1,
                        label=("ET (held out)" if i == 0 else None))
            ax.semilogx(STANDARD_DISTANCES_FT, rf_levels[i], ':', color=cmap[i],
                        lw=1.0, label=("RF (held out)" if i == 0 else None))
            ax.fill_between(STANDARD_DISTANCES_FT, tbl.L[i] - std[i], tbl.L[i] + std[i],
                            color=cmap[i], alpha=.12)
        ax.set_xlabel("slant distance [ft]"); ax.set_ylabel(f"{metric} [dB]")
        ax.set_title(f"{ac.name} ({npd_id}): {metric}/{om}, "
                     f"aircraft-group held out (\u00b11\u03c3 band)",
                    fontsize=10.5)
        ax.grid(True, which='both', alpha=.25); ax.legend(fontsize=8)
        fig.tight_layout(); fig.savefig(f"{OUT}/reproduce_{npd_id}_{metric}_{om}.png", dpi=130)
        plt.close(fig)
        rmse_et = float(np.sqrt(np.mean((tbl.L - truth) ** 2)))
        rmse_rf = float(np.sqrt(np.mean((rf_levels - truth) ** 2)))
        return rmse_et, rmse_rf

    print()
    for cid in CANDIDATES:
        r = reproduce(cid)
        if r is not None:
            print(f"[B] {cid:10s} held-out RMSE  ET={r[0]:.2f} dB  "
                  f"RF={r[1]:.2f} dB")

    # ---- (C) grouped 5-fold validation scatter (fast, whole-population) --------
    def grouped_scatter(metric="SEL", om="D"):
        X, Y, npd_groups = SurrogateNPDModel("et")._design_matrix(
            db, metric, om)
        G = np.array([npd_to_group[str(npd_id)] for npd_id in npd_groups])
        gkf = GroupKFold(n_splits=5); tr_all, pr_all = [], []
        for tri, tei in gkf.split(X, Y, G):
            model = SurrogateNPDModel("et", random_state=0)._new_regressor()
            model.fit(X[tri], Y[tri])
            pr_all.append(model.predict(X[tei])); tr_all.append(Y[tei])
        tr = np.vstack(tr_all).ravel(); pr = np.vstack(pr_all).ravel()
        fig, ax = plt.subplots(1, 2, figsize=(11, 4.3))
        ax[0].scatter(tr, pr, s=6, alpha=.28, color="#2b6cb0")
        lo, hi = min(tr.min(), pr.min()), max(tr.max(), pr.max())
        ax[0].plot([lo, hi], [lo, hi], 'k--', lw=1)
        ax[0].set_xlabel("ANP true level [dB]"); ax[0].set_ylabel("predicted (5-fold) [dB]")
        ax[0].set_title(f"{metric}/{om}  RMSE={np.sqrt(np.mean((pr-tr)**2)):.2f} dB")
        ax[1].hist(pr - tr, bins=45, color="#2b6cb0", alpha=.85)
        ax[1].set_xlabel("error [dB]"); ax[1].set_ylabel("count")
        ax[1].set_title("error distribution")
        fig.tight_layout(); fig.savefig(f"{OUT}/validation_scatter_{metric}_{om}.png", dpi=130)
        plt.close(fig)

    grouped_scatter("SEL", "D")
    print("\n[C] validation scatter saved (validation_scatter_SEL_D.png)")

    # ---- (D) feature importance from full RF (SEL/D) ---------------------------
    rf = sur.models[("SEL", "D")]
    imp = rf.feature_importances_
    names = ParametricAircraft.feature_names() + ["log_power_lb", "throttle_frac"]
    order = np.argsort(imp)[::-1]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.barh([names[i] for i in order][::-1], imp[order][::-1], color="#2b6cb0")
    ax.set_title("Surrogate feature importance (SEL / Departure)")
    ax.set_xlabel("importance"); fig.tight_layout()
    fig.savefig(f"{OUT}/feature_importance_SEL_D.png", dpi=130); plt.close(fig)
    print("[D] top features:", {names[i]: round(float(imp[i]), 3) for i in order[:5]})

    # ---- (E) END-TO-END: parametric aircraft -> NPD -> trajectory -> sideline --
    syn = DepartureSynthesizer(db)
    assert db.dep_steps is not None  # demo needs the departure procedural steps
    usable = set(db.dep_steps['ACFT_ID'].unique())
    match = db.nearest_aircraft(future.mtow_lb, engine_type=future.engine_type,
                                n_engines=future.n_engines, n=5,
                                restrict_to=usable)
    donor = match['ACFT_ID'].iloc[0]
    donor_thrust = float(match['Max Sea Level Static Thrust (lb)'].iloc[0])
    scale = future.max_static_thrust_lb / donor_thrust
    prof_future = syn.synthesize(donor, stage_length=1,
                                 weight_lb=0.85 * future.mtow_lb,
                                 thrust_scale=scale, out_name=future.name)
    print(f"\n[E] end-to-end: borrowed '{donor}' departure procedure "
          f"(thrust deck rescaled x{scale:.2f}, W=0.85 MTOW) -> "
          f"{len(prof_future.points)} profile points, "
          f"top of profile {prof_future.points['altitude_ft'].iloc[-1]:.0f} ft")

    # reference: real A320-211 with its own ANP truth table + synthesized profile
    ref_id = 'A320-211'
    ref_row = db.aircraft[db.aircraft['ACFT_ID'] == ref_id].iloc[0]
    ref_npd = db.curve(str(ref_row['NPD_ID']), 'LAmax', 'D')
    ref_tbl = NPDTable(ref_npd['Power Setting'].values.astype(float),
                       ref_npd[DIST_COLS].values, 'LAmax', 'D', npd_id=ref_id)
    prof_ref = syn.synthesize(ref_id, stage_length=1)

    ftab, _ = tables[("LAmax", "D")]
    xs = np.linspace(2000, 80000, 60)                       # along-track [ft]
    side = 1476.0                                           # 450 m sideline
    lam_f = [prof_future.flyover_level(ftab, x, side) for x in xs]
    lam_r = [prof_ref.flyover_level(ref_tbl, x, side) for x in xs]

    fig, ax = plt.subplots(1, 2, figsize=(11.5, 4.4))
    for prof, lab, col in [(prof_ref, f"{ref_id} (ANP truth NPD)", "#2b6cb0"),
                           (prof_future, f"{future.name} (generated NPD)", "#c53030")]:
        ax[0].plot(prof.points['distance_ft'] / 6076, prof.points['altitude_ft'],
                   'o-', color=col, label=lab, lw=1.6, ms=4)
    ax[0].set_xlabel("along-track distance [NM]"); ax[0].set_ylabel("altitude AFE [ft]")
    ax[0].set_title("Synthesized departure profiles (SAE-AIR-1845 style)")
    ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)
    ax[1].plot(xs / 6076, lam_r, '-', color="#2b6cb0", lw=1.8,
               label=f"{ref_id} (ANP truth NPD)")
    ax[1].plot(xs / 6076, lam_f, '-', color="#c53030", lw=1.8,
               label=f"{future.name} (generated NPD)")
    ax[1].set_xlabel("observer along-track position [NM]")
    ax[1].set_ylabel("single-event LAmax [dB]")
    ax[1].set_title("Sideline LAmax, 450 m offset (end-to-end)")
    ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)
    fig.tight_layout(); fig.savefig(f"{OUT}/end_to_end_sideline.png", dpi=130)
    plt.close(fig)
    print(f"    peak sideline LAmax: {ref_id} {max(lam_r):.1f} dB | "
          f"{future.name} {max(lam_f):.1f} dB  -> end_to_end_sideline.png")

    print("\nDone. Outputs in", OUT)



def cmd_compare():
    """Algorithm bake-off: leave-one-aircraft-out comparison of supported
    NPD predictor, on the same harness that produced the README RMSE table.

    Candidates
      rf       - SurrogateNPDModel('rf')        (baseline to beat)
      et       - SurrogateNPDModel('et')        (ExtraTrees, static config from
                 the evolutionary search registry)
    Columns per model: pooled RMSE (dB, pools all cells - reproduces the README,
    e.g. rf SEL/D = 5.09), and the per-aircraft RMSE mean and median (dB). Winner
    is chosen on the lowest per-aircraft median RMSE averaged across metric:op.

    Per model per combo, two gap-report CSVs are also written:
      outputs/gap_report/per_aircraft_{model}_{metric}_{mode}.csv  (LOO per-aircraft df)
      outputs/gap_report/cells_{model}_{metric}_{mode}.csv         (long-format per-cell df)

    Run:  .venv\\Scripts\\python.exe pnmf_cli.py compare [SEL:D SEL:A ...]
    (formerly compare_algorithms.py)
    With no args, runs all eight combos (SEL/LAmax/EPNL/PNLTM x D/A). With args,
    runs only those combos and merges into outputs/algorithm_comparison.csv
    (existing rows for the same combo are replaced), so a long run can be split
    into short per-combo commands. The winner summary prints once all eight
    combos are in the CSV.
    """
    import os
    import sys
    import time
    import pandas as pd

    from pnmf import ANPDatabase, SurrogateNPDModel
    from pnmf.models import loo_validate

    db = ANPDatabase('.')
    OUT = './outputs'; os.makedirs(OUT, exist_ok=True)
    GAP = f"{OUT}/gap_report"; os.makedirs(GAP, exist_ok=True)
    CSV = f"{OUT}/algorithm_comparison.csv"

    ALL_COMBOS = [("SEL", "D"), ("SEL", "A"), ("LAmax", "D"), ("LAmax", "A"),
                  ("EPNL", "D"), ("EPNL", "A"), ("PNLTM", "D"), ("PNLTM", "A")]
    MODELS = {
        "rf":      lambda: SurrogateNPDModel("rf"),
        "et":      lambda: SurrogateNPDModel("et"),
    }

    combos = ([tuple(a.split(":")) for a in sys.argv[1:]]
              if len(sys.argv) > 1 else ALL_COMBOS)

    rows = []
    for metric, om in combos:
        rec: dict[str, float | str] = {"metric_op": f"{metric}:{om}"}
        for name, fac in MODELS.items():
            t = time.time()
            summary, per_ac, cells = loo_validate(db, fac, metric, om,
                                                  return_cells=True)
            per_ac.to_csv(f"{GAP}/per_aircraft_{name}_{metric}_{om}.csv",
                          index=False)
            cells.to_csv(f"{GAP}/cells_{name}_{metric}_{om}.csv", index=False)
            rec[f"{name}_pooledRMSE"] = round(summary["rmse_dB"], 2)
            rec[f"{name}_meanRMSE"] = round(float(per_ac["rmse"].mean()), 2)
            rec[f"{name}_medRMSE"] = round(float(per_ac["rmse"].median()), 2)
            print(f"{metric}:{om:2s} {name:8s} pooled={rec[f'{name}_pooledRMSE']:5.2f} "
                  f"mean={rec[f'{name}_meanRMSE']:5.2f} med={rec[f'{name}_medRMSE']:5.2f} "
                  f"({time.time()-t:4.0f}s)", flush=True)
        rows.append(rec)

    new = pd.DataFrame(rows)
    if os.path.exists(CSV):
        old = pd.read_csv(CSV)
        old = old[~old["metric_op"].isin(new["metric_op"])]
        new = pd.concat([old, new], ignore_index=True)
    order = [f"{m}:{om}" for m, om in ALL_COMBOS]
    present = [c for c in order if c in set(new["metric_op"])]
    new = new.set_index("metric_op").reindex(present).reset_index()
    new.to_csv(CSV, index=False)
    print("Wrote", CSV)

    # ---- winner selection: mean over combos of per-aircraft median RMSE ---------
    if len(new) == len(ALL_COMBOS):
        names = [c[:-len("_medRMSE")] for c in new.columns
                 if c.endswith("_medRMSE")]
        print(f"\nOverall (mean of per-aircraft median RMSE across the "
              f"{len(ALL_COMBOS)} combos):")
        overall = {n: float(new[f"{n}_medRMSE"].mean()) for n in names}
        overall = {n: v for n, v in overall.items() if v == v}  # drop all-NaN
        for name, v in sorted(overall.items(), key=lambda kv: kv[1]):
            print(f"  {name:8s} {v:5.2f} dB")
        winner = min(overall, key=overall.__getitem__)
        print(f"\nWINNER: {winner}  (mean per-aircraft median RMSE "
              f"{overall[winner]:.2f} dB)")



def cmd_subs():
    """External validation against the EASA/ECAC aircraft-substitution table.

    This is independent of the 111-aircraft ANP NPD population used to train and
    leave-one-out-validate the surrogate: it is ~19.5k real certificated aircraft
    records with measured LATERAL / FLYOVER / APPROACH EPNL, MTOW, and engine
    count, each carrying its own real mismatch (DELTA_DEP_dB / DELTA_APP_dB)
    against the ANP proxy assigned to it by EASA's own substitution methodology.

    Two things come out of this:
    1. A real-world accuracy benchmark: how far off is a *manually curated*
       nearest-proxy substitution from truth, in practice? (DELTA_* columns)
    2. An independent scaling/trend check: does the surrogate's EPNL-vs-MTOW-and-
       thrust trend agree with this much larger, independently sourced dataset?

    Run:  .venv\\Scripts\\python.exe pnmf_cli.py subs /path/to/substitution.xlsx
    (formerly validate_against_substitutions.py)
    """
    import sys, os
    import numpy as np
    import pandas as pd
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

    from pnmf import ANPDatabase, ParametricAircraft, SurrogateNPDModel

    SUB_PATH = sys.argv[1] if len(sys.argv) > 1 else \
        "/mnt/project/anp_aircraft_substitutions__jets_heavy_props_22022018_.xlsx"
    OUT = "./outputs"; os.makedirs(OUT, exist_ok=True)

    db = ANPDatabase('.')
    sub = db.load_substitution_table(SUB_PATH)
    print(f"Loaded {len(sub)} certificated aircraft records "
          f"({sub['anp_proxy'].nunique()} distinct ANP proxies used).")

    # ---- (1) real-world substitution accuracy benchmark ------------------------
    print("\n[1] Real-world nearest-proxy substitution accuracy (EASA methodology):")
    for col, label in [('delta_dep_db', 'departure'), ('delta_app_db', 'approach')]:
        d = sub[col].dropna()
        print(f"  {label:10s}: mean={d.mean():+.2f} dB  std={d.std():.2f} dB  "
             f"RMSE={np.sqrt((d**2).mean()):.2f} dB  (n={len(d)})")
    print("  -> this is the accuracy ceiling of *manual* nearest-proxy "
          "substitution in real practice;\n     compare directly with the "
          "surrogate's leave-one-out RMSE in outputs/validation_summary.csv.")

    # ---- (2) independent EPNL vs size/thrust trend check ------------------------
    sur = SurrogateNPDModel("rf").fit_all(db, metrics=("EPNL",), op_modes=("D", "A"))
    jet = sub[(sub['engine'].notna()) & (sub['n_engines'] > 0)].copy()
    jet['mtow_lb'] = jet['mtow_kg'] * 2.20462
    # sample for tractability + de-duplicate near-identical variants
    jet_s = jet.drop_duplicates(subset=['ICAO_CODE']).dropna(subset=['flyover_epndb'])
    print(f"\n[2] Independent trend check on {len(jet_s)} unique ICAO types "
          f"(certified FLYOVER_LEVEL_EPNdB vs surrogate EPNL/Departure prediction "
          f"at a representative thrust setting).")

    preds = []
    for _, r in jet_s.iterrows():
        ac = ParametricAircraft(name=str(r['ICAO_CODE']), engine_type="Jet",
                                n_engines=int(r['n_engines']),
                                max_static_thrust_lb=max(r['mtow_lb'] * 0.28, 3000),
                                mtow_lb=r['mtow_lb'],
                                mlw_lb=r['mlw_kg'] * 2.20462 if pd.notna(r['mlw_kg']) else r['mtow_lb'] * 0.85,
                                noise_chapter=int(r['NOISE_CHAPTER']) if pd.notna(r['NOISE_CHAPTER']) else 4)
        tbl = sur.predict_table(ac, "EPNL", "D", [ac.max_static_thrust_lb * 0.9])
        preds.append(tbl.level(ac.max_static_thrust_lb * 0.9, 6500))
    jet_s = jet_s.assign(surrogate_epnl_proxy=preds)

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(jet_s['flyover_epndb'], jet_s['surrogate_epnl_proxy'], s=14, alpha=.55,
              color="#c53030")
    lo = min(jet_s['flyover_epndb'].min(), jet_s['surrogate_epnl_proxy'].min())
    hi = max(jet_s['flyover_epndb'].max(), jet_s['surrogate_epnl_proxy'].max())
    ax.plot([lo, hi], [lo, hi], 'k--', lw=1, label="1:1 (not expected to match "
            "exactly - different geometry & distance)")
    corr = np.corrcoef(jet_s['flyover_epndb'], jet_s['surrogate_epnl_proxy'])[0, 1]
    ax.set_xlabel("certified FLYOVER EPNdB (substitution table)")
    ax.set_ylabel("surrogate EPNL @ 6500 ft, 90% thrust [dB]")
    ax.set_title(f"Independent trend check  (Pearson r = {corr:.2f})")
    ax.legend(fontsize=7)
    fig.tight_layout(); fig.savefig(f"{OUT}/external_trend_check.png", dpi=130)
    plt.close(fig)
    print(f"  Pearson correlation with certified flyover levels: r = {corr:.2f}")
    print(f"  (r>0 confirms the surrogate's size/thrust scaling direction is "
          f"correct on data\n   it never saw; absolute level offset is expected "
          f"since the certification geometry\n   differs from the fixed 6500 ft "
          f"/ 90%-thrust query point used here.)")

    jet_s[['ICAO_CODE', 'mtow_lb', 'n_engines', 'flyover_epndb',
          'surrogate_epnl_proxy']].to_csv(f"{OUT}/external_trend_check.csv", index=False)
    print("\nSaved: outputs/external_trend_check.png, outputs/external_trend_check.csv")



COMMANDS = {
    "datastore": cmd_datastore,
    "manifest": cmd_manifest,
    "predict": cmd_predict,
    "validate": cmd_validate,
    "validate-model": cmd_validate_model,
    "validate-jet-reference": cmd_validate_jet_reference,
    "physics": cmd_physics,
    "demo": cmd_demo,
    "compare": cmd_compare,
    "subs": cmd_subs,
}


def _usage():
    print((__doc__ or "").strip())


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help") \
            or sys.argv[1] not in COMMANDS:
        _usage()
        return 0 if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help") else 1
    cmd = sys.argv.pop(1)          # shift: command args become argv[1:]
    sys.argv[0] = f"pnmf_cli.py {cmd}"
    COMMANDS[cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
