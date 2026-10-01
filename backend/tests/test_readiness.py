from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app


def test_readiness_success_releases_connection_and_engine(monkeypatch):
    engine = MagicMock()
    monkeypatch.setattr("app.main.create_database_engine", lambda settings: engine)

    with TestClient(app) as client:
        engine.connect.assert_not_called()
        response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    connection = engine.connect.return_value.__enter__.return_value
    assert str(connection.execute.call_args.args[0]) == "SELECT 1"
    engine.connect.return_value.__exit__.assert_called_once()
    engine.dispose.assert_called_once()


def test_database_failure_keeps_health_available_and_hides_errors(monkeypatch):
    engine = MagicMock()
    engine.connect.side_effect = OperationalError(None, None, Exception("secret password"))
    monkeypatch.setattr("app.main.create_database_engine", lambda settings: engine)

    with TestClient(app) as client:
        response = client.get("/api/ready")
        health = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "secret" not in response.text
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    engine.dispose.assert_called_once()
