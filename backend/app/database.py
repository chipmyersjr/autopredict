"""Lazy SQLAlchemy connectivity; no domain schema is created here."""

from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.settings import Settings


def create_database_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_timeout=settings.db_connect_timeout,
        connect_args={
            "connect_timeout": settings.db_connect_timeout,
            "options": "-c statement_timeout=3000 -c timezone=UTC",
        },
    )


def check_database(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def get_session(request: Request) -> Iterator[Session]:
    """One session per request; roll back on errors and always release resources."""
    with Session(request.app.state.database_engine) as session:
        try:
            yield session
        except SQLAlchemyError:
            session.rollback()
            raise HTTPException(status_code=503, detail="Database unavailable") from None
        except Exception:
            session.rollback()
            raise
