from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.main import app
from app.models import Game, Market, Selection, Strategy
from app.schemas import DecisionRequest, StrategyCreate
from app.seed import demo_games
from app.seed_strategy import RANDOM_STRATEGY_ID, seed_strategy
from app.strategies import resolve_candidates, random_decisions

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
PATH = f"/api/strategies/{RANDOM_STRATEGY_ID}/decisions"


def game_fixture():
    game = demo_games(date(2026, 10, 1))[0]
    game.start_time = NOW + timedelta(days=1)
    return game


class Pick:
    def __init__(self, index):
        self.index = index

    def choice(self, values):
        return values[self.index]


def test_engine_both_sides_zero_line_and_copied_snapshot():
    game = game_fixture()
    for s in game.markets[0].selections:
        s.line = Decimal("0.00")
    candidates, skip = resolve_candidates(game, NOW)
    assert skip is None and len(candidates) == 2
    assert candidates == sorted(candidates, key=lambda c: (c.market_id, c.selection_id))
    first = random_decisions([candidates, []], Pick(0))[0]
    last = random_decisions([candidates], Pick(-1))[0]
    assert first.selection_id != last.selection_id
    assert first.line == last.line == 0
    assert first.price == Decimal("1.9091")
    assert first.quote_provenance is None
    game.markets[0].selections[0].price = Decimal("2.1")
    assert first.price == last.price == Decimal("1.9091")
    with pytest.raises(ValidationError):
        first.price = Decimal("3")
    assert random_decisions([[], []], Pick(0)) == []


@pytest.mark.parametrize("change,reason", [
    (lambda g: setattr(g, "status", "in_progress"), "game_not_scheduled"),
    (lambda g: setattr(g, "status", "completed"), "game_not_scheduled"),
    (lambda g: setattr(g, "status", "canceled"), "game_not_scheduled"),
    (lambda g: setattr(g, "start_time", NOW), "kickoff_reached"),
    (lambda g: setattr(g, "start_time", NOW - timedelta(seconds=1)), "kickoff_reached"),
    (lambda g: setattr(g, "start_time", None), "spread_unavailable"),
    (lambda g: setattr(g.markets[0], "status", "closed"), "spread_unavailable"),
    (lambda g: setattr(g.markets[0].selections[0], "is_active", False), "spread_unavailable"),
    (lambda g: setattr(g.markets[0].selections[0], "line", None), "spread_unavailable"),
    (lambda g: setattr(g.markets[0].selections[0], "line", Decimal("NaN")), "spread_unavailable"),
    (lambda g: setattr(g.markets[0].selections[0], "price", Decimal("Infinity")), "spread_unavailable"),
    (lambda g: setattr(g.markets[0].selections[0], "price", Decimal("1")), "spread_unavailable"),
    (lambda g: setattr(g.markets[0].selections[0], "side", "Wrong team"), "spread_unavailable"),
    (lambda g: setattr(g.markets[0].selections[0], "line", Decimal("99")), "spread_unavailable"),
])
def test_eligibility_guards(change, reason):
    game = game_fixture()
    change(game)
    candidates, skip = resolve_candidates(game, NOW)
    assert candidates == [] and skip.reason == reason


def test_multiple_markets_and_just_before_kickoff():
    game = game_fixture()
    game.start_time = NOW + timedelta(microseconds=1)
    market = Market(id=uuid4(), type="spread", status="active")
    market.selections = [Selection(id=uuid4(), side=side, line=Decimal("0"), price=Decimal("2"), is_active=True) for side in (game.home_team, game.away_team)]
    game.markets.append(market)
    candidates, skip = resolve_candidates(game, NOW)
    assert skip is None and len(candidates) == 4
    assert len(random_decisions([candidates, candidates], Pick(-1))) == 2


@pytest.mark.parametrize("positional", [False, True])
def test_persisted_quote_matches_both_selection_side_representations(positional):
    game = game_fixture()
    pair = game.markets[0].selections
    if positional:
        pair[0].side, pair[1].side = "home", "away"
    quote = MagicMock(
        id=uuid4(), bookmaker="alpha", source_timestamp=NOW, fetched_at=NOW,
        home_line=pair[0].line, home_price=pair[0].price,
        away_line=pair[1].line, away_price=pair[1].price,
    )
    session = MagicMock()
    session.scalar.return_value = quote
    candidates, skip = resolve_candidates(game, NOW, session)
    assert skip is None and len(candidates) == 2
    assert all(c.quote_provenance.observation_id == quote.id for c in candidates)
    assert {c.side for c in candidates} == {s.side for s in pair}
    quote.home_line += Decimal("1")
    candidates, skip = resolve_candidates(game, NOW, session)
    assert candidates == [] and skip.reason == "spread_unavailable"


@pytest.mark.parametrize("body", [{"game_ids": []}, {"game_ids": [str(RANDOM_STRATEGY_ID)] * 2}, {"game_ids": ["bad"]}, {"game_ids": [str(RANDOM_STRATEGY_ID)], "stake": 10}])
def test_invalid_decision_input(body):
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(body)


@pytest.mark.parametrize("body", [{"name": " "}, {"name": "X", "type": "ml"}, {"name": "X", "config": {"seed": 1}}, {"name": "X", "user_id": str(uuid4())}])
def test_invalid_strategy_input(body):
    with pytest.raises(ValidationError):
        StrategyCreate.model_validate(body)


@pytest.fixture
def api(migrated_database, monkeypatch):
    engine, _ = migrated_database
    monkeypatch.setattr("app.main.create_database_engine", lambda settings: engine)
    monkeypatch.setattr("app.routes.utc_now", lambda: NOW)
    with TestClient(app) as client:
        yield client, engine


def test_strategy_bootstrap_create_and_constraints(api):
    client, engine = api
    assert client.get("/api/strategies").json() == []
    assert seed_strategy(engine)
    assert not seed_strategy(engine)
    baseline = client.get(f"/api/strategies/{RANDOM_STRATEGY_ID}").json()
    assert baseline["name"] == "Random Strategy" and baseline["config"] is None
    assert "user_id" not in baseline
    assert baseline["created_at"].endswith("+00:00")
    for config in [None, {}]:
        response = client.post("/api/strategies", json={"name": " Shared ", "config": config})
        assert response.status_code == 201
        assert response.json()["name"] == "Shared" and response.json()["config"] == config
    rows = client.get("/api/strategies").json()
    assert len(rows) == 3 and rows == sorted(rows, key=lambda s: s["id"])
    assert client.get(f"/api/strategies/{uuid4()}").status_code == 404
    assert client.get("/api/strategies/bad").status_code == 422
    for body in [{"name": " "}, {"name": "X", "type": "ai"}, {"name": "X", "config": {"x": 1}}, {"name": "X", "user_id": str(uuid4())}]:
        assert client.post("/api/strategies", json=body).status_code == 422
    assert not inspect(engine).get_foreign_keys("strategies")
    assert "user_id" not in {c["name"] for c in inspect(engine).get_columns("strategies")}
    with Session(engine) as session:
        baseline = session.get(Strategy, RANDOM_STRATEGY_ID)
        baseline.name = "Edited baseline"
        baseline.is_active = False
        session.commit()
    assert not seed_strategy(engine)
    with Session(engine) as session:
        baseline = session.get(Strategy, RANDOM_STRATEGY_ID)
        assert baseline.name == "Edited baseline" and not baseline.is_active
        for name, kind, config in [(" ", "random", None), ("X", "ml", None), ("X", "random", {"x": 1})]:
            session.add(Strategy(name=name, type=kind, config=config))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()


def test_preview_retired_without_database_or_prediction(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Retired preview must not access the database")
    monkeypatch.setattr("app.database.Session", forbidden)
    monkeypatch.setattr("app.main.create_database_engine", lambda settings: MagicMock())
    with TestClient(app) as client:
        for strategy_id in [RANDOM_STRATEGY_ID, uuid4()]:
            for body in [None, {}, {"game_ids": ["bad"]}]:
                response = client.post(f"/api/strategies/{strategy_id}/decisions", json=body)
                assert response.status_code == 410
                assert "POST /api/runs" in response.json()["detail"]
        schema = client.get("/openapi.json").json()
        operation = schema["paths"]["/api/strategies/{strategy_id}/decisions"]["post"]
        assert operation["deprecated"] and "410" in operation["responses"]
        for origin, status in [("http://localhost:5173", 200), ("https://unapproved.example", 400)]:
            response = client.options(PATH, headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                                     "Access-Control-Request-Headers": "content-type"})
            assert response.status_code == status


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/strategies", None),
    ("get", f"/api/strategies/{RANDOM_STRATEGY_ID}", None),
    ("post", "/api/strategies", {"name": "X"}),
    ("get", f"/api/runs/{uuid4()}/execution", None),
])
def test_database_errors_are_safe(monkeypatch, method, path, body):
    session = MagicMock()
    error = OperationalError(None, None, Exception("secret credentials"))
    session.scalars.side_effect = error
    session.get.side_effect = error
    session.commit.side_effect = error
    context = MagicMock()
    context.__enter__.return_value = session
    monkeypatch.setattr("app.database.Session", lambda engine: context)
    monkeypatch.setattr("app.main.create_database_engine", lambda settings: MagicMock())
    with TestClient(app) as client:
        response = client.request(method, path, json=body)
        assert response.status_code == 503 and response.json() == {"detail": "Database unavailable"}
        assert "secret" not in response.text
    session.rollback.assert_called_once()
    context.__exit__.assert_called_once()
