from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.models import Game, Market, Selection
from app.seed import demo_games, seed_demo, validate_fixtures


def test_demo_validation():
    games = demo_games(date(2026, 10, 1))
    validate_fixtures(games)
    assert len(games) == 5
    assert sum(len(g.markets) for g in games) == 4
    assert sum(len(m.selections) for g in games for m in g.markets) == 8
    assert games[2].markets[0].selections[0].line == 0
    assert games[4].markets == []
    games[0].markets[0].selections[0].line = Decimal("3.50")
    with pytest.raises(ValueError, match="opposite"):
        validate_fixtures(games)


@pytest.mark.parametrize("bad_price", ["1", "NaN", "Infinity", "1.12345"])
def test_invalid_demo_price(bad_price):
    games = demo_games(date(2026, 10, 1))
    games[0].markets[0].selections[0].price = Decimal(bad_price)
    with pytest.raises(ValueError, match="price"):
        validate_fixtures(games)


def test_seed_preserves_existing_and_different_anchor(migrated_database):
    engine, _ = migrated_database
    anchor = date(2026, 10, 1)
    assert seed_demo(engine, demo_games(anchor)) == 5
    with Session(engine) as session:
        game = session.scalar(select(Game).order_by(Game.start_time))
        game.notes = "Keep this edit"
        kickoff = game.start_time
        game_id = game.id
        selection = session.scalar(select(Selection))
        selection.is_active = False
        selection_id = selection.id
        session.commit()
    assert seed_demo(engine, demo_games(anchor)) == 0
    assert seed_demo(engine, demo_games(date(2030, 1, 1))) == 0
    with Session(engine) as session:
        assert session.get(Game, game_id).notes == "Keep this edit"
        assert session.get(Game, game_id).start_time == kickoff
        assert session.get(Selection, selection_id).is_active is False
        for model, count in ((Game, 5), (Market, 4), (Selection, 8)):
            assert session.scalar(select(func.count()).select_from(model)) == count


def test_seed_atomic_on_validation_and_database_failure(migrated_database):
    engine, _ = migrated_database
    games = demo_games(date(2026, 10, 1))
    games[-2].markets[0].selections[0].side = "Wrong team"
    with pytest.raises(ValueError, match="matching teams"):
        seed_demo(engine, games)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Game)) == 0
    games = demo_games(date(2026, 10, 1))
    games[-1].home_team = "x" * 256  # Database error after the prior graphs were inserted.
    with pytest.raises(DataError):
        seed_demo(engine, games)
    with Session(engine) as session:
        for model in (Game, Market, Selection):
            assert session.scalar(select(func.count()).select_from(model)) == 0
