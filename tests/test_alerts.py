from uuid import uuid4

from sqlalchemy import func, select

from app.models.domain import Alert, MonitoringRun


def csv_data(shift: int = 0, missing_column: bool = False, reverse_labels: bool = False) -> bytes:
    header = "score,prediction,actual" if not missing_column else "score,prediction,actual,extra"
    rows = [header]
    for i in range(60):
        prediction = i % 2
        actual = 1 - prediction if reverse_labels else prediction
        row = f"{i + shift},{prediction},{actual}"
        rows.append(row if not missing_column else f"{row},new")
    return ("\n".join(rows) + "\n").encode()


def test_calculated_alerts_and_resolve(client, upload_dataset, registered_model, db):
    ref = upload_dataset(csv_data(), dataset_type="reference").json()
    prod = upload_dataset(csv_data(shift=200, missing_column=True, reverse_labels=True),
                          dataset_type="production").json()
    response = client.post("/monitoring/drift", json={
        "reference_dataset_id": ref["id"], "production_dataset_id": prod["id"],
        "prediction_column": "prediction", "target_column": "actual"})
    assert response.status_code == 201, response.text
    alerts = client.get("/alerts", params={"model_id": registered_model["id"], "unresolved": True}).json()
    types = {item["alert_type"] for item in alerts}
    assert "DATA_DRIFT" in types
    assert "SCHEMA_DRIFT" in types
    assert "PERFORMANCE_DEGRADATION" in types
    assert all(item["monitoring_run_id"] == response.json()["id"] for item in alerts)
    first = alerts[0]
    resolved = client.patch(f"/alerts/{first['id']}/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None
    assert len(client.get("/alerts", params={"unresolved": True}).json()) == len(alerts) - 1
    assert client.get("/alerts", params={"model_id": str(uuid4())}).json() == []
    assert client.patch(f"/alerts/{uuid4()}/resolve").status_code == 404


def test_healthy_run_has_no_result_alerts(client, upload_dataset, db):
    ref = upload_dataset(csv_data(), dataset_type="reference").json()
    prod = upload_dataset(csv_data(), dataset_type="production").json()
    response = client.post("/monitoring/drift", json={
        "reference_dataset_id": ref["id"], "production_dataset_id": prod["id"]})
    assert response.status_code == 201
    assert response.json()["overall_status"] == "healthy"
    assert client.get("/alerts").json() == []
    assert db.scalar(select(func.count()).select_from(MonitoringRun)) == 1
    assert db.scalar(select(func.count()).select_from(Alert)) == 0
