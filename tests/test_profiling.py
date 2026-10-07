"""Deterministic profiling edge cases and useful quality signals."""

import json

import numpy as np
import pandas as pd
import pytest

from app.monitoring.profiling import infer_type, profile_dataset


def test_numeric_profile_matches_known_statistics() -> None:
    result = profile_dataset(pd.DataFrame({"income": [1, 2, 3, 4, 5]}))
    assert result["row_count"] == 5
    column = result["columns"][0]
    assert column["name"] == "income"
    assert column["type"] == "numeric"
    assert column["missing_count"] == 0
    assert column["unique_count"] == 5
    stats = column["statistics"]
    assert stats["mean"] == pytest.approx(3)
    assert stats["median"] == pytest.approx(3)
    assert stats["standard_deviation"] == pytest.approx(np.sqrt(2.5))
    assert stats["minimum"] == 1
    assert stats["maximum"] == 5
    assert stats["q1"] == pytest.approx(2)
    assert stats["q3"] == pytest.approx(4)
    assert stats["outlier_count"] == 0
    assert result["quality"]["status"] == "healthy"


def test_missing_infinite_and_empty_columns_are_json_safe() -> None:
    result = profile_dataset(pd.DataFrame({"score": [1, np.nan, np.inf, -np.inf], "empty": [None] * 4}))
    score, empty = result["columns"]
    assert score["missing_count"] == 1
    assert score["missing_percentage"] == 25
    assert score["statistics"]["finite_count"] == 1
    assert score["statistics"]["non_finite_count"] == 2
    assert score["statistics"]["mean"] == 1
    assert score["statistics"]["standard_deviation"] is None
    assert empty["type"] == "empty"
    assert empty["missing_percentage"] == 100
    assert result["quality"]["status"] == "critical"
    assert any(item["check"] == "non_finite_values" for item in result["quality"]["issues"])
    json.dumps(result, allow_nan=False)


def test_all_infinite_column_explains_unavailable_statistics() -> None:
    result = profile_dataset(pd.DataFrame({"value": [np.inf, -np.inf]}))
    stats = result["columns"][0]["statistics"]
    assert stats["finite_count"] == 0
    assert stats["mean"] is None
    assert stats["notes"]
    json.dumps(result, allow_nan=False)


def test_duplicate_rows_and_constant_columns_are_calculated() -> None:
    result = profile_dataset(pd.DataFrame({"x": [5, 5, 5, 5], "category": ["a", "a", "b", "b"]}))
    quality = result["quality"]
    assert quality["duplicate_row_count"] == 2
    assert quality["status"] == "critical"
    assert next(item for item in quality["issues"] if item["check"] == "constant_column")["column"] == "x"
    assert result["columns"][0]["statistics"]["outlier_count"] == 0


def test_iqr_outliers_and_zero_iqr_policy() -> None:
    result = profile_dataset(pd.DataFrame({"value": [1, 1, 1, 1, 100]}))
    stats = result["columns"][0]["statistics"]
    assert stats["iqr"] == 0
    assert stats["outlier_count"] == 1
    assert stats["outlier_percentage"] == 20
    assert "IQR is zero" in stats["outlier_reason"]
    assert any(item["check"] == "numeric_outliers" for item in result["quality"]["issues"])


def test_regular_iqr_rule_flags_extreme_observation() -> None:
    result = profile_dataset(pd.DataFrame({"value": [1, 2, 3, 4, 5, 6, 100]}))
    assert result["columns"][0]["statistics"]["outlier_count"] == 1


@pytest.mark.parametrize("values", [[5], [1, 100], [1, 2, 100]])
def test_tiny_samples_do_not_claim_outlier_evidence(values) -> None:
    stats = profile_dataset(pd.DataFrame({"x": values}))["columns"][0]["statistics"]
    assert stats["outlier_count"] is None
    assert "At least four" in stats["outlier_reason"]


def test_category_summary_is_bounded_and_percentage_includes_missing() -> None:
    values = ["a", "a", None] + [f"category_{i}" for i in range(20)]
    column = profile_dataset(pd.DataFrame({"segment": values}))["columns"][0]
    assert column["type"] == "categorical"
    assert column["unique_count"] == 21
    assert len(column["categories"]) == 10
    assert column["categories_truncated"] is True
    assert column["categories"][0]["value"] == "a"
    assert column["categories"][0]["count"] == 2
    assert column["categories"][0]["percentage"] == pytest.approx(100 * 2 / len(values), abs=1e-6)


def test_category_labels_are_bounded() -> None:
    column = profile_dataset(pd.DataFrame({"text": ["x" * 1000]}))["columns"][0]
    assert len(column["categories"][0]["value"]) == 120


def test_mixed_predominantly_numeric_strings_are_reported() -> None:
    column_values = ["1", "2", "3", "4", "oops"]
    result = profile_dataset(pd.DataFrame({"income": column_values}))
    assert result["columns"][0]["type"] == "categorical"
    issue = next(item for item in result["quality"]["issues"] if item["check"] == "type_inconsistency")
    assert issue["count"] == 1
    assert issue["percentage"] == 20


@pytest.mark.parametrize(
    ("values", "expected"),
    [([True, False], "boolean"), ([True, None], "boolean"), ([1, 2], "numeric"), (["1", "2"], "numeric"), (["a", "b"], "categorical"), ([None, None], "empty")],
)
def test_type_inference(values, expected: str) -> None:
    assert infer_type(pd.Series(values)) == expected


def test_empty_dataframe_has_clear_status_and_no_nan() -> None:
    result = profile_dataset(pd.DataFrame({"x": []}))
    assert result["row_count"] == 0
    assert result["quality"]["status"] == "critical"
    json.dumps(result, allow_nan=False)


def test_extreme_finite_values_do_not_emit_nan_or_infinity() -> None:
    result = profile_dataset(pd.DataFrame({"x": [-1.7e308, 1.7e308]}))
    stats = result["columns"][0]["statistics"]
    assert stats["mean"] == 0
    assert stats["median"] == 0
    assert stats["standard_deviation"] is None
    assert "standard_deviation exceeds" in stats["notes"][0]
    json.dumps(result, allow_nan=False)


def test_small_missing_fraction_is_warning() -> None:
    result = profile_dataset(pd.DataFrame({"x": list(range(19)) + [None]}))
    assert result["quality"]["status"] == "warning"
