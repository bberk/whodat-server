from fastapi.testclient import TestClient

from app.api.main import create_app


def test_health_returns_ok() -> None:
    """The hello/liveness endpoint responds 200 with a JSON status."""
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
