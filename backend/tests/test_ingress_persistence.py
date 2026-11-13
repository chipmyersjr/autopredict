"""Ingress schema checks run only against the generated disposable database."""
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Game, GameResultChange, Market, ProviderCalendar, ProviderCallReservation,
    ProviderGameLink, ProviderQuotaPeriod, QuoteObservation, RefreshRun,
    TeamAlias, WeeklyRefreshBucket,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_POSTGRES_TESTS") != "1",
    reason="Set RUN_POSTGRES_TESTS=1 for disposable PostgreSQL integration tests",
)
NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)


@pytest.fixture
def graph(migrated_database):
    engine, _ = migrated_database
    with Session(engine) as session:
        bucket = WeeklyRefreshBucket(week_start=NOW, week_end=NOW + timedelta(days=7), accepted_attempts=1)
        period = ProviderQuotaPeriod(provider="odds", period_key="unknown-initial", allowance=500, used=1, reserved=1)
        game = Game(season=2026, week=11, home_team="Home", away_team="Away", start_time=NOW + timedelta(days=1), status="scheduled")
        market = Market(type="spread", status="active")
        game.markets.append(market)
        session.add_all([bucket, period, game])
        session.flush()
        run = RefreshRun(bucket_id=bucket.id, started_at=NOW, deadline_at=NOW + timedelta(seconds=45),
                         status="running", provider_started_at=NOW,
                         item_failures=[{"provider": "odds", "external_id": "unmatched", "reason": "ambiguous_match"}])
        session.add(run)
        session.flush()
        link = ProviderGameLink(provider="cfbd", external_id="123", game_id=game.id, season=2026, week=11,
                                season_type="regular", home_identity="home-id", away_identity="away-id",
                                home_classification="fbs", away_classification="fbs", neutral_site=True,
                                source_state="scheduled", source_kickoff=game.start_time, fetched_at=NOW)
        call = ProviderCallReservation(run_id=run.id, quota_period_id=period.id, endpoint="odds",
                                       estimated_cost=1, status="unknown", dispatched_at=NOW)
        quote = QuoteObservation(game_id=game.id, market_id=market.id, run_id=run.id,
                                 external_event_id="odds-event", bookmaker="book-a", home_line=Decimal("-3.50"),
                                 away_line=Decimal("3.50"), home_price=Decimal("1.9091"), away_price=Decimal("2.0100"),
                                 fetched_at=NOW, content_hash="a" * 64, is_current=True)
        alias = TeamAlias(provider="odds", season=2026, source_identity="Home", source_name="Home", canonical_team="Home")
        calendar = ProviderCalendar(season=2026, weeks=[{"week": 11, "seasonType": "regular"}], fetched_at=NOW)
        change = GameResultChange(game_id=game.id, run_id=run.id, old_status="scheduled", new_status="completed",
                                  new_home_score=21, new_away_score=17, source_state="final", fetched_at=NOW)
        rows = dict(bucket=bucket, period=period, game=game, market=market, run=run, link=link,
                    call=call, quote=quote, alias=alias, calendar=calendar, change=change)
        session.add_all([link, call, quote, alias, calendar, change])
        session.commit()
        return {key: row.id for key, row in rows.items()}


def test_exact_values_and_durable_ledgers(migrated_database, graph):
    engine, _ = migrated_database
    url = engine.url
    engine.dispose()
    restarted = create_engine(url)
    try:
        with Session(restarted) as session:
            quote = session.get(QuoteObservation, graph["quote"])
            assert quote.home_line == Decimal("-3.50") and quote.away_line == Decimal("3.50")
            assert quote.home_price == Decimal("1.9091") and quote.away_price == Decimal("2.0100")
            assert quote.fetched_at == NOW and quote.fetched_at.utcoffset() == timedelta(0)
            assert quote.source_timestamp is None
            period = session.get(ProviderQuotaPeriod, graph["period"])
            assert (period.used, period.reserved, period.reserve_fraction) == (1, 1, Decimal("0.1000"))
            assert period.starts_at is period.resets_at is None
            assert session.get(WeeklyRefreshBucket, graph["bucket"]).accepted_attempts == 1
            call = session.get(ProviderCallReservation, graph["call"])
            assert call.status == "unknown" and call.actual_cost is None
            run = session.get(RefreshRun, graph["run"])
            assert run.generation > 0 and run.item_failures[0]["reason"] == "ambiguous_match"
            newer = RefreshRun(bucket_id=graph["bucket"], started_at=NOW, deadline_at=NOW + timedelta(seconds=45))
            session.add(newer)
            session.flush()
            assert newer.generation > run.generation
            assert session.get(ProviderGameLink, graph["link"]).neutral_site is True
            assert session.get(GameResultChange, graph["change"]).new_home_score == 21
            assert session.get(ProviderCalendar, graph["calendar"]).weeks[0]["week"] == 11
    finally:
        restarted.dispose()


def test_unique_identities_and_current_projection(migrated_database, graph):
    engine, _ = migrated_database
    with Session(engine) as session:
        generation = session.get(RefreshRun, graph["run"]).generation
        duplicate_factories = [
            lambda: WeeklyRefreshBucket(week_start=NOW, week_end=NOW + timedelta(days=7)),
            lambda: ProviderQuotaPeriod(provider="odds", period_key="unknown-initial", allowance=500, is_current=False),
            lambda: ProviderQuotaPeriod(provider="odds", period_key="second-period", allowance=500),
            lambda: ProviderCalendar(season=2026, weeks=[], fetched_at=NOW),
            lambda: TeamAlias(provider="odds", season=2026, source_identity="Home", source_name="Different", canonical_team="Other"),
            lambda: ProviderGameLink(provider="cfbd", external_id="123", game_id=graph["game"], season=2026,
                                     home_identity="h", away_identity="a", fetched_at=NOW),
            lambda: RefreshRun(bucket_id=graph["bucket"], generation=generation, started_at=NOW,
                               deadline_at=NOW + timedelta(seconds=45)),
        ]
        for factory in duplicate_factories:
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(factory())
                session.flush()
        original = session.get(QuoteObservation, graph["quote"])
        values = {column.name: getattr(original, column.name) for column in QuoteObservation.__table__.columns
                  if column.name not in {"id", "created_at", "updated_at"}}
        # Repeated content is rejected even when it is no longer current.
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(QuoteObservation(**{**values, "is_current": False}))
            session.flush()
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(QuoteObservation(**{**values, "content_hash": "b" * 64}))
            session.flush()
        original.is_current = False
        session.flush()
        replacement = QuoteObservation(**{**values, "content_hash": "b" * 64, "bookmaker": "book-b"})
        session.add(replacement)
        session.flush()
        assert len(session.scalars(select(QuoteObservation)).all()) == 2
        # A valid pick'em pair must remain representable without null/fake lines.
        replacement.home_line = replacement.away_line = Decimal("0.00")
        session.flush()
        assert replacement.home_line == replacement.away_line == Decimal("0.00")


@pytest.mark.parametrize("model,key,field,value", [
    (WeeklyRefreshBucket, "bucket", "accepted_attempts", -1),
    (WeeklyRefreshBucket, "bucket", "accepted_attempts", 21),
    (WeeklyRefreshBucket, "bucket", "week_end", NOW),
    (RefreshRun, "run", "bucket_id", uuid4()),
    (RefreshRun, "run", "status", "unknown"),
    (RefreshRun, "run", "item_failures", {}),
    (ProviderQuotaPeriod, "period", "provider", "paid_source"),
    (ProviderQuotaPeriod, "period", "reserved", -1),
    (ProviderQuotaPeriod, "period", "reserve_fraction", Decimal("1")),
    (ProviderCallReservation, "call", "run_id", uuid4()),
    (ProviderCallReservation, "call", "quota_period_id", uuid4()),
    (ProviderCallReservation, "call", "estimated_cost", 0),
    (ProviderCallReservation, "call", "actual_cost", -1),
    (ProviderCalendar, "calendar", "weeks", {}),
    (TeamAlias, "alias", "canonical_team", " "),
    (ProviderGameLink, "link", "game_id", uuid4()),
    (QuoteObservation, "quote", "game_id", uuid4()),
    (QuoteObservation, "quote", "market_id", uuid4()),
    (QuoteObservation, "quote", "run_id", uuid4()),
    (QuoteObservation, "quote", "away_line", Decimal("3.51")),
    (QuoteObservation, "quote", "home_price", Decimal("1")),
    (QuoteObservation, "quote", "home_price", Decimal("NaN")),
    (QuoteObservation, "quote", "home_line", Decimal("NaN")),
    (GameResultChange, "change", "game_id", uuid4()),
    (GameResultChange, "change", "run_id", uuid4()),
    (GameResultChange, "change", "new_home_score", -1),
    (GameResultChange, "change", "new_away_score", None),
])
def test_invalid_or_orphan_records_rejected(migrated_database, graph, model, key, field, value):
    engine, _ = migrated_database
    with Session(engine) as session:
        row = session.get(model, graph[key])
        setattr(row, field, value)
        with pytest.raises(IntegrityError):
            session.flush()


def test_audit_foreign_keys_prevent_history_deletion(migrated_database, graph):
    engine, _ = migrated_database
    with Session(engine) as session:
        for model, key in ((Game, "game"), (Market, "market"), (RefreshRun, "run"),
                           (ProviderQuotaPeriod, "period"), (WeeklyRefreshBucket, "bucket")):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.delete(session.get(model, graph[key]))
                session.flush()


def test_additive_upgrade_preserves_domain_data_and_schema(migrated_database):
    engine, config = migrated_database
    command.downgrade(config, "0003")
    before = {table: [(c["name"], str(c["type"]), c["nullable"]) for c in inspect(engine).get_columns(table)]
              for table in inspect(engine).get_table_names() if table != "alembic_version"}
    with Session(engine) as session:
        game = Game(season=2026, week=11, home_team="Preserved", away_team="Away", start_time=NOW, status="scheduled")
        session.add(game)
        session.commit()
        game_id = game.id
    command.upgrade(config, "head")
    command.check(config)
    inspector = inspect(engine)
    for table, columns in before.items():
        assert [(c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)] == columns
    quote_columns = {c["name"]: c for c in inspector.get_columns("quote_observations")}
    ingress_tables = set(inspector.get_table_names()) - set(before) - {"alembic_version"}
    for table in ingress_tables:
        for column in inspector.get_columns(table):
            if hasattr(column["type"], "timezone"):
                assert column["type"].timezone
    with engine.connect() as connection:
        persistence = dict(connection.execute(text(
            "SELECT relname, relpersistence FROM pg_class WHERE relnamespace = 'public'::regnamespace"
        )).all())
        assert all(persistence[table] == "p" for table in ingress_tables)
    for name in ("home_line", "away_line"):
        assert (quote_columns[name]["type"].precision, quote_columns[name]["type"].scale) == (10, 2)
    for name in ("home_price", "away_price"):
        assert (quote_columns[name]["type"].precision, quote_columns[name]["type"].scale) == (10, 4)
    assert quote_columns["source_timestamp"]["nullable"]
    command.downgrade(config, "0003")
    with Session(engine) as session:
        assert session.get(Game, game_id).home_team == "Preserved"
    command.upgrade(config, "head")
    command.check(config)
