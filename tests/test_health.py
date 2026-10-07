from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app

client = TestClient(app)


def test_root_endpoint() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"name": "ML Sentinel", "status": "running"}


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "ml-sentinel"}


def test_health_endpoint_reports_unavailable_database(client: TestClient, db, monkeypatch) -> None:
    def unavailable(*_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, RuntimeError("database offline"))

    monkeypatch.setattr(db, "execute", unavailable)
    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
