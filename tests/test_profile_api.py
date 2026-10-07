from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.models.domain import Dataset, DatasetProfile
from app.services import ingestion


def test_profile_and_quality_are_persisted(client, db, upload_dataset, storage):
    content = b"income,segment\n10,a\n20,a\n30,b\n1000,b\n,b\n"
    response = upload_dataset(content)
    assert response.status_code == 201
    dataset_id = response.json()["id"]
    profile = client.get(f"/datasets/{dataset_id}/profile")
    assert profile.status_code == 200
    assert profile.json()["row_count"] == 5
    persisted = db.get(DatasetProfile, dataset_id)
    assert persisted is not None
    assert profile.json() == {"dataset_id": dataset_id, **persisted.report}
    assert content.decode() not in profile.text
    assert not {"rows", "raw_rows", "records", "sample_rows", "raw_data"} & profile.json().keys()
    assert "file_path" not in profile.json()

    quality_response = client.get(f"/datasets/{dataset_id}/quality")
    assert quality_response.status_code == 200
    quality = quality_response.json()
    assert quality == {"dataset_id": dataset_id, **persisted.report["quality"]}
    assert quality["status"] in {"warning", "critical"}
    assert quality["issues"]
    # A report is a persisted snapshot, independent of later filesystem access.
    for path in storage.root.glob("*.csv"):
        path.unlink()
    assert client.get(f"/datasets/{dataset_id}/profile").json() == profile.json()
    assert client.get(f"/datasets/{dataset_id}/quality").json() == quality
    assert db.scalar(select(func.count()).select_from(DatasetProfile)) == 1


@pytest.mark.parametrize("report", ["profile", "quality"])
def test_missing_profile_dataset(client, report):
    assert client.get(f"/datasets/{uuid4()}/{report}").status_code == 404
    assert client.get(f"/datasets/invalid/{report}").status_code == 422


@pytest.mark.parametrize("report", ["profile", "quality"])
def test_legacy_dataset_without_profile_has_clear_error(client, db, upload_dataset, report):
    response = upload_dataset()
    assert response.status_code == 201
    dataset_id = response.json()["id"]
    db.delete(db.get(DatasetProfile, dataset_id))
    db.commit()

    response = client.get(f"/datasets/{dataset_id}/{report}")
    assert response.status_code == 409
    assert "upload" in response.json()["detail"].lower()


def test_profile_computation_failure_leaves_no_dataset(monkeypatch, db, storage, upload_dataset):
    def fail_profile(_frame):
        raise ValueError("private dataframe contents")

    monkeypatch.setattr(ingestion, "profile_dataset", fail_profile)
    response = upload_dataset()
    assert response.status_code == 500
    assert "private dataframe contents" not in response.text
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0
    assert db.scalar(select(func.count()).select_from(DatasetProfile)) == 0
    assert not list(storage.root.glob("*.csv"))


def test_profile_commit_failure_rolls_back_dataset_and_profile(monkeypatch, db, storage, upload_dataset):
    def fail_commit():
        # A successful flush proves that rollback also removes an inserted profile.
        db.flush()
        raise SQLAlchemyError("private database detail")

    monkeypatch.setattr(db, "commit", fail_commit)
    response = upload_dataset()
    assert response.status_code == 500
    assert "private database detail" not in response.text
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0
    assert db.scalar(select(func.count()).select_from(DatasetProfile)) == 0
    assert not list(storage.root.glob("*.csv"))


def test_profile_insert_failure_rolls_back_dataset(monkeypatch, db, storage, upload_dataset):
    original_add = db.add

    def fail_profile_add(instance, *args, **kwargs):
        if isinstance(instance, DatasetProfile):
            raise SQLAlchemyError("profile insert failure")
        return original_add(instance, *args, **kwargs)

    monkeypatch.setattr(db, "add", fail_profile_add)
    response = upload_dataset()
    assert response.status_code == 500
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0
    assert db.scalar(select(func.count()).select_from(DatasetProfile)) == 0
    assert not list(storage.root.glob("*.csv"))
