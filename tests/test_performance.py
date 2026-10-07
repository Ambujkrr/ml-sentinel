import pandas as pd

from app.monitoring.performance import classification_metrics, compare_performance


def test_binary_metrics_are_computed_from_rows():
    frame = pd.DataFrame({"prediction": [1, 1, 0, 0], "actual": [1, 0, 0, 0]})
    metrics = classification_metrics(frame, "prediction", "actual")
    assert metrics["status"] == "available"
    assert metrics["accuracy"] == 0.75
    assert round(metrics["precision"], 6) == 0.75
    assert round(metrics["recall"], 6) == round((1.0 + 2 / 3) / 2, 6)
    assert metrics["sample_count"] == 4


def test_multiclass_metrics_and_missing_labels():
    frame = pd.DataFrame({"prediction": ["a", "b", "b", "c", None],
                          "actual": ["a", "b", "c", "c", "a"]})
    metrics = classification_metrics(frame, "prediction", "actual")
    assert metrics["status"] == "available"
    assert metrics["sample_count"] == 4
    assert len(metrics["labels"]) == 3
    assert metrics["accuracy"] == 0.75


def test_f1_degradation_is_measured_against_reference():
    ref = pd.DataFrame({"prediction": [0, 1] * 30, "actual": [0, 1] * 30})
    prod = pd.DataFrame({"prediction": [0, 1] * 30, "actual": [1, 0] * 30})
    result = compare_performance(ref, prod, "prediction", "actual")
    assert result["status"] == "warning"
    assert result["reference_metrics"]["f1"] == 1.0
    assert result["production_metrics"]["f1"] == 0.0
    assert result["f1_drop"] == 1.0


def test_no_ground_truth_or_continuous_labels_are_not_fabricated():
    frame = pd.DataFrame({"prediction": list(range(60)), "actual": list(range(60))})
    assert classification_metrics(frame, "prediction", "actual")["status"] == "unavailable"
    no_labels = frame.drop(columns="actual")
    result = compare_performance(frame, no_labels, "prediction", "actual")
    assert result["status"] == "unavailable"
    assert result["production_metrics"] is None


def test_production_only_labels_report_baseline_unavailable():
    ref = pd.DataFrame({"prediction": [0, 1] * 10})
    prod = pd.DataFrame({"prediction": [0, 1] * 10, "actual": [0, 1] * 10})
    result = compare_performance(ref, prod, "prediction", "actual")
    assert result["status"] == "baseline_unavailable"
    assert result["production_metrics"]["accuracy"] == 1.0
