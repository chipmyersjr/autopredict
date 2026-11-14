"""Flat CFBD /games fixtures; all HTTP uses fake keys and mock transports."""
import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cfbd_import import CFBDImporter, normalize
from app.ingress import ProviderClients, current_week
from app.models import (Game, GameResultChange, ProviderCalendar, ProviderCallReservation,
                        ProviderGameLink, ProviderQuotaPeriod, RefreshRun, TeamAlias, WeeklyRefreshBucket,
                        Market, Selection)
from app.refresh_admission import OwnershipLost, RefreshAdmission
from app.settings import Settings


def game(**overrides):
    # /games includes classifications, points and completed; schedule responses
    # may omit those fields, requiring the separately budgeted season query.
    return {"id": 401, "season": 2026, "week": 11, "seasonType": "regular",
            "startDate": "2026-11-15T23:00:00Z", "startTimeTBD": False,
            "neutralSite": True, "homeId": 1, "awayId": 2,
            "homeTeam": "USC", "awayTeam": "UCLA", "homeClassification": "fbs",
            "awayClassification": "fbs", "completed": False,
            "homePoints": None, "awayPoints": None, **overrides}


@pytest.mark.parametrize("changes", [
    {"startDate": None}, {"startDate": "2026-11-15T23:00:00"},
    {"startTimeTBD": True}, {"week": None}, {"week": True},
    {"status": "postponed"}, {"status": "mystery"}, {"homeTeam": "TBD"},
    {"awayId": 1}, {"completed": True, "homePoints": -1, "awayPoints": 0},
    {"completed": True, "homePoints": 21.5, "awayPoints": 0},
    {"completed": True, "homePoints": True, "awayPoints": 0},
    {"completed": True, "homePoints": 21},
    {"completed": True, "status": "scheduled"}, {"seasonType": "spring"},
])
def test_invalid_source_records_are_rejected(changes):
    with pytest.raises((ValueError, TypeError)):
        normalize(game(**changes))


def test_explicit_state_only_and_final_scores():
    assert normalize(game())["status"] == "scheduled"
    assert normalize(game(status="in_progress"))["status"] == "in_progress"
    assert normalize(game(status="canceled"))["status"] == "canceled"
    final = normalize(game(completed=True, homePoints=0, awayPoints=31))
    assert final["status"] == "completed" and final["scores"] == (0, 31)
    # A past kickoff and non-final live scores do not establish completion.
    assert normalize(game(startDate="2020-01-01T00:00:00Z", homePoints=31, awayPoints=7))["scores"] == (None, None)


@pytest.fixture
def context(migrated_database):
    engine, _ = migrated_database
    clock = [datetime(2026, 11, 15, 23, 30, tzinfo=UTC)]
    return engine, clock, RefreshAdmission(engine, clock=lambda: clock[0])


def test_repeat_identity_reschedule_and_final_correction(context):
    engine, clock, admission = context
    window = current_week(clock[0])
    with admission.acquire() as owner:
        importer = CFBDImporter(owner, None)
        importer.apply([game()], [], window)
        clock[0] += timedelta(seconds=1)
        importer.apply([game()], [], window)
        with Session(engine) as session:
            original = session.scalar(select(Game.id))
        clock[0] += timedelta(seconds=1)
        importer.apply([game(startDate="2026-11-20T00:00:00Z")], [], window)
        clock[0] += timedelta(seconds=1)
        final = game(startDate="2026-11-20T00:00:00Z", completed=True, homePoints=24, awayPoints=0)
        importer.apply([final], [], window)
        clock[0] += timedelta(seconds=1)
        importer.apply([{**final, "homePoints": 27}], [], window)
        clock[0] += timedelta(seconds=1)
        importer.apply([{**final, "homePoints": 27}], [], window)
        with Session(engine) as session:
            stored = session.get(Game, original)
            assert stored.home_score == 27 and stored.status == "completed"
            assert session.scalar(select(func.count()).select_from(Game)) == 1
            assert session.scalar(select(func.count()).select_from(ProviderGameLink)) == 1
            assert session.scalar(select(func.count()).select_from(TeamAlias)) == 2
            audits = session.scalars(select(GameResultChange).order_by(GameResultChange.fetched_at)).all()
            assert [(audit.old_home_score, audit.new_home_score) for audit in audits] == [(None, 24), (24, 27)]
            link = session.scalar(select(ProviderGameLink))
            assert (link.season, link.week, link.season_type, link.neutral_site) == (2026, 11, "regular", True)
            assert stored.start_time == datetime(2026, 11, 20, tzinfo=UTC)


def test_partial_quarantine_and_exact_window_fbs(context):
    engine, clock, admission = context
    window = current_week(clock[0])
    rows = [game(), game(id=402, awayClassification="fcs"),
            game(id=403, startDate=window.end.isoformat()),
            game(id=404, startDate=window.start.isoformat()),
            game(id=405, startTimeTBD=True), game(id=406, status="unknown"),
            game(id=407, homeClassification=None), game(id=408, completed=True)]
    with admission.acquire() as owner:
        outcome = CFBDImporter(owner, None).apply(rows, [], window)
        assert outcome == {"status": "rejected/quarantined", "applied": 2, "excluded": 2, "quarantined": 4}
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Game)) == 2
            assert len(session.get(RefreshRun, owner.run_id).item_failures) == 4


def test_stale_observations_and_identity_conflict(context):
    engine, clock, admission = context
    window = current_week(clock[0])
    row = game(updatedAt="2026-11-15T23:00:00Z")
    with admission.acquire() as owner:
        importer = CFBDImporter(owner, None)
        importer.apply([row], [], window)
        clock[0] += timedelta(seconds=1)
        importer.apply([{**row, "status": "canceled"}], [], window)  # equal source time
        importer.apply([{**row, "updatedAt": "2026-11-15T22:00:00Z", "status": "canceled"}], [], window)
        importer.apply([{**row, "updatedAt": "2026-11-15T23:01:00Z", "awayId": 3}], [], window)
        with Session(engine) as session:
            assert session.scalar(select(Game.status)) == "scheduled"
            assert session.scalar(select(func.count()).select_from(TeamAlias)) == 2
            assert len(session.get(RefreshRun, owner.run_id).item_failures) == 1


def test_only_source_cancellation_and_no_final_regression(context):
    engine, clock, admission = context
    window = current_week(clock[0])
    with admission.acquire() as owner:
        importer = CFBDImporter(owner, None)
        importer.apply([game(status="canceled"), game(id=402, completed=True, homePoints=0, awayPoints=21)], [], window)
        clock[0] += timedelta(seconds=1)
        importer.apply([game(id=402)], [], window)
        with Session(engine) as session:
            assert sorted(session.scalars(select(Game.status))) == ["canceled", "completed"]
            assert len(session.get(RefreshRun, owner.run_id).item_failures) == 1


def test_import_writes_are_fenced(context):
    engine, clock, admission = context
    with admission.acquire() as owner:
        importer = CFBDImporter(owner, None)
        owner.generation += 1
        with pytest.raises(OwnershipLost):
            importer.apply([game()], [], current_week(clock[0]))
        owner.generation -= 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Game)) == 0


def test_conflicting_duplicates_are_quarantined_before_creation(context):
    engine, clock, admission = context
    with admission.acquire() as owner:
        importer = CFBDImporter(owner, None)
        outcome = importer.apply([game(), game(awayId=3)], [], current_week(clock[0]))
        assert outcome["quarantined"] == 2
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Game)) == 0


def test_rescheduling_disables_old_projection_without_replacing_selections(context):
    engine, clock, admission = context
    with admission.acquire() as owner:
        importer = CFBDImporter(owner, None)
        window = current_week(clock[0])
        importer.apply([game()], [], window)
        with owner.transaction() as (session, _):
            stored = session.scalar(select(Game))
            market = Market(game_id=stored.id, type="spread", status="active")
            session.add(market)
            session.flush()
            selection = Selection(market_id=market.id, side="home", line=0, price=2, is_active=True)
            session.add(selection)
            session.flush()
            selection_id = selection.id
        clock[0] += timedelta(seconds=1)
        importer.apply([game(startDate="2026-11-20T00:00:00Z")], [], window)
        with Session(engine) as session:
            assert session.get(Selection, selection_id).is_active is False
            assert session.scalar(select(Market.status)) == "closed"
            assert session.scalar(select(func.count()).select_from(Selection)) == 1


def execute(owner, handler):
    async def run():
        async with ProviderClients(Settings(_env_file=None, cfbd_api_key="fake"),
                                   transport=httpx.MockTransport(handler)) as clients:
            return await CFBDImporter(owner, clients).run(current_week(owner.clock()))
    return asyncio.run(run())


def provider_handler(requests, *, bad=False, error=False):
    def handler(request):
        requests.append(request)
        path = request.url.path
        if path == "/info":
            return httpx.Response(200, json={"monthlyAllowance": 1000, "remainingCalls": 999})
        if path == "/calendar":
            return httpx.Response(200, json=[] if request.url.params["year"] == "2025" else [{
                "seasonType": "regular", "week": 11,
                "startDate": "2026-11-09T00:00:00Z", "endDate": "2026-11-16T08:00:00Z"}])
        if path == "/games/schedule":
            if error:
                return httpx.Response(500, text="private-response")
            schedule = deepcopy(game())
            for key in ("homeClassification", "awayClassification", "completed", "homePoints", "awayPoints"):
                schedule.pop(key)
            for side in ("home", "away"):
                schedule[side + "Team"] = {"id": schedule.pop(side + "Id"),
                                          "name": schedule[side + "Team"]}
            return httpx.Response(200, json={"selection": "explicit", "games":
                [schedule] + ([game(id=402, status="unknown")] if bad else [])})
        assert path == "/games"
        return httpx.Response(200, json=[game(completed=True, homePoints=31, awayPoints=0)])
    return handler


@pytest.mark.parametrize("kind", ["success", "partial", "error"])
def test_budgeted_mock_success_partial_error_and_calendar_cache(context, kind):
    engine, clock, admission = context
    requests = []
    handler = provider_handler(requests, bad=kind == "partial", error=kind == "error")
    with admission.acquire() as owner:
        outcome = execute(owner, handler)
        assert outcome["status"] == {"success": "fetched-and-applied", "partial": "rejected/quarantined", "error": "failed"}[kind]
        run_id = owner.run_id
        with Session(engine) as session:
            assert session.scalar(select(RefreshRun.data_changed).where(RefreshRun.id == run_id)) == (kind != "error")
            calls = session.scalars(select(ProviderCallReservation)).all()
            assert len(calls) == len(requests)
            assert all(call.status in {"succeeded", "failed"} for call in calls)
            assert session.scalar(select(func.count()).select_from(ProviderCalendar)) == 2
            if kind != "error":
                assert session.scalar(select(Game.status)) == "completed"
    clock[0] += timedelta(seconds=61)
    requests.clear()
    with admission.acquire() as owner:
        execute(owner, handler)
    assert all(request.url.path != "/calendar" for request in requests)


def test_provider_budget_prevents_metadata_dispatch(context):
    engine, _, admission = context
    with admission.acquire() as owner:
        with owner.transaction() as (session, _):
            session.add(ProviderQuotaPeriod(provider="cfbd", period_key="exhausted", allowance=1000, used=900))
        outcome = execute(owner, lambda request: pytest.fail("budget must block HTTP"))
        assert outcome["status"] == "quota-blocked"
        assert outcome["reason"] == "provider_budget"


def test_missing_key_preflight_does_not_spend_attempt(context):
    engine, _, admission = context
    async def run(owner):
        async with ProviderClients(Settings(_env_file=None, cfbd_api_key=""),
                                   transport=httpx.MockTransport(lambda request: pytest.fail("no HTTP"))) as clients:
            return await CFBDImporter(owner, clients).run(current_week(owner.clock()))
    with admission.acquire() as owner:
        outcome = asyncio.run(run(owner))
        assert outcome["reason"] == "configuration_error"
    with Session(engine) as session:
        assert session.scalar(select(WeeklyRefreshBucket.accepted_attempts)) == 0
        assert session.scalar(select(func.count()).select_from(ProviderCallReservation)) == 0


def test_network_calls_hold_no_database_transaction(context):
    engine, _, admission = context
    requests = []
    base = provider_handler(requests)
    with admission.acquire() as owner:
        def handler(request):
            assert not owner.connection.in_transaction()
            return base(request)
        execute(owner, handler)


def test_season_history_follows_reschedule_missing_from_schedule(context):
    engine, clock, admission = context
    with admission.acquire() as owner:
        importer = CFBDImporter(owner, None)
        importer.apply([game()], [], current_week(clock[0]))
        clock[0] += timedelta(seconds=1)
        requests = []
        base = provider_handler(requests)
        def handler(request):
            if request.url.path == "/games/schedule":
                return httpx.Response(200, json={"games": []})
            if request.url.path == "/games":
                return httpx.Response(200, json=[game(startDate="2026-11-20T00:00:00Z")])
            return base(request)
        execute(owner, handler)
        with Session(engine) as session:
            assert session.scalar(select(Game.start_time)) == datetime(2026, 11, 20, tzinfo=UTC)
            assert session.scalar(select(func.count()).select_from(Game)) == 1


def test_empty_schedule_without_known_games_skips_season_query(context):
    _, _, admission = context
    requests = []
    base = provider_handler(requests)
    def handler(request):
        if request.url.path == "/games/schedule":
            return httpx.Response(200, json={"games": []})
        assert request.url.path != "/games"
        return base(request)
    with admission.acquire() as owner:
        outcome = execute(owner, handler)
        assert outcome == {"status": "fetched-and-applied", "applied": 0, "excluded": 0, "quarantined": 0}
