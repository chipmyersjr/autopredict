"""Disposable PostgreSQL-backed browser server; never touches development fixtures."""
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import signal
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
from app.models import Game, RunGame, Selection, Market
from app.seed import demo_games, seed_demo
from app.seed_strategy import seed_strategy
from app.seed_user import seed_user
from app.settings import Settings


def mutate(metadata, run_id):
    database = json.loads(metadata.read_text())['database']
    if not database.startswith('autopredict_browser_') or len(database) != len('autopredict_browser_') + 32:
        raise ValueError('Only generated browser databases may be mutated')
    os.environ['POSTGRES_DB'] = database
    engine = create_database_engine(Settings())
    try:
        with Session(engine) as session:
            ids = session.scalars(select(RunGame.game_id).where(RunGame.run_id == UUID(run_id))).all()
            if not ids:
                raise ValueError('Run must exist in the disposable database')
            for game in session.scalars(select(Game).where(Game.id.in_(ids))):
                game.home_team = 'Changed current home'
                game.away_team = 'Changed current away'
                game.start_time = datetime.now(timezone.utc) - timedelta(days=14)
            for selection in session.scalars(select(Selection).join(Market).where(Market.game_id.in_(ids))):
                selection.line = Decimal('0.00')
                selection.price = Decimal('3.1234')
            session.commit()
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8017)
    parser.add_argument('--origin', default='http://127.0.0.1:5187')
    parser.add_argument('--mutate-run')
    args = parser.parse_args()
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
    settings = Settings()
    admin = create_engine(settings.database_url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    engine = None
    try:
        os.environ['POSTGRES_DB'] = database
        os.environ['CORS_ORIGINS'] = json.dumps([args.origin])
        command.upgrade(Config(str(ROOT / 'backend/alembic.ini')), 'head')
        engine = create_database_engine(Settings())
        games = demo_games(date.today())
        for index, game in enumerate(games):
            game.start_time = datetime.now(timezone.utc) + timedelta(days=index + 3)
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
