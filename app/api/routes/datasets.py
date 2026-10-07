from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_dataset, require_model
from app.db.session import get_db
from app.models.domain import Dataset
from app.schemas.domain import DatasetRead
from app.services.ingestion import ingest_dataset
from app.services.storage import LocalStorage, get_storage

router = APIRouter(tags=["datasets"])


@router.post("/models/{model_id}/datasets", response_model=DatasetRead, status_code=201)
def upload_dataset(model_id: UUID, name: str = Form(..., min_length=1, max_length=120),
                   dataset_type: Literal["reference", "production"] = Form(...),
                   file: UploadFile = File(...), db: Session = Depends(get_db),
                   storage: LocalStorage = Depends(get_storage)):
    require_model(db, str(model_id))
    if not name.strip():
        raise HTTPException(422, "Dataset name must not be blank")
    return ingest_dataset(db, storage, str(model_id), name.strip(), dataset_type, file)


@router.get("/models/{model_id}/datasets", response_model=list[DatasetRead])
def list_datasets(model_id: UUID, limit: int = Query(100, ge=1, le=200),
                  offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    require_model(db, str(model_id))
    return db.scalars(select(Dataset).where(Dataset.model_id == str(model_id))
                      .order_by(Dataset.created_at.desc(), Dataset.id).offset(offset).limit(limit)).all()


@router.get("/datasets/{dataset_id}", response_model=DatasetRead)
def get_dataset(dataset_id: UUID, db: Session = Depends(get_db)):
    return require_dataset(db, str(dataset_id))
