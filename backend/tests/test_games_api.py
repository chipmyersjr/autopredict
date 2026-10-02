from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.main import app
from app.models import Game, Market, Selection
from app.seed import demo_games, seed_demo


@pytest.fixture
def api(migrated_database, monkeypatch):
    engine, _ = migrated_database
    monkeypatch.setattr("app.main.create_database_engine", lambda settings: engine)
    with TestClient(app) as client:
        yield client, engine


def test_empty_and_nested_game_contract(api):
    client, engine = api
    assert client.get("/api/games").json() == []
    fixtures = demo_games(date(2026, 10, 1))
    seed_demo(engine, fixtures)
    response = client.get("/api/games")
    assert response.status_code == 200
    games = response.json()
    assert len(games) == 5
    assert [(g["start_time"], g["id"]) for g in games] == sorted((g["start_time"], g["id"]) for g in games)
    assert set(games[0]) == {"id", "season", "week", "home_team", "away_team", "start_time", "status", "home_score", "away_score", "venue", "notes", "created_at", "updated_at", "markets"}
    for game in games:
        assert client.get(f'/api/games/{game["id"]}').json() == game
        assert game["home_score"] is None and game["away_score"] is None
        assert "Demo data" in game["notes"]
        for field in ("start_time", "created_at", "updated_at"):
            assert game[field].endswith("+00:00")
        assert game["markets"] == sorted(game["markets"], key=lambda m: m["id"])
        for market in game["markets"]:
            assert market["game_id"] == game["id"]
            assert len(market["selections"]) == 2
            pair = market["selections"]
            assert pair == sorted(pair, key=lambda s: s["id"])
            assert {s["side"] for s in pair} == {game["home_team"], game["away_team"]}
            assert sum(Decimal(s["line"]) for s in pair) == 0
            for selection in pair:
                assert selection["price"] == "1.9091"
                assert isinstance(selection["line"], str)
                assert selection["market_id"] == market["id"]
                assert selection["is_active"] is True
    assert games[-1]["markets"] == []
    assert any(s["line"] == "0.00" for g in games for m in g["markets"] for s in m["selections"])
    assert engine.pool.checkedout() == 0
    docs = client.get("/openapi.json").json()
    assert "GameResponse" in docs["components"]["schemas"]


def test_market_contract_and_stored_inactive_records(api):
    client, engine = api
    seed_demo(engine, demo_games(date(2026, 10, 1)))
    with Session(engine) as session:
        selection = session.scalar(select(Selection).order_by(Selection.id))
        selection.is_active = False
        selection.line = None
        selection.market.status = "closed"
        selection.market.game.status = "completed"
        selection.market.game.home_score = 31
        selection.market.game.away_score = 24
        session.commit()
    games = client.get("/api/games").json()
    found_inactive = False
    for game in games:
        response = client.get(f'/api/games/{game["id"]}/markets')
        assert response.status_code == 200
        assert response.json() == game["markets"]
        for market in game["markets"]:
            detail = client.get(f'/api/markets/{market["id"]}')
            assert detail.status_code == 200
            assert detail.json() == market
            if market["status"] == "closed":
                assert game["status"] == "completed" and game["home_score"] == 31
                inactive = next(s for s in market["selections"] if not s["is_active"])
                assert inactive["line"] is None
                found_inactive = True
    assert found_inactive
    assert engine.pool.checkedout() == 0


@pytest.mark.parametrize("path,detail", [
    ("/api/games/{id}", "Game not found"),
    ("/api/games/{id}/markets", "Game not found"),
    ("/api/markets/{id}", "Market not found"),
])
def test_missing_and_malformed_ids_release_sessions(api, path, detail):
    client, engine = api
    response = client.get(path.format(id=uuid4()))
    assert response.status_code == 404
    assert response.json() == {"detail": detail}
    assert client.get(path.format(id="bad-id")).status_code == 422
    assert engine.pool.checkedout() == 0


def test_list_queries_do_not_grow_per_game_and_ties_are_stable(api):
    client, engine = api
    fixtures = demo_games(date(2026, 10, 1))
    seed_demo(engine, fixtures)
    statements = []
    def count_query(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(engine, "before_cursor_execute", count_query)
    try:
        assert client.get("/api/games").status_code == 200
        assert len(statements) == 3
        with Session(engine) as session:
            for index in range(20):
                game = Game(season=2026, week=5, home_team=f"Demo {index}", away_team="Demo opponent", start_time=fixtures[0].start_time, status="scheduled")
                market = Market(type="spread", status="active")
                market.selections.append(Selection(side=game.home_team, line=Decimal("0"), price=Decimal("1.9")))
                game.markets.append(market)
                session.add(game)
            session.commit()
        statements.clear()
        games = client.get("/api/games").json()
        assert len(games) == 25
        assert len(statements) == 3
        assert [(g["start_time"], g["id"]) for g in games] == sorted((g["start_time"], g["id"]) for g in games)
    finally:
        event.remove(engine, "before_cursor_execute", count_query)


@pytest.mark.parametrize("path", ["/api/games", f"/api/games/{uuid4()}", f"/api/games/{uuid4()}/markets", f"/api/markets/{uuid4()}"])
def test_database_failure_is_sanitized_and_session_rolls_back_and_closes(monkeypatch, path):
    session = MagicMock()
    session.scalar.side_effect = OperationalError(None, None, Exception("secret credentials"))
    session.scalars.side_effect = OperationalError(None, None, Exception("secret credentials"))
    context = MagicMock()
    context.__enter__.return_value = session
    monkeypatch.setattr("app.database.Session", lambda engine: context)
    engine = MagicMock()
    monkeypatch.setattr("app.main.create_database_engine", lambda settings: engine)
    with TestClient(app) as client:
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
        assert "secret" not in response.text
        assert client.get("/api/health").status_code == 200
    session.rollback.assert_called_once()
    context.__exit__.assert_called_once()
    engine.dispose.assert_called_once()
