"""One bounded, shared demo. No uploads, resets, caller-supplied IDs, or file writes."""
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.domain import Dataset, DatasetProfile, MonitoredModel, MonitoringRun
from app.monitoring.profiling import profile_dataset
from app.services.ingestion import parse_csv
from app.services.monitoring import create_monitoring_run


def demo_id(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://ml-sentinel/demo/v1/{name}"))


DEMO_MODEL_ID = demo_id("model")
DEMO_NAME = "Loan risk — Synthetic demo"
DEMO_VERSION = "synthetic-demo-v1"
DEMO_DESCRIPTION = "Shared read-only demonstration. Synthetic data only; no real borrowers."
DEMO_DIR = Path(__file__).resolve().parents[2] / "demo"
DEMO_FILES = {
    "reference": "reference.csv",
    "normal": "production_normal.csv",
    "shifted": "production_drifted.csv",
}
DEMO_DATASET_IDS = {role: demo_id(f"dataset/{role}") for role in DEMO_FILES}
DEMO_RUN_IDS = {role: demo_id(f"run/{role}") for role in ("normal", "shifted")}


def manifest() -> dict:
    return {"model_id": DEMO_MODEL_ID, "dataset_ids": dict(DEMO_DATASET_IDS),
            "run_ids": dict(DEMO_RUN_IDS), "read_only": True}


def existing_demo(db: Session) -> dict:
    """Fail closed on a collision or damaged seed; never repair/overwrite records."""
    model = db.get(MonitoredModel, DEMO_MODEL_ID)
    valid = (model is not None and model.name == DEMO_NAME
             and model.model_version == DEMO_VERSION and model.description == DEMO_DESCRIPTION)
    for role, dataset_id in DEMO_DATASET_IDS.items():
        dataset = db.get(Dataset, dataset_id)
        valid = valid and (dataset is not None and dataset.model_id == DEMO_MODEL_ID
                           and dataset.dataset_type == ("reference" if role == "reference" else "production")
                           and dataset.file_path == f"bundled-demo-v1-{role}.csv"
                           and db.get(DatasetProfile, dataset_id) is not None)
    for role, run_id in DEMO_RUN_IDS.items():
        run = db.get(MonitoringRun, run_id)
        valid = valid and (run is not None and run.model_id == DEMO_MODEL_ID
                           and run.reference_dataset_id == DEMO_DATASET_IDS["reference"]
                           and run.production_dataset_id == DEMO_DATASET_IDS[role]
                           and run.prediction_column == "prediction" and run.target_column == "actual")
    if not valid:
        raise HTTPException(409, "Demo records conflict or are incomplete; no existing data was changed")
    return manifest()


def load_demo(db: Session) -> dict:
    if db.get(MonitoredModel, DEMO_MODEL_ID) is not None:
        return existing_demo(db)
    try:
        db.add(MonitoredModel(id=DEMO_MODEL_ID, name=DEMO_NAME,
                             model_version=DEMO_VERSION, description=DEMO_DESCRIPTION))
        # The primary key arbitrates concurrent requests across processes. Flush
        # before computing: contenders wait for this transaction, then reuse it.
        db.flush()
        datasets = {}
        frames = {}
        for role, filename in DEMO_FILES.items():
            frames[role] = parse_csv((DEMO_DIR / filename).read_bytes())
            dataset = Dataset(id=DEMO_DATASET_IDS[role], model_id=DEMO_MODEL_ID,
                              name=filename, file_name=filename,
                              dataset_type="reference" if role == "reference" else "production",
                              file_path=f"bundled-demo-v1-{role}.csv",
                              row_count=len(frames[role]), column_count=len(frames[role].columns))
            db.add(dataset)
            db.flush()
            db.add(DatasetProfile(dataset_id=dataset.id, report=profile_dataset(frames[role])))
            datasets[role] = dataset
        for role, run_id in DEMO_RUN_IDS.items():
            create_monitoring_run(db, datasets["reference"], datasets[role],
                                  frames["reference"], frames[role], "prediction", "actual",
                                  run_id=run_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        # Either another request committed the complete seed or a reserved ID
        # collided. In the latter case existing_demo refuses to mutate anything.
        return existing_demo(db)
    except Exception:
        db.rollback()
        raise
    return manifest()


def saved_demo_comparison(db: Session, reference_id: str, production_id: str,
                          prediction_column: str | None,
                          target_column: str | None) -> MonitoringRun:
    existing_demo(db)
    if (reference_id != DEMO_DATASET_IDS["reference"]
            or prediction_column != "prediction" or target_column != "actual"):
        raise HTTPException(409, "The shared demo offers two saved comparisons using prediction and actual columns")
    for role, run_id in DEMO_RUN_IDS.items():
        if production_id == DEMO_DATASET_IDS[role]:
            return db.get(MonitoringRun, run_id)
    raise HTTPException(409, "Choose one of the demo's two production datasets")
