"""The shared monitoring pipeline; callers own the transaction."""
import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.domain import Dataset, DatasetProfile, MonitoringRun
from app.monitoring.alerts import build_alerts
from app.monitoring.drift import compare_datasets, compare_feature
from app.monitoring.performance import compare_performance


def create_monitoring_run(db: Session, ref: Dataset, prod: Dataset,
                          reference_frame: pd.DataFrame, production_frame: pd.DataFrame,
                          prediction_column: str | None, target_column: str | None,
                          *, run_id: str | None = None) -> MonitoringRun:
    if target_column and not prediction_column:
        raise HTTPException(422, "target_column requires prediction_column")
    if prediction_column:
        if prediction_column not in reference_frame or prediction_column not in production_frame:
            raise HTTPException(400, "Prediction column must exist in both datasets")
        if target_column == prediction_column:
            raise HTTPException(422, "Prediction and target columns must be different")
    result = compare_datasets(reference_frame, production_frame,
                              exclude_columns={value for value in (prediction_column,
                                                                   target_column) if value})
    if prediction_column:
        result["prediction_drift"] = compare_feature(
            reference_frame[prediction_column], production_frame[prediction_column],
            prediction_column, categorical=True)
        prediction = result["prediction_drift"]
        if prediction["status"] == "critical":
            result["overall_status"] = "critical"
        elif prediction["status"] in {"warning", "insufficient_data"} and result["overall_status"] == "healthy":
            result["overall_status"] = "warning"
    if target_column:
        result["performance"] = compare_performance(reference_frame, production_frame,
                                                     prediction_column, target_column)
        if result["performance"]["status"] == "warning" and result["overall_status"] == "healthy":
            result["overall_status"] = "warning"
    run = MonitoringRun(model_id=ref.model_id, reference_dataset_id=ref.id,
                        production_dataset_id=prod.id, overall_status=result["overall_status"],
                        drifted_feature_count=result["drifted_feature_count"],
                        total_feature_count=result["total_feature_count"], report=result,
                        prediction_column=prediction_column, target_column=target_column)
    if run_id is not None:
        run.id = run_id
    db.add(run)
    db.flush()
    stored_profile = db.get(DatasetProfile, prod.id)
    quality = stored_profile.report["quality"] if stored_profile else None
    db.add_all(build_alerts(ref.model_id, run.id, result, quality))
    return run
