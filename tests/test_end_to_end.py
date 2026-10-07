from pathlib import Path


DEMO = Path(__file__).resolve().parents[1] / "demo"


def test_full_loan_risk_monitoring_workflow(client):
    model_response = client.post("/models", json={
        "name": "Loan default risk", "model_version": "demo-1",
        "description": "Synthetic interview workflow"})
    assert model_response.status_code == 201
    model_id = model_response.json()["id"]

    datasets = {}
    for filename, dataset_type in [
        ("reference.csv", "reference"),
        ("production_normal.csv", "production"),
        ("production_drifted.csv", "production"),
    ]:
        response = client.post(f"/models/{model_id}/datasets",
                               data={"name": filename.removesuffix(".csv"),
                                     "dataset_type": dataset_type},
                               files={"file": (filename, (DEMO / filename).read_bytes(), "text/csv")})
        assert response.status_code == 201, response.text
        datasets[filename] = response.json()
    assert len(client.get(f"/models/{model_id}/datasets").json()) == 3

    reference_id = datasets["reference.csv"]["id"]
    normal_id = datasets["production_normal.csv"]["id"]
    drifted_id = datasets["production_drifted.csv"]["id"]
    profile = client.get(f"/datasets/{drifted_id}/profile")
    assert profile.status_code == 200
    assert profile.json()["row_count"] == 240
    assert client.get(f"/datasets/{drifted_id}/quality").json()["issues"]

    def monitor(production_id):
        response = client.post("/monitoring/drift", json={
            "reference_dataset_id": reference_id,
            "production_dataset_id": production_id,
            "prediction_column": "prediction", "target_column": "actual"})
        assert response.status_code == 201, response.text
        return response.json()

    normal = monitor(normal_id)
    changed = monitor(drifted_id)
    assert normal["report"]["drifted_feature_count"] == 0
    assert changed["report"]["drifted_feature_count"] >= 3
    assert changed["report"]["performance"]["status"] == "warning"
    assert changed["report"]["performance"]["f1_drop"] > 0.1
    assert changed["report"]["schema_changes"]["missing_columns"] == []
    assert changed["report"]["prediction_drift"]["feature"] == "prediction"
    assert client.get(f"/monitoring/runs/{changed['id']}").json() == changed
    assert len(client.get("/monitoring/runs", params={"model_id": model_id}).json()) == 2
    alert_types = {item["alert_type"] for item in client.get("/alerts", params={"model_id": model_id}).json()}
    assert {"DATA_DRIFT", "DATA_QUALITY", "PERFORMANCE_DEGRADATION"}.issubset(alert_types)
    assert client.get("/dashboard").status_code == 200
