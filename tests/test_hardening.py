from uuid import uuid4

from app.core.config import get_settings


def test_upload_limit_can_reject_large_declared_body(client, registered_model, monkeypatch):
    monkeypatch.setattr(get_settings(), "MAX_UPLOAD_BYTES", 1024)
    response = client.post(f"/models/{registered_model['id']}/datasets",
                           headers={"content-length": "99999999"},
                           data={"name": "Too large", "dataset_type": "reference"},
                           files={"file": ("data.csv", b"x\n1\n", "text/csv")})
    assert response.status_code == 413


def test_bad_ids_and_missing_records_return_clean_errors(client):
    assert client.get("/models/not-uuid").status_code == 422
    assert client.get(f"/models/{uuid4()}").json() == {"detail": "Monitored model not found"}
    assert client.get(f"/datasets/{uuid4()}").json() == {"detail": "Dataset not found"}
    assert client.get(f"/monitoring/runs/{uuid4()}").json() == {"detail": "Monitoring run not found"}
    assert client.get("/alerts?model_id=bad").status_code == 422
