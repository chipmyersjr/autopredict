"""Opt-in PostgreSQL checks; only generated disposable databases are migrated."""
import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Game, Market, Selection

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_POSTGRES_TESTS") != "1",
    reason="Set RUN_POSTGRES_TESTS=1 to create and test a disposable PostgreSQL database",
)


def test_schema_and_migration_cycle(migrated_database):
    engine, config = migrated_database
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {"alembic_version", "games", "markets", "selections"}
    for table in ("games", "markets", "selections"):
        columns = {c["name"]: c for c in inspector.get_columns(table)}
        assert str(columns["id"]["type"]) == "UUID"
        assert inspector.get_pk_constraint(table)["constrained_columns"] == ["id"]
        for name in ("created_at", "updated_at"):
            assert columns[name]["type"].timezone
            assert not columns[name]["nullable"]
    selection_columns = {c["name"]: c for c in inspector.get_columns("selections")}
    assert (selection_columns["line"]["type"].precision, selection_columns["line"]["type"].scale) == (10, 2)
    assert (selection_columns["price"]["type"].precision, selection_columns["price"]["type"].scale) == (10, 4)
    assert selection_columns["line"]["nullable"]
    assert {c["name"]: c for c in inspector.get_columns("games")}["start_time"]["type"].timezone is True
    for table, column, parent in (("markets", "game_id", "games"), ("selections", "market_id", "markets")):
        foreign_key, = inspector.get_foreign_keys(table)
        assert foreign_key["constrained_columns"] == [column]
        assert foreign_key["referred_table"] == parent
        assert any(index["column_names"] == [column] for index in inspector.get_indexes(table))
    assert any(index["column_names"] == ["start_time"] for index in inspector.get_indexes("games"))
    command.check(config)
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    command.check(config)
    assert set(inspect(engine).get_table_names()) == {"alembic_version", "games", "markets", "selections"}


def test_relationships_values_and_constraints(migrated_database):
    engine, _ = migrated_database
    with Session(engine) as session:
        game = Game(season=2026, week=5, home_team="USC", away_team="UCLA", start_time=datetime.now(timezone.utc), status="scheduled")
        market = Market(type="spread", status="active")
        selection = Selection(side="USC", line=Decimal("-3.50"), price=Decimal("1.9091"))
        market.selections.append(selection)
        game.markets.extend([market, Market(type="spread", status="closed")])
        session.add(game)
        session.commit()
        session.expire_all()
        stored = session.scalar(select(Game))
        assert len(stored.markets) == 2  # Multiple markets per game remain valid.
        assert selection.market.game is stored
        assert selection.line == Decimal("-3.50")
        assert selection.price == Decimal("1.9091")
        assert selection.is_active is True
        assert stored.home_score is None and stored.away_score is None
        assert stored.start_time.utcoffset().total_seconds() == 0
        assert stored.created_at.tzinfo is not None
        before = stored.updated_at
        stored.notes = "updated"
        session.commit()
        assert stored.updated_at > before
        selection.line = None
        session.commit()
        assert selection.line is None
        for invalid in (
            Market(game_id=uuid4(), type="spread", status="active"),
            Selection(market_id=uuid4(), side="USC", price=Decimal("1.9091")),
        ):
            session.add(invalid)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
        for obj, field, value in (
            (stored, "home_score", -1), (stored, "away_score", -1),
            (stored, "status", "unknown"), (market, "status", "unknown"),
            (market, "type", "moneyline"), (selection, "price", Decimal("1")),
        ):
            setattr(obj, field, value)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
