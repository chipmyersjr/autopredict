"""Explicit, idempotent baseline loader; never called during app startup."""
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from app.database import create_database_engine
from app.models import Strategy
from app.settings import Settings

RANDOM_STRATEGY_ID = UUID("40000000-0000-4000-8000-000000000001")


def seed_strategy(engine: Engine) -> bool:
    with engine.begin() as connection:
        result = connection.execute(insert(Strategy).values(
            id=RANDOM_STRATEGY_ID, name="Random Strategy", type="random",
            description="Uniform random selection from eligible stored spread selections.",
            is_active=True, config=None,
        ).on_conflict_do_nothing(index_elements=[Strategy.id]).returning(Strategy.id))
        return result.scalar_one_or_none() is not None


def main():
    engine = create_database_engine(Settings())
    try:
        inserted = seed_strategy(engine)
        print(f"Random Strategy: {'inserted' if inserted else 'already exists; preserved'} ({RANDOM_STRATEGY_ID})")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
