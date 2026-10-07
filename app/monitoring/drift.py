"""Finite, inspectable distribution comparisons for immutable CSV snapshots."""

import math

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, fisher_exact, ks_2samp

from app.core.config import Settings, get_settings
from app.monitoring.profiling import infer_type


def _numeric_values(series: pd.Series) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    return values[np.isfinite(values)]


def _numeric_distribution(ref: np.ndarray, prod: np.ndarray, bins: int) -> tuple[dict, float | None]:
    """Quantile bins from reference; tail bins retain out-of-range production data."""
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 2:
        return {"kind": "numeric", "labels": ["reference value", "other"],
                "reference": [1.0, 0.0],
                "production": [float(np.mean(prod == ref[0])), float(np.mean(prod != ref[0]))]}, None
    internal = edges[1:-1]
    ref_counts = np.bincount(np.searchsorted(internal, ref, side="right"), minlength=len(internal) + 1)
    prod_counts = np.bincount(np.searchsorted(internal, prod, side="right"), minlength=len(internal) + 1)
    ref_rates = ref_counts / len(ref)
    prod_rates = prod_counts / len(prod)
    # A small probability floor prevents log(0); normalize again after smoothing.
    smoothing = 1e-6
    p = (ref_rates + smoothing) / (1 + len(ref_rates) * smoothing)
    q = (prod_rates + smoothing) / (1 + len(prod_rates) * smoothing)
    psi = float(np.sum((q - p) * np.log(q / p)))
    labels = [f"≤ {edges[1]:.4g}"]
    labels += [f"{edges[i]:.4g}–{edges[i + 1]:.4g}" for i in range(1, len(edges) - 2)]
    labels += [f"> {edges[-2]:.4g}"]
    # With one interval there is only one bin, not two labeled tails.
    if len(ref_rates) == 1:
        labels = ["all values"]
    if len(labels) != len(ref_rates):
        labels = [f"bin {i + 1}" for i in range(len(ref_rates))]
    return {"kind": "numeric", "labels": labels,
            "reference": ref_rates.tolist(), "production": prod_rates.tolist()}, psi


def _categories(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("(missing)")


def _categorical_comparison(reference: pd.Series, production: pd.Series, minimum: int, alpha: float) -> dict:
    ref = _categories(reference)
    prod = _categories(production)
    ref_counts = ref.value_counts()
    prod_counts = prod.value_counts()
    categories = sorted(set(ref_counts.index) | set(prod_counts.index))
    top = sorted(categories, key=lambda key: -(int(ref_counts.get(key, 0)) + int(prod_counts.get(key, 0))))[:10]
    labels = [str(value)[:80] for value in top]
    if len(categories) > len(top):
        labels.append("Other")

    def rates(counts, total):
        parts = [int(counts.get(key, 0)) for key in top]
        if len(categories) > len(top):
            parts.append(total - sum(parts))
        return [part / total for part in parts]

    result = {"method": "chi_square", "statistic": None, "p_value": None,
              "psi": None, "status": "insufficient_data", "drift_detected": None,
              "reason": None,
              "distribution": {"kind": "categorical", "labels": labels,
                               "reference": rates(ref_counts, len(ref)),
                               "production": rates(prod_counts, len(prod))}}
    if min(len(ref), len(prod)) < minimum:
        result["reason"] = f"At least {minimum} observations per dataset are needed."
        return result
    if len(categories) <= 1:
        result.update(status="healthy", drift_detected=False, method="constant",
                      reason="Both datasets contain the same single category.")
        return result
    if len(categories) > 100:
        result["reason"] = "More than 100 distinct categories; statistical test skipped."
        return result
    table = np.array([[int(ref_counts.get(category, 0)) for category in categories],
                      [int(prod_counts.get(category, 0)) for category in categories]])
    if len(categories) == 2:
        chi = chi2_contingency(table, correction=False)
        if np.min(chi.expected_freq) < 5:
            odds, p = fisher_exact(table)
            result.update(method="fisher_exact", statistic=float(odds) if math.isfinite(odds) else None,
                          p_value=float(p), reason="Fisher exact test used for sparse 2×2 counts.")
        else:
            result.update(statistic=float(chi.statistic), p_value=float(chi.pvalue))
    else:
        chi = chi2_contingency(table, correction=False)
        if np.min(chi.expected_freq) < 5:
            result["reason"] = "Expected counts below five; chi-square test is unreliable."
            return result
        result.update(statistic=float(chi.statistic), p_value=float(chi.pvalue))
    drifted = result["p_value"] < alpha
    result.update(status="warning" if drifted else "healthy", drift_detected=drifted)
    return result


def compare_feature(reference: pd.Series, production: pd.Series, name: str,
                    settings: Settings | None = None, categorical: bool = False) -> dict:
    settings = settings or get_settings()
    ref_type, prod_type = infer_type(reference), infer_type(production)
    ref_missing = float(reference.isna().mean())
    prod_missing = float(production.isna().mean())
    result = {"feature": name, "type": "categorical" if categorical else ref_type,
              "reference_count": len(reference), "production_count": len(production),
              "missing_percentage_reference": round(ref_missing * 100, 6),
              "missing_percentage_production": round(prod_missing * 100, 6)}
    if ref_type == "empty" or prod_type == "empty":
        result.update(method=None, statistic=None, p_value=None, psi=None,
                      status="insufficient_data", drift_detected=None,
                      reason="One dataset contains only missing values.", distribution=None)
        return result
    if ref_type != prod_type and not categorical:
        result.update(method=None, statistic=None, p_value=None, psi=None,
                      status="incompatible", drift_detected=None,
                      reason=f"Type changed from {ref_type} to {prod_type}.", distribution=None)
        return result
    if categorical or ref_type in {"categorical", "boolean"}:
        result.update(_categorical_comparison(reference, production,
                                             settings.MIN_DRIFT_SAMPLES, settings.DRIFT_ALPHA))
    else:
        ref, prod = _numeric_values(reference), _numeric_values(production)
        result.update(method="ks_2samp", statistic=None, p_value=None, psi=None,
                      status="insufficient_data", drift_detected=None, reason=None, distribution=None)
        if min(len(ref), len(prod)) < settings.MIN_DRIFT_SAMPLES:
            result["reason"] = f"At least {settings.MIN_DRIFT_SAMPLES} finite values per dataset are needed."
            return result
        distribution, psi = _numeric_distribution(ref, prod, settings.PSI_BINS)
        result["distribution"] = distribution
        if len(np.unique(ref)) == 1:
            drifted = bool(np.any(prod != ref[0]))
            result.update(method="constant_reference", psi=psi, drift_detected=drifted,
                          status="critical" if drifted else "healthy",
                          reason="Reference is constant; KS/PSI are not meaningful. Exact value change checked.")
            return result
        ks = ks_2samp(ref, prod)
        psi = psi if psi is not None and math.isfinite(psi) else None
        detected = bool(ks.pvalue < settings.DRIFT_ALPHA or
                        (psi is not None and psi >= settings.PSI_WARNING))
        severity = ("critical" if psi is not None and psi >= settings.PSI_CRITICAL
                    else "warning" if detected else "healthy")
        result.update(statistic=float(ks.statistic), p_value=float(ks.pvalue), psi=psi,
                      status=severity, drift_detected=detected,
                      reason="KS compares finite numerical values; PSI uses reference quantile bins.")
    if abs(prod_missing - ref_missing) >= settings.MISSING_RATE_CHANGE:
        result["missing_rate_changed"] = True
        if result["status"] == "healthy":
            result["status"] = "warning"
        if result["drift_detected"] is False:
            result["drift_detected"] = True
    else:
        result["missing_rate_changed"] = False
    return result


def compare_datasets(reference: pd.DataFrame, production: pd.DataFrame,
                     settings: Settings | None = None,
                     exclude_columns: set[str] | None = None) -> dict:
    settings = settings or get_settings()
    if exclude_columns:
        reference = reference.drop(columns=list(exclude_columns), errors="ignore")
        production = production.drop(columns=list(exclude_columns), errors="ignore")
    missing = [name for name in reference if name not in production]
    unexpected = [name for name in production if name not in reference]
    type_changes = []
    features = []
    for name in reference:
        if name not in production:
            continue
        ref_type = infer_type(reference[name])
        prod_type = infer_type(production[name])
        if ref_type != prod_type and ref_type != "empty" and prod_type != "empty":
            type_changes.append({"column": name, "reference_type": ref_type, "production_type": prod_type})
        features.append(compare_feature(reference[name], production[name], name, settings))
    drifted = sum(feature["drift_detected"] is True for feature in features)
    critical = bool(missing or type_changes or any(feature["status"] == "critical" for feature in features))
    warning = bool(unexpected or drifted or any(feature["status"] in {"insufficient_data", "incompatible"} for feature in features))
    return {"overall_status": "critical" if critical else "warning" if warning else "healthy",
            "drifted_feature_count": drifted, "total_feature_count": len(reference.columns),
            "summary": f"{drifted} of {len(reference.columns)} reference features drifted; "
                       f"{len(missing)} missing, {len(unexpected)} unexpected columns, "
                       f"{len(type_changes)} type changes.",
            "features": features,
            "schema_changes": {"missing_columns": missing, "unexpected_columns": unexpected,
                               "type_changes": type_changes},
            "thresholds": {"ks_alpha": settings.DRIFT_ALPHA, "psi_warning": settings.PSI_WARNING,
                           "psi_critical": settings.PSI_CRITICAL,
                           "minimum_samples": settings.MIN_DRIFT_SAMPLES}}
