from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import require_dataset
from app.db.session import get_db
from app.models.domain import DatasetProfile

router = APIRouter(prefix="/datasets", tags=["profiling"])


def stored_profile(db: Session, dataset_id: str) -> dict:
    require_dataset(db, dataset_id)
    profile = db.get(DatasetProfile, dataset_id)
    if profile is None:
        raise HTTPException(409, "Profile unavailable for this legacy dataset; upload it again")
    return profile.report


@router.get("/{dataset_id}/profile")
def get_profile(dataset_id: UUID, db: Session = Depends(get_db)):
    return {"dataset_id": str(dataset_id), **stored_profile(db, str(dataset_id))}


@router.get("/{dataset_id}/quality")
def get_quality(dataset_id: UUID, db: Session = Depends(get_db)):
    return {"dataset_id": str(dataset_id), **stored_profile(db, str(dataset_id))["quality"]}
