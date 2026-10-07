"""Registration and ingestion contracts, including failed-write cleanup."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.domain import Dataset, MonitoredModel


def test_register_list_and_retrieve_models(client: TestClient, db: Session) -> None:
    assert client.get("/models").json() == []
    response = client.post(
        "/models",
        json={"name": "Loan default risk", "description": "Credit risk classifier"},
    )
    assert response.status_code == 201
    model = response.json()
    UUID(model["id"])
    assert model["name"] == "Loan default risk"
    assert model["description"] == "Credit risk classifier"
    assert model["model_version"] == "1.0"
    assert model["created_at"]
    assert client.get(f"/models/{model['id']}").json() == model
    assert client.get("/models").json() == [model]
    assert db.scalar(select(func.count()).select_from(MonitoredModel)) == 1


@pytest.mark.parametrize("name", ["", "   ", "x" * 121])
def test_invalid_model_name_is_rejected(client: TestClient, db: Session, name: str) -> None:
    assert client.post("/models", json={"name": name}).status_code == 422
    assert db.scalar(select(func.count()).select_from(MonitoredModel)) == 0


@pytest.mark.parametrize("resource", ["models", "datasets"])
def test_unknown_and_invalid_ids(client: TestClient, resource: str) -> None:
    assert client.get(f"/{resource}/{uuid4()}").status_code == 404
    assert client.get(f"/{resource}/not-a-uuid").status_code == 422


def test_upload_stores_metadata_and_safe_file(
    client: TestClient, db: Session, storage, registered_model: dict, upload_dataset
) -> None:
    response = upload_dataset(filename="../../outside.csv")
    assert response.status_code == 201, response.text
    dataset = response.json()
    UUID(dataset["id"])
    assert dataset["model_id"] == registered_model["id"]
    assert dataset["dataset_type"] == "reference"
    assert dataset["row_count"] == 2
    assert dataset["column_count"] == 2
    assert "file_path" not in dataset
    assert client.get(f"/datasets/{dataset['id']}").json() == dataset
    assert client.get(f"/models/{registered_model['id']}/datasets").json() == [dataset]

    stored = db.get(Dataset, dataset["id"])
    assert stored is not None
    files = list(Path(storage.root).glob("*.csv"))
    assert len(files) == 1
    UUID(files[0].stem)
    assert files[0].resolve().parent == Path(storage.root).resolve()
    assert files[0].read_bytes() == b"income,segment\n50000,salaried\n70000,business\n"
    assert not (Path(storage.root).parent / "outside.csv").exists()


def test_dataset_list_is_scoped_to_model(client: TestClient, registered_model, upload_dataset) -> None:
    uploaded = upload_dataset(dataset_type="production")
    assert uploaded.status_code == 201
    other = client.post("/models", json={"name": "Other model"}).json()
    assert client.get(f"/models/{other['id']}/datasets").json() == []
    assert len(client.get(f"/models/{registered_model['id']}/datasets").json()) == 1


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"   \n\n",
        b"income,segment\n",
        b"income,income\n1,2\n",
        b",segment\n1,salaried\n",
        b"income,segment\n1,salaried,extra\n",
        b'income,segment\n1,"unterminated\n',
        b"income,segment\n1,\x00binary\n",
        b"\xff\xfe\x00\x00",
    ],
    ids=["empty", "whitespace", "header-only", "duplicate-header", "empty-header", "ragged", "bad-quote", "nul", "binary"],
)
def test_invalid_csv_leaves_no_record_or_file(db: Session, storage, upload_dataset, content: bytes) -> None:
    response = upload_dataset(content)
    assert response.status_code == 400, response.text
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0
    assert not list(Path(storage.root).glob("*.csv"))


@pytest.mark.parametrize("dataset_type", ["training", "REFERENCE", ""])
def test_invalid_dataset_type(db: Session, storage, upload_dataset, dataset_type: str) -> None:
    assert upload_dataset(dataset_type=dataset_type).status_code == 422
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0
    assert not list(Path(storage.root).glob("*.csv"))


@pytest.mark.parametrize("name", ["", "   ", "x" * 121])
def test_invalid_dataset_name(upload_dataset, name: str) -> None:
    assert upload_dataset(name=name).status_code == 422


def test_upload_to_missing_model(client: TestClient, db: Session, storage, upload_dataset) -> None:
    missing_id = str(uuid4())
    assert upload_dataset(model_id=missing_id).status_code == 404
    assert client.get(f"/models/{missing_id}/datasets").status_code == 404
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0
    assert not list(Path(storage.root).glob("*.csv"))


def test_upload_rejects_invalid_model_id(upload_dataset) -> None:
    assert upload_dataset(model_id="invalid-id").status_code == 422


def test_upload_requires_csv_extension(db: Session, storage, upload_dataset) -> None:
    response = upload_dataset(filename="data.exe")
    assert response.status_code == 400
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0
    assert not list(Path(storage.root).glob("*.csv"))


def test_missing_upload_file(client: TestClient, registered_model: dict) -> None:
    response = client.post(
        f"/models/{registered_model['id']}/datasets",
        data={"name": "Missing file", "dataset_type": "reference"},
    )
    assert response.status_code == 422


def test_upload_limit_is_enforced(monkeypatch, db: Session, storage, upload_dataset) -> None:
    monkeypatch.setattr(get_settings(), "MAX_UPLOAD_BYTES", 24)
    response = upload_dataset(b"income\n" + b"123456789\n" * 10)
    assert response.status_code == 413, response.text
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0
    assert not list(Path(storage.root).glob("*.csv"))


def test_database_failure_cleans_uploaded_file(monkeypatch, db: Session, storage, upload_dataset) -> None:
    def fail_commit() -> None:
        raise SQLAlchemyError("private database detail")

    monkeypatch.setattr(db, "commit", fail_commit)
    response = upload_dataset()
    assert response.status_code == 500
    assert "private database detail" not in response.text
    assert not list(Path(storage.root).glob("*.csv"))
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0


def test_storage_failure_leaves_no_dataset_record(monkeypatch, db: Session, storage, upload_dataset) -> None:
    def fail_save(_content: bytes) -> str:
        raise OSError("private storage path")

    monkeypatch.setattr(storage, "save", fail_save)
    response = upload_dataset()
    assert response.status_code == 500
    assert "private storage path" not in response.text
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0
    assert not list(Path(storage.root).glob("*.csv"))


def test_utf8_bom_and_single_column_csv_are_supported(upload_dataset) -> None:
    response = upload_dataset(b"\xef\xbb\xbfincome\n50000\n70000\n")
    assert response.status_code == 201, response.text
    assert response.json()["row_count"] == 2
    assert response.json()["column_count"] == 1
