from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.main import app
from app.settings import Settings


@pytest.mark.parametrize("origin", ["http://127.0.0.1:5173", "http://localhost:5173"])
def test_allowed_origin_and_preflight(origin):
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"Origin": origin})
        assert response.headers["access-control-allow-origin"] == origin
        assert "access-control-allow-credentials" not in response.headers
        preflight = client.options("/api/games", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == origin


def test_disallowed_origin():
    with TestClient(app) as client:
        origin = "https://unapproved.example"
        response = client.get("/api/health", headers={"Origin": origin})
        assert "access-control-allow-origin" not in response.headers
        preflight = client.options("/api/games", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert preflight.status_code == 400
        assert "access-control-allow-origin" not in preflight.headers


def test_origins_from_root_env(tmp_path, monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    env = tmp_path / ".env"
    env.write_text('CORS_ORIGINS=["http://localhost:5174"]\n')
    assert Settings(_env_file=env).cors_origins == ["http://localhost:5174"]
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:5175"]')
    assert Settings(_env_file=env).cors_origins == ["http://localhost:5175"]


@pytest.mark.parametrize("origin", ["*", "http://localhost:5173/path", "https://user:pass@example.com", "https://*.example.com"])
def test_reject_non_origin_configuration(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=[origin])
