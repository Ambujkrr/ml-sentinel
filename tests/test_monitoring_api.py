from uuid import uuid4

import numpy as np
from sqlalchemy import func, select

from app.models.domain import MonitoringRun


def csv_scores(start: int = 0) -> bytes:
    rows = ["score,segment"]
    for score in np.linspace(start, start + 99, 100):
        rows.append(f"{score:.3f},{'a' if int(score) % 2 else 'b'}")
    return ("\n".join(rows) + "\n").encode()


def test_drift_run_is_calculated_and_persisted(client, upload_dataset, registered_model, db):
    ref = upload_dataset(csv_scores(), dataset_type="reference").json()
    normal = upload_dataset(csv_scores(), dataset_type="production").json()
    drifted = upload_dataset(csv_scores(200), dataset_type="production").json()
    payload = {"reference_dataset_id": ref["id"], "production_dataset_id": normal["id"]}
    baseline = client.post("/monitoring/drift", json=payload)
    assert baseline.status_code == 201, baseline.text
    assert baseline.json()["overall_status"] == "healthy"
    assert baseline.json()["report"]["features"][0]["p_value"] == 1.0
    payload["production_dataset_id"] = drifted["id"]
    shifted = client.post("/monitoring/drift", json=payload)
    assert shifted.status_code == 201, shifted.text
    assert shifted.json()["drifted_feature_count"] >= 1
    assert shifted.json()["overall_status"] in {"warning", "critical"}
    assert shifted.json()["model_id"] == registered_model["id"]
    assert client.get(f"/monitoring/runs/{shifted.json()['id']}").json() == shifted.json()
    listed = client.get("/monitoring/runs", params={"model_id": registered_model["id"]}).json()
    assert len(listed) == 2
    assert "report" not in listed[0]
    assert db.scalar(select(func.count()).select_from(MonitoringRun)) == 2


def test_run_validation_and_missing_file(client, upload_dataset, registered_model, storage, db):
    ref = upload_dataset(csv_scores(), dataset_type="reference").json()
    prod = upload_dataset(csv_scores(), dataset_type="production").json()
    payload = {"reference_dataset_id": ref["id"], "production_dataset_id": prod["id"]}
    assert client.post("/monitoring/drift", json={**payload, "reference_dataset_id": prod["id"]}).status_code == 400
    assert client.post("/monitoring/drift", json={**payload, "production_dataset_id": ref["id"]}).status_code == 400
    assert client.post("/monitoring/drift", json={**payload, "production_dataset_id": str(uuid4())}).status_code == 404
    assert client.post("/monitoring/drift", json={**payload, "production_dataset_id": "bad"}).status_code == 422
    assert client.get(f"/monitoring/runs/{uuid4()}").status_code == 404
    for path in storage.root.glob("*.csv"):
        path.unlink()
    assert client.post("/monitoring/drift", json=payload).status_code == 409
    assert db.scalar(select(func.count()).select_from(MonitoringRun)) == 0
