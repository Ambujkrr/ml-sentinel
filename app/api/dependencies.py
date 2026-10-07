from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.domain import Dataset, MonitoredModel


def require_model(db: Session, model_id: str) -> MonitoredModel:
    model = db.get(MonitoredModel, model_id)
    if model is None:
        raise HTTPException(404, "Monitored model not found")
    return model


def require_dataset(db: Session, dataset_id: str) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(404, "Dataset not found")
    return dataset
