"""Frozen ANP v6.3 release-holdout validation for production ET/RF models."""
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

PROTOCOL = "jet_reference_v63_release_holdout"
TRAIN_SOURCE = "legacy_v2.3"
REFERENCE_SOURCE = "supplement_v6.3"
FROZEN_REFERENCES = {
    2: {"npd_id": "A330-743L", "acft_id": "A330-743L"},
    3: {"npd_id": "FAL900EX", "acft_id": "FAL900EX"},
    4: {"npd_id": "747400RN", "acft_id": "747400RN"},
}
EXPECTED_REFERENCE_DESCRIPTIONS = {
    "A330-743L": "Airbus A330-743L / RR Trent 772B",
    "FAL900EX": "Dassault FAL900EX / TFE731-60",
    "747400RN": "Boeing 747400RN / PW4062A",
}
FAMILY_PURGE = frozenset(
    {"CF680E", "TRENT7", "JT9DBD", "JT9DFL", "JT9D7Q", "PW4056", "GENX67"}
)
FAMILY_PURGE_REASON = {
    "CF680E": "predeclared_A330_family_guard",
    "TRENT7": "predeclared_A330_family_guard",
    "JT9DBD": "predeclared_747_family_guard",
    "JT9DFL": "predeclared_747_family_guard",
    "JT9D7Q": "predeclared_747_family_guard",
    "PW4056": "predeclared_747_family_guard",
    "GENX67": "predeclared_747_family_guard",
}
EXPECTED_FAL_POWER_GRIDS = {
    "A": (500.0, 1000.0, 1500.0, 2000.0),
    "D": (2500.0, 3000.0, 3500.0, 4000.0, 4500.0, 4700.0),
}
EXPECTED = {
    "selection_candidates": 11,
    "legacy_jet_curves_before_purge": 83,
    "purged_legacy_curves": 7,
    "train_curves": 76,
    "train_twin_curves": 57,
    "train_tri_curves": 9,
    "train_quad_curves": 10,
    "test_curves": 3,
    "test_twin_curves": 1,
    "test_tri_curves": 1,
    "test_quad_curves": 1,
    "train_power_rows": 2052,
    "test_power_rows": 116,
    "truth_cells": 1160,
    "train_A": 216,
    "train_D": 297,
    "test_A": 12,
    "test_D": 17,
}
SELECTION_FEATURES = ("log_mtow", "log_total_thrust", "noise_chapter")
OFFICIAL_SOURCE_URLS = {
    "easa_anp_data": (
        "https://www.easa.europa.eu/en/domains/environment/policy-support-and-"
        "research/aircraft-noise-and-performance-anp-data"
    ),
    "easa_anp_legacy_data": (
        "https://www.easa.europa.eu/en/domains/environment/policy-support-and-"
        "research/aircraft-noise-and-performance-anp-data/anp-legacy-data"
    ),
    "eu_regulation_598_2014": (
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32014R0598"
    ),
}
OFFICIAL_CONCLUSION = (
    "v6.3 is preferable as newer EASA-collected/verified reference provenance, "
    "but no official source proves universal accuracy superiority."
)
COLORS = {"et": "#0072B2", "rf": "#D55E00", "truth": "#202020"}
DISTANCES_FT = (200, 400, 630, 1000, 2000, 4000, 6300, 10000, 16000, 25000)


def _complete_curve_table(samples: pd.DataFrame) -> pd.DataFrame:
    """Return one row per curve with complete-task status."""
    columns = [
        "npd_id", "aircraft_group_id", "acft_ids",
        "aircraft_group_acft_ids", "representative_acft_id",
        "source_dataset", "source_file", "engine_type", "engine_count",
        *SELECTION_FEATURES,
    ]
    curve = samples[columns].drop_duplicates("npd_id").copy()
    task_counts = (
        samples[["npd_id", "metric", "op_mode"]]
        .drop_duplicates()
        .groupby("npd_id")
        .size()
    )
    curve["n_tasks"] = curve["npd_id"].map(task_counts).astype(int)
    return curve


def select_jet_references(
    samples: pd.DataFrame,
) -> tuple[dict[int, dict], pd.DataFrame]:
    """Select only from complete-task v6.3 jets, without reading noise targets."""
    curve = _complete_curve_table(samples)
    pool = curve[
        (curve["source_dataset"] == REFERENCE_SOURCE)
        & (curve["engine_type"] == "Jet")
        & curve["engine_count"].isin((2, 3, 4))
        & (curve["n_tasks"] == len(COMBOS))
    ].copy()
    rows: list[pd.DataFrame] = []
    selected: dict[int, dict] = {}
    for engine_count in (2, 3, 4):
        candidates = pool[pool["engine_count"] == engine_count].copy()
        if candidates.empty:
            raise RuntimeError(
                f"no complete-task {REFERENCE_SOURCE} Jet candidate for "
                f"{engine_count} engines"
            )
        median = candidates.loc[:, SELECTION_FEATURES].median()
        iqr = (
            candidates.loc[:, SELECTION_FEATURES].quantile(0.75)
            - candidates.loc[:, SELECTION_FEATURES].quantile(0.25)
        )
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
            candidates[f"median_{feature}"] = float(median[feature])
            candidates[f"iqr_{feature}"] = float(iqr[feature])
            squared += component ** 2
        candidates["robust_distance"] = np.sqrt(squared)
        candidates = candidates.sort_values(
            ["robust_distance", "npd_id"], kind="mergesort"
        ).reset_index(drop=True)
        candidates["selection_rank"] = np.arange(1, len(candidates) + 1)
        candidates["selected"] = candidates["selection_rank"] == 1
        winner = candidates.iloc[0]
        acft_ids = [part for part in str(winner["acft_ids"]).split("|") if part]
        if not acft_ids:
            raise RuntimeError(f"selected curve {winner['npd_id']} has no ACFT_ID")
        selected[engine_count] = {
            "engine_count": engine_count,
            "npd_id": str(winner["npd_id"]),
            "acft_id": acft_ids[0],
            "aircraft_group_id": str(winner["aircraft_group_id"]),
            "robust_distance": float(winner["robust_distance"]),
            "source_dataset": str(winner["source_dataset"]),
            "source_file": str(winner["source_file"]),
            "log10_mtow_lb": float(winner["log_mtow"]),
            "log10_total_static_thrust_lb": float(winner["log_total_thrust"]),
            "noise_chapter": float(winner["noise_chapter"]),
            "population_curves": int(len(candidates)),
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
            "v6.3 jet-reference selection drifted; expected "
            f"{FROZEN_REFERENCES}, derived {actual}. Audit before evaluation."
        )
    if not np.isclose(selected[2]["robust_distance"], 0.216692, atol=5e-7):
        raise RuntimeError(
            "twin-engine robust distance drifted; expected 0.216692, got "
            f"{selected[2]['robust_distance']:.9f}"
        )
    return selected, candidate_frame


def build_jet_reference_split(
    samples: pd.DataFrame, selected: dict[int, dict]
) -> pd.DataFrame:
    """Create the auditable legacy-train/v6.3-test release split."""
    curve = _complete_curve_table(samples)
    jet = curve[
        (curve["engine_type"] == "Jet")
        & curve["engine_count"].isin((2, 3, 4))
        & (curve["n_tasks"] == len(COMBOS))
        & curve["source_dataset"].isin((TRAIN_SOURCE, REFERENCE_SOURCE))
    ].copy()
    selected_ids = {value["npd_id"] for value in selected.values()}

    def role(row: pd.Series) -> str:
        if row["source_dataset"] == TRAIN_SOURCE:
            return "excluded_family_purge" if row["npd_id"] in FAMILY_PURGE else "train"
        return "test" if row["npd_id"] in selected_ids else "excluded_candidate"

    jet["role"] = jet.apply(role, axis=1)
    jet["exclusion_reason"] = jet["npd_id"].map(FAMILY_PURGE_REASON).fillna("")
    jet.loc[jet["role"] == "excluded_candidate", "exclusion_reason"] = (
        "not_selected_by_frozen_descriptor_rule"
    )
    reference_category = {
        value["npd_id"]: count for count, value in selected.items()
    }
    jet["reference_engine_count"] = jet["npd_id"].map(reference_category)
    jet.insert(0, "protocol", PROTOCOL)
    return jet.sort_values(
        ["role", "source_dataset", "engine_count", "npd_id"],
        kind="mergesort",
        ignore_index=True,
    )


def verify_jet_reference_contract(
    samples: pd.DataFrame, split: pd.DataFrame
) -> dict:
    """Fail closed on source, purge, overlap, grid, and exact count drift."""
    train_ids = set(split.loc[split["role"] == "train", "npd_id"])
    test_ids = set(split.loc[split["role"] == "test", "npd_id"])
    purged_ids = set(
        split.loc[split["role"] == "excluded_family_purge", "npd_id"]
    )
    candidate_ids = set(split.loc[split["source_dataset"] == REFERENCE_SOURCE, "npd_id"])
    legacy_ids = set(split.loc[split["source_dataset"] == TRAIN_SOURCE, "npd_id"])
    train = samples[samples["npd_id"].isin(train_ids)].copy()
    test = samples[samples["npd_id"].isin(test_ids)].copy()

    if purged_ids != FAMILY_PURGE:
        raise RuntimeError(
            f"family purge drifted; expected {sorted(FAMILY_PURGE)}, "
            f"observed {sorted(purged_ids)}"
        )
    if train_ids & test_ids:
        raise RuntimeError("NPD curve overlap in release holdout")
    if set(train["source_dataset"]) != {TRAIN_SOURCE}:
        raise RuntimeError("training must contain only legacy_v2.3 target rows")
    if set(test["source_dataset"]) != {REFERENCE_SOURCE}:
        raise RuntimeError("test must contain only supplement_v6.3 target rows")
    if set(train["engine_type"]) != {"Jet"} or set(test["engine_type"]) != {"Jet"}:
        raise RuntimeError("release holdout must contain only Jet samples")
    if set(test_ids) != {value["npd_id"] for value in FROZEN_REFERENCES.values()}:
        raise RuntimeError("test IDs differ from the frozen v6.3 references")
    if train_ids & FAMILY_PURGE:
        raise RuntimeError("predeclared family-purge curve entered training")
    train_groups = set(
        split.loc[split["role"] == "train", "aircraft_group_id"]
    )
    test_groups = set(split.loc[split["role"] == "test", "aircraft_group_id"])
    if train_groups & test_groups:
        raise RuntimeError("aircraft identity group overlap in release holdout")
    train_acft = {
        part
        for field in split.loc[split["role"] == "train", "acft_ids"]
        for part in str(field).split("|")
        if part
    }
    test_acft = {
        part
        for field in split.loc[split["role"] == "test", "acft_ids"]
        for part in str(field).split("|")
        if part
    }
    if train_acft & test_acft:
        raise RuntimeError("exact ACFT_ID overlap in release holdout")

    fal = test[test["npd_id"] == "FAL900EX"]
    for metric, mode in COMBOS:
        observed = tuple(
            fal[(fal["metric"] == metric) & (fal["op_mode"] == mode)]
            .sort_values("power_setting")["power_setting"]
            .to_numpy(float)
        )
        if observed != EXPECTED_FAL_POWER_GRIDS[mode]:
            raise RuntimeError(
                f"FAL900EX {metric}/{mode} grid drifted: {observed}"
            )

    counts = {
        "selection_candidates": len(candidate_ids),
        "legacy_jet_curves_before_purge": len(legacy_ids),
        "purged_legacy_curves": len(purged_ids),
        "train_curves": len(train_ids),
        "train_twin_curves": int(
            split[(split["role"] == "train") & (split["engine_count"] == 2)][
                "npd_id"
            ].nunique()
        ),
        "train_tri_curves": int(
            split[(split["role"] == "train") & (split["engine_count"] == 3)][
                "npd_id"
            ].nunique()
        ),
        "train_quad_curves": int(
            split[(split["role"] == "train") & (split["engine_count"] == 4)][
                "npd_id"
            ].nunique()
        ),
        "test_curves": len(test_ids),
        "test_twin_curves": int((split["role"].eq("test") & split["engine_count"].eq(2)).sum()),
        "test_tri_curves": int((split["role"].eq("test") & split["engine_count"].eq(3)).sum()),
        "test_quad_curves": int((split["role"].eq("test") & split["engine_count"].eq(4)).sum()),
        "train_power_rows": int(len(train)),
        "test_power_rows": int(len(test)),
        "truth_cells": int(len(test) * len(DIST_COLS)),
    }
    for mode in ("A", "D"):
        train_values = {
            int(value)
            for value in train.loc[train["op_mode"] == mode]
            .groupby(["metric", "op_mode"])
            .size()
            .tolist()
        }
        test_values = {
            int(value)
            for value in test.loc[test["op_mode"] == mode]
            .groupby(["metric", "op_mode"])
            .size()
            .tolist()
        }
        if len(train_values) != 1 or len(test_values) != 1:
            raise RuntimeError(
                f"inconsistent {mode} rows across tasks: "
                f"train={train_values}, test={test_values}"
            )
        counts[f"train_{mode}"] = train_values.pop()
        counts[f"test_{mode}"] = test_values.pop()
    if counts != EXPECTED:
        raise RuntimeError(
            f"v6.3 release-holdout corpus drifted; expected {EXPECTED}, "
            f"observed {counts}"
        )
    return counts


def _prediction_frame(
    test: pd.DataFrame, prediction: np.ndarray, learner: str
) -> pd.DataFrame:
    identity = test[
        [
            "sample_id", "metric", "op_mode", "npd_id",
            "aircraft_group_id", "acft_ids", "source_dataset", "source_file",
            "engine_count", "power_parameter", "power_setting",
        ]
    ].reset_index(drop=True)
    truth = test.loc[:, TRUTH_COLUMNS].to_numpy(float)
    frames = []
    for index, distance in enumerate(DISTANCES_FT):
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
        train = combo[
            combo["npd_id"].isin(train_ids)
            & (combo["source_dataset"] == TRAIN_SOURCE)
        ]
        test = combo[
            combo["npd_id"].isin(test_ids)
            & (combo["source_dataset"] == REFERENCE_SOURCE)
        ]
        for learner in SUPPORTED_LEARNERS:
            prediction, duration = _fit_predict(learner, seed, train, test)
            predictions.append(_prediction_frame(test, prediction, learner))
            runs.append(
                {
                    "protocol": PROTOCOL,
                    "model": learner,
                    "metric": metric,
                    "op_mode": mode,
                    "train_source": TRAIN_SOURCE,
                    "test_source": REFERENCE_SOURCE,
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


def _basic_metrics(errors: np.ndarray) -> dict:
    absolute = np.abs(errors)
    return {
        "mse": float(np.mean(errors ** 2)),
        "mae_dB": float(np.mean(absolute)),
        "bias_dB": float(np.mean(errors)),
        "p90_abs_error_dB": float(np.percentile(absolute, 90)),
        "pct_within_3_dB": float(100 * np.mean(absolute <= 3.0)),
        "pct_within_5_dB": float(100 * np.mean(absolute <= 5.0)),
    }


def _metrics(frame: pd.DataFrame, balanced: bool) -> dict:
    """Cell-pooled metrics or equal engine-category mean metrics."""
    if frame.empty:
        raise ValueError("cannot score an empty prediction frame")
    if not balanced:
        result = _basic_metrics(frame["error_dB"].to_numpy(float))
    else:
        units = [
            _basic_metrics(group["error_dB"].to_numpy(float))
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
            scopes.append(("task_category", str(int(count)), metric, mode, frame))
        for scope, category, metric, mode, frame in scopes:
            for aggregation, balanced in (
                ("cell_pooled", False),
                ("category_balanced", True),
            ):
                row = {
                    "protocol": PROTOCOL,
                    "model": model,
                    "scope": scope,
                    "engine_count_category": category,
                    "metric": metric,
                    "op_mode": mode,
                    "aggregation": aggregation,
                }
                row.update(_metrics(frame, balanced))
                rows.append(row)
    return pd.DataFrame(rows).sort_values(
        [
            "model", "scope", "engine_count_category", "metric",
            "op_mode", "aggregation",
        ],
        kind="mergesort",
        ignore_index=True,
    )


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path,
        dpi=240,
        bbox_inches="tight",
        metadata={"Software": "PNMF v6.3 jet release-holdout validation"},
    )
    plt.close(fig)


def generate_charts(
    predictions: pd.DataFrame, summary: pd.DataFrame, assets_dir: Path
) -> list[Path]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    fig, ax = plt.subplots(figsize=(13, 4.2))
    ax.set_axis_off()
    boxes = [
        (0.01, "Legacy v2.3 Jet\n83 complete curves"),
        (0.255, "Predeclared family purge\n7 A330/747 NPDs"),
        (0.50, "76 legacy train curves\n57 twin / 9 tri / 10 quad"),
        (0.745, "3 frozen v6.3 tests\nET + RF / 8 tasks"),
    ]
    for x, text in boxes:
        patch = FancyBboxPatch(
            (x, 0.32), 0.205, 0.36, boxstyle="round,pad=0.02",
            facecolor="#EAF2F8", edgecolor="#0072B2", linewidth=1.8,
            transform=ax.transAxes,
        )
        ax.add_patch(patch)
        ax.text(
            x + 0.1025, 0.50, text, ha="center", va="center",
            fontsize=10.5, transform=ax.transAxes,
        )
    for x in (0.215, 0.46, 0.705):
        ax.annotate(
            "", xy=(x + 0.04, 0.50), xytext=(x, 0.50),
            xycoords=ax.transAxes,
            arrowprops={"arrowstyle": "->", "lw": 2, "color": "#555555"},
        )
    ax.text(
        0.5, 0.12,
        "v6.3 targets are absent from training and descriptor selection never "
        "uses noise levels; the physics route remains independent.",
        ha="center", fontsize=9.8, transform=ax.transAxes,
    )
    path = assets_dir / "jet_reference_architecture.png"
    _save(fig, path)
    paths.append(path)

    category = summary[
        (summary["scope"] == "category_overall")
        & (summary["aggregation"] == "cell_pooled")
    ]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    categories = [2, 3, 4]
    x = np.arange(3)
    width = 0.34
    for offset, model in enumerate(SUPPORTED_LEARNERS):
        frame = category[category["model"] == model].set_index(
            "engine_count_category"
        )
        axes[0].bar(
            x + (offset - 0.5) * width,
            [frame.loc[str(c), "rmse_dB"] for c in categories],
            width,
            color=COLORS[model],
            label=model.upper(),
        )
        axes[1].bar(
            x + (offset - 0.5) * width,
            [frame.loc[str(c), "pct_within_5_dB"] for c in categories],
            width,
            color=COLORS[model],
            label=model.upper(),
        )
    for axis, ylabel, title in (
        (axes[0], "RMSE [dB]", "Error magnitude"),
        (
            axes[1],
            "Cells within ±5 dB [%]",
            "Threshold agreement (correlated cells)",
        ),
    ):
        axis.set_xticks(x, [f"{c} engines" for c in categories])
        axis.set_ylabel(ylabel)
        axis.set_title(title)
        axis.grid(axis="y", alpha=0.25)
        axis.legend()
    fig.suptitle("Frozen v6.3 references: results by engine-count category")
    path = assets_dir / "jet_reference_metrics.png"
    _save(fig, path)
    paths.append(path)

    selected = predictions[
        (predictions["metric"] == "SEL") & (predictions["op_mode"] == "D")
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), sharey=True)
    for axis, npd_id in zip(
        axes, [FROZEN_REFERENCES[count]["npd_id"] for count in (2, 3, 4)]
    ):
        frame = selected[selected["npd_id"] == npd_id]
        max_power = float(frame["power_setting"].max())
        view = frame[frame["power_setting"] == max_power]
        truth = view.drop_duplicates("distance_ft").sort_values("distance_ft")
        axis.semilogx(
            truth["distance_ft"], truth["truth_dB"], "o-",
            color=COLORS["truth"], label="v6.3 truth", lw=2,
        )
        for model in SUPPORTED_LEARNERS:
            model_view = view[view["model"] == model].sort_values("distance_ft")
            axis.semilogx(
                model_view["distance_ft"], model_view["prediction_dB"], "s--",
                color=COLORS[model], label=model.upper(), lw=1.7,
            )
        count = int(frame["engine_count"].iloc[0])
        axis.set_title(f"{npd_id} · {count} engines\nSEL/D, max power")
        axis.set_xlabel("Slant distance [ft]")
        axis.grid(alpha=0.25, which="both")
    axes[0].set_ylabel("SEL [dB]")
    axes[-1].legend()
    fig.suptitle("v6.3 truth versus legacy-trained prediction", y=0.98)
    fig.subplots_adjust(top=0.78, wspace=0.16)
    path = assets_dir / "jet_reference_npd_comparison.png"
    _save(fig, path)
    paths.append(path)

    residual = (
        predictions.groupby(
            ["metric", "op_mode", "model", "engine_count"], sort=True
        )["error_dB"]
        .mean()
        .unstack(["model", "engine_count"])
    )
    columns = [
        (model, count) for model in SUPPORTED_LEARNERS for count in (2, 3, 4)
    ]
    residual = residual.reindex(columns=columns)
    values = residual.to_numpy(float)
    limit = max(1.0, float(np.nanmax(np.abs(values))))
    fig, ax = plt.subplots(figsize=(10, 6))
    image = ax.imshow(
        values, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto"
    )
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
            ax.text(
                column, row, f"{values[row, column]:+.1f}",
                ha="center", va="center", fontsize=8,
            )
    ax.set_title("Mean signed residual (prediction − v6.3 truth) [dB]")
    fig.colorbar(image, ax=ax, label="Bias [dB]")
    path = assets_dir / "jet_reference_residual_heatmap.png"
    _save(fig, path)
    paths.append(path)
    return paths


def write_report(
    path: Path,
    summary: pd.DataFrame,
    selected: dict[int, dict],
    counts: dict,
    manifest: dict,
) -> None:
    overall = summary[summary["scope"] == "overall"].copy()
    category = summary[
        (summary["scope"] == "category_overall")
        & (summary["aggregation"] == "cell_pooled")
    ].copy()
    columns = [
        "model", "aggregation", "engine_count_category",
        "rmse_dB", "mae_dB", "bias_dB", "p90_abs_error_dB",
        "pct_within_3_dB", "pct_within_5_dB", "n_cells",
    ]
    lines = [
        "# ANP v6.3 Jet Release-Holdout Validation Report",
        "",
        f"> Generated {manifest['run']['finished_utc']} from frozen EASA ANP "
        "reference data. This is conceptual-screening evidence, not "
        "certification evidence.",
        "",
        "## Conclusion and evidence boundary",
        "",
        OFFICIAL_CONCLUSION,
        "",
        "This conclusion is about source provenance and release chronology, not "
        "a claim that every v6.3 curve is intrinsically more accurate than every "
        "legacy curve. EASA states that it collects, verifies and makes ANP data "
        "available under Regulation (EU) No 598/2014. EASA separately describes "
        "v2.3 as legacy data collected before that mandate.",
        "",
        f"- [EASA Aircraft Noise and Performance (ANP)]"
        f"({OFFICIAL_SOURCE_URLS['easa_anp_data']})",
        f"- [EASA ANP legacy data]"
        f"({OFFICIAL_SOURCE_URLS['easa_anp_legacy_data']})",
        f"- [Regulation (EU) No 598/2014]"
        f"({OFFICIAL_SOURCE_URLS['eu_regulation_598_2014']})",
        "",
        "## Protocol",
        "",
        "The primary training protocol uses only complete-task Jet curves from "
        "legacy v2.3. No v6.3 target row enters training. The frozen test contains "
        "three v6.3 references selected before errors by descriptor-only distance.",
        "",
        "![Validation architecture](jet_reference_assets/jet_reference_architecture.png)",
        "",
        "For each engine-count category, the candidate pool is restricted to "
        "`source_dataset=supplement_v6.3`, `engine_type=Jet`, and all eight "
        "metric/mode tasks. Medians and IQRs are calculated within that v6.3 "
        "category over `[log10(MTOW_lb), log10(total static thrust_lb), noise "
        "chapter]`:",
        "",
        "`distance = sqrt(sum_j (((x_j - median_j) / IQR_j)^2))`.",
        "",
        "A zero-IQR contribution is exactly zero. Lowest score wins; lexical "
        "`NPD_ID` is the deterministic tie-break. Noise targets, predictions and "
        "errors are not selection inputs.",
        "",
    ]
    for count in (2, 3, 4):
        value = selected[count]
        lines.append(
            f"- {count} engines: `{value['npd_id']}` / "
            f"{value['description']} / robust distance "
            f"`{value['robust_distance']:.6f}`."
        )
    lines.extend(
        [
            "",
            "The three-engine and four-engine categories each contain only one "
            "v6.3 candidate. Their zero distances express singleton category "
            "medians; those aircraft are not general representatives of their "
            "engine-count populations.",
            "",
            "## Family purge and exact separation",
            "",
            "Before fitting, the conservative predeclared family guard removes "
            "`CF680E`, `TRENT7`, `JT9DBD`, `JT9DFL`, `JT9D7Q`, `PW4056`, and "
            "`GENX67` from the legacy training pool because they are A330/747 "
            "family analogues of the selected references. Falcon 20 is not "
            "automatically purged: no broad Falcon-name heuristic is used.",
            "",
            f"The resulting train/test split is {counts['train_curves']}/"
            f"{counts['test_curves']} curves. Training contains "
            f"{counts['train_twin_curves']} twin, {counts['train_tri_curves']} "
            f"tri, and {counts['train_quad_curves']} quad curves. Per task it "
            f"contains {counts['train_A']} approach and {counts['train_D']} "
            f"departure power rows. The test contains {counts['test_A']} approach "
            f"and {counts['test_D']} departure rows per metric: 29 per metric × "
            f"4 metrics = {counts['test_power_rows']} rows and "
            f"{counts['truth_cells']} power-distance cells.",
            "",
            "FAL900EX grids are approach `{500, 1000, 1500, 2000}` lbf and "
            "departure `{2500, 3000, 3500, 4000, 4500, 4700}` lbf. The contract "
            "fails if these grids, the source split, purge set, counts, ACFT_ID "
            "separation, or selected references drift.",
            "",
            "## Models and metrics",
            "",
            "Production Extra Trees (ET) and Random Forest (RF) are fitted "
            "independently for all eight EPNL, LAmax, PNLTM and SEL × approach/"
            "departure tasks. The standard 12 learned features and monotone "
            "distance projection are unchanged. `PhysicsNPDModel` remains an "
            "independent SEL/LAmax component-source route and supplies neither "
            "features nor targets to this experiment.",
            "",
            "- `error = prediction − truth`",
            "- `RMSE = sqrt(mean(error²))`",
            "- `MAE = mean(abs(error))`",
            "- `bias = mean(error)`",
            "- `p90 = percentile(abs(error), 90)`",
            "- `within ±k dB = 100 × mean(abs(error) ≤ k)`",
            "",
            "Cell-pooled results weight every power-distance cell equally. "
            "Category-balanced results calculate metrics per engine-count category "
            "and give each of the three categories equal weight; balanced RMSE is "
            "the square root of mean category MSE.",
            "",
            _markdown_table(overall.assign(engine_count_category="all"), columns),
            "",
            "## Results by reference category",
            "",
            _markdown_table(category, columns),
            "",
            "![Overall metrics](jet_reference_assets/jet_reference_metrics.png)",
            "",
            "“Within ±3 dB” and “within ±5 dB” are threshold-agreement "
            "percentages over correlated cells. They are not aircraft-level "
            "success rates, confidence probabilities, or certification margins.",
            "",
            "![Truth versus prediction](jet_reference_assets/jet_reference_npd_comparison.png)",
            "",
            "![Residual heatmap](jet_reference_assets/jet_reference_residual_heatmap.png)",
            "",
            "## Limitations",
            "",
            "- Only three independent NPD curves are tested; 1,160 cells do not "
            "constitute 1,160 independent aircraft.",
            "- Tri- and quad-engine results each come from a singleton v6.3 "
            "candidate and cannot establish category-wide performance.",
            "- Descriptor selection covers only weight, installed static thrust "
            "and noise chapter; it omits detailed geometry and engine technology.",
            "- The conservative A330/747 purge reduces obvious family leakage but "
            "cannot prove the absence of all engineering similarity.",
            "- Findings apply to these conventional jets and eight NPD tasks, not "
            "unconventional configurations, fleet-wide accuracy, or certification.",
            "",
            "## Reproducibility and provenance",
            "",
            f"- Seed `{manifest['config']['seed']}`; runtime "
            f"`{manifest['run']['duration_seconds']:.3f}` s.",
            f"- Datastore SHA-256 `{manifest['inputs']['datastore_sha256']}`.",
            f"- Source-manifest SHA-256 "
            f"`{manifest['inputs']['source_manifest_sha256']}`.",
            f"- Git `{manifest['git']['commit']}`, dirty "
            f"`{manifest['git']['dirty']}`.",
            "- Full candidate scores, reference metadata, split exclusions, "
            "predictions, fit records, summaries, source manifest, artifact hashes "
            "and official URLs are in "
            "`outputs/model_validation/jet_reference_v63`.",
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
    started = datetime.now(timezone.utc)
    timer = time.perf_counter()
    db = ANPDatabase(db_path)
    source_manifest = db.dataset_manifest()
    samples = build_samples(db)
    selected, candidates = select_jet_references(samples)
    params = db.param_table()
    for value in selected.values():
        descriptor = params.loc[value["npd_id"]]
        description = str(descriptor["Description"])
        if description != EXPECTED_REFERENCE_DESCRIPTIONS[value["npd_id"]]:
            raise RuntimeError(
                f"reference description drifted for {value['npd_id']}: "
                f"{description!r}"
            )
        value.update(
            {
                "description": description,
                "mtow_lb": float(descriptor["Max Gross Takeoff Weight (lb)"]),
                "static_thrust_per_engine_lb": float(
                    descriptor["Max Sea Level Static Thrust (lb)"]
                ),
                "total_static_thrust_lb": float(
                    descriptor["Max Sea Level Static Thrust (lb)"]
                    * descriptor["Number Of Engines"]
                ),
                "descriptor_source_dataset": str(
                    descriptor["source_dataset"]
                ),
                "descriptor_source_file": str(descriptor["source_file"]),
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
        "schema_version": 2,
        "protocol": PROTOCOL,
        "run": {
            "started_utc": started.isoformat(),
            "finished_utc": finished.isoformat(),
            "duration_seconds": time.perf_counter() - timer,
        },
        "config": {
            "seed": seed,
            "models": list(SUPPORTED_LEARNERS),
            "tasks": [{"metric": m, "op_mode": o} for m, o in COMBOS],
            "train_source": TRAIN_SOURCE,
            "test_source": REFERENCE_SOURCE,
            "frozen_references": FROZEN_REFERENCES,
            "family_purge_npd_ids": sorted(FAMILY_PURGE),
        },
        "selection": {
            "population": (
                "complete-task supplement_v6.3 Jet curves by engine count"
            ),
            "features": list(SELECTION_FEATURES),
            "distance": "IQR-scaled Euclidean; zero-IQR contributes zero",
            "tie_break": "NPD_ID lexical ascending",
            "target_blind": True,
            "derived_references": selected,
        },
        "source_separation": {
            "training_targets": TRAIN_SOURCE,
            "selection_descriptors": REFERENCE_SOURCE,
            "test_targets": REFERENCE_SOURCE,
            "v63_target_rows_in_training": 0,
            "family_purge": sorted(FAMILY_PURGE),
        },
        "official_conclusion": OFFICIAL_CONCLUSION,
        "official_source_urls": OFFICIAL_SOURCE_URLS,
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
            "source_files": sorted(
                source_manifest[
                    ["logical_table", "source_dataset", "source_file"]
                ].to_dict(orient="records"),
                key=lambda row: (
                    row["logical_table"],
                    row["source_dataset"],
                    row["source_file"],
                ),
            ),
        },
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
            "matplotlib": matplotlib.__version__,
            "platform": platform.platform(),
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
            "path": str(artifact.resolve()),
            "sha256": _sha256_file(artifact),
            "bytes": artifact.stat().st_size,
        }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen v6.3 jet release holdout against legacy-trained ET/RF."
        )
    )
    parser.add_argument("--db", default=str(PROJECT_ROOT / "anp_data.sqlite"))
    parser.add_argument(
        "--output-dir", default="outputs/model_validation/jet_reference_v63"
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
            args.output_dir,
            PROJECT_ROOT / "outputs/model_validation/jet_reference_v63",
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
        "v6.3 jet release-holdout validation complete: "
        f"{manifest['counts']['train_curves']} train / "
        f"{manifest['counts']['test_curves']} test curves, "
        f"{manifest['run']['duration_seconds']:.1f} s"
    )
    print(f"artifacts: {args.output_dir}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
