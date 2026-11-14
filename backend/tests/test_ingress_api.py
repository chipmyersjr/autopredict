"""HTTP ingress contracts using fake providers and disposable PostgreSQL only."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models import Game, QuoteObservation, Selection
from app.refresh import RefreshService
from app.settings import Settings
from test_refresh import handler_for


@pytest.fixture
def api(migrated_database, monkeypatch):
    engine, _ = migrated_database
    clock = [datetime(2026, 11, 14, 18, tzinfo=UTC)]
    requests = []
    handler = [handler_for("success", requests)]
    monkeypatch.setattr("app.main.create_database_engine", lambda settings: engine)
    monkeypatch.setattr("app.routes.utc_now", lambda: clock[0])
    monkeypatch.setattr("app.routes.RefreshService", lambda engine, settings: RefreshService(
        engine, Settings(_env_file=None, cfbd_api_key="fake", odds_api_key="fake"),
        clock=lambda: clock[0], transport=httpx.MockTransport(lambda request: handler[0](request))))
    with TestClient(app) as client:
        yield client, engine, clock, requests, handler


@pytest.mark.parametrize("kind,reason,changed", [
    ("success", "refreshed", True), ("empty", "no_games", False),
    ("error", "partial_failure", True), ("invalid", "partial_failure", True),
])
def test_refresh_http_outcomes(api, kind, reason, changed):
    client, engine, clock, requests, handler = api
    handler[0] = handler_for(kind, requests)
    response = client.post("/api/games/refresh")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"success", "reason", "message", "remaining_refreshes",
                         "reserved_for_sunday", "retry_at", "data_changed", "run_id"}
    assert body["reason"] == reason
    assert body["success"] == (kind in {"success", "empty"})
    assert body["data_changed"] == changed
    assert body["remaining_refreshes"] == 19 and body["reserved_for_sunday"] == 2
    assert "private-key-material" not in response.text
    before = len(requests)
    assert len(client.get("/api/games?window=current").json()) == int(changed)
    assert len(requests) == before
    limited = client.post("/api/games/refresh")
    assert limited.status_code == 429 and limited.json()["reason"] == "cooldown"
    assert len(requests) == before


def test_refresh_input_and_openapi(api):
    client, _, _, requests, _ = api
    for kwargs in ({"json": {"week": 1}}, {"params": {"week": 1}},
                   {"content": "{", "headers": {"Content-Type": "application/json"}}):
        response = client.post("/api/games/refresh", **kwargs)
        assert response.status_code == 422
        assert response.json()["success"] is False
        assert response.json()["data_changed"] is False
    assert not requests
    assert client.get("/api/games?window=other").status_code == 422
    docs = client.get("/openapi.json").json()
    contract = docs["paths"]["/api/games/refresh"]["post"]["responses"]
    for code in ("200", "409", "429", "503", "422"):
        assert contract[code]["content"]["application/json"]["schema"]["$ref"].endswith("/RefreshResponse")


@pytest.mark.parametrize("sunday", [False, True])
def test_missing_keys_http_handoff_spends_nothing(api, monkeypatch, sunday):
    """Automated HTTP contract only; CHIP's deployed HTTP smoke stays pending."""
    from uuid import UUID
    from sqlalchemy import func
    from app.models import ProviderCallReservation, RefreshRun, WeeklyRefreshBucket

    client, engine, clock, requests, _ = api
    if sunday:
        clock[0] += timedelta(days=1)
    monkeypatch.setattr("app.routes.RefreshService", lambda engine, settings: RefreshService(
        engine, Settings(_env_file=None, cfbd_api_key="", odds_api_key=""),
        clock=lambda: clock[0], transport=httpx.MockTransport(
            lambda request: pytest.fail("missing keys must never dispatch provider HTTP"))))
    before = client.get("/api/games?window=current").json()
    run_ids = []
    for _ in range(2):
        response = client.post("/api/games/refresh")
        assert response.status_code == 200
        body = response.json()
        run_ids.append(UUID(body["run_id"]))
        assert body == {
            "success": False, "reason": "configuration_error",
            "message": "Refresh failed: provider credentials are missing or were rejected. "
                       "20 refreshes remaining this week."
                       + ("" if sunday else " 2 are reserved until Sunday."),
            "remaining_refreshes": 20, "reserved_for_sunday": 0 if sunday else 2,
            "retry_at": None, "data_changed": False, "run_id": str(run_ids[-1]),
        }
    assert run_ids[0] != run_ids[1]
    assert client.get("/api/games?window=current").json() == before
    assert not requests
    with Session(engine) as session:
        assert session.scalar(select(WeeklyRefreshBucket.accepted_attempts)) == 0
        assert session.scalar(select(WeeklyRefreshBucket.last_attempt_at)) is None
        assert session.scalar(select(func.count()).select_from(ProviderCallReservation)) == 0
        assert all(run.status == "rejected" and run.provider_started_at is None
                   for run in session.scalars(select(RefreshRun)))


def test_current_week_sunday_results_boundaries_and_cutoff(api):
    from app.ingress import current_week
    client, engine, clock, requests, _ = api
    window = current_week(clock[0])
    with Session(engine) as session:
        rows = [Game(season=2026, week=11, home_team="A", away_team="B",
                     start_time=time, status=status, home_score=score, away_score=score)
                for time, status, score in [
                    (window.start - timedelta(microseconds=1), "scheduled", None),
                    (window.start, "completed", 21),
                    (window.end - timedelta(microseconds=1), "completed", 31),
                    (window.end, "scheduled", None)]]
        session.add_all(rows)
        session.commit()
    filtered = client.get("/api/games?window=current").json()
    assert [g["home_score"] for g in filtered] == [31, 21]
    assert len(client.get("/api/games").json()) == 4
    assert not requests


def test_active_refresh_conflict(api):
    from app.refresh_admission import RefreshAdmission
    client, engine, clock, requests, _ = api
    with RefreshAdmission(engine, clock=lambda: clock[0]).acquire():
        response = client.post("/api/games/refresh")
        assert response.status_code == 409
        assert response.json()["reason"] == "refresh_in_progress"
        assert response.json()["remaining_refreshes"] == 20
    assert not requests


@pytest.mark.parametrize("attempts,reason,remaining", [
    (18, "sunday_reserve", 2), (20, "weekly_limit", 0),
])
def test_weekly_rejection_http_contract(api, attempts, reason, remaining):
    from app.ingress import current_week
    from app.models import WeeklyRefreshBucket

    client, engine, clock, requests, _ = api
    window = current_week(clock[0])
    with Session(engine) as session:
        session.add(WeeklyRefreshBucket(week_start=window.start, week_end=window.end,
                                       accepted_attempts=attempts))
        session.commit()
    response = client.post("/api/games/refresh")
    assert response.status_code == 429
    body = response.json()
    assert body["reason"] == reason
    assert body["remaining_refreshes"] == remaining
    assert body["reserved_for_sunday"] == remaining
    assert body["retry_at"] is not None
    assert body["run_id"] is None and body["data_changed"] is False
    assert not requests


def test_imported_provenance_snapshots_and_clock_cutoff(migrated_database, monkeypatch):
    from app.cfbd_import import CFBDImporter
    from app.ingress import current_week
    from app.models import TeamAlias
    from app.odds_import import OddsImporter
    from app.refresh_admission import RefreshAdmission
    from app.seed_strategy import seed_strategy, RANDOM_STRATEGY_ID
    from app.seed_user import seed_user
    from test_cfbd_import import game
    from test_odds_import import event, book

    engine, _ = migrated_database
    clock = [datetime(2026, 11, 15, 21, tzinfo=UTC)]
    seed_user(engine)
    seed_strategy(engine)
    monkeypatch.setattr("app.main.create_database_engine", lambda settings: engine)
    monkeypatch.setattr("app.routes.utc_now", lambda: clock[0])
    monkeypatch.setattr("app.runs.utc_now", lambda: clock[0])
    with RefreshAdmission(engine, clock=lambda: clock[0]).acquire() as owner:
        window = current_week(clock[0])
        CFBDImporter(owner, None).apply([game()], [], window)
        with owner.transaction() as (session, _):
            session.add_all([TeamAlias(provider="odds", season=2026, source_identity=name,
                source_name=name, canonical_team=team, classification="fbs")
                for name, team in [("Trojans", "USC"), ("Bruins", "UCLA")]])
        importer = OddsImporter(owner, None)
        importer.apply([event()], window)
        with Session(engine) as session:
            game_id = str(session.scalar(select(Game.id)))
            quote_id = str(session.scalar(select(QuoteObservation.id)))
        with TestClient(app) as client:
            decisions = client.post(f"/api/strategies/{RANDOM_STRATEGY_ID}/decisions",
                                    json={"game_ids": [game_id]}).json()
            assert decisions["decisions"][0]["quote_provenance"]["observation_id"] == quote_id
            response = client.post("/api/runs", headers={"Idempotency-Key": str(uuid4())}, json={
                "strategy_id": str(RANDOM_STRATEGY_ID), "game_ids": [game_id],
                "starting_bankroll": "100", "stake_per_bet": "10"})
            assert response.status_code == 201, response.text
            saved = response.json()["bets"][0]
            assert saved["quote_provenance"]["bookmaker"] == "alpha"
            clock[0] += timedelta(seconds=1)
            importer.apply([event([book("beta", point=-7)])], window)
            assert client.get(f'/api/bets/{saved["id"]}').json() == saved
            clock[0] = datetime.fromisoformat(saved["kickoff_at_placement"])
            for path in ["/api/games?window=current", f"/api/games/{game_id}"]:
                data = client.get(path).json()
                stored = data[0] if isinstance(data, list) else data
                assert stored["status"] == "scheduled"
                assert all(not s["is_active"] for m in stored["markets"] for s in m["selections"])
            for path in [f"/api/games/{game_id}/markets", f'/api/markets/{saved["market_id"]}']:
                data = client.get(path).json()
                markets = data if isinstance(data, list) else [data]
                assert all(not s["is_active"] for m in markets for s in m["selections"])
            assert client.post(f"/api/strategies/{RANDOM_STRATEGY_ID}/decisions",
                json={"game_ids": [game_id]}).json()["skipped_games"][0]["reason"] == "kickoff_reached"
        with Session(engine) as session:
            assert all(s.is_active for s in session.scalars(select(Selection)))


def test_refresh_database_failure_envelope_and_health(monkeypatch):
    from unittest.mock import MagicMock
    from sqlalchemy.exc import OperationalError

    engine = MagicMock()
    engine.connect.side_effect = OperationalError(None, None, Exception("private-key-material"))
    monkeypatch.setattr("app.main.create_database_engine", lambda settings: engine)
    with TestClient(app) as client:
        response = client.post("/api/games/refresh")
        assert response.status_code == 503
        body = response.json()
        assert body == {
            "success": False, "reason": "database_unavailable",
            "message": "Refresh failed: database unavailable.",
            "remaining_refreshes": None, "reserved_for_sunday": 0,
            "retry_at": None, "data_changed": False, "run_id": None,
        }
        assert "private-key-material" not in response.text
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/ready").status_code == 503
