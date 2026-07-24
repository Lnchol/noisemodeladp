"""Frozen representative-jet holdout validation for the production ET/RF models."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd
import sklearn

from .anp import ANPDatabase, DIST_COLS, PROJECT_ROOT
from .models import SUPPORTED_LEARNERS
from .validation import (
    COMBOS,
    FEATURES,
    TRUTH_COLUMNS,
    _fit_predict,
    _git_state,
    _markdown_table,
    _project_relative,
    _sha256_file,
    _sha256_json,
    build_samples,
    exact_model_params,
)

PROTOCOL = "frozen_jet_reference_holdout"
FROZEN_REFERENCES = {
    2: {"npd_id": "BR715", "acft_id": "717200"},
    3: {"npd_id": "3JT8E5", "acft_id": "727EM2"},
    4: {"npd_id": "PW4056", "acft_id": "747400"},
}
EXPECTED = {
    "jet_curves": 94,
    "jet_groups": 93,
    "train_curves": 91,
    "test_curves": 3,
    "test_power_rows": 104,
    "truth_cells": 1040,
    "train_A": 270,
    "train_D": 370,
    "test_A": 10,
    "test_D": 16,
}
SELECTION_FEATURES = ("log_mtow", "log_total_thrust", "noise_chapter")
COLORS = {"et": "#0072B2", "rf": "#D55E00", "truth": "#202020"}


def select_jet_references(
    samples: pd.DataFrame,
) -> tuple[dict[int, dict], pd.DataFrame]:
    """Derive and verify the frozen references without using noise errors.

    Category medians and IQRs use every complete-task jet curve. Only selectable
    references must be singleton identity groups: exactly one NPD curve and one
    ACFT_ID in the connected component. Zero-IQR dimensions contribute zero.
    """
    curve = samples[
        [
            "npd_id", "aircraft_group_id", "acft_ids",
            "aircraft_group_acft_ids", "representative_acft_id",
            "source_dataset", "engine_type", "engine_count",
            *SELECTION_FEATURES,
        ]
    ].drop_duplicates("npd_id")
    task_counts = (
        samples[["npd_id", "metric", "op_mode"]]
        .drop_duplicates()
        .groupby("npd_id")
        .size()
    )
    curve["n_tasks"] = curve["npd_id"].map(task_counts)
    jet = curve[
        (curve["engine_type"] == "Jet")
        & curve["engine_count"].isin((2, 3, 4))
        & (curve["n_tasks"] == len(COMBOS))
    ].copy()
    group_curve_counts = jet.groupby("aircraft_group_id")["npd_id"].nunique()
    jet["group_curve_count"] = jet["aircraft_group_id"].map(group_curve_counts)
    jet["group_acft_count"] = jet["aircraft_group_acft_ids"].map(
        lambda value: len([part for part in str(value).split("|") if part])
    )
    jet["eligible_singleton"] = (
        (jet["group_curve_count"] == 1) & (jet["group_acft_count"] == 1)
    )
    rows: list[pd.DataFrame] = []
    selected: dict[int, dict] = {}
    for engine_count in (2, 3, 4):
        population = jet[jet["engine_count"] == engine_count].copy()
        median = population.loc[:, SELECTION_FEATURES].median()
        iqr = (
            population.loc[:, SELECTION_FEATURES].quantile(0.75)
            - population.loc[:, SELECTION_FEATURES].quantile(0.25)
        )
        candidates = population[population["eligible_singleton"]].copy()
        squared = np.zeros(len(candidates), dtype=float)
        for feature in SELECTION_FEATURES:
            if float(iqr[feature]) > 0:
                component = (
                    (candidates[feature].to_numpy(float) - float(median[feature]))
                    / float(iqr[feature])
                )
            else:
                component = np.zeros(len(candidates), dtype=float)
            candidates[f"scaled_delta_{feature}"] = component
            squared += component ** 2
            candidates[f"median_{feature}"] = float(median[feature])
            candidates[f"iqr_{feature}"] = float(iqr[feature])
        candidates["robust_distance"] = np.sqrt(squared)
        candidates = candidates.sort_values(
            ["robust_distance", "npd_id"], kind="mergesort"
        ).reset_index(drop=True)
        candidates["selection_rank"] = np.arange(1, len(candidates) + 1)
        candidates["selected"] = candidates["selection_rank"] == 1
        winner = candidates.iloc[0]
        acft_ids = [part for part in str(winner["acft_ids"]).split("|") if part]
        selected[engine_count] = {
            "engine_count": engine_count,
            "npd_id": str(winner["npd_id"]),
            "acft_id": acft_ids[0],
            "aircraft_group_id": str(winner["aircraft_group_id"]),
            "robust_distance": float(winner["robust_distance"]),
            "source_dataset": str(winner["source_dataset"]),
            "log10_mtow_lb": float(winner["log_mtow"]),
            "log10_total_static_thrust_lb": float(
                winner["log_total_thrust"]
            ),
            "noise_chapter": float(winner["noise_chapter"]),
            "population_curves": int(len(population)),
            "eligible_candidates": int(len(candidates)),
            "median": {key: float(median[key]) for key in SELECTION_FEATURES},
            "iqr": {key: float(iqr[key]) for key in SELECTION_FEATURES},
        }
        rows.append(candidates)
    candidate_frame = pd.concat(rows, ignore_index=True).sort_values(
        ["engine_count", "selection_rank"], kind="mergesort", ignore_index=True
    )
    actual = {
        count: {"npd_id": value["npd_id"], "acft_id": value["acft_id"]}
        for count, value in selected.items()
    }
    if actual != FROZEN_REFERENCES:
        raise RuntimeError(
            "jet-reference selection drifted; expected "
            f"{FROZEN_REFERENCES}, derived {actual}. Do not evaluate until "
            "the datastore/selection change is audited."
        )
    return selected, candidate_frame


def build_jet_reference_split(
    samples: pd.DataFrame, selected: dict[int, dict]
) -> pd.DataFrame:
    curves = samples[
        [
            "npd_id", "aircraft_group_id", "acft_ids", "source_dataset",
            "engine_type", "engine_count",
        ]
    ].drop_duplicates()
    jet = curves[
        (curves["engine_type"] == "Jet")
        & curves["engine_count"].isin((2, 3, 4))
    ].copy()
    task_counts = (
        samples[["npd_id", "metric", "op_mode"]]
        .drop_duplicates().groupby("npd_id").size()
    )
    jet = jet[jet["npd_id"].map(task_counts) == len(COMBOS)].copy()
    held_groups = {
        value["aircraft_group_id"]: count for count, value in selected.items()
    }
    jet["role"] = np.where(
        jet["aircraft_group_id"].isin(held_groups), "test", "train"
    )
    jet["reference_engine_count"] = jet["aircraft_group_id"].map(held_groups)
    jet.insert(0, "protocol", PROTOCOL)
    return jet.sort_values(
        ["role", "engine_count", "npd_id"], kind="mergesort", ignore_index=True
    )


def verify_jet_reference_contract(
    samples: pd.DataFrame, split: pd.DataFrame
) -> dict:
    jet_ids = set(split["npd_id"])
    jet_samples = samples[samples["npd_id"].isin(jet_ids)]
    train_ids = set(split.loc[split["role"] == "train", "npd_id"])
    test_ids = set(split.loc[split["role"] == "test", "npd_id"])
    train = jet_samples[jet_samples["npd_id"].isin(train_ids)]
    test = jet_samples[jet_samples["npd_id"].isin(test_ids)]
    counts = {
        "jet_curves": len(jet_ids),
        "jet_groups": int(split["aircraft_group_id"].nunique()),
        "train_curves": len(train_ids),
        "test_curves": len(test_ids),
        "test_power_rows": int(len(test)),
        "truth_cells": int(len(test) * len(DIST_COLS)),
    }
    for mode in ("A", "D"):
        train_values = {
            int(value)
            for value in train.loc[train["op_mode"] == mode]
            .groupby(["metric", "op_mode"]).size().tolist()
        }
        test_values = {
            int(value)
            for value in test.loc[test["op_mode"] == mode]
            .groupby(["metric", "op_mode"]).size().tolist()
        }
        if len(train_values) != 1 or len(test_values) != 1:
            raise RuntimeError(
                f"inconsistent {mode} sample counts across metric tasks: "
                f"train={train_values}, test={test_values}"
            )
        counts[f"train_{mode}"] = train_values.pop()
        counts[f"test_{mode}"] = test_values.pop()
    if counts != EXPECTED:
        raise RuntimeError(
            f"jet-reference corpus drifted; expected {EXPECTED}, observed {counts}"
        )
    train_groups = set(split.loc[split["role"] == "train", "aircraft_group_id"])
    test_groups = set(split.loc[split["role"] == "test", "aircraft_group_id"])
    if train_groups & test_groups:
        raise RuntimeError("aircraft identity group overlap in jet-reference split")
    if set(train["engine_type"]) != {"Jet"}:
        raise RuntimeError("jet-reference training contains non-Jet samples")
    return counts


def _prediction_frame(
    test: pd.DataFrame, prediction: np.ndarray, learner: str
) -> pd.DataFrame:
    identity = test[
        [
            "sample_id", "metric", "op_mode", "npd_id",
            "aircraft_group_id", "acft_ids", "source_dataset",
            "engine_count", "power_parameter", "power_setting",
        ]
    ].reset_index(drop=True)
    truth = test.loc[:, TRUTH_COLUMNS].to_numpy(float)
    frames = []
    for index, distance in enumerate(
        [200, 400, 630, 1000, 2000, 4000, 6300, 10000, 16000, 25000]
    ):
        frame = identity.copy()
        frame["distance_ft"] = float(distance)
        frame["truth_dB"] = truth[:, index]
        frame["prediction_dB"] = prediction[:, index]
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    result["error_dB"] = result["prediction_dB"] - result["truth_dB"]
    result.insert(0, "model", learner)
    result.insert(0, "protocol", PROTOCOL)
    return result


def evaluate_jet_reference(
    samples: pd.DataFrame, split: pd.DataFrame, seed: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_ids = set(split.loc[split["role"] == "train", "npd_id"])
    test_ids = set(split.loc[split["role"] == "test", "npd_id"])
    predictions, runs = [], []
    for metric, mode in COMBOS:
        combo = samples[
            (samples["metric"] == metric) & (samples["op_mode"] == mode)
        ]
        train = combo[combo["npd_id"].isin(train_ids)]
        test = combo[combo["npd_id"].isin(test_ids)]
        for learner in SUPPORTED_LEARNERS:
            prediction, duration = _fit_predict(learner, seed, train, test)
            predictions.append(_prediction_frame(test, prediction, learner))
            runs.append(
                {
                    "protocol": PROTOCOL, "model": learner,
                    "metric": metric, "op_mode": mode,
                    "train_samples": int(len(train)),
                    "train_curves": int(train["npd_id"].nunique()),
                    "train_groups": int(train["aircraft_group_id"].nunique()),
                    "test_samples": int(len(test)),
                    "test_curves": int(test["npd_id"].nunique()),
                    "test_groups": int(test["aircraft_group_id"].nunique()),
                    "fit_predict_seconds": float(duration),
                }
            )
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(runs)


def _metrics(frame: pd.DataFrame, balanced: bool) -> dict:
    def basic(errors: np.ndarray) -> dict:
        absolute = np.abs(errors)
        return {
            "mse": float(np.mean(errors ** 2)),
            "mae_dB": float(np.mean(absolute)),
            "bias_dB": float(np.mean(errors)),
            "p90_abs_error_dB": float(np.percentile(absolute, 90)),
            "pct_within_3_dB": float(100 * np.mean(absolute <= 3.0)),
            "pct_within_5_dB": float(100 * np.mean(absolute <= 5.0)),
        }
    if not balanced:
        result = basic(frame["error_dB"].to_numpy(float))
        result["rmse_dB"] = float(np.sqrt(result.pop("mse")))
    else:
        units = [
            basic(group["error_dB"].to_numpy(float))
            for _, group in frame.groupby("engine_count", sort=True)
        ]
        result = {
            key: float(np.mean([unit[key] for unit in units]))
            for key in units[0]
        }
        result["rmse_dB"] = float(np.sqrt(result.pop("mse")))
    result.update(
        {
            "n_cells": int(len(frame)),
            "n_power_rows": int(frame["sample_id"].nunique()),
            "n_curves": int(frame["npd_id"].nunique()),
            "n_categories": int(frame["engine_count"].nunique()),
        }
    )
    return result


def summarize_jet_reference(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model, model_frame in predictions.groupby("model", sort=True):
        scopes = [("overall", "all", "all", "all", model_frame)]
        for count, frame in model_frame.groupby("engine_count", sort=True):
            scopes.append(("category_overall", str(int(count)), "all", "all", frame))
        for (metric, mode), frame in model_frame.groupby(
            ["metric", "op_mode"], sort=True
        ):
            scopes.append(("task_overall", "all", metric, mode, frame))
        for (metric, mode, count), frame in model_frame.groupby(
            ["metric", "op_mode", "engine_count"], sort=True
        ):
            scopes.append(
                ("task_category", str(int(count)), metric, mode, frame)
            )
        for scope, category, metric, mode, frame in scopes:
            for aggregation, balanced in (
                ("cell_pooled", False),
                ("curve_category_balanced", True),
            ):
                row = {
                    "protocol": PROTOCOL, "model": model, "scope": scope,
                    "engine_count_category": category, "metric": metric,
                    "op_mode": mode, "aggregation": aggregation,
                }
                row.update(_metrics(frame, balanced))
                rows.append(row)
    return pd.DataFrame(rows).sort_values(
        [
            "model", "scope", "engine_count_category", "metric",
            "op_mode", "aggregation",
        ],
        kind="mergesort", ignore_index=True,
    )


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path, dpi=240, bbox_inches="tight",
        metadata={"Software": "PNMF frozen jet-reference validation"},
    )
    plt.close(fig)


def generate_charts(
    predictions: pd.DataFrame, summary: pd.DataFrame, assets_dir: Path
) -> list[Path]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    fig, ax = plt.subplots(figsize=(13, 4.2))
    ax.set_axis_off()
    boxes = [
        (0.02, "Combined ANP truth\nv2.3 + v6.3"),
        (0.27, "Identity grouping\nJet 2/3/4 engines"),
        (0.52, "Frozen split\n91 train / 3 test curves"),
        (0.77, "ET + RF\n8 NPD tasks"),
    ]
    for x, text in boxes:
        patch = FancyBboxPatch(
            (x, 0.32), 0.19, 0.36, boxstyle="round,pad=0.02",
            facecolor="#EAF2F8", edgecolor="#0072B2", linewidth=1.8,
            transform=ax.transAxes,
        )
        ax.add_patch(patch)
        ax.text(x + 0.095, 0.50, text, ha="center", va="center",
                fontsize=11, transform=ax.transAxes)
    for x in (0.21, 0.46, 0.71):
        ax.annotate(
            "", xy=(x + 0.055, 0.50), xytext=(x, 0.50),
            xycoords=ax.transAxes,
            arrowprops={"arrowstyle": "->", "lw": 2, "color": "#555555"},
        )
    ax.text(
        0.5, 0.12,
        "Noise targets are never used to select references; the physics route "
        "remains separate and is not fitted here.",
        ha="center", fontsize=10, transform=ax.transAxes,
    )
    path = assets_dir / "jet_reference_architecture.png"
    _save(fig, path); paths.append(path)

    overall_category = summary[
        (summary["scope"] == "category_overall")
        & (summary["aggregation"] == "cell_pooled")
    ]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    categories = [2, 3, 4]
    x = np.arange(3); width = 0.34
    for offset, model in enumerate(SUPPORTED_LEARNERS):
        frame = overall_category[overall_category["model"] == model].set_index(
            "engine_count_category"
        )
        axes[0].bar(
            x + (offset - 0.5) * width,
            [frame.loc[str(c), "rmse_dB"] for c in categories],
            width, color=COLORS[model], label=model.upper(),
        )
        axes[1].bar(
            x + (offset - 0.5) * width,
            [frame.loc[str(c), "pct_within_5_dB"] for c in categories],
            width, color=COLORS[model], label=model.upper(),
        )
    for ax, ylabel, title in (
        (axes[0], "RMSE [dB]", "Error magnitude"),
        (
            axes[1],
            "Cells within +/-5 dB [%]",
            "Within +/-5 dB threshold agreement",
        ),
    ):
        ax.set_xticks(x, [f"{c} engines" for c in categories])
        ax.set_ylabel(ylabel); ax.set_title(title); ax.grid(axis="y", alpha=.25)
        ax.legend()
    fig.suptitle("Frozen jet references: overall results by category")
    path = assets_dir / "jet_reference_metrics.png"
    _save(fig, path); paths.append(path)

    sel = predictions[
        (predictions["metric"] == "SEL") & (predictions["op_mode"] == "D")
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), sharey=True)
    for ax, npd_id in zip(axes, ["BR715", "3JT8E5", "PW4056"]):
        frame = sel[sel["npd_id"] == npd_id]
        max_power = float(frame["power_setting"].max())
        view = frame[frame["power_setting"] == max_power]
        truth = (
            view.drop_duplicates("distance_ft")
            .sort_values("distance_ft")
        )
        ax.semilogx(
            truth["distance_ft"], truth["truth_dB"], "o-",
            color=COLORS["truth"], label="ANP truth", lw=2,
        )
        for model in SUPPORTED_LEARNERS:
            model_view = view[view["model"] == model].sort_values("distance_ft")
            ax.semilogx(
                model_view["distance_ft"], model_view["prediction_dB"],
                "s--", color=COLORS[model], label=model.upper(), lw=1.7,
            )
        count = int(frame["engine_count"].iloc[0])
        ax.set_title(f"{npd_id} · {count} engines\nSEL/D, max power")
        ax.set_xlabel("Slant distance [ft]"); ax.grid(alpha=.25, which="both")
    axes[0].set_ylabel("SEL [dB]"); axes[-1].legend()
    fig.suptitle(
        "Actual versus predicted NPD curves (illustrative task)", y=.98
    )
    fig.subplots_adjust(top=.78, wspace=.16)
    path = assets_dir / "jet_reference_npd_comparison.png"
    _save(fig, path); paths.append(path)

    residual = (
        predictions.groupby(
            ["metric", "op_mode", "model", "engine_count"], sort=True
        )["error_dB"].mean().unstack(["model", "engine_count"])
    )
    columns = [(model, count) for model in SUPPORTED_LEARNERS for count in (2, 3, 4)]
    residual = residual.reindex(columns=columns)
    values = residual.to_numpy(float)
    limit = max(1.0, float(np.nanmax(np.abs(values))))
    fig, ax = plt.subplots(figsize=(10, 6))
    image = ax.imshow(values, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
    ax.set_yticks(
        np.arange(len(residual)),
        [f"{metric}/{mode}" for metric, mode in residual.index],
    )
    ax.set_xticks(
        np.arange(len(columns)),
        [f"{model.upper()}\n{count} eng" for model, count in columns],
    )
    for row in range(values.shape[0]):
        for column in range(values.shape[1]):
            ax.text(column, row, f"{values[row, column]:+.1f}",
                    ha="center", va="center", fontsize=8)
    ax.set_title("Mean signed residual (prediction − truth) [dB]")
    fig.colorbar(image, ax=ax, label="Bias [dB]")
    path = assets_dir / "jet_reference_residual_heatmap.png"
    _save(fig, path); paths.append(path)
    return paths


def write_report(
    path: Path,
    summary: pd.DataFrame,
    selected: dict[int, dict],
    counts: dict,
    manifest: dict,
) -> None:
    overall = summary[summary["scope"] == "overall"]
    category = summary[
        (summary["scope"] == "category_overall")
        & (summary["aggregation"] == "cell_pooled")
    ]
    columns = [
        "model", "aggregation", "engine_count_category",
        "rmse_dB", "mae_dB", "bias_dB",
        "p90_abs_error_dB", "pct_within_3_dB", "pct_within_5_dB",
        "n_cells",
    ]
    lines = [
        "# Frozen Jet-Reference Validation Report",
        "",
        f"> Generated {manifest['run']['finished_utc']} from measured ANP truth. "
        "This is conceptual-screening evidence, not certification evidence.",
        "",
        "## Plain-language result",
        "",
        "Three ordinary jet references—one twin, one three-engine aircraft, "
        "and one four-engine aircraft—were frozen before model errors were "
        "calculated. Every aircraft identity connected to a reference curve "
        "was removed from training. Extra Trees (ET) and Random Forest (RF) "
        "then predicted the published NPD levels from aircraft descriptors and "
        "the requested power grid.",
        "",
        _markdown_table(overall.assign(engine_count_category="all"), columns),
        "",
        "Only three independent curves are tested. The 1,040 cells are repeated "
        "power/distance observations within those curves and are correlated; "
        "they are not 1,040 independent aircraft tests.",
        "",
        "![Validation architecture](jet_reference_assets/jet_reference_architecture.png)",
        "",
        "## Database and frozen selection",
        "",
        "The canonical datastore combines the EASA ANP legacy v2.3 source with "
        "the v6.3 supplement. Among curves with all eight tasks, the jet subset "
        f"contains {counts['jet_curves']} curves in {counts['jet_groups']} "
        "connected aircraft-identity groups. There are no one-engine jets; the "
        "categories are 2, 3 and 4 engines.",
        "",
        "Reference selection never uses a noise target or prediction error. For "
        "each engine-count category, the population median and IQR are computed "
        "over all complete-task jet curves for `[log10(MTOW_lb), "
        "log10(total_static_thrust_lb), noise_chapter]`. A selectable candidate "
        "must be a one-curve, one-ACFT_ID identity group. Its score is",
        "",
        "`distance = sqrt(sum_j (((x_j - median_j) / IQR_j)^2))`.",
        "",
        "A zero-IQR feature contributes zero; lowest distance wins and NPD_ID "
        "lexical order is the exact tie-break. The implementation derives the "
        "following frozen mapping and fails if future datastore drift changes it:",
        "",
    ]
    for count in (2, 3, 4):
        value = selected[count]
        lines.append(
            f"- {count} engines: NPD `{value['npd_id']}`, ACFT_ID "
            f"`{value['acft_id']}`, robust distance "
            f"`{value['robust_distance']:.6f}`."
        )
    lines.extend(
        [
            "",
            "## Exact separation and learning layout",
            "",
            f"Training uses {counts['train_curves']} other jet curves; testing "
            f"uses {counts['test_curves']} frozen curves. Each approach task "
            f"has {counts['train_A']} training and {counts['test_A']} held-out "
            f"power rows; each departure task has {counts['train_D']} training "
            f"and {counts['test_D']} held-out rows. Across all tasks the test "
            f"has {counts['test_power_rows']} power rows × 10 distances = "
            f"{counts['truth_cells']} truth cells.",
            "",
            "Each model input is `[jet/turboprop/piston one-hot, engine count, "
            "log10(MTOW), log10(MLW), MLW/MTOW, log10(static thrust per engine), "
            "log10(total static thrust), noise chapter, log10(converted row "
            "power in lbf), throttle]`. The target is the ten-distance NPD "
            "level vector. The held-out power grid is part of the requested "
            "prediction; held-out noise levels are used only for scoring.",
            "",
            "ET builds 500 highly randomized trees (`max_depth=24`, "
            "`max_features=0.5`, leaf size 1). RF builds 200 bootstrap trees "
            "(leaf size 2). Both use the frozen production settings and the "
            "normal non-increasing distance projection.",
            "",
            "The separate `PhysicsNPDModel` is not trained or evaluated here. "
            "It remains an independent component-source cross-check for SEL "
            "and LAmax only; it does not supply features or targets to ET/RF.",
            "",
            "## Measured results by category",
            "",
            _markdown_table(category, columns),
            "",
            "![Overall metrics](jet_reference_assets/jet_reference_metrics.png)",
            "",
            "RMSE emphasizes large misses; MAE is the typical absolute cell "
            "error; signed bias is positive when the model overpredicts; p90 "
            "is the 90th percentile absolute error. “Within ±3/±5 dB” is the "
            "percentage of correlated cells inside those bands, not a "
            "probability of aircraft-level success.",
            "",
            "![Actual versus predicted curves]"
            "(jet_reference_assets/jet_reference_npd_comparison.png)",
            "",
            "![Residual heatmap]"
            "(jet_reference_assets/jet_reference_residual_heatmap.png)",
            "",
            "## Limitations and conclusion",
            "",
            "- Three independent curves are too few for a population-wide "
            "accuracy or certification claim.",
            "- Selection is representative only in three available descriptor "
            "dimensions; engine technology, geometry and family labels are not "
            "part of the rule.",
            "- Power rows and distance cells within one curve are strongly "
            "correlated. Category-balanced results therefore matter alongside "
            "cell-pooled results.",
            "- These references are interpolation-oriented conventional jets, "
            "not evidence for unconventional configurations or unseen families.",
            "",
            "This experiment is a transparent, pre-frozen sanity check: it "
            "shows how the production ET/RF models behave on three typical jet "
            "curves with strict identity separation. It supplements, but does "
            "not replace, the broader grouped and temporal validation report.",
            "",
            "## Reproducibility",
            "",
            f"- Seed `{manifest['config']['seed']}`; runtime "
            f"`{manifest['run']['duration_seconds']:.3f}` s.",
            f"- Datastore SHA-256 `{manifest['inputs']['datastore_sha256']}`.",
            f"- Source-manifest SHA-256 "
            f"`{manifest['inputs']['source_manifest_sha256']}`.",
            f"- Git `{manifest['git']['commit']}`, dirty "
            f"`{manifest['git']['dirty']}`.",
            "",
            "All candidate scores, split roles, predictions, per-fit records, "
            "detailed task/category summaries and environment metadata are in "
            "`outputs/model_validation/jet_reference`.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run_jet_reference_validation(
    *,
    db_path: Path,
    output_dir: Path,
    report_path: Path,
    assets_dir: Path,
    seed: int = 20260724,
) -> dict:
    started = datetime.now(timezone.utc); timer = time.perf_counter()
    db = ANPDatabase(db_path)
    source_manifest = db.dataset_manifest()
    samples = build_samples(db)
    selected, candidates = select_jet_references(samples)
    params = db.param_table()
    for value in selected.values():
        descriptor = params.loc[value["npd_id"]]
        value.update(
            {
                "description": str(descriptor["Description"]),
                "mtow_lb": float(
                    descriptor["Max Gross Takeoff Weight (lb)"]
                ),
                "static_thrust_per_engine_lb": float(
                    descriptor["Max Sea Level Static Thrust (lb)"]
                ),
                "total_static_thrust_lb": float(
                    descriptor["Max Sea Level Static Thrust (lb)"]
                    * descriptor["Number Of Engines"]
                ),
            }
        )
    split = build_jet_reference_split(samples, selected)
    counts = verify_jet_reference_contract(samples, split)
    predictions, fit_runs = evaluate_jet_reference(samples, split, seed)
    summary = summarize_jet_reference(predictions)
    reference_frame = pd.DataFrame(list(selected.values()))

    output_dir.mkdir(parents=True, exist_ok=True)
    frames = {
        "selection_candidates.csv": candidates,
        "split.csv": split,
        "predictions.csv": predictions,
        "fit_runs.csv": fit_runs,
        "summary.csv": summary,
        "reference_metadata.csv": reference_frame,
        "source_manifest.csv": source_manifest,
    }
    for name, frame in frames.items():
        frame.to_csv(output_dir / name, index=False, lineterminator="\n")
    (output_dir / "summary.json").write_text(
        json.dumps(summary.to_dict(orient="records"), indent=2),
        encoding="utf-8",
    )
    (output_dir / "reference_metadata.json").write_text(
        json.dumps(selected, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    charts = generate_charts(predictions, summary, assets_dir)

    repo_root = PROJECT_ROOT.parents[1]
    db_file = db_path if db_path.is_file() else db_path / "anp_data.sqlite"
    finished = datetime.now(timezone.utc)
    manifest = {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "run": {
            "started_utc": started.isoformat(),
            "finished_utc": finished.isoformat(),
            "duration_seconds": time.perf_counter() - timer,
        },
        "config": {
            "seed": seed, "models": list(SUPPORTED_LEARNERS),
            "tasks": [{"metric": m, "op_mode": o} for m, o in COMBOS],
            "frozen_references": FROZEN_REFERENCES,
        },
        "selection": {
            "population": "all complete-task Jet curves by engine count",
            "eligibility": "one-curve and one-ACFT_ID identity groups",
            "features": list(SELECTION_FEATURES),
            "distance": "IQR-scaled Euclidean; zero-IQR contributes zero",
            "tie_break": "NPD_ID lexical ascending",
            "derived_references": selected,
        },
        "counts": counts,
        "features": list(FEATURES),
        "targets": list(DIST_COLS),
        "models": exact_model_params(seed),
        "inputs": {
            "datastore": str(db_file.resolve()),
            "datastore_sha256": _sha256_file(db_file),
            "source_manifest_sha256": _sha256_json(
                source_manifest.to_dict(orient="records")
            ),
        },
        "software": {
            "python": platform.python_version(), "numpy": np.__version__,
            "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
            "matplotlib": matplotlib.__version__, "platform": platform.platform(),
        },
        "git": _git_state(repo_root),
        "fit_runs": fit_runs.to_dict(orient="records"),
        "artifacts": {},
    }
    write_report(report_path, summary, selected, counts, manifest)
    files = [
        *(output_dir / name for name in frames),
        output_dir / "summary.json",
        output_dir / "reference_metadata.json",
        report_path,
        *charts,
    ]
    for artifact in files:
        manifest["artifacts"][artifact.name] = {
            "path": str(artifact.resolve()), "sha256": _sha256_file(artifact),
            "bytes": artifact.stat().st_size,
        }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen representative-jet ET/RF holdout."
    )
    parser.add_argument("--db", default=str(PROJECT_ROOT / "anp_data.sqlite"))
    parser.add_argument(
        "--output-dir", default="outputs/model_validation/jet_reference"
    )
    parser.add_argument(
        "--report", default="docs/JET_REFERENCE_VALIDATION_REPORT.md"
    )
    parser.add_argument(
        "--assets-dir", default="docs/jet_reference_assets"
    )
    parser.add_argument("--seed", type=int, default=20260724)
    args = parser.parse_args(argv)
    manifest = run_jet_reference_validation(
        db_path=_project_relative(args.db, PROJECT_ROOT / "anp_data.sqlite"),
        output_dir=_project_relative(
            args.output_dir, PROJECT_ROOT / "outputs/model_validation/jet_reference"
        ),
        report_path=_project_relative(
            args.report, PROJECT_ROOT / "docs/JET_REFERENCE_VALIDATION_REPORT.md"
        ),
        assets_dir=_project_relative(
            args.assets_dir, PROJECT_ROOT / "docs/jet_reference_assets"
        ),
        seed=args.seed,
    )
    print(
        "jet-reference validation complete: "
        f"{manifest['counts']['train_curves']} train / "
        f"{manifest['counts']['test_curves']} test curves, "
        f"{manifest['run']['duration_seconds']:.1f} s"
    )
    print(f"artifacts: {args.output_dir}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
