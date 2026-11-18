"""Real HTTP handoff using the same disposable server as FE-04 (no providers)."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from uuid import UUID

from app.models import Bet, Game
from app.settings import Settings

HELPER = Path(__file__).resolve().parents[2] / 'frontend/tests/support/live_backend.py'
spec = importlib.util.spec_from_file_location('live_backend', HELPER)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.mark.parametrize('database', ['autopredict', 'autopredict_browser_' + 'g' * 32,
                                      'autopredict_browser_' + 'a' * 31])
def test_mutation_guard_before_connection(tmp_path, monkeypatch, database):
    metadata = tmp_path / 'metadata.json'
    metadata.write_text(json.dumps({'database': database}))
    def forbidden(*args, **kwargs):
        pytest.fail('Unsafe database must be rejected before connecting')
    monkeypatch.setattr(fixture, 'create_database_engine', forbidden)
    with pytest.raises(ValueError):
        fixture.mutate(metadata, str(uuid4()))
    with pytest.raises(ValueError):
        fixture.finalize(metadata, str(uuid4()), {})


def test_http_resolution_handoff(tmp_path):
    if os.environ.get('RUN_POSTGRES_TESTS') != '1':
        pytest.skip('Set RUN_POSTGRES_TESTS=1 for disposable PostgreSQL tests')
    metadata = tmp_path / 'backend.json'
    results_file = tmp_path / 'results.json'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'CFBD_API_KEY': '', 'ODDS_API_KEY': '',
           'PYTHONDONTWRITEBYTECODE': '1'}
    base = [sys.executable, str(HELPER), '--metadata', str(metadata)]
    database = None
    with (tmp_path / 'server.log').open('w+') as log:
        process = subprocess.Popen(base + ['--port', str(port), '--origin', 'http://127.0.0.1:5187'],
                                   env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=5) as client:
                deadline = time.monotonic() + 45
                while True:
                    if process.poll() is not None:
                        log.seek(0)
                        pytest.fail(log.read())
                    try:
                        if metadata.exists() and client.get('/api/ready').status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert time.monotonic() < deadline, 'Fixture readiness timed out'
                    time.sleep(.1)
                database = json.loads(metadata.read_text())['database']
                games = client.get('/api/games?window=current').json()
                assert len(games) == 5
                strategy = client.get('/api/strategies').json()[0]
                payload = dict(strategy_id=strategy['id'], game_ids=[g['id'] for g in games],
                               starting_bankroll='100.00', stake_per_bet='10.00')
                headers = {'Idempotency-Key': str(uuid4())}
                response = client.post('/api/runs', json=payload, headers=headers)
                assert response.status_code == 201, response.text
                saved = response.json()
                bets = saved['bets']
                assert len(bets) == 4
                assert all(b['line'] == '0.00' and b['price'] == '1.9500' for b in bets)
                path = '/api/runs/' + saved['run']['id']
                assert client.post(path + '/settle').json()['settled_bet_ids'] == []

                # A known Run alone must not authorize mutation of an unrelated Game.
                engine = fixture.guarded_engine(metadata)
                try:
                    with pytest.raises(ValueError):
                        fixture.finalize(metadata, str(uuid4()), {
                            bets[0]['game_id']: dict(status='canceled', home_score=None, away_score=None)})
                    with pytest.raises(ValueError):
                        fixture.finalize(metadata, saved['run']['id'], {
                            bets[0]['game_id']: dict(status='canceled', home_score=None, away_score=None),
                            str(uuid4()): dict(status='completed', home_score=1, away_score=0)})
                    with Session(engine) as session:
                        assert session.get(Game, UUID(bets[0]['game_id'])).status == 'scheduled'
                finally:
                    engine.dispose()

                def finalize(results):
                    results_file.write_text(json.dumps(results))
                    command = subprocess.run(base + ['--finalize-run', saved['run']['id'],
                                                     '--results', str(results_file)],
                                             env=env, capture_output=True, text=True, timeout=15)
                    assert command.returncode == 0, command.stderr

                results = {}
                for index, bet in enumerate(bets[:3]):
                    home = bet['side'] in ('home', bet['home_team'])
                    # Independent zero-line oracle: chosen team wins, loses, ties.
                    scores = ((21, 14) if home else (14, 21)) if index == 0 else (
                        ((14, 21) if home else (21, 14)) if index == 1 else (7, 7))
                    results[bet['game_id']] = dict(status='completed', home_score=scores[0], away_score=scores[1])
                finalize(results)
                # Existing quote/participant mutation interface must preserve snapshots.
                mutation = subprocess.run(base + ['--mutate-run', saved['run']['id']],
                                          env=env, capture_output=True, text=True, timeout=15)
                assert mutation.returncode == 0, mutation.stderr
                assert client.get(path + '/bets').json() == bets
                partial = client.post(path + '/settle').json()
                assert [b['result'] for b in partial['bets']] == ['won', 'lost', 'pushed', None]
                assert [b['profit'] for b in partial['bets']] == ['9.50', '-10.00', '0.00', None]
                for field, expected in dict(total_profit='-0.50', committed_stake='10.00',
                                            available_bankroll='89.50', current_bankroll='99.50',
                                            roi='-0.0050').items():
                    assert partial['run'][field] == expected
                assert partial['run']['final_bankroll'] is partial['run']['end_time'] is None
                # Treat the first POST response as lost; retry cannot duplicate profit.
                assert client.post(path + '/settle').json() == {**partial, 'settled_bet_ids': []}
                assert client.get(path).json() == partial['run']
                pending = bets[3]['game_id']
                finalize({pending: dict(status='completed', home_score=None, away_score=None)})
                assert client.post(path + '/settle').json()['pending_games'] == [
                    {'game_id': pending, 'reason': 'final_scores_missing'}]
                finalize({pending: dict(status='canceled', home_score=None, away_score=None)})
                complete = client.post(path + '/settle').json()
                assert complete['run']['status'] == 'completed'
                assert complete['run']['final_bankroll'] == complete['run']['available_bankroll'] == '99.50'
                assert complete['run']['committed_stake'] == '0.00'
                assert complete['bets'][3]['result'] == 'void'
                assert client.post(path + '/settle').json() == {**complete, 'settled_bet_ids': []}
                assert client.get(path).json() == complete['run']
                assert client.get(path + '/bets').json() == complete['bets']
                replay = client.post('/api/runs', json=payload, headers=headers).json()
                assert replay['run'] == complete['run'] and replay['bets'] == complete['bets']
                dashboard = client.get('/api/dashboard').json()
                assert dashboard['realized_profit'] == '-0.50'
                assert dashboard['current_bankroll_total'] == '99.50'
                assert dashboard['roi'] == '-0.0050'
                assert [dashboard[k] for k in ('win_count', 'loss_count', 'push_count', 'void_count')] == [1, 1, 1, 1]
                engine = fixture.guarded_engine(metadata)
                try:
                    with Session(engine) as session:
                        for index, original in enumerate(bets):
                            persisted = session.get(Bet, UUID(original['id']))
                            assert persisted.side == original['side']
                            assert str(persisted.line) == original['line']
                            assert str(persisted.price) == original['price']
                            assert str(persisted.profit) == ['9.50', '-10.00', '0.00', '0.00'][index]
                            assert persisted.settled_at is not None
                            assert persisted.settlement_game_status == ('canceled' if index == 3 else 'completed')
                finally:
                    engine.dispose()
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                pytest.fail('Fixture did not cleanly terminate')
        assert not metadata.exists()
        admin = create_engine(Settings(_env_file=None).database_url.set(database='postgres'))
        try:
            with admin.connect() as connection:
                assert connection.scalar(text('SELECT count(*) FROM pg_database WHERE datname=:name'),
                                         {'name': database}) == 0
        finally:
            admin.dispose()
