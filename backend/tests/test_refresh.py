"""Service tests use disposable PostgreSQL and fake provider credentials only."""
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (Game, ProviderCallReservation, ProviderQuotaPeriod,
                        RefreshRun, WeeklyRefreshBucket)
from app.refresh import RefreshService
from app.settings import Settings
from test_cfbd_import import game, provider_handler


@pytest.fixture
def setup(migrated_database):
    engine, _ = migrated_database
    clock = [datetime(2026, 11, 14, 18, tzinfo=UTC)]
    return engine, clock


def service(setup, handler, **keys):
    engine, clock = setup
    return RefreshService(engine, Settings(_env_file=None, **{
        "cfbd_api_key": "fake", "odds_api_key": "fake", **keys}),
        clock=lambda: clock[0], transport=httpx.MockTransport(handler))


def handler_for(kind, requests):
    base = provider_handler(requests)
    def handler(request):
        if request.url.host == "api.the-odds-api.com":
            requests.append(request)
            if kind == "error":
                return httpx.Response(500, text="private-key-material")
            if kind == "rate":
                return httpx.Response(429, headers={"retry-after": "120"})
            # Missing spreads in a successful response is normal unavailability.
            return httpx.Response(200, json=[])
        if request.url.path == "/games/schedule" and kind == "empty":
            requests.append(request)
            return httpx.Response(200, json={"games": []})
        if request.url.path == "/games":
            requests.append(request)
            return httpx.Response(200, json=[game()])
        if request.url.path == "/games/schedule" and kind == "invalid":
            requests.append(request)
            return httpx.Response(200, json={"games": [game(), game(id=402, status="unknown")]})
        return base(request)
    return handler


@pytest.mark.parametrize("kind,reason", [
    ("success", "refreshed"), ("empty", "no_games"),
    ("error", "partial_failure"), ("invalid", "partial_failure"),
    ("rate", "partial_failure"),
])
def test_composed_outcomes_and_one_attempt(setup, kind, reason):
    engine, clock = setup
    requests = []
    result = asyncio.run(service(setup, handler_for(kind, requests)).run())
    assert result.http_status == 200
    assert result.body["reason"] == reason
    assert result.body["success"] == (kind in {"success", "empty"})
    assert result.body["remaining_refreshes"] == 19
    assert "private-key-material" not in result.body["message"]
    if kind == "rate":
        assert result.body["retry_at"] == clock[0] + timedelta(seconds=120)
    with Session(engine) as session:
        run = session.get(RefreshRun, result.body["run_id"])
        assert run.status != "running"
        assert set(run.stage_outcomes) == {"cfbd", "odds"}
        assert run.data_changed == result.body["data_changed"] == (kind != "empty")
        assert session.scalar(select(WeeklyRefreshBucket.accepted_attempts)) == 1
        calls = session.scalars(select(ProviderCallReservation)).all()
        assert len(calls) == len(requests)
        if kind == "empty":
            assert run.stage_outcomes["odds"]["status"] == "skipped-not-needed"
            assert all(call.endpoint != "spreads" for call in calls)
        if kind == "invalid":
            assert run.item_failures


def test_entirely_missing_configuration_spends_nothing(setup):
    engine, _ = setup
    result = asyncio.run(service(setup, lambda request: pytest.fail("no HTTP"),
                                 cfbd_api_key="", odds_api_key="").run())
    assert result.body["reason"] == "configuration_error"
    assert result.body["remaining_refreshes"] == 20
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProviderCallReservation)) == 0


def test_budget_blocked_cfbd_still_updates_saved_odds_scope(setup):
    from app.cfbd_import import CFBDImporter
    from app.ingress import current_week
    from app.refresh_admission import RefreshAdmission
    engine, clock = setup
    with RefreshAdmission(engine, clock=lambda: clock[0]).acquire() as owner:
        CFBDImporter(owner, None).apply([game()], [], current_week(clock[0]))
        with owner.transaction() as (session, _):
            session.add(ProviderQuotaPeriod(provider="cfbd", period_key="full", allowance=1000, used=900))
    requests = []
    result = asyncio.run(service(setup, handler_for("success", requests)).run())
    assert result.body["reason"] == "partial_failure"
    assert result.body["remaining_refreshes"] == 19
    assert len(requests) == 1 and requests[0].url.host == "api.the-odds-api.com"


def test_budget_change_between_stages_retains_cfbd_commit(setup):
    engine, _ = setup
    requests = []
    base = handler_for("success", requests)
    def handler(request):
        if request.url.path == "/games":
            with Session(engine) as session, session.begin():
                session.add(ProviderQuotaPeriod(provider="odds", period_key="external", allowance=500, used=450))
        return base(request)
    result = asyncio.run(service(setup, handler).run())
    assert result.body["reason"] == "partial_failure" and result.body["data_changed"]
    assert all(request.url.host != "api.the-odds-api.com" for request in requests)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Game)) == 1


@pytest.mark.parametrize("interrupt", ["cancel", "deadline"])
def test_interrupted_network_charged_and_exclusive_until_terminated(setup, interrupt):
    engine, clock = setup
    requests = []
    base = handler_for("success", requests)
    async def execute():
        entered, release = asyncio.Event(), asyncio.Event()
        async def handler(request):
            if request.url.host == "api.the-odds-api.com":
                entered.set()
                await release.wait()
            return base(request)
        active_service = service(setup, handler)
        task = asyncio.create_task(active_service.run())
        await entered.wait()
        concurrent = await service(setup, lambda request: pytest.fail("overlap")).run()
        assert concurrent.http_status == 409
        if interrupt == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            clock[0] += timedelta(seconds=46)
            release.set()
            result = await task
            assert result.body["reason"] == "partial_failure"
            assert result.body["data_changed"]
        with Session(engine) as session:
            run = session.scalar(select(RefreshRun))
            assert run.status == "partial_failure" and run.data_changed
            call = session.scalar(select(ProviderCallReservation).where(ProviderCallReservation.endpoint == "spreads"))
            assert call.status == "unknown"
            assert session.scalar(select(WeeklyRefreshBucket.accepted_attempts)) == 1
        clock[0] += timedelta(seconds=61)
        recovered = await service(setup, handler_for("success", [])).run()
        assert recovered.body["success"] and recovered.body["remaining_refreshes"] == 18
    asyncio.run(execute())


def test_safe_messages_do_not_echo_errors():
    svc = RefreshService(None, None, clock=lambda: datetime(2026, 11, 14, tzinfo=UTC))
    result = svc.result("provider_budget", remaining=2)
    assert result.http_status == 429
    assert result.body["reserved_for_sunday"] == 2
    assert "not yet known" in result.body["message"]


def test_provider_failure_consumes_attempt_and_reports_failure(setup):
    engine, _ = setup
    result = asyncio.run(service(setup, lambda request: httpx.Response(
        500, text="secret response body")).run())
    assert result.http_status == 200
    assert result.body["reason"] == "provider_failure"
    assert result.body["remaining_refreshes"] == 19
    assert not result.body["data_changed"]
    assert "secret" not in result.body["message"]
    with Session(engine) as session:
        assert session.scalar(select(RefreshRun.status)) == "failed"


def test_results_only_skips_odds(setup):
    requests = []
    # The shared fixture supplies explicitly completed games with final scores.
    result = asyncio.run(service(setup, provider_handler(requests)).run())
    assert result.body["reason"] == "refreshed"
    assert all(request.url.host != "api.the-odds-api.com" for request in requests)


def test_total_deadline_cancels_pending_provider_without_refund(setup, monkeypatch):
    import app.refresh_admission as admission
    monkeypatch.setattr(admission, "REFRESH_SECONDS", 0.01)
    engine, _ = setup
    async def handler(request):
        await asyncio.Event().wait()
    result = asyncio.run(service(setup, handler).run())
    assert result.body["reason"] == "provider_failure"
    assert result.body["remaining_refreshes"] == 19
    with Session(engine) as session:
        assert session.scalar(select(ProviderCallReservation.status)) == "unknown"
        assert session.scalar(select(RefreshRun.status)) == "failed"


def test_preflight_provider_budget_rejection_keeps_attempt(setup):
    engine, _ = setup
    with Session(engine) as session, session.begin():
        session.add(ProviderQuotaPeriod(provider="cfbd", period_key="full", allowance=1000, used=900))
    result = asyncio.run(service(setup, lambda request: pytest.fail("no HTTP")).run())
    assert result.http_status == 429
    assert result.body["reason"] == "provider_budget"
    assert result.body["remaining_refreshes"] == 20
