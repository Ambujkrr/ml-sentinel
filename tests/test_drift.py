import json

import numpy as np
import pandas as pd

from app.monitoring.drift import compare_datasets, compare_feature


def test_identical_numeric_distribution_is_healthy():
    values = pd.Series(np.linspace(1, 100, 100))
    report = compare_feature(values, values.copy(), "score")
    assert report["method"] == "ks_2samp"
    assert report["p_value"] == 1.0
    assert report["statistic"] == 0.0
    assert report["psi"] < 0.1
    assert report["drift_detected"] is False
    json.dumps(report, allow_nan=False)


def test_shifted_numeric_distribution_detects_ks_and_psi():
    ref = pd.Series(np.linspace(1, 100, 100))
    prod = pd.Series(np.linspace(101, 200, 100))
    report = compare_feature(ref, prod, "score")
    assert report["p_value"] < 0.05
    assert report["psi"] > 0.25
    assert report["status"] == "critical"
    assert report["drift_detected"] is True
    assert sum(report["distribution"]["reference"]) == 1.0
    assert sum(report["distribution"]["production"]) == 1.0


def test_constant_reference_and_missing_values_have_explicit_handling():
    ref = pd.Series([5.0] * 40)
    same = compare_feature(ref, ref.copy(), "score")
    assert same["status"] == "healthy"
    assert same["p_value"] is None and same["psi"] is None
    changed = compare_feature(ref, pd.Series([6.0] * 40), "score")
    assert changed["status"] == "critical"
    assert changed["drift_detected"] is True
    missing = compare_feature(ref, pd.Series([np.nan] * 40), "score")
    assert missing["status"] == "insufficient_data"
    assert missing["p_value"] is None


def test_tiny_and_nonfinite_samples_return_reason():
    tiny = compare_feature(pd.Series([1.0, 2.0]), pd.Series([3.0, 4.0]), "x")
    assert tiny["status"] == "insufficient_data"
    assert "10" in tiny["reason"]
    nonfinite = compare_feature(pd.Series([np.inf] * 10), pd.Series([1.0] * 10), "x")
    assert nonfinite["status"] == "insufficient_data"
    json.dumps(nonfinite, allow_nan=False)


def test_categorical_unseen_category_and_sparse_fisher():
    ref = pd.Series(["a"] * 40 + ["b"] * 40)
    prod = pd.Series(["a"] * 40 + ["new"] * 40)
    report = compare_feature(ref, prod, "segment")
    assert report["status"] in {"warning", "insufficient_data"}
    assert "new" in report["distribution"]["labels"]
    assert report["p_value"] is None or report["p_value"] < 0.05
    sparse = compare_feature(pd.Series(["a"] * 19 + ["b"]),
                             pd.Series(["a"] * 19 + ["b"]), "segment")
    assert sparse["method"] == "fisher_exact"
    assert sparse["status"] == "healthy"


def test_schema_drift_detects_missing_new_and_incompatible():
    ref = pd.DataFrame({"age": range(40), "income": range(40), "segment": ["a"] * 40})
    prod = pd.DataFrame({"age": ["low"] * 40, "segment": ["a"] * 40,
                         "new_field": [1] * 40})
    report = compare_datasets(ref, prod)
    assert report["overall_status"] == "critical"
    assert report["schema_changes"]["missing_columns"] == ["income"]
    assert report["schema_changes"]["unexpected_columns"] == ["new_field"]
    assert report["schema_changes"]["type_changes"][0]["column"] == "age"
    json.dumps(report, allow_nan=False)


def test_missing_rate_change_is_reported():
    ref = pd.Series(list(range(40)), dtype=float)
    prod = pd.Series(list(range(30)) + [np.nan] * 10)
    report = compare_feature(ref, prod, "score")
    assert report["missing_rate_changed"] is True
    assert report["drift_detected"] is True
