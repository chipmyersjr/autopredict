"""Explicit, bounded refresh service. Importing this module starts no work."""

import asyncio
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.cfbd_import import CFBDImporter
from app.ingress import PACIFIC, ProviderClients, current_week
from app.models import Game, ProviderGameLink, ProviderQuotaPeriod, WeeklyRefreshBucket
from app.odds_import import OddsImporter
from app.refresh_admission import AdmissionRejected, OwnershipLost, RefreshAdmission, utcnow


@dataclass(frozen=True)
class RefreshResult:
    http_status: int
    body: dict


MESSAGES = {
    "refreshed": "Refresh successful.",
    "no_games": "Refresh successful. No FBS games this week.",
    "partial_failure": "Refresh failed to update all data. Successful updates were saved; failed stages kept saved data.",
    "provider_failure": "Refresh failed: provider request failed or timed out. Saved data remains available.",
    "configuration_error": "Refresh failed: provider credentials are missing or were rejected.",
    "weekly_limit": "Refresh failed: all 20 weekly refreshes have been used. Provider availability follows separate limits.",
    "sunday_reserve": "Refresh failed: the remaining 2 refreshes are reserved until Sunday.",
    "cooldown": "Refresh failed: refreshed recently. Wait until the retry time.",
    "provider_budget": "Refresh failed: a provider's free allowance safety limit was reached. External key use can exhaust it earlier.",
    "provider_rate_limit": "Refresh failed: a provider temporarily limited requests.",
    "refresh_in_progress": "Refresh failed: another refresh is in progress.",
    "database_unavailable": "Refresh failed: database unavailable.",
}


class RefreshService:
    def __init__(self, engine, settings, *, clock=utcnow, transport=None):
        self.engine, self.settings = engine, settings
        self.clock, self.transport = clock, transport

    def result(self, reason, *, remaining=None, retry_at=None, changed=False,
               run_id=None, started=False):
        reserved = min(2, remaining) if remaining is not None and self.clock().astimezone(PACIFIC).weekday() != 6 else 0
        message = MESSAGES[reason]
        if remaining is not None:
            message += f" {remaining} refreshes remaining this week."
        if reserved:
            message += f" {reserved} are reserved until Sunday."
        if reason in {"provider_budget", "provider_rate_limit"}:
            message += " Provider retry/reset time: " + (retry_at.isoformat() if retry_at else "not yet known") + "."
        status = 200
        if reason == "database_unavailable":
            status = 503
        elif reason == "refresh_in_progress":
            status = 409
        elif not started and reason in {"weekly_limit", "sunday_reserve", "cooldown", "provider_budget", "provider_rate_limit"}:
            status = 429
        return RefreshResult(status, dict(
            success=reason in {"refreshed", "no_games"}, reason=reason, message=message,
            remaining_refreshes=remaining, reserved_for_sunday=reserved,
            retry_at=retry_at, data_changed=changed, run_id=run_id,
        ))

    def remaining(self):
        with Session(self.engine) as session:
            used = session.scalar(select(WeeklyRefreshBucket.accepted_attempts).where(
                WeeklyRefreshBucket.week_start == current_week(self.clock()).start))
            return 20 - (used or 0)

    async def run(self):
        """Cancellation ends work before releasing ownership; no detached writer.

        Dispatched but unanswered calls remain charged and become unknown. A
        process/connection loss is fenced and recovered by the next admission.
        """
        try:
            with RefreshAdmission(self.engine, clock=self.clock).acquire() as owner:
                return await self._run(owner)
        except AdmissionRejected as error:
            return self.result(error.reason, remaining=self.remaining(), retry_at=error.retry_at)
        except (SQLAlchemyError, OwnershipLost):
            # Do not attempt writes through a lost owner or expose DB details.
            return self.result("database_unavailable")

    async def _run(self, owner):
        window = current_week(self.clock())
        outcomes = {}
        interrupted = False
        try:
            with owner.transaction() as (_, run):
                seconds = max(0, (run.deadline_at - self.clock()).total_seconds())
            async with asyncio.timeout(seconds):
                async with ProviderClients(self.settings, transport=self.transport) as clients:
                    outcomes["cfbd"] = await CFBDImporter(owner, clients).run(window)
                    outcomes["odds"] = await OddsImporter(owner, clients).run(window)
        except asyncio.CancelledError:
            interrupted = True
            raise
        except (TimeoutError, OwnershipLost):
            # Deadline expiry still permits a fenced terminal audit write.
            # Actual lock loss fails that write and is handled by run().
            interrupted = True
        finally:
            with owner.transaction(allow_expired=True) as (session, run):
                stages = {**(run.stage_outcomes or {}), **outcomes}
                for stage in ("cfbd", "odds"):
                    if stage not in stages:
                        stages[stage] = {"status": "failed", "reason": "provider_failure"}
                changed, failures = run.data_changed, list(run.item_failures or [])
                started = run.provider_started_at is not None
                remaining = 20 - session.get(WeeklyRefreshBucket, run.bucket_id).accepted_attempts
                has_games = session.scalar(select(Game.id).join(ProviderGameLink).where(
                    ProviderGameLink.provider == "cfbd", Game.start_time >= window.start,
                    Game.start_time < window.end).limit(1)) is not None
                provider_retries = list(session.scalars(select(ProviderQuotaPeriod.retry_at).where(
                    ProviderQuotaPeriod.is_current, ProviderQuotaPeriod.retry_at > self.clock())))
            good = {"fetched-and-applied", "skipped-not-needed"}
            failed = [stage for stage in stages.values() if stage["status"] not in good or stage.get("quarantined", 0)]
            retry_times = [datetime.fromisoformat(stage["retry_at"]) for stage in failed if stage.get("retry_at")] + provider_retries
            retry_at = max(retry_times) if retry_times else None
            if not failed and not failures and not interrupted:
                reason = "refreshed" if has_games else "no_games"
                status = "succeeded"
            elif changed or any(stage.get("applied", 0) or stage["status"] == "fetched-and-applied" for stage in stages.values()):
                reason, status = "partial_failure", "partial_failure"
            else:
                reasons = {stage.get("reason") for stage in failed}
                reason = next((r for r in ("configuration_error", "provider_rate_limit", "provider_budget") if r in reasons), "provider_failure")
                status = "failed" if started else "rejected"
            owner.finish(status=status, reason=reason, data_changed=changed,
                         stage_outcomes=stages, item_failures=failures)
        result = self.result(reason, remaining=remaining, retry_at=retry_at,
                             changed=changed, run_id=owner.run_id, started=started)
        if reason == "partial_failure":
            for name, stage in stages.items():
                label = "Games/results" if name == "cfbd" else "Spreads"
                if stage["status"] == "fetched-and-applied":
                    result.body["message"] += f" {label} updated."
                elif stage["status"] != "skipped-not-needed":
                    detail = MESSAGES.get(stage.get("reason"), "Some relevant items could not be applied.")
                    result.body["message"] += f" {label}: {detail}"
                    if stage.get("reason") in {"provider_budget", "provider_rate_limit"}:
                        result.body["message"] += " Provider retry/reset time: " + (retry_at.isoformat() if retry_at else "not yet known") + "."
        return result
