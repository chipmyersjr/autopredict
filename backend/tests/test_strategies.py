from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import inspect, select, event
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.main import app
from app.models import Game, Market, Selection, Strategy
from app.schemas import DecisionRequest, StrategyCreate
from app.seed import demo_games, seed_demo
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


def test_preview_order_precision_skips_and_no_writes(api, monkeypatch):
    client, engine = api
    fixtures = demo_games(date(2026, 10, 1))
    seed_demo(engine, fixtures)
    seed_strategy(engine)
    statements = []
    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement.lstrip().split()[0].upper())
    event.listen(engine, "before_cursor_execute", capture)
    try:
        ids = [str(g.id) for g in reversed(fixtures)]
        response = client.post(PATH, json={"game_ids": ids})
        assert response.status_code == 200
        body = response.json()
        assert body["requested_game_ids"] == ids
        assert [d["game_id"] for d in body["decisions"]] == ids[1:]
        assert body["skipped_games"] == [{"game_id": ids[0], "reason": "spread_unavailable"}]
        assert body["generated_at"].endswith("Z")
        assert statements == ["SELECT"] * 4
        for decision in body["decisions"]:
            assert decision["price"] == "1.9091" and decision["quote_provenance"] is None
            source = next(s for g in fixtures for m in g.markets for s in m.selections if str(s.id) == decision["selection_id"])
            assert Decimal(decision["line"]) == source.line and decision["side"] == source.side
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    with Session(engine) as session:
        for game in session.scalars(select(Game)):
            game.start_time = NOW
        session.commit()
    all_skipped = client.post(PATH, json={"game_ids": ids}).json()
    assert all_skipped["decisions"] == []
    assert all(s["reason"] == "kickoff_reached" for s in all_skipped["skipped_games"])
    # Returned snapshots cannot be rewritten by later database updates.
    assert len(body["decisions"]) == 4
    generator = MagicMock()
    monkeypatch.setattr("app.routes.random_decisions", generator)
    assert client.post(PATH, json={"game_ids": [ids[0], str(uuid4())]}).status_code == 404
    generator.assert_not_called()
    assert engine.pool.checkedout() == 0


def test_preview_errors_and_cors(api):
    client, engine = api
    seed_strategy(engine)
    for ids in [[], ["bad"], [str(uuid4())] * 2]:
        assert client.post(PATH, json={"game_ids": ids}).status_code == 422
    assert client.post(f"/api/strategies/{uuid4()}/decisions", json={"game_ids": [str(uuid4())]}).status_code == 404
    with Session(engine) as session:
        session.get(Strategy, RANDOM_STRATEGY_ID).is_active = False
        session.commit()
    assert client.post(PATH, json={"game_ids": [str(uuid4())]}).status_code == 409
    for origin, status in [("http://localhost:5173", 200), ("https://unapproved.example", 400)]:
        response = client.options(PATH, headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
        assert response.status_code == status
        if status == 200:
            assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/strategies", None),
    ("get", f"/api/strategies/{RANDOM_STRATEGY_ID}", None),
    ("post", "/api/strategies", {"name": "X"}),
    ("post", PATH, {"game_ids": [str(uuid4())]}),
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
