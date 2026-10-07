"""Alert rules are derived solely from calculated monitoring results."""

from app.models.domain import Alert


def build_alerts(model_id: str, run_id: str, report: dict,
                 quality: dict | None = None) -> list[Alert]:
    alerts: list[Alert] = []

    def add(kind: str, severity: str, message: str) -> None:
        alerts.append(Alert(model_id=model_id, monitoring_run_id=run_id,
                            alert_type=kind, severity=severity, message=message[:500]))

    schema = report["schema_changes"]
    for column in schema["missing_columns"]:
        add("SCHEMA_DRIFT", "critical", f"Production dataset is missing expected column {column}.")
    for column in schema["unexpected_columns"]:
        add("SCHEMA_DRIFT", "warning", f"Production dataset introduced column {column}.")
    for change in schema["type_changes"]:
        add("SCHEMA_DRIFT", "critical",
            f"Column {change['column']} changed from {change['reference_type']} to {change['production_type']}.")
    for feature in report["features"]:
        if feature.get("drift_detected") is True:
            severity = "critical" if feature["status"] == "critical" else "warning"
            add("DATA_DRIFT", severity, f"Distribution shift detected in {feature['feature']}.")
    prediction = report.get("prediction_drift")
    if prediction and prediction.get("drift_detected") is True:
        severity = "critical" if prediction["status"] == "critical" else "warning"
        add("PREDICTION_DRIFT", severity,
            f"Prediction distribution shifted in {prediction['feature']}.")
    performance = report.get("performance")
    if performance and performance["status"] == "warning":
        add("PERFORMANCE_DEGRADATION", "warning",
            f"Model macro F1 fell by {performance['f1_drop']:.3f}, "
            f"exceeding the {performance['threshold']:.3f} threshold.")
    if quality and quality["status"] in {"warning", "critical"}:
        severity = quality["status"]
        add("DATA_QUALITY", severity,
            f"Production dataset quality is {severity}: {len(quality['issues'])} issue(s) detected.")
    return alerts
