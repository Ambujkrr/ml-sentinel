from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_model
from app.db.session import get_db
from app.models.domain import MonitoredModel
from app.schemas.domain import ModelCreate, ModelRead

router = APIRouter(prefix="/models", tags=["models"])


@router.post("", response_model=ModelRead, status_code=201)
def create_model(payload: ModelCreate, db: Session = Depends(get_db)):
    model = MonitoredModel(**payload.model_dump())
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


@router.get("", response_model=list[ModelRead])
def list_models(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
                db: Session = Depends(get_db)):
    return db.scalars(select(MonitoredModel).order_by(MonitoredModel.created_at.desc(), MonitoredModel.id)
                      .offset(offset).limit(limit)).all()


@router.get("/{model_id}", response_model=ModelRead)
def get_model(model_id: UUID, db: Session = Depends(get_db)):
    return require_model(db, str(model_id))
