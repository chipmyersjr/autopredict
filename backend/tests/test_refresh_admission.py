"""Admission tests use disposable PostgreSQL and fake provider work only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ingress import ProviderClients, ProviderError
from app.models import ProviderCallReservation, ProviderQuotaPeriod, RefreshRun, WeeklyRefreshBucket
from app.refresh_admission import AdmissionRejected, LOCK_KEY, OwnershipLost, RefreshAdmission
from app.settings import Settings


@pytest.fixture
def admission(migrated_database):
    engine, _ = migrated_database
    clock = [datetime(2026, 11, 12, 12, tzinfo=UTC)]
    return engine, clock, RefreshAdmission(engine, clock=lambda: clock[0])


def spend(service):
    with service.acquire() as owner:
        call = owner.reserve_call("cfbd", "info")
        owner.dispatch(call)
        owner.finish_call(call, succeeded=True)


def test_week_sunday_and_monday_do_not_reset_provider(admission):
    engine, clock, service = admission
    for _ in range(18):
        spend(service)
        clock[0] += timedelta(seconds=61)
    with pytest.raises(AdmissionRejected) as error:
        spend(service)
    assert error.value.reason == "sunday_reserve" and error.value.remaining == 2
    clock[0] = error.value.retry_at
    spend(service)
    clock[0] += timedelta(seconds=61)
    spend(service)
    clock[0] += timedelta(seconds=61)
    with pytest.raises(AdmissionRejected, match="weekly_limit"):
        spend(service)
    clock[0] = datetime(2026, 11, 16, 8, tzinfo=UTC)
    spend(service)
    with Session(engine) as session:
        assert session.scalar(select(ProviderQuotaPeriod.used)) == 21
        assert sorted(session.scalars(select(WeeklyRefreshBucket.accepted_attempts))) == [1, 20]


def test_preflight_and_cooldown_across_monday(admission):
    engine, clock, service = admission
    with service.acquire() as owner:
        with pytest.raises(AdmissionRejected, match="configuration_error"):
            owner.reserve_call("cfbd", "info", configured=False)
        owner.reserve_call("odds", "odds")
    with Session(engine) as session:
        assert session.scalar(select(WeeklyRefreshBucket.accepted_attempts)) == 0
        assert session.scalar(select(ProviderQuotaPeriod.reserved)) == 0
    clock[0] = datetime(2026, 11, 16, 7, 59, 50, tzinfo=UTC)
    spend(service)
    clock[0] += timedelta(seconds=20)
    with pytest.raises(AdmissionRejected, match="cooldown"):
        spend(service)


def test_concurrent_tabs_and_deadline_do_not_steal_lock(admission):
    engine, clock, service = admission
    with service.acquire() as owner:
        owner.dispatch(owner.reserve_call("cfbd", "info"))
        def contender(_):
            with pytest.raises(AdmissionRejected, match="refresh_in_progress"):
                spend(service)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(contender, range(8)))
        clock[0] += timedelta(seconds=46)
        contender(None)
        with pytest.raises(OwnershipLost):
            owner.reserve_call("cfbd", "info")
    with Session(engine) as session:
        assert session.scalar(select(WeeklyRefreshBucket.accepted_attempts)) == 1
        assert session.scalar(select(ProviderQuotaPeriod.used)) == 1


def test_lock_loss_restart_recovery_and_generation_fence(admission):
    engine, clock, service = admission
    with service.acquire() as old:
        call = old.reserve_call("cfbd", "info")
        old.dispatch(call)
        old.reserve_call("odds", "odds")
        # Simulate loss of the dedicated database session, not browser closure.
        old.connection.invalidate()
        with pytest.raises(OwnershipLost):
            old.finish_call(call, succeeded=True)
        clock[0] += timedelta(seconds=61)
        restarted = RefreshAdmission(engine, clock=lambda: clock[0])
        with restarted.acquire() as new:
            assert new.generation > old.generation
            with pytest.raises(OwnershipLost):
                with old.transaction():
                    pytest.fail("stale writer admitted")
        with Session(engine) as session:
            assert session.get(RefreshRun, old.run_id).status == "abandoned"
            assert session.get(ProviderCallReservation, call).status == "unknown"
            assert session.scalar(select(ProviderQuotaPeriod.used).where(ProviderQuotaPeriod.provider == "cfbd")) == 1
            assert session.scalar(select(ProviderQuotaPeriod.reserved).where(ProviderQuotaPeriod.provider == "odds")) == 0


def test_unlocked_connection_is_fenced(admission):
    _, _, service = admission
    with service.acquire() as owner:
        with owner.connection.begin():
            owner.connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
        with pytest.raises(OwnershipLost):
            owner.reserve_call("cfbd", "info")


def test_generation_mismatch_rolls_back_import_writes(admission):
    engine, _, service = admission
    with service.acquire() as owner:
        owner.generation += 1
        with pytest.raises(OwnershipLost):
            with owner.transaction() as (session, _):
                session.add(ProviderQuotaPeriod(provider="cfbd", period_key="stale", allowance=1000))
    with Session(engine) as session:
        assert session.scalar(select(ProviderQuotaPeriod.id)) is None


def test_recovery_commits_even_when_cooldown_rejects(admission):
    engine, _, service = admission
    with service.acquire() as old:
        old.dispatch(old.reserve_call("cfbd", "info"))
        old.connection.invalidate()
        with pytest.raises(AdmissionRejected, match="cooldown"):
            with service.acquire():
                pytest.fail("cooldown bypassed")
        with Session(engine) as session:
            assert session.get(RefreshRun, old.run_id).status == "abandoned"


def test_reserve_external_usage_unknown_month_and_known_reset(admission):
    engine, clock, service = admission
    with service.acquire() as owner:
        call = owner.reserve_call("odds", "odds")
        owner.dispatch(call)
        owner.finish_call(call, succeeded=True, used=449, remaining=51, allowance=10000)
        call = owner.reserve_call("odds", "odds")
        owner.dispatch(call)
        owner.finish_call(call, succeeded=False)
        with pytest.raises(AdmissionRejected, match="provider_budget"):
            owner.reserve_call("odds", "odds")
        # The other provider can still work in the same attempt.
        call = owner.reserve_call("cfbd", "info")
        owner.dispatch(call)
        owner.finish_call(call, succeeded=True, used=900, remaining=100,
                          resets_at=clock[0] + timedelta(days=30))
    clock[0] += timedelta(days=31)
    with service.acquire() as owner:
        with pytest.raises(AdmissionRejected, match="provider_budget"):
            owner.reserve_call("odds", "odds")
        call = owner.reserve_call("cfbd", "info")
        owner.dispatch(call)
    with Session(engine) as session:
        periods = session.scalars(select(ProviderQuotaPeriod).where(ProviderQuotaPeriod.provider == "cfbd")).all()
        assert sorted(p.used for p in periods) == [1, 900]
        assert session.scalar(select(ProviderQuotaPeriod.resets_at).where(ProviderQuotaPeriod.provider == "odds")) is None


def test_reconcile_between_reservation_and_dispatch(admission):
    engine, _, service = admission
    with service.acquire() as owner:
        first = owner.reserve_call("odds", "odds")
        second = owner.reserve_call("odds", "odds")
        owner.dispatch(first)
        owner.finish_call(first, succeeded=True, remaining=50, used=450)
        with pytest.raises(AdmissionRejected, match="provider_budget"):
            owner.dispatch(second)
    with Session(engine) as session:
        assert session.scalar(select(ProviderQuotaPeriod.used)) == 450
        assert session.scalar(select(ProviderQuotaPeriod.reserved)) == 0


def test_simultaneous_last_pre_sunday_attempt(admission):
    engine, clock, service = admission
    with service.acquire():
        pass
    with Session(engine) as session, session.begin():
        bucket = session.scalar(select(WeeklyRefreshBucket))
        bucket.accepted_attempts = 17
        session.add(ProviderQuotaPeriod(provider="cfbd", period_key="boundary",
                                        allowance=1000, used=899))
    barrier = Barrier(4)

    def contender(_):
        barrier.wait(timeout=10)
        try:
            spend(service)
        except AdmissionRejected as error:
            return error.reason
        return "accepted"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(contender, range(4)))
    assert results.count("accepted") == 1
    assert set(results) <= {"accepted", "refresh_in_progress", "sunday_reserve"}
    with Session(engine) as session:
        assert session.scalar(select(WeeklyRefreshBucket.accepted_attempts)) == 18
        assert session.scalar(select(ProviderQuotaPeriod.used)) == 900
        assert session.scalar(select(ProviderQuotaPeriod.reserved)) == 0


def test_first_dispatch_cannot_use_previous_week_bucket(admission):
    engine, clock, service = admission
    clock[0] = datetime(2026, 11, 16, 7, 59, 50, tzinfo=UTC)
    with service.acquire() as owner:
        call = owner.reserve_call("cfbd", "info")
        clock[0] += timedelta(seconds=20)
        with pytest.raises(OwnershipLost):
            owner.dispatch(call)
    with Session(engine) as session:
        assert session.scalar(select(WeeklyRefreshBucket.accepted_attempts)) == 0
        assert session.scalar(select(ProviderQuotaPeriod.used)) == 0
        assert session.get(ProviderCallReservation, call).status == "released"
    spend(service)
    with Session(engine) as session:
        assert sorted(session.scalars(select(WeeklyRefreshBucket.accepted_attempts))) == [0, 1]


def test_reserved_call_cannot_dispatch_after_provider_reset(admission):
    engine, clock, service = admission
    with service.acquire() as owner:
        call = owner.reserve_call("cfbd", "info")
        with owner.transaction() as (session, _):
            period = session.scalar(select(ProviderQuotaPeriod))
            period.resets_at = clock[0] + timedelta(seconds=5)
        clock[0] += timedelta(seconds=6)
        with pytest.raises(AdmissionRejected, match="provider_budget"):
            owner.dispatch(call)
        fresh = owner.reserve_call("cfbd", "info")
        owner.dispatch(fresh)
    with Session(engine) as session:
        assert session.get(ProviderCallReservation, call).status == "released"
        periods = session.scalars(select(ProviderQuotaPeriod)).all()
        assert sorted(p.used for p in periods) == [0, 1]
        assert all(p.reserved == 0 for p in periods)
        assert session.scalar(select(WeeklyRefreshBucket.accepted_attempts)) == 1


def test_transaction_crossing_deadline_rolls_back(admission):
    engine, clock, service = admission
    with service.acquire() as owner:
        with pytest.raises(OwnershipLost):
            with owner.transaction() as (session, _):
                session.add(ProviderQuotaPeriod(provider="cfbd", period_key="too-late", allowance=1000))
                clock[0] += timedelta(seconds=46)
    with Session(engine) as session:
        assert session.scalar(select(ProviderQuotaPeriod.id)) is None


def test_rate_limit_retry_and_cfbd_ceiling(admission):
    engine, clock, service = admission
    retry = clock[0] + timedelta(seconds=120)
    with service.acquire() as owner:
        call = owner.reserve_call("cfbd", "info")
        owner.dispatch(call)
        owner.finish_call(call, succeeded=False, http_status=429, retry_at=retry)
        with pytest.raises(AdmissionRejected) as error:
            owner.reserve_call("cfbd", "info")
        assert error.value.reason == "provider_rate_limit" and error.value.retry_at == retry
    clock[0] = retry
    with service.acquire() as owner:
        with owner.transaction() as (session, _):
            period = session.scalar(select(ProviderQuotaPeriod))
            period.used = 899
        call = owner.reserve_call("cfbd", "info")
        with pytest.raises(AdmissionRejected, match="provider_budget"):
            owner.reserve_call("cfbd", "calendar")
        owner.dispatch(call)
    with Session(engine) as session:
        assert session.scalar(select(ProviderQuotaPeriod.used)) == 900


@pytest.mark.parametrize("response", ["success", "partial", "error", "timeout"])
def test_mock_provider_outcomes_are_charged_once(admission, response):
    engine, _, service = admission
    def handler(request):
        if response == "timeout":
            raise httpx.ReadTimeout("fake timeout")
        return httpx.Response(500 if response == "error" else 200,
                              json={"games": []} if response == "partial" else [])
    async def work(owner, call):
        settings = Settings(_env_file=None, cfbd_api_key="fake")
        async with ProviderClients(settings, transport=httpx.MockTransport(handler)) as client:
            owner.dispatch(call)
            try:
                payload, _ = await client.info()
            except ProviderError as error:
                owner.finish_call(call, succeeded=False, http_status=error.status)
            else:
                owner.finish_call(call, succeeded=True)
                assert payload == ({"games": []} if response == "partial" else [])
    with service.acquire() as owner:
        asyncio.run(work(owner, owner.reserve_call("cfbd", "info")))
        status, reason = {"success": ("succeeded", "refreshed"),
                          "partial": ("partial_failure", "partial_failure")}.get(
                              response, ("failed", "provider_failure"))
        owner.finish(status=status, reason=reason)
    with Session(engine) as session:
        assert session.scalar(select(WeeklyRefreshBucket.accepted_attempts)) == 1
        assert session.scalar(select(ProviderQuotaPeriod.used)) == 1
        assert session.scalar(select(ProviderQuotaPeriod.reserved)) == 0
