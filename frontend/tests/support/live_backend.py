"""Disposable PostgreSQL-backed browser server; never touches development fixtures."""
import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import signal
import re
from pathlib import Path
import sys
import multiprocessing
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
from app.seed_strategy import seed_strategy, seed_agent_strategy
from app.seed_user import seed_user
from app.settings import Settings


def fixture_worker(database, ready, control_path):
    """Production execution loop; only external transports are test doubles."""
    import httpx
    from app.agent_services import DuckDuckGoSearch, local_model_client
    from app.predictors import get_predictor
    from app.run_worker import serve

    def controls():
        return json.loads(control_path.read_text()) if control_path.exists() else {}

    class Search:
        def __init__(self, *, timeout):
            assert timeout == 10

        def text(self, query, *, backend, max_results):
            assert backend == 'duckduckgo' and max_results == 5
            if controls().get(query, {}).get('mode') == 'research_failed':
                return []
            return [dict(title='Fictional fixture evidence', href='https://example.test/football',
                         body='Controlled fictional teams have comparable recent form.')]

    async def chat(request):
        body = json.loads(request.content)
        # Keep processing observable for close/reopen and worker restart checks.
        await asyncio.sleep(.3)
        messages = body['messages']
        context = json.loads(messages[1]['content'])
        game_id = context['game_id']
        with Session(engine) as session:
            attempts = session.scalar(select(RunGame.attempts).join(Run).where(
                RunGame.game_id == UUID(game_id), Run.execution_status == 'running'))
        while controls().get(game_id, {}).get('hold_attempt') == attempts:
            await asyncio.sleep(.05)
        mode = controls().get(game_id, {}).get('mode')
        if mode == 'unavailable' or (mode == 'retry_once' and attempts == 1):
            return httpx.Response(503, json={'error': 'controlled unavailable'})
        if mode == 'invalid':
            return httpx.Response(200, json=dict(model='fixture-model', done=True,
                message=dict(role='assistant', content='{}')))
        if messages[-1]['role'] != 'tool':
            message = dict(role='assistant', content='', tool_calls=[dict(function=dict(
                name='web_search', arguments={'query': game_id}))])
        else:
            context = json.loads(messages[1]['content'])
            evidence = json.loads(messages[-1]['content'])['untrusted_evidence']
            assert evidence[0]['url'] == 'https://example.test/football'
            message = dict(role='assistant', content=json.dumps(dict(
                selection_id=context['selections'][0]['selection_id'],
                reasoning='Controlled fictional research supports this saved spread selection.')))
        return httpx.Response(200, json=dict(model='fixture-model', message=message, done=True))

    engine = guarded_engine_from_database(database)
    async def run():
        settings = Settings(_env_file=None, postgres_db=database,
                            ollama_host='http://fixture.invalid', ollama_model='fixture-model')
        search = DuckDuckGoSearch(factory=Search)
        try:
            async with local_model_client(settings, transport=httpx.MockTransport(chat)) as client:
                with engine.connect() as connection:
                    connection.execute(text('SELECT 1 FROM runs LIMIT 1'))
                ready.send(True)
                ready.close()
                await serve(engine, lambda kind, config: get_predictor(
                    kind, config, client=client, search=search, model=settings.ollama_model))
        finally:
            await search.aclose()
    try:
        asyncio.run(run())
    finally:
        engine.dispose()


def guarded_engine_from_database(database):
    if not re.fullmatch(r'autopredict_browser_[0-9a-f]{32}', database):
        raise ValueError('Only generated browser databases may be mutated')
    return create_database_engine(Settings(_env_file=None, postgres_db=database))


def guarded_engine(metadata):
    database = json.loads(metadata.read_text())['database']
    return guarded_engine_from_database(database)


async def serve_fixture(args, database):
    import uvicorn
    context = multiprocessing.get_context('spawn')
    worker = None
    server = uvicorn.Server(uvicorn.Config('app.main:app', host='127.0.0.1',
                                         port=args.port, log_level='warning'))

    async def start_worker():
        nonlocal worker
        receiver, sender = context.Pipe(duplex=False)
        worker = context.Process(target=fixture_worker, args=(database, sender,
            args.metadata.with_suffix('.control.json')))
        worker.start()
        sender.close()
        try:
            deadline = asyncio.get_running_loop().time() + 20
            while not receiver.poll():
                if not worker.is_alive() or asyncio.get_running_loop().time() > deadline:
                    raise RuntimeError('Fixture worker failed readiness')
                await asyncio.sleep(.05)
            assert receiver.recv() is True
        finally:
            receiver.close()

    def publish():
        temporary = args.metadata.with_suffix(args.metadata.suffix + '.tmp')
        temporary.write_text(json.dumps(dict(database=database, pid=os.getpid(),
            worker_pid=worker.pid if worker else None)))
        temporary.replace(args.metadata)

    api = None
    try:
        if args.agent_worker:
            await start_worker()
        api = asyncio.create_task(server.serve())
        while not server.started:
            if api.done():
                await api
                raise RuntimeError('Fixture API failed readiness')
            await asyncio.sleep(.05)
        publish()
        print('Disposable browser backend ready', flush=True)
        while not api.done():
            if worker and not worker.is_alive():
                worker.join()
                await start_worker()
                publish()
            await asyncio.sleep(.1)
        await api
    finally:
        server.should_exit = True
        if api and not api.done():
            await api
        if worker:
            if worker.is_alive():
                worker.terminate()
            await asyncio.to_thread(worker.join, 10)
            if worker.is_alive():
                worker.kill()
                worker.join()


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
                if restore:
                    game.status = 'scheduled'
                    game.home_score = game.away_score = None
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
            rows = session.scalars(select(RunGame).where(RunGame.run_id == run.id)
                                   .order_by(RunGame.position)).all()
            print(json.dumps({'run': record(run), 'bets': [record(bet) for bet in bets],
                              'games': [record(row) for row in rows]}, default=str))
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8017)
    parser.add_argument('--origin', default='http://127.0.0.1:5187')
    parser.add_argument('--agent-worker', action='store_true',
                        help='Run the durable worker with controlled local model/search transports')
    parser.add_argument('--mutate-run')
    parser.add_argument('--restore-run')
    parser.add_argument('--inspect-run')
    parser.add_argument('--control', help='Per-fictional-game transport controls as JSON')
    parser.add_argument('--quote-run', help='Change only fictional current prices during research')
    parser.add_argument('--restart-worker', action='store_true')
    parser.add_argument('--finalize-run')
    parser.add_argument('--results', type=Path, help='JSON mapping game UUIDs to status/home_score/away_score')
    args = parser.parse_args()
    if args.control is not None or args.quote_run or args.restart_worker:
        engine = guarded_engine(args.metadata)
        try:
            if args.control is not None:
                values = json.loads(args.control)
                known = {str(game.id) for game in demo_games(date.today())}
                if not isinstance(values, dict) or not values.keys() <= known:
                    raise ValueError('Controls require known fictional game IDs')
                for value in values.values():
                    if (not isinstance(value, dict) or not value.keys() <= {'mode', 'hold_attempt'}
                        or value.get('mode') not in {None, 'retry_once', 'unavailable', 'invalid', 'research_failed'}
                        or value.get('hold_attempt') not in {None, 1, 2}):
                        raise ValueError('Invalid transport control')
                target = args.metadata.with_suffix('.control.json')
                temporary = target.with_suffix('.tmp')
                temporary.write_text(json.dumps(values))
                temporary.replace(target)
            if args.quote_run:
                with Session(engine) as session, session.begin():
                    ids = [game.id for game in run_games(session, args.quote_run)]
                    for selection in session.scalars(select(Selection).join(Market).where(Market.game_id.in_(ids))):
                        selection.price += Decimal('.0100')
            if args.restart_worker:
                info = json.loads(args.metadata.read_text())
                if not info.get('worker_pid'):
                    raise ValueError('Agent worker was not enabled')
                os.kill(info['worker_pid'], signal.SIGTERM)
        finally:
            engine.dispose()
        return
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
        seed_agent_strategy(engine)
        seed_user(engine)
        asyncio.run(serve_fixture(args, database))
    finally:
        if engine:
            engine.dispose()
        args.metadata.unlink(missing_ok=True)
        args.metadata.with_suffix('.control.json').unlink(missing_ok=True)
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        admin.dispose()


if __name__ == '__main__':
    main()
