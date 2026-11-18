"""Disposable PostgreSQL-backed browser server; never touches development fixtures."""
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import signal
import re
from pathlib import Path
import sys
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from app.database import create_database_engine
from app.models import Bet, Game, Run, RunGame, Selection, Market
from app.ingress import current_week
from app.seed import demo_games, seed_demo
from app.seed_strategy import seed_strategy
from app.seed_user import seed_user
from app.settings import Settings


def guarded_engine(metadata):
    database = json.loads(metadata.read_text())['database']
    if not re.fullmatch(r'autopredict_browser_[0-9a-f]{32}', database):
        raise ValueError('Only generated browser databases may be mutated')
    return create_database_engine(Settings(_env_file=None, postgres_db=database))


def run_games(session, run_id):
    ids = session.scalars(select(RunGame.game_id).where(RunGame.run_id == UUID(run_id))).all()
    games = list(session.scalars(select(Game).where(Game.id.in_(ids))))
    known = {game.id for game in demo_games(date.today())}
    if not games or any(game.id not in known for game in games):
        raise ValueError('Run must contain only known fictional fixture games')
    return games


def finalize(metadata, run_id, results):
    """Only fixture Games change; saved Bets and settlement remain API-owned."""
    engine = guarded_engine(metadata)
    try:
        with Session(engine) as session, session.begin():
            games = {str(game.id): game for game in run_games(session, run_id)}
            if not isinstance(results, dict) or not results or not results.keys() <= games.keys():
                raise ValueError('Results must name known games in this Run')
            for game_id, result in results.items():
                if not isinstance(result, dict) or set(result) != {'status', 'home_score', 'away_score'}:
                    raise ValueError('Expected status, home_score and away_score')
                if result['status'] not in {'completed', 'canceled'}:
                    raise ValueError('Expected completed or canceled')
                if any(score is not None and (type(score) is not int or not 0 <= score <= 2147483647)
                       for score in (result['home_score'], result['away_score'])):
                    raise ValueError('Scores must be nonnegative integers or null')
            for game_id, result in results.items():
                for field, value in result.items():
                    setattr(games[game_id], field, value)
    finally:
        engine.dispose()


def mutate(metadata, run_id, restore=False):
    engine = guarded_engine(metadata)
    try:
        with Session(engine) as session:
            games = run_games(session, run_id)
            ids = [game.id for game in games]
            originals = {game.id: game for game in demo_games(date.today())}
            now = datetime.now(timezone.utc)
            for game in games:
                game.home_team = originals[game.id].home_team if restore else 'Changed current home'
                game.away_team = originals[game.id].away_team if restore else 'Changed current away'
                game.start_time = now + (current_week(now).end - now) / 2 if restore else now - timedelta(days=14)
            for selection in session.scalars(select(Selection).join(Market).where(Market.game_id.in_(ids))):
                selection.line = Decimal('0.00')
                selection.price = Decimal('1.9500') if restore else Decimal('3.1234')
            session.commit()
    finally:
        engine.dispose()


def inspect_run(metadata, run_id):
    """Read persisted evidence only, behind the same disposable database guard."""
    engine = guarded_engine(metadata)
    try:
        with Session(engine) as session:
            run_games(session, run_id)
            run = session.get(Run, UUID(run_id))
            bets = session.scalars(select(Bet).where(Bet.run_id == UUID(run_id))).all()
            def record(row):
                return {column.name: getattr(row, column.name) for column in row.__table__.columns}
            print(json.dumps({'run': record(run), 'bets': [record(bet) for bet in bets]}, default=str))
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8017)
    parser.add_argument('--origin', default='http://127.0.0.1:5187')
    parser.add_argument('--mutate-run')
    parser.add_argument('--restore-run')
    parser.add_argument('--inspect-run')
    parser.add_argument('--finalize-run')
    parser.add_argument('--results', type=Path, help='JSON mapping game UUIDs to status/home_score/away_score')
    args = parser.parse_args()
    if args.restore_run:
        if args.mutate_run or args.finalize_run or args.results or args.inspect_run:
            parser.error('--restore-run excludes other actions')
        mutate(args.metadata, args.restore_run, restore=True)
        return
    if args.inspect_run:
        if args.mutate_run or args.finalize_run or args.results:
            parser.error('--inspect-run excludes mutations')
        inspect_run(args.metadata, args.inspect_run)
        return
    if args.finalize_run:
        if args.mutate_run or not args.results:
            parser.error('--finalize-run requires --results and excludes --mutate-run')
        finalize(args.metadata, args.finalize_run, json.loads(args.results.read_text()))
        return
    if args.results:
        parser.error('--results requires --finalize-run')
    if args.mutate_run:
        mutate(args.metadata, args.mutate_run)
        return
    import uvicorn
    # Uvicorn replays termination signals after shutdown. Convert that replay
    # to an exception so the outer finally always removes the test database.
    def terminate(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    database = 'autopredict_browser_' + uuid4().hex
    settings = Settings(_env_file=None)
    admin = create_engine(settings.database_url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    engine = None
    try:
        os.environ['POSTGRES_DB'] = database
        os.environ['CORS_ORIGINS'] = json.dumps([args.origin])
        command.upgrade(Config(str(ROOT / 'backend/alembic.ini')), 'head')
        engine = create_database_engine(Settings(_env_file=None))
        games = demo_games(date.today())
        now = datetime.now(timezone.utc)
        # Fit even late Sunday into the current Pacific week, before its end.
        kickoff = now + (current_week(now).end - now) / 2
        for game in games:
            game.start_time = kickoff
            for market in game.markets:
                for selection in market.selections:
                    selection.line = Decimal('0.00')
                    selection.price = Decimal('1.9500')
        seed_demo(engine, games)
        seed_strategy(engine)
        seed_user(engine)
        args.metadata.write_text(json.dumps({'database': database, 'pid': os.getpid()}))
        print('Disposable browser backend ready', flush=True)
        uvicorn.run('app.main:app', host='127.0.0.1', port=args.port, log_level='warning')
    finally:
        if engine:
            engine.dispose()
        args.metadata.unlink(missing_ok=True)
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        admin.dispose()


if __name__ == '__main__':
    main()
