from pathlib import Path

import pytest
from pydantic import ValidationError

from app.settings import ROOT_ENV, Settings


def test_root_env_path():
    assert ROOT_ENV == Path(__file__).resolve().parents[2] / ".env"


def test_settings_load_file_and_environment_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("POSTGRES_PORT=5433\nPOSTGRES_PASSWORD=a@b:c\nUNRELATED=value\n")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    settings = Settings(_env_file=env_file)
    assert settings.postgres_port == 5433
    assert settings.postgres_host == "localhost"
    assert settings.database_url.password == "a@b:c"
    assert "a@b:c" not in repr(settings)


def test_settings_reject_invalid_port():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, postgres_port=70000)
