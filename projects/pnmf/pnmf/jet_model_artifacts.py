"""Persist and document the Jet learned-model validation evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import pandas as pd  # noqa: PANDAS_OK - validation artifacts use the existing DataFrame contract.

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
RunRecord: TypeAlias = dict[str, str | int | float]


@dataclass(frozen=True, slots=True)
class ArtifactBundle:
    """Frames and JSON payloads emitted by one immutable validation run."""

    samples: pd.DataFrame
    splits: pd.DataFrame
    predictions: pd.DataFrame
    runs: tuple[RunRecord, ...]
    schema_metrics: dict[str, JSONValue]
    gates: dict[str, JSONValue]
    bootstrap: dict[str, JSONValue]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decision_payload(decision) -> dict[str, JSONValue]:
    """Convert a gate decision to a stable JSON object."""
    return {
        "passed": decision.passed,
        "relative_improvement": decision.relative_improvement,
        "failures": list(decision.failures),
    }


def metrics_payload(metrics) -> dict[str, JSONValue]:
    """Convert balanced metrics to a stable JSON object."""
    return {
        "overall_rmse": metrics.overall_rmse,
        "task_rmse": dict(metrics.task_rmse),
        "slice_rmse": dict(metrics.slice_rmse),
        "bootstrap_delta_ci": list(metrics.bootstrap_delta_ci),
        "rf_overall_rmse": metrics.rf_overall_rmse,
        "rf_task_rmse": dict(metrics.rf_task_rmse),
    }


def write_artifacts(output_dir: Path, bundle: ArtifactBundle) -> dict[str, dict[str, JSONValue]]:
    """Write machine-readable frames and return their integrity records."""
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle.samples.to_csv(output_dir / "samples.csv", index=False, lineterminator="\n")
    bundle.splits.to_csv(output_dir / "splits.csv", index=False, lineterminator="\n")
    bundle.predictions.to_csv(output_dir / "predictions.csv", index=False, lineterminator="\n")
    pd.DataFrame(bundle.runs).to_csv(output_dir / "fit_runs.csv", index=False, lineterminator="\n")
    for name, payload in (
        ("schema_metrics.json", bundle.schema_metrics),
        ("gate_decisions.json", bundle.gates),
        ("bootstrap_results.json", bundle.bootstrap),
    ):
        (output_dir / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
    records: dict[str, dict[str, JSONValue]] = {}
    for name in (
        "samples.csv",
        "splits.csv",
        "predictions.csv",
        "fit_runs.csv",
        "schema_metrics.json",
        "gate_decisions.json",
        "bootstrap_results.json",
    ):
        path = output_dir / name
        records[name] = {
            "path": str(path.resolve()),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
    return records


def write_report(path: Path, manifest: dict[str, JSONValue]) -> None:
    """Write the durable Jet learned-model screening report."""
    promotion = manifest["promotion"]
    selected = manifest["feature_selection"]
    counts = manifest["counts"]
    selected_metrics = selected.get("selected_metrics")
    if selected_metrics is None:
        selected_evaluation = next(
            evaluation
            for evaluation in selected["evaluations"]
            if evaluation["schema_id"] == selected["selected_schema"]
        )
        selected_metrics = selected_evaluation["metrics"]
    comparison = manifest.get("model_comparison", {})
    task_lines = [
        f"- `{task}`: `{value:.3f} dB`"
        for task, value in sorted(selected_metrics["task_rmse"].items())
    ]
    et_task_rmse = comparison.get("et_task_rmse", selected_metrics["task_rmse"])
    rf_task_rmse = comparison.get("rf_task_rmse", selected_metrics.get("rf_task_rmse", {}))
    task_comparison_lines: list[str] = []
    task_wins = 0
    if isinstance(et_task_rmse, dict) and isinstance(rf_task_rmse, dict):
        for task in sorted(set(et_task_rmse) & set(rf_task_rmse)):
            et_value = float(et_task_rmse[task])
            rf_value = float(rf_task_rmse[task])
            winner = "ET" if et_value < rf_value else "RF" if rf_value < et_value else "tie"
            task_wins += winner == "ET"
            task_comparison_lines.append(
                f"- `{task}`: ET `{et_value:.3f} dB` vs RF `{rf_value:.3f} dB` (winner: `{winner}`)."
            )
    task_result_line = (
        f"- Task-level result: **ET wins all {task_wins} recorded tasks.**"
        if task_comparison_lines and task_wins == len(task_comparison_lines)
        else "- Task-level result: no all-task ET sweep claim is made unless every recorded task favors ET."
    )
    source_hash = manifest["inputs"]["datastore_sha256"]
    lines = [
        "# Jet Model Methodology and Validation Report",
        "",
        "This report is screening evidence for interpolation in the available ANP "
        "population, not unseen-family, uncertainty-calibration, or certification evidence.",
        "",
        "## Decision",
        "",
        "- Feature set: compact nine-feature Jet production schema.",
        f"- Jet route gate: **{'PASS' if promotion['passed'] else 'FAIL'}**.",
        "- Production training population: complete Jet population.",
        f"- Population: `{counts['samples']}` rows, `{counts['curves']}` curves, "
        f"`{counts['aircraft_groups']}` aircraft groups.",
        "",
        "A failed candidate gate keeps the compact production feature set. Production promotion is an explicit audited source change; validation output cannot silently reroute production.",
        "",
        "## Learned-model comparison",
        "",
        f"- ET group/task-balanced RMSE: `{comparison.get('et_overall_rmse', selected_metrics['overall_rmse']):.3f} dB`; RF validation RMSE: `{comparison.get('rf_overall_rmse', selected_metrics['rf_overall_rmse']):.3f} dB`.",
        f"- Paired aircraft-group ET minus RF bootstrap interval: `{comparison.get('et_minus_rf_bootstrap_ci', manifest.get('bootstrap', {}).get('et_vs_rf', {}).get('delta_ci_rmse_dB', ['not recorded', 'not recorded']))}` dB; RF cannot become the production learner through this workflow.",
        "- Equal task weighting is applied after aircraft-group balancing. Selected-schema task RMSE:",
        *task_lines,
        "- Selected-schema balanced task comparison:",
        *task_comparison_lines,
        task_result_line,
        "",
        "## Protocol",
        "",
        f"Five-fold grouped validation uses seeds `{manifest['config']['seeds']}`. "
        "Groups are stratified jointly by engine count and aircraft-level log-total-static-thrust tertile; "
        "no aircraft group crosses folds. All eight metric/mode tasks contain all 94 Jet curves.",
        "The selected-feature RMSE reuses the grouped folds used for feature selection; it is not a nested-CV or post-selection holdout estimate.",
        "The frozen 83-legacy-to-11-v6.3 comparison remains descriptive release-transfer evidence, not a pristine unseen test.",
        "",
        "## Feature schemas and formula",
        "",
        "The derived field is `log_total_operating_cnt_lb = log10(per-engine corrected net thrust in lb) + log10(engine count)`. "
        "It is not generic power output. Jet schemas remove constant engine-type one-hot columns and compare compact, count-removed, count-replaced, and count-plus-total candidates.",
        "",
        "Production feature order: `"
        + "`, `".join(
            manifest["features"]["schemas"][selected["selected_schema"]])
        + "`.",
        "The frozen comparison covers the compact feature set, engine count removed, engine count replaced by total operating CNT, and compact features plus total operating CNT.",
        "",
        "## Conservative gate",
        "",
        f"Thresholds: `{json.dumps(manifest['thresholds'], sort_keys=True)}`. ET must improve at least 5%; the 10,000-resample paired aircraft-group bootstrap interval must be below zero; task, count/static/operating-CNT slices and RF are bounded by the declared regression limits.",
        "",
        "## Artifacts",
        "",
        "`samples.csv`, `splits.csv`, `predictions.csv`, `fit_runs.csv`, `schema_metrics.json`, `gate_decisions.json`, and `bootstrap_results.json` contain the exact features, formulas, splits, predictions, metrics, thresholds, hashes, and decisions.",
        f"The validated datastore SHA-256 is `{source_hash}`. Source release hashes and URLs are recorded in `anp_dataset_manifest` and `docs/EASA_ECAC_SOURCE_LEDGER.md`.",
        "The Doc 29 lane is run only with `verify-doc29-reference --workbook <official-workbook>` and checks interpolation/reference-case equivalence; it does not measure ET accuracy or validate component physics.",
        "Component physics remains a separate SEL/LAmax plausibility lane with its own provenance, fallbacks, and exclusions; it does not receive learned features, residuals, or corrections.",
        "",
        "## Scientific boundaries",
        "",
        "The learned ET/RF and frozen physics SEL/LAmax routes remain independent. No power-axis monotonic constraint is added because the Jet truth contains curve-task reversals. Results remain conceptual screening evidence, not certification or calibrated uncertainty.",
        "EASA source provenance does not establish ML accuracy. ECAC Doc 29 Volume 3 Part 1 is an implementation/reference-case check, not real-aircraft measurement validation.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_status(output_dir: Path, manifest: dict[str, JSONValue]) -> dict[str, JSONValue]:
    """Write the conditional production-scope status artifact."""
    path = output_dir / "promotion_status.json"
    payload: dict[str, JSONValue] = {
        "promoted": manifest["promotion"]["passed"],
        "scope": manifest["promotion"]["production_scope"],
        "selected_schema": manifest["feature_selection"]["selected_schema"],
        "report_sha256": manifest["artifacts"]["validation_report"]["sha256"],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def write_manifest(output_dir: Path, manifest: dict[str, JSONValue]) -> None:
    """Write the final manifest after all artifact hashes are known."""
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
