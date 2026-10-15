"""Tests apply real migrations to a disposable SQLite database, never PostgreSQL."""

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Set before application imports so tests cannot use a developer's DATABASE_URL.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["DATASET_DELETION_ENABLED"] = "false"
os.environ["ADMIN_USERNAME"] = ""
os.environ["ADMIN_PASSWORD"] = ""
os.environ["ADMIN_ALLOWED_ORIGIN"] = ""

from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.storage import LocalStorage, get_storage  # noqa: E402


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    with Session(engine, expire_on_commit=False) as session:
        yield session
        session.rollback()
    engine.dispose()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=tmp_path / "uploads")


@pytest.fixture
def client(db: Session, storage: LocalStorage) -> Generator[TestClient, None, None]:
    def override_db() -> Generator[Session, None, None]:
        yield db

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_storage] = lambda: storage
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


@pytest.fixture
def registered_model(client: TestClient) -> dict:
    response = client.post("/models", json={"name": "Loan risk", "model_version": "1.0"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def upload_dataset(client: TestClient, registered_model: dict):
    def upload(
        content: bytes = b"income,segment\n50000,salaried\n70000,business\n",
        *,
        dataset_type: str = "reference",
        name: str = "Sample dataset",
        filename: str = "sample.csv",
        model_id: str | None = None,
    ):
        return client.post(
            f"/models/{model_id or registered_model['id']}/datasets",
            data={"name": name, "dataset_type": dataset_type},
            files={"file": (filename, content, "text/csv")},
        )

    return upload
