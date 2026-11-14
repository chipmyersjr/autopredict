"""Durable admission primitives for explicit refreshes, not an orchestrator.

Keep the owner context alive through provider work. All importer writes must use
owner.transaction(); never pass its session across a network await. A connection
loss permanently fences this owner, even if SQLAlchemy reconnects afterwards.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ingress import (
    PACIFIC, CFBD_FREE_CALLS, ODDS_FREE_CREDITS, COOLDOWN_SECONDS,
    REFRESH_SECONDS, current_week,
)
from app.models import (
    ProviderCallReservation, ProviderQuotaPeriod, RefreshRun, WeeklyRefreshBucket,
)

# Deployment-wide, session-scoped lock. Never use a pooled session for ownership.
LOCK_KEY = 71832071
FREE_ALLOWANCES = {"cfbd": CFBD_FREE_CALLS, "odds": ODDS_FREE_CREDITS}


class AdmissionRejected(Exception):
    def __init__(self, reason, retry_at=None, remaining=None):
        self.reason, self.retry_at, self.remaining = reason, retry_at, remaining
        super().__init__(reason)


class OwnershipLost(Exception):
    pass


def utcnow():
    return datetime.now(UTC)


class RefreshAdmission:
    def __init__(self, engine, *, clock=utcnow):
        self.engine, self.clock = engine, clock

    @contextmanager
    def acquire(self):
        connection = self.engine.connect()
        locked = False
        owner = None
        try:
            with connection.begin():
                locked = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY})
                if not locked:
                    raise AdmissionRejected("refresh_in_progress")
                pid = connection.scalar(text("SELECT pg_backend_pid()"))
            owner = RefreshOwner(connection, pid, self.clock)
            owner.initialize()
            yield owner
        finally:
            # Cleanup does not refund dispatched work, including cancellation.
            try:
                if owner is not None and owner.run_id is not None:
                    owner.close()
            finally:
                try:
                    if locked and not connection.invalidated:
                        with connection.begin():
                            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                finally:
                    # Do not return an uncertain session-level lock to the pool.
                    if locked:
                        connection.invalidate()
                    connection.close()


class RefreshOwner:
    def __init__(self, connection, pid, clock):
        self.connection, self.pid, self.clock = connection, pid, clock
        self.run_id = self.generation = None
        self.lost = False
        self.finished = False

    def _check_lock(self, session):
        if self.lost or self.connection.invalidated:
            self.lost = True
            raise OwnershipLost()
        valid = session.scalar(text(
            "SELECT pg_backend_pid() = :pid AND EXISTS (SELECT 1 FROM pg_locks "
            "WHERE locktype = 'advisory' AND pid = :pid AND classid = 0 "
            "AND objid = :key AND objsubid = 1 AND granted)"
        ), {"pid": self.pid, "key": LOCK_KEY})
        if not valid:
            self.lost = True
            raise OwnershipLost()

    @contextmanager
    def transaction(self, *, allow_expired=False):
        """Fenced short transaction for accounting and later importer writes."""
        with Session(self.connection, expire_on_commit=False) as session, session.begin():
            self._check_lock(session)
            run = None
            if self.run_id is not None:
                run = session.get(RefreshRun, self.run_id, with_for_update=True)
                if (run is None or run.generation != self.generation or run.status != "running"
                        or (not allow_expired and self.clock() >= run.deadline_at)):
                    raise OwnershipLost()
            yield session, run
            self._check_lock(session)
            if run is not None and not allow_expired and self.clock() >= run.deadline_at:
                raise OwnershipLost()

    def initialize(self):
        now = self.clock()
        window = current_week(now)
        with self.transaction() as (session, _):
            # Acquiring the exclusive lock proves prior owners have lost it;
            # deadlines alone never authorize takeover.
            for run in session.scalars(select(RefreshRun).where(RefreshRun.status == "running")):
                self._release_calls(session, run.id, now)
                run.status, run.reason, run.finished_at = "abandoned", "provider_failure", now
        # Recovery must survive a subsequent cooldown/weekly rejection.
        with self.transaction() as (session, _):
            bucket = session.scalar(select(WeeklyRefreshBucket).where(
                WeeklyRefreshBucket.week_start == window.start))
            if bucket is None:
                bucket = WeeklyRefreshBucket(week_start=window.start, week_end=window.end, accepted_attempts=0)
                session.add(bucket)
                session.flush()
            self._weekly_check(session, bucket, now)
            run = RefreshRun(bucket_id=bucket.id, started_at=now,
                             deadline_at=now + timedelta(seconds=REFRESH_SECONDS), status="running")
            session.add(run)
            session.flush()
            run_id, generation = run.id, run.generation
        self.run_id, self.generation = run_id, generation

    def _weekly_check(self, session, bucket, now):
        remaining = 20 - bucket.accepted_attempts
        if remaining == 0:
            raise AdmissionRejected("weekly_limit", bucket.week_end, remaining)
        if now.astimezone(PACIFIC).weekday() != 6 and remaining <= 2:
            sunday = bucket.week_start.astimezone(PACIFIC).date() + timedelta(days=6)
            raise AdmissionRejected("sunday_reserve", datetime.combine(sunday, time.min, PACIFIC).astimezone(UTC), remaining)
        # Cooldown also spans the Monday bucket boundary.
        last = session.scalar(select(WeeklyRefreshBucket.last_attempt_at).where(
            WeeklyRefreshBucket.last_attempt_at.is_not(None)).order_by(
                WeeklyRefreshBucket.last_attempt_at.desc()).limit(1))
        if last is not None and now < last + timedelta(seconds=COOLDOWN_SECONDS):
            raise AdmissionRejected("cooldown", last + timedelta(seconds=COOLDOWN_SECONDS), remaining)

    def _period(self, session, provider, now):
        allowance = FREE_ALLOWANCES[provider]
        period = session.scalar(select(ProviderQuotaPeriod).where(
            ProviderQuotaPeriod.provider == provider, ProviderQuotaPeriod.is_current).with_for_update())
        if period is not None and period.resets_at is not None and now >= period.resets_at:
            start = period.resets_at
            period.is_current = False
            session.flush()
            period = ProviderQuotaPeriod(provider=provider, period_key=str(uuid4()),
                                         starts_at=start, allowance=allowance, used=0, reserved=0)
            session.add(period)
        elif period is None:
            period = ProviderQuotaPeriod(provider=provider, period_key=str(uuid4()),
                                         allowance=allowance, used=0, reserved=0)
            session.add(period)
        session.flush()
        return period

    def reserve_call(self, provider, endpoint, *, cost=1, configured=True):
        """Reserve each metadata/data call separately; no attempt charged yet."""
        if not configured:
            raise AdmissionRejected("configuration_error")
        if provider not in FREE_ALLOWANCES or type(cost) is not int or cost <= 0:
            raise ValueError("Invalid provider/cost")
        if not endpoint or len(endpoint) > 64 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_/-" for c in endpoint):
            raise ValueError("Endpoint must be a safe label")
        now = self.clock()
        with self.transaction() as (session, run):
            period = self._period(session, provider, now)
            if period.retry_at is not None and now < period.retry_at:
                raise AdmissionRejected("provider_rate_limit", period.retry_at)
            allowance = min(period.allowance, FREE_ALLOWANCES[provider])
            reserve = max(period.reserve_fraction, Decimal("0.1"))
            ceiling = int(Decimal(allowance) * (1 - reserve))
            if (period.used + period.reserved + cost > ceiling or
                    (period.reported_remaining is not None and
                     period.reported_remaining - period.reserved - cost < allowance - ceiling)):
                raise AdmissionRejected("provider_budget", period.resets_at)
            period.reserved += cost
            call = ProviderCallReservation(run_id=run.id, quota_period_id=period.id,
                                           endpoint=endpoint, estimated_cost=cost, status="reserved")
            session.add(call)
            session.flush()
            return call.id

    def dispatch(self, call_id):
        """Commit before sending HTTP: a crash immediately afterwards is charged."""
        now = self.clock()
        with self.transaction() as (session, run):
            call = self._call(session, call_id, {"reserved"})
            period = session.get(ProviderQuotaPeriod, call.quota_period_id, with_for_update=True)
            # Reservations belong to a particular provider period. Never send a
            # call charged to an expired ledger; reserve again in the new period.
            if not period.is_current or (period.resets_at is not None and now >= period.resets_at):
                raise AdmissionRejected("provider_budget", now)
            allowance = min(period.allowance, FREE_ALLOWANCES[period.provider])
            ceiling = int(Decimal(allowance) * (1 - max(period.reserve_fraction, Decimal("0.1"))))
            if period.retry_at is not None and now < period.retry_at:
                raise AdmissionRejected("provider_rate_limit", period.retry_at)
            if (period.used + period.reserved > ceiling or
                    (period.reported_remaining is not None and
                     period.reported_remaining - period.reserved < allowance - ceiling)):
                raise AdmissionRejected("provider_budget", period.resets_at)
            if run.provider_started_at is None:
                bucket = session.get(WeeklyRefreshBucket, run.bucket_id, with_for_update=True)
                # The refresh window was established at admission. A request
                # crossing Monday before any work must start a fresh admission,
                # rather than spend last week's attempts on this week's calls.
                if not bucket.week_start <= now < bucket.week_end:
                    raise OwnershipLost()
                self._weekly_check(session, bucket, now)
                bucket.accepted_attempts += 1
                bucket.last_attempt_at = run.provider_started_at = now
            period.reserved -= call.estimated_cost
            period.used += call.estimated_cost
            if period.reported_remaining is not None:
                period.reported_remaining = max(0, period.reported_remaining - call.estimated_cost)
            call.status, call.dispatched_at = "dispatched", now

    def _call(self, session, call_id, statuses):
        call = session.get(ProviderCallReservation, call_id, with_for_update=True)
        if call is None or call.run_id != self.run_id or call.status not in statuses:
            raise ValueError("Invalid call transition")
        return call

    def finish_call(self, call_id, *, succeeded, actual_cost=None, used=None,
                    remaining=None, allowance=None, resets_at=None, retry_at=None,
                    http_status=None):
        """Apply normalized authoritative metadata; never infer a reset from Monday
        or falling counters. Unknown/error outcomes retain the full estimate.
        """
        for value in (actual_cost, used, remaining, allowance):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Invalid quota count")
        if allowance == 0:
            raise ValueError("Invalid allowance")
        now = self.clock()
        for value in (resets_at, retry_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("Aware quota timestamp required")
        with self.transaction() as (session, _):
            call = self._call(session, call_id, {"dispatched"})
            period = session.get(ProviderQuotaPeriod, call.quota_period_id, with_for_update=True)
            if actual_cost is not None:
                # Never refund an uncertain estimate from an untrusted low cost.
                period.used += max(0, actual_cost - call.estimated_cost)
            if allowance is not None:
                period.allowance = min(allowance, FREE_ALLOWANCES[period.provider])
            if used is not None:
                period.used = max(period.used, used)
            if remaining is not None:
                period.reported_remaining = min(remaining, period.reported_remaining) if period.reported_remaining is not None else remaining
                period.used = max(period.used, period.allowance - remaining)
            if resets_at is not None and resets_at > now:
                period.resets_at = resets_at
            if retry_at is not None:
                period.retry_at = retry_at
            period.checked_at = now
            call.actual_cost, call.http_status = actual_cost, http_status
            call.status = "succeeded" if succeeded else ("failed" if http_status else "unknown")
            call.finished_at = now

    @staticmethod
    def _release_calls(session, run_id, now):
        for call in session.scalars(select(ProviderCallReservation).where(
                ProviderCallReservation.run_id == run_id,
                ProviderCallReservation.status.in_(["reserved", "dispatched"]))):
            if call.status == "reserved":
                period = session.get(ProviderQuotaPeriod, call.quota_period_id, with_for_update=True)
                period.reserved -= call.estimated_cost
                call.status = "released"
            else:
                call.status = "unknown"
            call.finished_at = now

    def close(self):
        if self.finished or self.lost or self.connection.invalidated:
            return
        try:
            with self.transaction(allow_expired=True) as (session, run):
                self._release_calls(session, run.id, self.clock())
                run.status, run.finished_at = "failed", self.clock()
                run.reason = "provider_failure" if run.provider_started_at else "provider_budget"
        except OwnershipLost:
            self.lost = True

    def finish(self, *, status, reason, data_changed=False, stage_outcomes=None, item_failures=None):
        """Later orchestration supplies the truthful aggregate stage outcome."""
        if status not in {"succeeded", "partial_failure", "failed", "rejected"}:
            raise ValueError("Invalid terminal status")
        with self.transaction(allow_expired=True) as (session, run):
            self._release_calls(session, run.id, self.clock())
            run.status, run.reason, run.finished_at = status, reason, self.clock()
            run.data_changed = data_changed
            run.stage_outcomes, run.item_failures = stage_outcomes or {}, item_failures or []
        self.finished = True
