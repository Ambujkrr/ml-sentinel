"""Exercise the running API with tracked synthetic data, without touching user data."""
import os
from pathlib import Path

import httpx


BASE_URL = os.environ.get("ML_SENTINEL_URL", "http://127.0.0.1:8765")
DEMO = Path(__file__).resolve().parents[1] / "demo"


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        root = client.get("/")
        health = client.get("/health")
        dashboard = client.get("/dashboard")
        assert root.status_code == health.status_code == dashboard.status_code == 200
        assert root.json()["name"] == "ML Sentinel"
        assert health.json()["status"] == "healthy"
        assert "Model health at a glance" in dashboard.text
        assert client.get("/assets/dashboard.js").status_code == 200

        model_response = client.post("/models", json={"name": "Live verification loan risk"})
        model_response.raise_for_status()
        model_id = model_response.json()["id"]
        ids = {}
        for filename, kind in (("reference.csv", "reference"),
                               ("production_normal.csv", "production"),
                               ("production_drifted.csv", "production")):
            response = client.post(f"/models/{model_id}/datasets",
                                   data={"name": filename, "dataset_type": kind},
                                   files={"file": (filename, (DEMO / filename).read_bytes(), "text/csv")})
            response.raise_for_status()
            ids[filename] = response.json()["id"]

        quality = client.get(f"/datasets/{ids['production_drifted.csv']}/quality")
        profile = client.get(f"/datasets/{ids['production_drifted.csv']}/profile")
        quality.raise_for_status()
        profile.raise_for_status()
        assert quality.json()["issues"]
        assert profile.json()["row_count"] == 240

        def monitor(filename: str):
            response = client.post("/monitoring/drift", json={
                "reference_dataset_id": ids["reference.csv"],
                "production_dataset_id": ids[filename],
                "prediction_column": "prediction", "target_column": "actual"})
            response.raise_for_status()
            return response.json()

        normal = monitor("production_normal.csv")
        changed = monitor("production_drifted.csv")
        assert normal["report"]["drifted_feature_count"] == 0
        assert changed["report"]["drifted_feature_count"] >= 3
        assert changed["report"]["performance"]["status"] == "warning"
        assert client.get(f"/monitoring/runs/{changed['id']}").json() == changed
        runs = client.get("/monitoring/runs", params={"model_id": model_id}).json()
        alerts = client.get("/alerts", params={"model_id": model_id}).json()
        assert len(runs) == 2
        assert {"DATA_DRIFT", "DATA_QUALITY", "PERFORMANCE_DEGRADATION"}.issubset(
            {alert["alert_type"] for alert in alerts})
        print({"root": root.status_code, "health": health.status_code,
               "dashboard": dashboard.status_code, "models": 1, "datasets": 3,
               "runs": len(runs), "normal_drifted_features": normal["drifted_feature_count"],
               "shifted_drifted_features": changed["drifted_feature_count"],
               "f1_drop": round(changed["report"]["performance"]["f1_drop"], 3),
               "alerts": len(alerts)})


if __name__ == "__main__":
    main()
