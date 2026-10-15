"""A public seed operation with a fixed, one-time database footprint."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.demo import load_demo, manifest

router = APIRouter(prefix="/demo", tags=["demo"])
logger = logging.getLogger("ml_sentinel")


class DemoRead(BaseModel):
    model_id: str
    dataset_ids: dict[str, str]
    run_ids: dict[str, str]
    read_only: bool


async def bounded_request(request: Request) -> None:
    if request.query_params:
        raise HTTPException(422, "Demo loading does not accept parameters")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 256:
            raise HTTPException(413, "Demo request is too large")
        body.extend(chunk)
    try:
        if body and json.loads(body) != {}:
            raise ValueError
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, "Demo loading accepts only an empty request or {}") from exc


@router.get("", response_model=DemoRead)
def demo_info():
    """Describe reserved demo IDs without creating any records."""
    return manifest()


@router.post("/load", response_model=DemoRead, dependencies=[Depends(bounded_request)])
def load_synthetic_demo(db: Session = Depends(get_db)):
    try:
        return load_demo(db)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        # Exception strings can contain database credentials or SQL parameters.
        logger.warning("Synthetic demo unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Synthetic demo is temporarily unavailable; please try again later") from exc
