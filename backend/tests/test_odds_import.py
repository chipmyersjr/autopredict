"""Mock free-provider contracts and disposable PostgreSQL paired imports."""
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cfbd_import import CFBDImporter
from app.ingress import ProviderClients, current_week
from app.models import (Game, Market, Selection, TeamAlias, QuoteObservation,
                        ProviderCallReservation, ProviderQuotaPeriod, ProviderGameLink)
from app.odds_import import OddsImporter, paired_books, number
from app.refresh_admission import OwnershipLost, RefreshAdmission, AdmissionRejected
from app.settings import Settings
from test_cfbd_import import game


def book(key="alpha", point=-3.125, price=1.91235, *, source="2026-11-15T20:00:00Z"):
    return {"key": key, "last_update": source, "markets": [{"key": "spreads", "outcomes": [
        {"name": "Trojans", "point": point, "price": price},
        {"name": "Bruins", "point": -point, "price": 2}]}]}


def event(books=None, **overrides):
    return {"id": "event-1", "home_team": "Trojans", "away_team": "Bruins",
            "commence_time": "2026-11-15T23:00:00Z",
            "bookmakers": [book()] if books is None else books, **overrides}


def test_pair_decimal_rounding_zero_and_no_mixed_books():
    pairs, invalid = paired_books(event())
    assert invalid == 0
    assert pairs["alpha"]["home_line"] == Decimal("-3.13")
    assert pairs["alpha"]["away_line"] == Decimal("3.13")
    assert pairs["alpha"]["home_price"] == Decimal("1.9124")
    assert paired_books(event([book(point=0)]))[0]["alpha"]["home_line"] == 0
    first, second = book(), book("beta")
    first["markets"][0]["outcomes"].pop()
    second["markets"][0]["outcomes"].pop(0)
    assert paired_books(event([first, second])) == ({}, 2)


@pytest.mark.parametrize("value", [True, None, "NaN", "Infinity", "-Infinity", {}, "999999.99999"])
def test_invalid_decimal(value):
    with pytest.raises(ValueError):
        number(value, ".0001", Decimal("1e6"))


@pytest.mark.parametrize("mutate", [
    lambda b: b["markets"][0]["outcomes"][0].update(price=1),
    lambda b: b["markets"][0]["outcomes"][0].update(point=3),
    lambda b: b["markets"][0]["outcomes"][0].update(name="Unknown"),
    lambda b: b.update(last_update="2026-01-01"),
])
def test_invalid_book(mutate):
    item = book()
    mutate(item)
    assert paired_books(event([item])) == ({}, 1)


@pytest.fixture
def context(migrated_database):
    engine, _ = migrated_database
    clock = [datetime(2026, 11, 15, 21, tzinfo=UTC)]
    admission = RefreshAdmission(engine, clock=lambda: clock[0])
    with admission.acquire() as owner:
        CFBDImporter(owner, None).apply([game()], [], current_week(clock[0]))
        with owner.transaction() as (session, _):
            session.add_all([TeamAlias(provider="odds", season=2026, source_identity=source,
                source_name=source, canonical_team=canonical, classification="fbs")
                for source, canonical in (("Trojans", "USC"), ("Bruins", "UCLA"))])
    return engine, clock, admission


def test_repeat_retention_fallback_stable_selections_and_history(context):
    engine, clock, admission = context
    with admission.acquire() as owner:
        importer = OddsImporter(owner, None)
        window = current_week(clock[0])
        assert importer.apply([event([book("beta"), book()])], window)["applied"] == 1
        with Session(engine) as session:
            ids = set(session.scalars(select(Selection.id)))
            assert session.scalar(select(QuoteObservation.bookmaker)) == "alpha"
        for books in ([book("beta"), book()], [book("aaa"), book()], [book("beta")]):
            clock[0] += timedelta(seconds=1)
            importer.apply([event(books)], window)
        with Session(engine) as session:
            assert set(session.scalars(select(Selection.id))) == ids
            assert session.scalar(select(func.count()).select_from(Market)) == 1
            assert session.scalar(select(func.count()).select_from(QuoteObservation)) == 2
            current = session.scalar(select(QuoteObservation).where(QuoteObservation.is_current))
            assert current.bookmaker == "beta"
            assert current.home_line == Decimal("-3.13")


@pytest.mark.parametrize("rows", [[], [event([])], [event([book(price=1)])]])
def test_success_absence_or_invalid_pair_closes_without_deleting_history(context, rows):
    engine, clock, admission = context
    with admission.acquire() as owner:
        importer, window = OddsImporter(owner, None), current_week(clock[0])
        importer.apply([event()], window)
        clock[0] += timedelta(seconds=1)
        importer.apply(rows, window)
        with Session(engine) as session:
            assert session.scalar(select(Market.status)) == "closed"
            assert all(not s.is_active for s in session.scalars(select(Selection)))
            assert session.scalar(select(func.count()).select_from(QuoteObservation)) == 1
            assert not session.scalar(select(QuoteObservation.is_current))
        # A late old response cannot restore explicitly removed availability.
        importer.apply([event()], window, fetched_at=clock[0] - timedelta(seconds=1))
        with Session(engine) as session:
            assert session.scalar(select(Market.status)) == "closed"


def test_stale_fetch_and_source_cannot_overwrite(context):
    engine, clock, admission = context
    with admission.acquire() as owner:
        importer, window = OddsImporter(owner, None), current_week(clock[0])
        importer.apply([event()], window)
        clock[0] += timedelta(seconds=1)
        for source in ("2026-11-15T19:00:00Z", "2026-11-15T20:00:00Z", None):
            importer.apply([event([book(point=-7, source=source)])], window)
        importer.apply([], window, fetched_at=clock[0] - timedelta(seconds=1))
        with Session(engine) as session:
            assert session.scalar(select(QuoteObservation.home_line)) == Decimal("-3.13")
            assert session.scalar(select(QuoteObservation.is_current))


def test_neutral_reverse_orientation(context):
    engine, _, admission = context
    with admission.acquire() as owner:
        outcome = OddsImporter(owner, None).apply([event(home_team="Bruins", away_team="Trojans")], current_week(owner.clock()))
        assert outcome["applied"] == 1
        with Session(engine) as session:
            assert session.scalar(select(QuoteObservation.home_line)) == Decimal("-3.13")
            assert session.scalar(select(Selection.line).where(Selection.side == "home")) == Decimal("-3.13")


def test_prior_book_survives_unavailability_and_zero_line_restoration(context):
    engine, clock, admission = context
    with admission.acquire() as owner:
        importer, window = OddsImporter(owner, None), current_week(clock[0])
        importer.apply([event([book("beta", point=0)])], window)
        clock[0] += timedelta(seconds=1)
        importer.apply([], window)
        clock[0] += timedelta(seconds=1)
        importer.apply([event([book(), book("beta", point=0)])], window)
        with Session(engine) as session:
            quote = session.scalar(select(QuoteObservation).where(QuoteObservation.is_current))
            assert quote.bookmaker == "beta" and quote.home_line == quote.away_line == 0
            assert session.scalar(select(func.count()).select_from(QuoteObservation)) == 1


def test_established_event_follows_reschedule_and_fences_prefetched_response(context):
    engine, clock, admission = context
    with admission.acquire() as owner:
        importer, window = OddsImporter(owner, None), current_week(clock[0])
        importer.apply([event()], window)
        prefetched = clock[0]
        clock[0] += timedelta(seconds=1)
        CFBDImporter(owner, None).apply([game(startDate="2026-11-16T01:00:00Z")], [], window)
        importer.apply([event()], window, fetched_at=prefetched)
        with Session(engine) as session:
            assert not session.scalar(select(QuoteObservation.is_current))
        clock[0] += timedelta(seconds=1)
        # Stable event ID wins over proximity after initial unique matching.
        importer.apply([event()], window)
        with Session(engine) as session:
            assert session.scalar(select(QuoteObservation.is_current))
            assert session.scalar(select(func.count()).select_from(ProviderGameLink).where(
                ProviderGameLink.provider == "odds")) == 1


def test_demo_and_non_neutral_reversal_are_not_matched(context):
    engine, clock, admission = context
    with admission.acquire() as owner:
        with owner.transaction() as (session, _):
            session.scalar(select(ProviderGameLink).where(ProviderGameLink.provider == "cfbd")).neutral_site = False
            original = session.scalar(select(Game))
            session.add(Game(season=2026, week=11, home_team="USC", away_team="UCLA",
                             start_time=original.start_time, status="scheduled", notes="demo"))
        importer = OddsImporter(owner, None)
        result = importer.apply([event(home_team="Bruins", away_team="Trojans")], current_week(owner.clock()))
        assert result["quarantined"] == 1
        clock[0] += timedelta(seconds=1)
        assert importer.apply([event()], current_week(owner.clock()))["applied"] == 1
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Market)) == 1


def test_book_order_does_not_select_different_book(context):
    engine, clock, admission = context
    with admission.acquire() as owner:
        importer, window = OddsImporter(owner, None), current_week(clock[0])
        importer.apply([event([book("zulu"), book("beta"), book()])], window)
        clock[0] += timedelta(seconds=1)
        importer.apply([event([book(), book("beta"), book("zulu")])], window)
        with Session(engine) as session:
            assert session.scalar(select(QuoteObservation.bookmaker)) == "alpha"
            assert session.scalar(select(func.count()).select_from(QuoteObservation)) == 1


def test_empty_scope_watermark_blocks_older_first_quote_across_runs(context):
    engine, clock, admission = context
    with admission.acquire() as owner:
        OddsImporter(owner, None).apply([], current_week(clock[0]))
    old_fetch = clock[0] - timedelta(seconds=1)
    clock[0] += timedelta(seconds=1)
    with admission.acquire() as owner:
        result = OddsImporter(owner, None).apply([event()], current_week(clock[0]), fetched_at=old_fetch)
        assert result["applied"] == 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(QuoteObservation)) == 0


@pytest.mark.parametrize("kind", ["alias_collision", "unknown_alias", "kickoff", "multiple_games", "duplicate_event", "multiple_events"])
def test_strict_unique_matching(context, kind):
    engine, _, admission = context
    with admission.acquire() as owner:
        with owner.transaction() as (session, _):
            if kind == "alias_collision":
                session.add(TeamAlias(provider="odds", season=2026, source_identity="other",
                    source_name="Trojans", canonical_team="Other"))
            if kind == "unknown_alias":
                session.delete(session.scalar(select(TeamAlias).where(TeamAlias.provider == "odds")))
        if kind == "multiple_games":
            CFBDImporter(owner, None).apply([game(id=402)], [], current_week(owner.clock()))
        rows = [event(commence_time="2026-11-15T22:00:00Z")] if kind == "kickoff" else [event()]
        if kind in {"duplicate_event", "multiple_events"}:
            rows.append(event(id="event-1" if kind == "duplicate_event" else "event-2"))
        result = OddsImporter(owner, None).apply(rows, current_week(owner.clock()))
        assert result["quarantined"] > 0
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(QuoteObservation)) == 0


def execute(owner, handler, key="fake"):
    async def run():
        async with ProviderClients(Settings(_env_file=None, odds_api_key=key),
                                   transport=httpx.MockTransport(handler)) as clients:
            return await OddsImporter(owner, clients).run(current_week(owner.clock()))
    return asyncio.run(run())


@pytest.mark.parametrize("kind", ["success", "partial", "error", "timeout", "invalid_body", "rate_limit"])
def test_mock_provider_accounting_atomicity_and_preserved_failures(context, kind):
    engine, clock, admission = context
    with admission.acquire() as owner:
        OddsImporter(owner, None).apply([event()], current_week(clock[0]))
        clock[0] += timedelta(seconds=1)
        def handler(request):
            assert not owner.connection.in_transaction()
            assert request.url.params["regions"] == "us"
            assert request.url.params["markets"] == "spreads"
            if kind == "timeout":
                raise httpx.ReadTimeout("fake")
            headers = {"x-requests-used": "12", "x-requests-remaining": "488", "x-requests-last": "1"}
            if kind in {"error", "rate_limit"}:
                return httpx.Response(429 if kind == "rate_limit" else 500, headers=headers)
            rows = [event([book(point=-7, source="2026-11-15T20:01:00Z")])]
            if kind == "partial":
                rows.append(event(id="unknown", home_team="Unknown"))
            return httpx.Response(200, json={} if kind == "invalid_body" else rows, headers=headers)
        result = execute(owner, handler)
        assert result["status"] == ("fetched-and-applied" if kind == "success" else
            "rejected/quarantined" if kind == "partial" else "failed")
        with Session(engine) as session:
            quote = session.scalar(select(QuoteObservation).where(QuoteObservation.is_current))
            assert quote.home_line == (Decimal("-7") if kind in {"success", "partial"} else Decimal("-3.13"))
            calls = session.scalars(select(ProviderCallReservation)).all()
            assert len(calls) == 1
            assert calls[0].status == ("unknown" if kind == "timeout" else "failed" if kind in {"error", "rate_limit"} else "succeeded")
            if kind != "timeout":
                assert session.scalar(select(ProviderQuotaPeriod.used)) == 12


def test_fencing_and_concurrent_admission(context):
    engine, _, admission = context
    with admission.acquire() as owner:
        with pytest.raises(AdmissionRejected, match="refresh_in_progress"):
            with admission.acquire():
                pytest.fail("overlapping owner")
        owner.generation += 1
        with pytest.raises(OwnershipLost):
            OddsImporter(owner, None).apply([event()], current_week(owner.clock()))
        owner.generation -= 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(QuoteObservation)) == 0


@pytest.mark.parametrize("kind", ["missing_key", "budget", "past", "not_scheduled"])
def test_no_provider_dispatch_when_not_allowed(context, kind):
    engine, clock, admission = context
    with admission.acquire() as owner:
        with owner.transaction() as (session, _):
            if kind == "budget":
                session.add(ProviderQuotaPeriod(provider="odds", period_key="test", allowance=500, used=450))
            if kind == "past":
                session.scalar(select(Game)).start_time = clock[0]
            if kind == "not_scheduled":
                session.scalar(select(Game)).status = "in_progress"
        result = execute(owner, lambda _: pytest.fail("no HTTP"), key="" if kind == "missing_key" else "fake")
        assert result["status"] == ("quota-blocked" if kind in {"missing_key", "budget"} else "skipped-not-needed")
