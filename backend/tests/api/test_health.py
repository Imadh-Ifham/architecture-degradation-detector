from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root():
    response = client.get("/")

    assert response.status_code == 200

    data = response.json()

    assert data["message"] == "Architecture Degradation Detector API"
    assert data["environment"] == "development"


def test_postgres_health():
    response = client.get("/health/postgres")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["database"] == 1


def test_neo4j_health():
    response = client.get("/health/neo4j")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["database"] == 1