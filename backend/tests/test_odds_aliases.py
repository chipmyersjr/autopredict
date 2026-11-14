"""Catalog bootstrap and real provider labels in disposable PostgreSQL."""
from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cfbd_import import CFBDImporter
from app.ingress import current_week
from app.models import QuoteObservation, TeamAlias
from app.odds_aliases import seed_odds_aliases
from app.odds_import import OddsImporter
from app.refresh_admission import RefreshAdmission
from test_cfbd_import import game
from test_odds_import import book, event


def test_first_refresh_matches_real_labels_without_manual_alias_setup(migrated_database):
    engine, _ = migrated_database
    now = datetime(2026, 11, 15, 21, tzinfo=UTC)
    window = current_week(now)
    with RefreshAdmission(engine, clock=lambda: now).acquire() as owner:
        CFBDImporter(owner, None).apply([game()], [], window)
        quote = deepcopy(book())
        outcomes = quote["markets"][0]["outcomes"]
        outcomes[0]["name"], outcomes[1]["name"] = "USC Trojans", "UCLA Bruins"
        result = OddsImporter(owner, None).apply([
            event([quote], home_team="USC Trojans", away_team="UCLA Bruins")], window)
        assert result["applied"] == 1
        assert result["quarantined"] == 0
        with owner.transaction() as (session, _):
            assert seed_odds_aliases(session) == 0
            assert session.scalar(select(func.count()).select_from(QuoteObservation)) == 1
            assert {(a.source_name, a.canonical_team) for a in session.scalars(
                select(TeamAlias).where(TeamAlias.provider == "odds"))} == {
                    ("USC Trojans", "USC"), ("UCLA Bruins", "UCLA")}
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(QuoteObservation)) == 1


def test_catalog_preserves_existing_mappings_and_requires_unique_season_identity(migrated_database):
    engine, _ = migrated_database
    with Session(engine) as session, session.begin():
        def cfbd(season, identity, school, canonical=None, classification="fbs"):
            session.add(TeamAlias(provider="cfbd", season=season, source_identity=identity,
                source_name=school, canonical_team=canonical or school, classification=classification))
        cfbd(2026, "1", "USC")
        cfbd(2026, "2", "Miami", "Miami")
        cfbd(2026, "3", "Miami (OH)")
        cfbd(2027, "1", "USC", "Southern California")
        cfbd(2026, "4", "Unknown University")
        cfbd(2026, "5", "UCLA", classification="fcs")
        cfbd(2026, "6", "San José State")
        cfbd(2026, "7", "San Jose State")
        preserved = TeamAlias(provider="odds", season=2026, source_identity="USC Trojans",
            source_name="USC Trojans", canonical_team="Existing mapping", classification="fbs")
        session.add(preserved)
        session.flush()
        seed_odds_aliases(session)
        rows = {(a.season, a.source_name): a.canonical_team for a in session.scalars(
            select(TeamAlias).where(TeamAlias.provider == "odds"))}
        assert rows == {
            (2026, "USC Trojans"): "Existing mapping",
            (2027, "USC Trojans"): "Southern California",
            (2026, "Miami Hurricanes"): "Miami",
            (2026, "Miami (OH) RedHawks"): "Miami (OH)",
        }
        assert seed_odds_aliases(session) == 0
