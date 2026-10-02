"""PostgreSQL integration fixtures only touch generated disposable databases."""
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.database import create_database_engine
from app.settings import Settings


@pytest.fixture
def migrated_database(monkeypatch):
    if os.environ.get("RUN_POSTGRES_TESTS") != "1":
        pytest.skip("Set RUN_POSTGRES_TESTS=1 for disposable PostgreSQL integration tests")
    settings = Settings()
    database = "autopredict_test_" + uuid4().hex
    admin = create_engine(settings.database_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    engine = None
    try:
        monkeypatch.setenv("POSTGRES_DB", database)
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
        engine = create_database_engine(Settings())
        yield engine, config
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        admin.dispose()

