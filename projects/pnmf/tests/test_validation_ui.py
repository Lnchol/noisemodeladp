"""Tests for accuracy validation dataset builder and UI integration."""

import pytest
import pandas as pd
import numpy as np

from pnmf.anp import ANPDatabase
from pnmf.accuracy_validation import (
    build_accuracy_validation_dataset,
    load_or_build_accuracy_dataset,
)
from pnmf.jet_reference_validation import FROZEN_REFERENCES, FAMILY_PURGE


@pytest.fixture(scope="module")
def anp_db():
    return ANPDatabase(".")


def test_build_accuracy_validation_dataset_holdout(anp_db):
    """Verify the frozen v6.3 release-holdout accuracy dataset structure and roles."""
    ds = build_accuracy_validation_dataset(anp_db, protocol="holdout", learner="et")

    assert "summary_table" in ds
    assert "predictions" in ds
    assert "kpis" in ds
    assert ds["protocol"] == "holdout"

    summary = ds["summary_table"]
    assert isinstance(summary, pd.DataFrame)
    assert len(summary) > 0

    # Required columns
    expected_cols = [
        "NPD_ID",
        "ACFT_ID",
        "Description",
        "Role",
        "Role Description",
        "Dataset Source",
        "Engine Count",
        "Overall RMSE [dB]",
        "MAE [dB]",
        "Max Error [dB]",
        "Bias [dB]",
        "RMSE_SEL_D",
        "RMSE_SEL_A",
        "RMSE_LAmax_D",
        "RMSE_LAmax_A",
        "RMSE_EPNL_D",
        "RMSE_EPNL_A",
        "RMSE_PNLTM_D",
        "RMSE_PNLTM_A",
    ]
    for col in expected_cols:
        assert col in summary.columns, f"Missing column: {col}"

    # Verify frozen holdout references are tagged as VALIDATION_ONLY
    holdout_ids = {ref["npd_id"] for ref in FROZEN_REFERENCES.values()}
    for npd_id in holdout_ids:
        row = summary[summary["NPD_ID"] == npd_id]
        assert not row.empty, f"Holdout reference {npd_id} not found in summary table"
        assert row.iloc[0]["Role"] == "VALIDATION_ONLY"
        assert not np.isnan(row.iloc[0]["Overall RMSE [dB]"])
        assert row.iloc[0]["Overall RMSE [dB]"] > 0

    # Verify family purge aircraft are tagged as PURGED
    for npd_id in FAMILY_PURGE:
        row = summary[summary["NPD_ID"] == npd_id]
        assert not row.empty, f"Purged aircraft {npd_id} not found in summary table"
        assert row.iloc[0]["Role"] == "PURGED"

    # Verify training aircraft are tagged as TRAIN
    train_rows = summary[summary["Role"] == "TRAIN"]
    assert len(train_rows) >= 50
    for _, row in train_rows.iterrows():
        assert not np.isnan(row["Overall RMSE [dB]"])

    # Verify KPIs
    kpis = ds["kpis"]
    assert kpis["total_aircraft_count"] == len(summary)
    assert kpis["validation_aircraft_count"] == len(holdout_ids)
    assert kpis["purged_aircraft_count"] == len(FAMILY_PURGE)
    assert kpis["overall_validation_rmse_dB"] > 0
    assert kpis["overall_training_rmse_dB"] > 0


def test_build_accuracy_validation_dataset_group_cv(anp_db):
    """Verify 5-fold stratified group cross-validation dataset."""
    ds = build_accuracy_validation_dataset(anp_db, protocol="group_cv", learner="et")

    assert "summary_table" in ds
    assert "predictions" in ds
    assert "kpis" in ds
    assert ds["protocol"] == "group_cv"

    summary = ds["summary_table"]
    assert isinstance(summary, pd.DataFrame)
    assert len(summary) == 94  # Total jet curves in the population

    # Check that all aircraft have out-of-fold validation scores
    valid_scores = summary["Overall RMSE [dB]"].dropna()
    assert len(valid_scores) == 94
    assert (valid_scores > 0).all()

    # Predictions frame integrity
    preds = ds["predictions"]
    assert isinstance(preds, pd.DataFrame)
    assert len(preds) > 0
    assert "truth_dB" in preds.columns
    assert "prediction_dB" in preds.columns
    assert "error_dB" in preds.columns


def test_build_accuracy_validation_dataset_verified_5fold(anp_db):
    """Verify 5-fold cross-validation evaluated strictly on the 11 EASA-verified aircraft."""
    ds = build_accuracy_validation_dataset(anp_db, protocol="verified_5fold", learner="et")

    assert "summary_table" in ds
    assert "predictions" in ds
    assert "kpis" in ds
    assert ds["protocol"] == "verified_5fold"

    summary = ds["summary_table"]
    assert isinstance(summary, pd.DataFrame)
    assert len(summary) == 11  # Exactly 11 trainable verified types

    # Check verified columns
    assert "EASA Status" in summary.columns
    assert "Verification Date" in summary.columns
    assert "Engine Family" in summary.columns
    assert (summary["EASA Status"] == "✅ Verified (v6.3)").all()

    # Check out-of-fold accuracy metrics
    valid_scores = summary["Overall RMSE [dB]"].dropna()
    assert len(valid_scores) == 11
    assert (valid_scores > 0).all()

    # Check KPIs
    kpis = ds["kpis"]
    assert kpis["validation_aircraft_count"] == 11
    assert kpis["n_folds"] == 5
    assert kpis["overall_validation_rmse_dB"] > 0


def test_build_accuracy_validation_dataset_invalid_protocol(anp_db):
    """Verify error on unsupported protocol or learner."""
    with pytest.raises(ValueError, match="Unknown validation protocol"):
        build_accuracy_validation_dataset(anp_db, protocol="invalid_proto")

    with pytest.raises(ValueError, match="Unsupported learner"):
        build_accuracy_validation_dataset(anp_db, learner="invalid_learner")


def test_validation_chart_rendering(anp_db):
    """Verify boxplot and residual curve rendering logic runs without errors."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ds = build_accuracy_validation_dataset(anp_db, protocol="holdout", learner="et")
    summary_df = ds["summary_table"]
    pred_df = ds["predictions"]

    # 1. Boxplot rendering
    valid_errs = summary_df.dropna(subset=["Overall RMSE [dB]"])
    fig, ax = plt.subplots(figsize=(6, 4))
    roles_present = sorted(valid_errs["Role"].unique())
    data_to_plot = [
        valid_errs[valid_errs["Role"] == r]["Overall RMSE [dB]"].dropna().values
        for r in roles_present
    ]
    box = ax.boxplot(data_to_plot, patch_artist=True)
    ax.set_xticks(range(1, len(roles_present) + 1))
    ax.set_xticklabels(roles_present)
    plt.close(fig)

    # 2. Residual curves rendering for a holdout reference
    acft_curve_preds = pred_df[
        (pred_df["npd_id"] == "A330-743L")
        & (pred_df["metric"] == "SEL")
        & (pred_df["op_mode"] == "D")
    ]
    assert not acft_curve_preds.empty
    fig, (ax_curve, ax_res) = plt.subplots(2, 1, figsize=(6.5, 5.2), sharex=True)
    dist_vals = acft_curve_preds["distance_ft"].unique()
    powers = sorted(acft_curve_preds["power_setting"].unique())
    for p in powers:
        sub_p = acft_curve_preds[acft_curve_preds["power_setting"] == p].sort_values("distance_ft")
        ax_curve.semilogx(sub_p["distance_ft"].values, sub_p["truth_dB"].values, "o-")
        ax_res.semilogx(sub_p["distance_ft"].values, sub_p["error_dB"].values, "o-")
    plt.close(fig)


def test_load_or_build_accuracy_dataset_caching(anp_db):
    """Verify load_or_build_accuracy_dataset loads instantly from disk cache."""
    import time
    # Should load in < 0.5s from precomputed cache
    t0 = time.time()
    ds = load_or_build_accuracy_dataset(anp_db, protocol="verified_5fold")
    elapsed = time.time() - t0

    assert "summary_table" in ds
    assert "predictions" in ds
    assert "kpis" in ds
    assert len(ds["summary_table"]) == 11
    assert elapsed < 1.0  # Must be sub-second cached load

