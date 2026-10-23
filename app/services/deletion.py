"""Delete only unused ordinary datasets, with durable, retryable file cleanup."""
from hashlib import sha256
import logging
from threading import RLock

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.domain import Dataset, DatasetProfile, MonitoringRun, PendingDatasetDeletion
from app.services.demo import DEMO_DATASET_IDS, DEMO_MODEL_ID
from app.services.storage import LocalStorage

logger = logging.getLogger("ml_sentinel")
# Bounded locks serialize local retries. PostgreSQL row locks and foreign keys
# protect different processes; SQLite takes a write lock before checking usage.
_locks = [RLock() for _ in range(64)]


def protect_demo(dataset_id: str, dataset: Dataset | None = None):
    if dataset_id in DEMO_DATASET_IDS.values() or (dataset and dataset.model_id == DEMO_MODEL_ID):
        raise HTTPException(403, "Shared synthetic demo datasets cannot be deleted")


def check_unused(db: Session, dataset: Dataset):
    protect_demo(dataset.id, dataset)
    used = db.scalar(select(func.count()).select_from(MonitoringRun).where(or_(
        MonitoringRun.reference_dataset_id == dataset.id,
        MonitoringRun.production_dataset_id == dataset.id)))
    if used:
        raise HTTPException(409, "Dataset is used by monitoring comparisons; its reports and alerts must be preserved")


def deletion_preview(db: Session, dataset_id: str) -> dict:
    protect_demo(dataset_id)
    dataset = db.get(Dataset, dataset_id)
    if dataset is not None:
        check_unused(db, dataset)
        return {"dataset_id": dataset.id, "name": dataset.name, "cleanup_pending": False,
                "removes": ["Dataset metadata", "Stored profile and quality report", "Uploaded CSV file, if present and not referenced by another dataset"]}
    pending = db.get(PendingDatasetDeletion, dataset_id)
    if pending is None:
        raise HTTPException(404, "Dataset not found")
    return {"dataset_id": pending.id, "name": pending.dataset_name, "cleanup_pending": True,
            "removes": ["Remaining uploaded CSV file, if not referenced by another dataset (metadata was already removed)"]}


def finish_cleanup(db: Session, storage: LocalStorage, job: PendingDatasetDeletion):
    try:
        # Legacy data or a retried cleanup may reference a file still in use.
        # Current uploads use fresh UUID keys and a unique constraint; never
        # remove a surviving dataset's file even if older data lacked that guard.
        shared = db.scalar(select(Dataset.id).where(Dataset.file_path == job.file_path).limit(1))
        if shared is None:
            storage.delete(job.file_path)
        db.execute(delete(PendingDatasetDeletion).where(PendingDatasetDeletion.id == job.id))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Dataset CSV cleanup pending (%s)", type(exc).__name__)
        raise HTTPException(503, "Dataset metadata was removed, but CSV cleanup is pending. Use Retry file cleanup in Administrator access.") from exc


def delete_dataset(db: Session, storage: LocalStorage, dataset_id: str):
    protect_demo(dataset_id)
    lock = _locks[sha256(dataset_id.encode()).digest()[0] % len(_locks)]
    with lock:
        try:
            if db.get_bind().dialect.name == "sqlite":
                connection = db.connection()
                if not connection.connection.driver_connection.in_transaction:
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
            dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id)
                                .with_for_update().execution_options(populate_existing=True))
            if dataset is None:
                pending = db.get(PendingDatasetDeletion, dataset_id)
                if pending is None:
                    raise HTTPException(404, "Dataset not found")
            else:
                check_unused(db, dataset)
                storage.validate_delete_key(dataset.file_path)
                pending = PendingDatasetDeletion(id=dataset.id, dataset_name=dataset.name,
                                                 file_path=dataset.file_path)
                db.add(pending)
                db.execute(delete(DatasetProfile).where(DatasetProfile.dataset_id == dataset.id))
                db.delete(dataset)
                db.flush()  # Foreign keys are the final guard against racing comparisons.
                db.commit()  # No file operations before the metadata transaction succeeds.
        except HTTPException:
            db.rollback()
            raise
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Dataset is still referenced by other records and cannot safely be deleted") from exc
        except Exception as exc:
            db.rollback()
            logger.warning("Dataset deletion transaction failed (%s)", type(exc).__name__)
            raise HTTPException(503, "Dataset deletion was not completed. Refresh and try again; no file was removed.") from exc
        finish_cleanup(db, storage, pending)
