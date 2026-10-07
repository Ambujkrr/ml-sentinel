def score_csv(reverse: bool = False, labels: bool = True) -> bytes:
    lines = ["score,prediction" + (",actual" if labels else "")]
    for i in range(60):
        prediction = i % 2
        actual = 1 - prediction if reverse else prediction
        lines.append(f"{i},{prediction}" + (f",{actual}" if labels else ""))
    return ("\n".join(lines) + "\n").encode()


def test_prediction_and_performance_reports_use_uploaded_rows(client, upload_dataset):
    ref = upload_dataset(score_csv(), dataset_type="reference").json()
    prod = upload_dataset(score_csv(reverse=True), dataset_type="production").json()
    response = client.post("/monitoring/drift", json={
        "reference_dataset_id": ref["id"], "production_dataset_id": prod["id"],
        "prediction_column": "prediction", "target_column": "actual"})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["prediction_column"] == "prediction"
    assert run["report"]["prediction_drift"]["drift_detected"] is False
    assert run["report"]["performance"]["f1_drop"] == 1.0
    assert run["report"]["performance"]["status"] == "warning"
    assert run["overall_status"] in {"warning", "critical"}
    assert client.get(f"/monitoring/runs/{run['id']}").json() == run


def test_prediction_without_labels_and_invalid_columns(client, upload_dataset):
    ref = upload_dataset(score_csv(labels=False), dataset_type="reference").json()
    prod = upload_dataset(score_csv(labels=False), dataset_type="production").json()
    payload = {"reference_dataset_id": ref["id"], "production_dataset_id": prod["id"]}
    response = client.post("/monitoring/drift", json={**payload, "prediction_column": "prediction",
                                                   "target_column": "actual"})
    assert response.status_code == 201
    assert response.json()["report"]["performance"]["status"] == "unavailable"
    assert client.post("/monitoring/drift", json={**payload, "prediction_column": "missing"}).status_code == 400
    assert client.post("/monitoring/drift", json={**payload, "target_column": "actual"}).status_code == 422
