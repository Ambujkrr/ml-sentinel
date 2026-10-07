"""Bounded dataset summaries and understandable data-quality checks.

Missing percentages use all rows; numeric statistics use finite values only.
Standard deviation is the sample standard deviation (ddof=1).
Outliers use the 1.5 * IQR rule with at least four finite observations. When
IQR is zero, any observation different from the common quartile is an outlier.
These monitoring defaults are heuristics, not universal measures of bad data.
"""

from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_numeric_dtype


TOP_CATEGORY_LIMIT = 10
CATEGORY_LABEL_LIMIT = 120
MISSING_CRITICAL_PERCENTAGE = 20.0
DUPLICATE_CRITICAL_PERCENTAGE = 20.0
OUTLIER_CRITICAL_PERCENTAGE = 10.0
PREDOMINANT_NUMERIC_FRACTION = 0.8
IQR_MULTIPLIER = 1.5
MIN_OUTLIER_OBSERVATIONS = 4


def infer_type(series: pd.Series) -> str:
    """Infer CSV-compatible types without treating mixed strings as numeric."""
    present = series.dropna()
    if present.empty:
        return "empty"
    if is_bool_dtype(series.dtype) or all(isinstance(value, (bool, np.bool_)) for value in present):
        return "boolean"
    if is_numeric_dtype(series.dtype) and not is_complex_dtype(series.dtype):
        return "numeric"
    # CSV parsing usually handles numeric strings already. This also supports
    # direct callers with string/object columns containing only numeric values.
    if not is_complex_dtype(series.dtype) and pd.to_numeric(present, errors="coerce").notna().all():
        return "numeric"
    return "categorical"


def _percentage(count: int, total: int) -> float:
    return round(100.0 * count / total, 6) if total else 0.0


def _number(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _numeric_statistics(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series.dropna(), errors="coerce").to_numpy(dtype=float)
    finite = values[np.isfinite(values)]
    count = len(finite)
    statistics: dict[str, Any] = {
        "finite_count": count,
        "non_finite_count": int(np.count_nonzero(~np.isfinite(values))),
        "mean": None,
        "median": None,
        "standard_deviation": None,
        "minimum": None,
        "maximum": None,
        "q1": None,
        "q3": None,
        "iqr": None,
        "outlier_count": None,
        "outlier_percentage": None,
        "outlier_reason": "At least four finite observations are required for IQR outlier detection.",
        "notes": [],
    }
    if not count:
        statistics["notes"].append("No finite observations are available for numeric statistics.")
        return statistics

    # Scaling avoids avoidable overflow in means, quantile interpolation and
    # squared deviations when CSV values approach the floating-point limit.
    scale = float(np.max(np.abs(finite))) or 1.0
    scaled = finite / scale
    q1, median, q3 = np.quantile(scaled, [0.25, 0.5, 0.75])
    with np.errstate(over="ignore", invalid="ignore"):
        calculated = {
            "mean": np.mean(scaled) * scale,
            "median": median * scale,
            "standard_deviation": np.std(scaled, ddof=1) * scale if count > 1 else None,
            "minimum": np.min(finite),
            "maximum": np.max(finite),
            "q1": q1 * scale,
            "q3": q3 * scale,
            "iqr": (q3 - q1) * scale,
        }
    for name, value in calculated.items():
        statistics[name] = _number(value) if value is not None else None
        if value is not None and statistics[name] is None:
            statistics["notes"].append(f"{name} exceeds the representable numeric range.")
    if count < 2:
        statistics["notes"].append("Sample standard deviation requires at least two finite observations.")

    if count >= MIN_OUTLIER_OBSERVATIONS:
        iqr = q3 - q1
        outliers = (scaled < q1 - IQR_MULTIPLIER * iqr) | (scaled > q3 + IQR_MULTIPLIER * iqr)
        statistics["outlier_count"] = int(outliers.sum())
        statistics["outlier_percentage"] = _percentage(statistics["outlier_count"], count)
        statistics["outlier_reason"] = (
            "IQR is zero; observations differing from the common quartile are flagged."
            if iqr == 0
            else "Values outside Q1 - 1.5 * IQR and Q3 + 1.5 * IQR are flagged."
        )
    return statistics


def profile_dataset(frame: pd.DataFrame) -> dict[str, Any]:
    """Calculate a finite, JSON-safe report without retaining uploaded rows."""
    total_rows = len(frame)
    issues: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []

    def issue(
        check: str, severity: str, message: str, count: int,
        column: str | None = None, percentage: float | None = None,
    ) -> None:
        item: dict[str, Any] = {"check": check, "severity": severity, "message": message, "count": count}
        if column is not None:
            item["column"] = column
        if percentage is not None:
            item["percentage"] = percentage
        issues.append(item)

    for name in frame.columns:
        series = frame[name]
        present = series.dropna()
        column_name = str(name)
        missing_count = int(series.isna().sum())
        missing_percentage = _percentage(missing_count, total_rows)
        unique_count = int(present.nunique())
        inferred_type = infer_type(series)
        column: dict[str, Any] = {
            "name": column_name,
            "type": inferred_type,
            "total_rows": total_rows,
            "missing_count": missing_count,
            "missing_percentage": missing_percentage,
            "unique_count": unique_count,
        }
        if missing_count:
            issue(
                "missing_values", "critical" if missing_percentage >= MISSING_CRITICAL_PERCENTAGE else "warning",
                f"{column_name} contains {missing_count} missing values ({missing_percentage:g}%).",
                missing_count, column_name, missing_percentage,
            )
        if unique_count == 1 and len(present) >= 2:
            issue("constant_column", "warning", f"{column_name} has only one distinct non-missing value.", len(present), column_name)

        if inferred_type == "numeric":
            statistics = _numeric_statistics(series)
            column["statistics"] = statistics
            non_finite_count = statistics["non_finite_count"]
            if non_finite_count:
                issue(
                    "non_finite_values", "critical",
                    f"{column_name} contains {non_finite_count} infinite values; finite values alone are used for statistics.",
                    non_finite_count, column_name, _percentage(non_finite_count, total_rows),
                )
            if statistics["outlier_count"]:
                outlier_percentage = statistics["outlier_percentage"]
                issue(
                    "numeric_outliers", "critical" if outlier_percentage >= OUTLIER_CRITICAL_PERCENTAGE else "warning",
                    f"{column_name} contains {statistics['outlier_count']} IQR outliers ({outlier_percentage:g}% of finite values).",
                    statistics["outlier_count"], column_name, outlier_percentage,
                )
        elif inferred_type in {"categorical", "boolean"}:
            column["categories"] = [
                {
                    "value": str(value)[:CATEGORY_LABEL_LIMIT],
                    "count": int(count),
                    "percentage": _percentage(int(count), total_rows),
                }
                for value, count in present.value_counts().head(TOP_CATEGORY_LIMIT).items()
            ]
            column["categories_truncated"] = unique_count > TOP_CATEGORY_LIMIT
            if inferred_type == "categorical" and not present.empty:
                numeric_count = int(pd.to_numeric(present, errors="coerce").notna().sum())
                if PREDOMINANT_NUMERIC_FRACTION <= numeric_count / len(present) < 1:
                    inconsistent_count = len(present) - numeric_count
                    issue(
                        "type_inconsistency", "warning",
                        f"{column_name} is predominantly numeric but contains {inconsistent_count} non-numeric values.",
                        inconsistent_count, column_name, _percentage(inconsistent_count, total_rows),
                    )
        columns.append(column)

    duplicate_count = int(frame.duplicated().sum())
    if duplicate_count:
        percentage = _percentage(duplicate_count, total_rows)
        issue(
            "duplicate_rows", "critical" if percentage >= DUPLICATE_CRITICAL_PERCENTAGE else "warning",
            f"Dataset contains {duplicate_count} duplicate rows beyond their first occurrence ({percentage:g}%).",
            duplicate_count, percentage=percentage,
        )
    if not total_rows:
        issue("empty_dataset", "critical", "Dataset contains no observations.", 0)
    status = "critical" if any(item["severity"] == "critical" for item in issues) else "warning" if issues else "healthy"
    return {
        "row_count": total_rows,
        "column_count": len(frame.columns),
        "columns": columns,
        "quality": {"status": status, "issues": issues, "duplicate_row_count": duplicate_count},
    }
