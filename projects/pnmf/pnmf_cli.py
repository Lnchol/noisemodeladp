"""PNMF command-line interface - all framework entry points in one file.

Usage:  .venv\\Scripts\\python.exe pnmf_cli.py <command> [args...]

Commands:
  datastore build anp_data.sqlite from raw v2.3 + v6.3 CSV sources
  manifest  inspect the combined training-corpus provenance
  predict   predict + QA-gate + store NPD tables for a future aircraft
  validate-jet-reference frozen representative Jet ET/RF holdout
  validate-jet-model evidence-gated Jet feature and learner comparison
  verify-doc29-reference official ECAC Doc 29 Volume 3 Part 1 contract
  physics   physics-route calibration + fleet validation + BPR sweep

See each command's docstring for flags and output artifacts.
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)


def parse_power_grid(value):
    """Parse an optional comma-separated NPD power grid in lbf/engine."""
    if value is None or not value.strip():
        return None
    try:
        return [float(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise ValueError(
            "NPD power grids must be comma-separated numeric lbf/engine values"
        ) from exc

def cmd_datastore():
    """Build the single-file SQLite datastore from the staged ANP CSVs.

    Usage (formerly build_datastore.py):
        .venv\\Scripts\\python.exe pnmf_cli.py datastore [root]

    Reads the raw v2.3 semicolon CSVs and v6.3 comma CSVs under 03_data,
    merges them with source provenance, and writes canonical truth tables.
    """
    from pnmf.anp import ANPDatabase, build_datastore

    root = sys.argv[1] if len(sys.argv) > 1 else "."
    db_path = build_datastore(root)
    print(f"built {db_path}")
    db = ANPDatabase(db_path)
    print(db.dataset_manifest().to_string(index=False))
    print("combined summary:", db.summary())


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
                      A320-270N, frozen) re-predicts SEL/LAmax; mean |delta| is
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
    from pnmf.api import NoisePredictor, prediction_model_identity
    from pnmf.anp import DB_FILENAME, PredictionStore


    def parse_args():
        ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
        ap.add_argument("--name", default=FUTURE_UHBR_TWIN["name"])
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
        ap.add_argument("--departure-powers", default=None, metavar="LBF,...",
                        help="optional departure NPD row powers [lbf/engine], "
                             "for example 18000,24000,30000")
        ap.add_argument("--approach-powers", default=None, metavar="LBF,...",
                        help="optional approach NPD row powers [lbf/engine], "
                             "for example 2500,4500,6500")
        ap.add_argument("--db", default=DB_FILENAME)
        ap.add_argument("--dry-run", action="store_true",
                        help="predict and QA-check but do not write to the database")
        return ap.parse_args()


    def main():
        args = parse_args()
        if not os.path.exists(args.db):
            sys.exit(f"{args.db} not found - run: pnmf_cli.py datastore first")

        aircraft = ParametricAircraft(
            name=args.name,
            n_engines=args.n_engines, max_static_thrust_lb=args.thrust_lb,
            mtow_lb=args.mtow_lb, mlw_lb=args.mlw_lb,
            bypass_ratio=args.bpr, noise_chapter=args.noise_chapter)
        try:
            power_settings = {
                "D": parse_power_grid(args.departure_powers),
                "A": parse_power_grid(args.approach_powers),
            }
        except ValueError as exc:
            sys.exit(f"invalid NPD power grid: {exc}")

        print("[1/4] fitting Extra Trees on the complete Jet population ...")
        pred = NoisePredictor(root=".")

        try:
            print(f"[2/4] predicting NPD tables for {aircraft.name} ...")
            result = pred.predict(aircraft, power_settings=power_settings)
        except ValueError as exc:
            sys.exit(f"prediction input rejected: {exc}")

        print(
            "      model: Extra Trees; training population: complete Jet "
            f"population; features: {len(result.metadata['feature_names'])}"
        )
        print("[3/4] independent physics cross-check (SEL/LAmax) ...")
        crosscheck = result.crosscheck_physics(bpr=args.bpr)
        for metric, delta in crosscheck.items():
            print(f"      {metric}: mean |physics - ET| = {delta:.2f} dB")

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
                                model=prediction_model_identity(),
                                crosscheck=crosscheck,
                                metadata=result.metadata)

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
                 f" -> {args.db} [predicted_npd / predicted_aircraft; "
                 "model=Extra Trees production]"))
        if not args.dry_run and (n_ok + n_caution):
            df = store.npd(name=aircraft.name)
            print(f"database now holds {len(df)} predicted NPD rows for "
                  f"{aircraft.name}. The anp_* truth tables are untouched.")


    if True:
        main()



def cmd_validate_jet_reference():
    """Run the frozen representative-jet ET/RF holdout experiment."""
    from pnmf.jet_reference_validation import main

    raise SystemExit(main(sys.argv[1:]))


def cmd_validate_jet_model():
    """Run the evidence-gated all-Jet feature and learner comparison."""
    import argparse

    from pnmf.jet_model_runner import (
        DEFAULT_OUTPUT_DIR,
        DEFAULT_REPORT_PATH,
        JET_V2_FOLDS,
        JET_V2_SEEDS,
        run_jet_model_validation,
    )

    parser = argparse.ArgumentParser(
        description="Run five-fold grouped Jet validation and promotion gates."
    )
    parser.add_argument("--db", default=str(PROJECT_ROOT / "anp_data.sqlite"))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--folds", type=int, default=JET_V2_FOLDS)
    parser.add_argument(
        "--seeds",
        default=",".join(str(seed) for seed in JET_V2_SEEDS),
        help="comma-separated grouped-CV seeds",
    )
    parser.add_argument("--bootstrap-resamples", type=int, default=10_000)
    args = parser.parse_args(sys.argv[1:])
    seeds = tuple(int(value.strip()) for value in args.seeds.split(",") if value.strip())
    manifest = run_jet_model_validation(
        db_path=Path(args.db),
        output_dir=Path(args.output_dir),
        report_path=Path(args.report),
        folds=args.folds,
        seeds=seeds,
        bootstrap_resamples=args.bootstrap_resamples,
    )
    promotion = manifest["promotion"]
    print("production feature gate: complete; see the machine manifest for details")
    print(
        f"route gate: {'PASS' if promotion['passed'] else 'FAIL'}; "
        "production population: complete Jet population"
    )
    print(f"report: {args.report}")


def cmd_verify_doc29_reference():
    import argparse

    from pnmf.doc29_reference import verify_doc29_workbook

    parser = argparse.ArgumentParser(
        description="Verify the official ECAC Doc 29 Volume 3 Part 1 workbook."
    )
    parser.add_argument("--workbook", required=True)
    parser.add_argument("--sha256", default=None)
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "outputs" / "doc29_reference_verification.json"),
    )
    args = parser.parse_args(sys.argv[1:])
    expected = args.sha256
    if expected is None:
        sidecar = Path(str(args.workbook) + ".sha256")
        if sidecar.is_file():
            expected = sidecar.read_text(encoding="utf-8").split()[0]
    if expected is None:
        parser.error("--sha256 or <workbook>.sha256 is required")
    manifest = verify_doc29_workbook(args.workbook, expected, args.output)
    print(f"Doc 29 reference verification: {manifest['status']}")
    print(f"workbook SHA-256: {manifest['sha256']}")
    print(f"artifact: {args.output}")


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
    from pnmf.physics_calibration import load_calibrated_model
    from pnmf.anp import DIST_COLS

    db = ANPDatabase('.')
    OUT = './outputs'; os.makedirs(OUT, exist_ok=True)

    # public bypass ratios for well-known ANP aircraft (ACFT_ID -> BPR)
    FLEET_BPR = {
        'A320-270N': 12.0,
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
    model, calibration = load_calibrated_model()
    print("[A] loaded frozen calibration:", calibration["anchor"],
          calibration["metrics"])


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
    des_cal, npd_cal = design_from_anp('A320-270N', FLEET_BPR['A320-270N'])
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
        ax.set_title(f"A320-270N SEL / {title} (calibration aircraft)", fontsize=10)
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
                         role='calibration' if acid == 'A320-270N' else 'out-of-sample'))
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
    sur = SurrogateNPDModel().fit(db, 'SEL', 'D')
    P = np.array([13500., 19500., 25500., 28500.])
    tbl_phys = model.predict_table(future_phys, 'SEL', 'D', P)
    tbl_sur, std = sur.predict_table(future_par, 'SEL', 'D', P, return_std=True)
    fig, ax = plt.subplots(figsize=(6.6, 4.6))
    cmap = plt.cm.viridis(np.linspace(0, .8, len(P)))
    for i in range(len(P)):
        ax.semilogx(STANDARD_DISTANCES_FT, tbl_phys.L[i], 'o-', color=cmap[i],
                    lw=1.6, label='physics (pyNA-family)' if i == 0 else None)
        ax.semilogx(STANDARD_DISTANCES_FT, tbl_sur.L[i], 's--', color=cmap[i],
                    lw=1.2, label='Extra Trees production' if i == 0 else None)
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



COMMANDS = {
    "datastore": cmd_datastore,
    "manifest": cmd_manifest,
    "predict": cmd_predict,
    "validate-jet-reference": cmd_validate_jet_reference,
    "validate-jet-model": cmd_validate_jet_model,
    "verify-doc29-reference": cmd_verify_doc29_reference,
    "physics": cmd_physics,
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
