"""Explicit, idempotent baseline loader; never called during app startup."""
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from app.database import create_database_engine
from app.models import User
from app.settings import Settings

LOCAL_USER_ID = UUID("50000000-0000-4000-8000-000000000001")


def seed_user(engine: Engine) -> bool:
    with engine.begin() as connection:
        result = connection.execute(insert(User).values(
            id=LOCAL_USER_ID, name="Local Simulator", email="simulator@autopredict.local",
        ).on_conflict_do_nothing(index_elements=[User.id]).returning(User.id))
        return result.scalar_one_or_none() is not None


def main():
    engine = create_database_engine(Settings())
    try:
        inserted = seed_user(engine)
        print(f"Local User: {'inserted' if inserted else 'already exists; preserved'} ({LOCAL_USER_ID})")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
