from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_dataset
from app.db.session import get_db
from app.models.domain import DatasetProfile, MonitoringRun
from app.monitoring.alerts import build_alerts
from app.monitoring.drift import compare_datasets
from app.monitoring.drift import compare_feature
from app.monitoring.performance import compare_performance
from app.schemas.monitoring import DriftRunCreate, MonitoringRunRead, MonitoringRunSummary
from app.services.ingestion import parse_csv
from app.services.storage import LocalStorage, get_storage

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.post("/drift", response_model=MonitoringRunRead, status_code=201)
def run_drift(payload: DriftRunCreate, db: Session = Depends(get_db),
              storage: LocalStorage = Depends(get_storage)):
    ref = require_dataset(db, str(payload.reference_dataset_id))
    prod = require_dataset(db, str(payload.production_dataset_id))
    if ref.id == prod.id:
        raise HTTPException(400, "Choose two different datasets")
    if ref.model_id != prod.model_id:
        raise HTTPException(400, "Datasets must belong to the same monitored model")
    if ref.dataset_type != "reference" or prod.dataset_type != "production":
        raise HTTPException(400, "Choose a reference dataset followed by a production dataset")
    try:
        reference_frame = parse_csv(storage.read(ref.file_path))
        production_frame = parse_csv(storage.read(prod.file_path))
    except FileNotFoundError as exc:
        raise HTTPException(409, "An uploaded dataset file is unavailable") from exc
    if payload.target_column and not payload.prediction_column:
        raise HTTPException(422, "target_column requires prediction_column")
    if payload.prediction_column:
        if payload.prediction_column not in reference_frame or payload.prediction_column not in production_frame:
            raise HTTPException(400, "Prediction column must exist in both datasets")
        if payload.target_column == payload.prediction_column:
            raise HTTPException(422, "Prediction and target columns must be different")
    result = compare_datasets(reference_frame, production_frame,
                              exclude_columns={value for value in (payload.prediction_column,
                                                                 payload.target_column) if value})
    if payload.prediction_column:
        result["prediction_drift"] = compare_feature(
            reference_frame[payload.prediction_column], production_frame[payload.prediction_column],
            payload.prediction_column, categorical=True)
        prediction = result["prediction_drift"]
        if prediction["status"] == "critical":
            result["overall_status"] = "critical"
        elif prediction["status"] in {"warning", "insufficient_data"} and result["overall_status"] == "healthy":
            result["overall_status"] = "warning"
    if payload.target_column:
        result["performance"] = compare_performance(reference_frame, production_frame,
                                                     payload.prediction_column, payload.target_column)
        if result["performance"]["status"] == "warning" and result["overall_status"] == "healthy":
            result["overall_status"] = "warning"
    run = MonitoringRun(model_id=ref.model_id, reference_dataset_id=ref.id,
                        production_dataset_id=prod.id, overall_status=result["overall_status"],
                        drifted_feature_count=result["drifted_feature_count"],
                        total_feature_count=result["total_feature_count"], report=result,
                        prediction_column=payload.prediction_column, target_column=payload.target_column)
    try:
        db.add(run)
        db.flush()
        stored_profile = db.get(DatasetProfile, prod.id)
        quality = stored_profile.report["quality"] if stored_profile else None
        db.add_all(build_alerts(ref.model_id, run.id, result, quality))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return run


@router.get("/runs", response_model=list[MonitoringRunSummary])
def list_runs(model_id: UUID | None = None, limit: int = Query(100, ge=1, le=200),
              offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = select(MonitoringRun)
    if model_id:
        query = query.where(MonitoringRun.model_id == str(model_id))
    return db.scalars(query.order_by(MonitoringRun.created_at.desc(), MonitoringRun.id)
                      .offset(offset).limit(limit)).all()


@router.get("/runs/{run_id}", response_model=MonitoringRunRead)
def get_run(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(MonitoringRun, str(run_id))
    if run is None:
        raise HTTPException(404, "Monitoring run not found")
    return run
