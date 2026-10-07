from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.domain import Alert, utc_now
from app.schemas.alerts import AlertRead

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertRead])
def list_alerts(model_id: UUID | None = None, unresolved: bool = False,
                limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
                db: Session = Depends(get_db)):
    query = select(Alert)
    if model_id:
        query = query.where(Alert.model_id == str(model_id))
    if unresolved:
        query = query.where(Alert.resolved_at.is_(None))
    return db.scalars(query.order_by(Alert.created_at.desc(), Alert.id)
                      .offset(offset).limit(limit)).all()


@router.patch("/{alert_id}/resolve", response_model=AlertRead)
def resolve_alert(alert_id: UUID, db: Session = Depends(get_db)):
    alert = db.get(Alert, str(alert_id))
    if alert is None:
        raise HTTPException(404, "Alert not found")
    if alert.resolved_at is None:
        alert.resolved_at = utc_now()
        db.commit()
    return alert
