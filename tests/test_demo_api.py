"""The public demo has one bounded footprint, even across restarts and races."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import app
from app.models.domain import Alert, Dataset, DatasetProfile, MonitoredModel, MonitoringRun
from app.services import demo
from app.services.storage import LocalStorage, get_storage

TABLES = (MonitoredModel, Dataset, DatasetProfile, MonitoringRun, Alert)


def counts(db):
    return tuple(db.scalar(select(func.count()).select_from(table)) for table in TABLES)


def test_demo_metadata_does_not_seed(client, db):
    assert client.get("/demo").json() == demo.manifest()
    assert counts(db) == (0, 0, 0, 0, 0)
    assert "Load Demo Data" in client.get("/dashboard").text


def test_demo_load_uses_real_pipeline_and_repeated_loads_do_not_write(client, db, storage, monkeypatch):
    response = client.post("/demo/load")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data == demo.manifest()
    assert counts(db) == (1, 3, 3, 2, 7)
    assert not storage.root.exists()  # No uploaded files to recover after restart.
    snapshots = {role: client.get(f"/monitoring/runs/{run_id}").json()
                 for role, run_id in data["run_ids"].items()}
    normal, shifted = snapshots["normal"], snapshots["shifted"]
    assert normal["drifted_feature_count"] == 0
    assert normal["report"]["performance"]["f1_drop"] == 0
    assert shifted["drifted_feature_count"] == 5
    assert shifted["report"]["performance"]["status"] == "warning"
    assert shifted["report"]["performance"]["f1_drop"] == pytest.approx(0.467, abs=0.001)
    assert shifted["report"]["prediction_drift"]["feature"] == "prediction"
    for dataset_id in data["dataset_ids"].values():
        profile = client.get(f"/datasets/{dataset_id}/profile")
        assert profile.status_code == 200
        assert profile.json()["row_count"] == 240
    assert client.get(f"/datasets/{data['dataset_ids']['shifted']}/quality").json()["issues"]
    original_alerts = client.get("/alerts").json()

    def unexpected_compute(*_args, **_kwargs):
        raise AssertionError("Repeated clicks must not recompute or regenerate")

    monkeypatch.setattr(demo, "profile_dataset", unexpected_compute)
    monkeypatch.setattr(db, "commit", unexpected_compute)
    for _ in range(5):
        assert client.post("/demo/load", json={}).json() == data
    assert counts(db) == (1, 3, 3, 2, 7)
    assert client.get("/alerts").json() == original_alerts
    for role, run_id in data["run_ids"].items():
        assert client.get(f"/monitoring/runs/{run_id}").json() == snapshots[role]


@pytest.mark.parametrize("body", [b'{"force":true}', b'{"model_id":"other"}', b'[]', b'null', b'no json'])
def test_demo_rejects_customization(client, db, body):
    assert client.post("/demo/load", content=body).status_code == 422
    assert counts(db) == (0, 0, 0, 0, 0)


def test_demo_rejects_query_and_oversized_chunked_body(client, db):
    assert client.post("/demo/load?reset=true").status_code == 422
    assert client.post("/demo/load", content=b" " * 257).status_code == 413
    assert client.post("/demo/load", content=iter([b" " * 200, b" " * 200])).status_code == 413
    assert counts(db) == (0, 0, 0, 0, 0)


def test_demo_namespace_is_read_only_and_comparisons_are_bounded(client, db):
    data = client.post("/demo/load").json()
    before = counts(db)
    assert client.post(f"/models/{data['model_id']}/datasets",
                       data={"name": "overwrite", "dataset_type": "production"},
                       files={"file": ("user.csv", b"x\n1\n", "text/csv")}).status_code == 409
    for role in ("normal", "shifted"):
        payload = {"reference_dataset_id": data["dataset_ids"]["reference"],
                   "production_dataset_id": data["dataset_ids"][role],
                   "prediction_column": "prediction", "target_column": "actual"}
        for _ in range(3):
            result = client.post("/monitoring/drift", json=payload)
            assert result.status_code == 201
            assert result.json()["id"] == data["run_ids"][role]
        assert client.post("/monitoring/drift", json={**payload, "prediction_column": "income"}).status_code == 409
    for alert in client.get("/alerts").json():
        assert client.patch(f"/alerts/{alert['id']}/resolve").status_code == 409
        assert alert["resolved_at"] is None
    assert counts(db) == before


def test_existing_user_model_with_same_name_is_preserved(client, db, upload_dataset, registered_model):
    model = db.get(MonitoredModel, registered_model["id"])
    model.name = demo.DEMO_NAME
    model.model_version = demo.DEMO_VERSION
    db.commit()
    uploaded = upload_dataset().json()
    prior_model = client.get(f"/models/{model.id}").json()
    prior_dataset = client.get(f"/datasets/{uploaded['id']}").json()
    client.post("/demo/load").raise_for_status()
    assert client.get(f"/models/{model.id}").json() == prior_model
    assert client.get(f"/datasets/{uploaded['id']}").json() == prior_dataset
    assert upload_dataset(name="Another ordinary upload").status_code == 201
    assert counts(db) == (2, 5, 5, 2, 7)


def test_reserved_model_collision_fails_closed(client, db):
    db.add(MonitoredModel(id=demo.DEMO_MODEL_ID, name="Existing private model"))
    db.commit()
    assert client.post("/demo/load").status_code == 409
    assert db.get(MonitoredModel, demo.DEMO_MODEL_ID).name == "Existing private model"
    assert counts(db) == (1, 0, 0, 0, 0)


def test_reserved_dataset_collision_rolls_back_without_overwriting(client, db, registered_model):
    db.add(Dataset(id=demo.DEMO_DATASET_IDS["reference"], model_id=registered_model["id"],
                   name="User dataset", dataset_type="reference", file_name="user.csv",
                   file_path="user-file.csv", row_count=1, column_count=1))
    db.commit()
    assert client.post("/demo/load").status_code == 409
    assert counts(db) == (1, 1, 0, 0, 0)
    assert db.get(Dataset, demo.DEMO_DATASET_IDS["reference"]).name == "User dataset"


def test_damaged_seed_is_not_silently_reset(client, db):
    data = client.post("/demo/load").json()
    profile = db.get(DatasetProfile, data["dataset_ids"]["shifted"])
    db.delete(profile)
    db.commit()
    before = counts(db)
    assert client.post("/demo/load").status_code == 409
    assert counts(db) == before


@pytest.mark.parametrize("failure_stage", ["assets", "profile", "second_run", "commit"])
def test_initialization_errors_roll_back_and_allow_retry(client, db, registered_model, monkeypatch, tmp_path,
                                                        failure_stage):
    def fail(*_args, **_kwargs):
        raise SQLAlchemyError("private database credential must not appear")

    with monkeypatch.context() as patch:
        if failure_stage == "assets":
            patch.setattr(demo, "DEMO_DIR", tmp_path / "missing-image-assets")
        elif failure_stage == "profile":
            patch.setattr(demo, "profile_dataset", fail)
        elif failure_stage == "commit":
            patch.setattr(db, "commit", fail)
        else:
            original = demo.create_monitoring_run

            def fail_second(*args, **kwargs):
                if kwargs["run_id"] == demo.DEMO_RUN_IDS["shifted"]:
                    fail()
                return original(*args, **kwargs)

            patch.setattr(demo, "create_monitoring_run", fail_second)
        response = client.post("/demo/load")
    assert response.status_code == 503
    assert "private database" not in response.text
    assert counts(db) == (1, 0, 0, 0, 0)
    assert db.get(MonitoredModel, registered_model["id"]) is not None
    assert client.post("/demo/load").status_code == 200
    assert counts(db) == (2, 3, 3, 2, 7)


@pytest.fixture
def durable_engine(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'demo.sqlite').as_posix()}",
                           connect_args={"check_same_thread": False, "timeout": 15})
    project = Path(__file__).resolve().parents[1]
    config = Config(str(project / "alembic.ini"))
    config.set_main_option("script_location", str(project / "alembic"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


@contextmanager
def restarted_client(engine, upload_dir):
    def database():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_storage] = lambda: LocalStorage(upload_dir)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_restart_recovery_uses_durable_reports_not_uploads_or_warm_cache(durable_engine, tmp_path, monkeypatch):
    with restarted_client(durable_engine, tmp_path / "old-uploads") as first:
        data = first.post("/demo/load").json()
        prior = first.get(f"/monitoring/runs/{data['run_ids']['shifted']}").json()
    durable_engine.dispose()  # Close connections and application lifespan; new sessions below.
    monkeypatch.setattr(demo, "DEMO_DIR", tmp_path / "unavailable-assets")
    empty_uploads = tmp_path / "new-empty-upload-directory"
    with restarted_client(durable_engine, empty_uploads) as restarted:
        assert restarted.post("/demo/load").json() == data
        assert restarted.get("/health").status_code == 200
        assert restarted.get(f"/monitoring/runs/{prior['id']}").json() == prior
        assert len(restarted.get("/monitoring/runs").json()) == 2
        assert len(restarted.get("/alerts").json()) == 7
        for dataset_id in data["dataset_ids"].values():
            assert restarted.get(f"/datasets/{dataset_id}/profile").status_code == 200
            assert restarted.get(f"/datasets/{dataset_id}/quality").status_code == 200
        result = restarted.post("/monitoring/drift", json={
            "reference_dataset_id": data["dataset_ids"]["reference"],
            "production_dataset_id": data["dataset_ids"]["shifted"],
            "prediction_column": "prediction", "target_column": "actual"})
        assert result.json() == prior
    assert not empty_uploads.exists()
    with Session(durable_engine) as db:
        assert counts(db) == (1, 3, 3, 2, 7)


def test_concurrent_first_loads_use_one_atomic_seed(durable_engine):
    barrier = Barrier(2)

    def load_in_session():
        with Session(durable_engine, expire_on_commit=False) as db:
            original_get = db.get
            first_model_read = True

            def simultaneous_get(entity, key, *args, **kwargs):
                nonlocal first_model_read
                result = original_get(entity, key, *args, **kwargs)
                if entity is MonitoredModel and key == demo.DEMO_MODEL_ID and first_model_read:
                    first_model_read = False
                    assert result is None
                    barrier.wait(timeout=10)
                return result

            db.get = simultaneous_get
            return demo.load_demo(db)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: load_in_session(), range(2)))
    assert results == [demo.manifest(), demo.manifest()]
    with Session(durable_engine) as db:
        assert counts(db) == (1, 3, 3, 2, 7)
