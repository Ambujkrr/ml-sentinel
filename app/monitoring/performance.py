"""Classification metrics from paired prediction and ground-truth columns."""

import math

import pandas as pd

from app.core.config import Settings, get_settings


def _label(value) -> str:
    if isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value).is_integer():
        return str(int(value))
    return str(value)


def _pairs(frame: pd.DataFrame, prediction_column: str, target_column: str):
    paired = frame[[prediction_column, target_column]].dropna()
    return [(_label(actual), _label(prediction)) for prediction, actual in
            paired[[prediction_column, target_column]].itertuples(index=False, name=None)]


def classification_metrics(frame: pd.DataFrame, prediction_column: str,
                           target_column: str, labels: list[str] | None = None) -> dict:
    pairs = _pairs(frame, prediction_column, target_column)
    if not pairs:
        return {"status": "unavailable", "reason": "No rows contain both prediction and actual labels.",
                "sample_count": 0, "accuracy": None, "precision": None, "recall": None, "f1": None,
                "labels": []}
    classes = labels or sorted({value for pair in pairs for value in pair})
    if len(classes) > 50 or (len(classes) > 20 and len(classes) > len(pairs) / 2):
        return {"status": "unavailable", "reason": "Labels appear continuous or too numerous for classification.",
                "sample_count": len(pairs), "accuracy": None, "precision": None, "recall": None,
                "f1": None, "labels": classes[:20]}
    correct = sum(actual == predicted for actual, predicted in pairs)
    per_class = []
    for label in classes:
        tp = sum(actual == label and predicted == label for actual, predicted in pairs)
        fp = sum(actual != label and predicted == label for actual, predicted in pairs)
        fn = sum(actual == label and predicted != label for actual, predicted in pairs)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class.append({"label": label[:80], "support": sum(actual == label for actual, _ in pairs),
                          "precision": precision, "recall": recall, "f1": f1})
    return {"status": "available", "reason": None, "sample_count": len(pairs),
            "accuracy": correct / len(pairs),
            "precision": sum(item["precision"] for item in per_class) / len(classes),
            "recall": sum(item["recall"] for item in per_class) / len(classes),
            "f1": sum(item["f1"] for item in per_class) / len(classes),
            "labels": per_class}


def compare_performance(reference: pd.DataFrame, production: pd.DataFrame,
                        prediction_column: str, target_column: str,
                        settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    if target_column not in production:
        return {"status": "unavailable", "reason": "Production ground-truth labels are not available.",
                "reference_metrics": None, "production_metrics": None,
                "f1_drop": None, "threshold": settings.PERFORMANCE_F1_DROP}
    labels = sorted({value for frame in (reference, production) if target_column in frame
                     for pair in _pairs(frame, prediction_column, target_column) for value in pair})
    current = classification_metrics(production, prediction_column, target_column, labels)
    baseline = (classification_metrics(reference, prediction_column, target_column, labels)
                if target_column in reference else None)
    if current["status"] == "unavailable":
        return {"status": "unavailable", "reason": current["reason"],
                "reference_metrics": baseline, "production_metrics": current,
                "f1_drop": None, "threshold": settings.PERFORMANCE_F1_DROP}
    if baseline is None or baseline["status"] == "unavailable":
        return {"status": "baseline_unavailable", "reason": "No reference labels are available for comparison.",
                "reference_metrics": baseline, "production_metrics": current,
                "f1_drop": None, "threshold": settings.PERFORMANCE_F1_DROP}
    drop = baseline["f1"] - current["f1"]
    return {"status": "warning" if drop >= settings.PERFORMANCE_F1_DROP else "healthy",
            "reason": None, "reference_metrics": baseline, "production_metrics": current,
            "f1_drop": drop, "threshold": settings.PERFORMANCE_F1_DROP}
