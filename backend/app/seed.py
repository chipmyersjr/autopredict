"""Explicit, atomic demo loader. No provider data or startup side effects."""

import argparse
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.database import create_database_engine
from app.models import Game, Market, Selection
from app.settings import Settings

DEMO_NOTES = "Demo data: fictional matchup and odds, not a live schedule or bookmaker quote."


def fixture_id(name: str):
    return uuid5(NAMESPACE_URL, f"autopredict/demo/v1/{name}")


def demo_games(anchor: date) -> list[Game]:
    games = []
    for index, (home, away, line, venue) in enumerate((
        ("USC", "UCLA", "-3.50", "Los Angeles Memorial Coliseum"),
        ("Oregon", "Washington", "-6.50", "Autzen Stadium"),
        ("Michigan", "Ohio State", "0.00", "Michigan Stadium"),
        ("Alabama", "Georgia", "2.50", "Bryant-Denny Stadium"),
        ("Texas", "Oklahoma", None, "Cotton Bowl"),
    ), start=1):
        game = Game(
            id=fixture_id(f"game/{index}"), season=anchor.year, week=5,
            home_team=home, away_team=away,
            start_time=datetime.combine(anchor + timedelta(days=index), time(19), timezone.utc),
            status="scheduled", home_score=None, away_score=None,
            venue=venue, notes=DEMO_NOTES,
        )
        if line is not None:
            market = Market(id=fixture_id(f"market/{index}"), type="spread", status="active", description="Demo spread market")
            for side_index, (team, handicap) in enumerate(((home, Decimal(line)), (away, -Decimal(line)))):
                market.selections.append(Selection(
                    id=fixture_id(f"selection/{index}/{side_index}"), side=team,
                    line=handicap, price=Decimal("1.9091"), is_active=True, notes=DEMO_NOTES,
                ))
            game.markets.append(market)
        games.append(game)
    return games


def validate_fixtures(games: list[Game]) -> None:
    ids = set()
    for game in games:
        for record in [game, *game.markets, *(s for m in game.markets for s in m.selections)]:
            if record.id is None or record.id in ids:
                raise ValueError("Demo IDs must be present and unique")
            ids.add(record.id)
        if game.start_time.tzinfo is None or game.start_time.utcoffset() != timedelta(0):
            raise ValueError("Demo kickoff must be UTC")
        if game.home_team == game.away_team or game.status != "scheduled" or game.home_score is not None or game.away_score is not None:
            raise ValueError("Demo games must have distinct teams and scheduled status with null scores")
        for market in game.markets:
            pair = market.selections
            if market.type != "spread" or market.status != "active" or len(pair) != 2 or {s.side for s in pair} != {game.home_team, game.away_team}:
                raise ValueError("Demo spread requires both matching teams")
            for selection in pair:
                if selection.line is None or not selection.line.is_finite() or selection.line != selection.line.quantize(Decimal("0.01")):
                    raise ValueError("Demo line must be finite with at most two decimal places")
                if not selection.price.is_finite() or selection.price <= 1 or selection.price != selection.price.quantize(Decimal("0.0001")) or not selection.is_active:
                    raise ValueError("Demo decimal price must exceed one with at most four decimal places")
            if pair[0].line + pair[1].line != 0:
                raise ValueError("Demo spread lines must be opposite")


def seed_demo(engine: Engine, games: list[Game]) -> int:
    validate_fixtures(games)
    inserted = 0
    with Session(engine) as session, session.begin():
        for game in games:
            # PostgreSQL arbitrates concurrent seeders; preserve an existing game's entire graph.
            values = {column.name: getattr(game, column.name) for column in Game.__table__.columns if column.name not in {"created_at", "updated_at"}}
            game_id = session.scalar(insert(Game).values(**values).on_conflict_do_nothing(index_elements=[Game.id]).returning(Game.id))
            if game_id is None:
                continue
            for market in game.markets:
                session.execute(insert(Market).values(
                    id=market.id, game_id=game_id, type=market.type,
                    status=market.status, description=market.description,
                ))
                for selection in market.selections:
                    session.execute(insert(Selection).values(
                        id=selection.id, market_id=market.id, side=selection.side,
                        line=selection.line, price=selection.price,
                        is_active=selection.is_active, notes=selection.notes,
                    ))
            inserted += 1
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Load fictional demo games; preserve existing fixtures.")
    parser.add_argument("--anchor-date", type=date.fromisoformat, default=datetime.now(timezone.utc).date(), metavar="YYYY-MM-DD")
    args = parser.parse_args()
    engine = create_database_engine(Settings())
    try:
        inserted = seed_demo(engine, demo_games(args.anchor_date))
        print(f"Demo games inserted: {inserted}; existing fixtures preserved. Anchor: {args.anchor_date}.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
