"""Lazy SQLAlchemy connectivity; no domain schema is created here."""

from sqlalchemy import Engine, create_engine, text

from app.settings import Settings


def create_database_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_timeout=settings.db_connect_timeout,
        connect_args={
            "connect_timeout": settings.db_connect_timeout,
            "options": "-c statement_timeout=3000",
        },
    )


def check_database(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
