"""Settlement uses only fictional data in generated PostgreSQL databases."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import Bet, Game, Selection
from test_runs import api, body, finished_post as post


def create(client, games):
    payload = {**body(games), 'starting_bankroll': '100.00'}
    key = uuid4()
    saved = post(client, payload, key).json()
    return saved, payload, key


def finals(engine, saved):
    # Known oracle: win 9.50, loss -10, push 0, pending.
    with Session(engine) as session:
        for index, item in enumerate(saved['bets']):
            bet = session.get(Bet, UUID(item['id']))
            bet.side = 'home' if index % 2 == 0 else bet.away_team
            bet.line = Decimal('0.00')
            bet.price = Decimal('1.9500')
            game = session.get(Game, bet.game_id)
            game.home_team = 'Refreshed label'
            if index < 3:
                game.status = 'completed'
                game.home_score, game.away_score = [(21, 14), (21, 14), (7, 7)][index]
        for selection in session.scalars(select(Selection)):
            selection.price = Decimal('3.0000')
        session.commit()


def test_mixed_retry_history_replay_and_completion(api):
    client, engine, games = api
    saved, payload, key = create(client, games)
    path = '/api/runs/' + saved['run']['id']
    assert client.post(path+'/settle').json()['settled_bet_ids'] == []
    finals(engine, saved)
    response = client.post(path+'/settle')
    assert response.status_code == 200, response.text
    partial = response.json()
    run = partial['run']
    for field, expected in {'total_profit':'-0.50', 'committed_stake':'10.00',
                            'available_bankroll':'89.50', 'current_bankroll':'99.50',
                            'roi':'-0.0050', 'settled_stake':'30.00'}.items():
        assert run[field] == expected
    assert run['end_time'] is run['final_bankroll'] is None
    assert [b['result'] for b in partial['bets']] == ['won','lost','pushed',None]
    assert [run[f] for f in ['win_count','loss_count','push_count','void_count','open_bet_count']] == [1,1,1,0,1]
    retry = client.post(path+'/settle').json()
    assert retry == {**partial, 'settled_bet_ids': []}
    replay = post(client, payload, key)
    assert replay.status_code == 200 and replay.json()['run'] == run
    assert replay.json()['bets'] == partial['bets']
    pending_id = UUID(partial['pending_games'][0]['game_id'])
    with Session(engine) as session:
        pending = session.get(Game, pending_id)
        pending.status = 'completed'
        session.commit()
    assert client.post(path+'/settle').json()['pending_games'][0]['reason'] == 'final_scores_missing'
    with Session(engine) as session:
        session.get(Game, pending_id).status = 'canceled'
        session.commit()
    complete = client.post(path+'/settle').json()
    assert complete['run']['status'] == 'completed'
    assert complete['run']['final_bankroll'] == complete['run']['available_bankroll'] == '99.50'
    assert complete['run']['committed_stake'] == '0.00'
    assert complete['run']['void_count'] == 1
    # Corrections cannot regrade settled evidence.
    with Session(engine) as session:
        for game in session.scalars(select(Game)):
            game.status, game.home_score, game.away_score = 'completed', 0, 99
        session.commit()
    assert client.post(path+'/settle').json() == {**complete, 'settled_bet_ids': []}
    statements = []
    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        assert client.get(path).json() == complete['run']
        assert client.get(path+'/bets').json() == complete['bets']
        client.get('/api/runs')
        client.get('/api/bets/'+complete['bets'][0]['id'])
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert all(s.lstrip().upper().startswith('SELECT') for s in statements)


def test_concurrent_and_independent_runs(api):
    client, engine, games = api
    saved, _, _ = create(client, games)
    other, _, _ = create(client, games)
    finals(engine, saved)
    path = '/api/runs/'+saved['run']['id']+'/settle'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(path), range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert sorted(len(r.json()['settled_bet_ids']) for r in responses) == [0,3]
    assert client.get('/api/runs/'+other['run']['id']).json()['total_profit'] is None
    assert client.post('/api/runs/'+other['run']['id']+'/settle').status_code == 200


@pytest.mark.parametrize('failure', ['snapshot', 'overflow', 'database'])
def test_atomic_rollback(api, monkeypatch, failure):
    client, engine, games = api
    saved, _, _ = create(client, games)
    finals(engine, saved)
    if failure == 'database':
        from app.runs import resolve_spread
        calls = []
        def fail(**kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise OperationalError(None, None, Exception('private'))
            return resolve_spread(**kwargs)
        monkeypatch.setattr('app.runs.resolve_spread', fail)
    else:
        with Session(engine) as session:
            bet = session.get(Bet, UUID(saved['bets'][2]['id']))
            if failure == 'snapshot':
                bet.side = 'unknown'
            else:
                bet.stake, bet.price = Decimal('9999999999.99'), Decimal('999999.9999')
                game = session.get(Game, bet.game_id)
                game.home_score, game.away_score = 99, 0
            session.commit()
    response = client.post('/api/runs/'+saved['run']['id']+'/settle')
    assert response.status_code == (503 if failure == 'database' else 409), response.text
    with Session(engine) as session:
        assert all(b.status == 'open' and b.profit is None for b in session.scalars(select(Bet)))
    assert client.get('/api/runs/'+saved['run']['id']).json()['total_profit'] is None


def test_input_and_ownership(api):
    client, engine, games = api
    saved, _, _ = create(client, games)
    path = '/api/runs/'+saved['run']['id']+'/settle'
    for content in ['{}','null','{"home_score":21}','broken']:
        assert client.post(path, content=content).status_code == 422
    assert client.post('/api/runs/bad/settle').status_code == 422
    assert client.post('/api/runs/'+str(uuid4())+'/settle').status_code == 404
    from app.models import Run, User
    with Session(engine) as session:
        owner = User(name='Other', email='settlement@example.local')
        session.add(owner)
        session.flush()
        session.get(Run, UUID(saved['run']['id'])).user_id = owner.id
        session.commit()
    assert client.post(path).status_code == 404


def test_openapi():
    from app.main import app
    operation = app.openapi()['paths']['/api/runs/{run_id}/settle']['post']
    assert 'requestBody' not in operation
    assert set(operation['responses']) >= {'200','404','409','422','503'}


def test_score_writer_lock_and_refresh_after_wait(api):
    import threading
    client, engine, games = api
    saved, _, _ = create(client, games)
    finals(engine, saved)
    started = threading.Event()
    finished = threading.Event()
    path = '/api/runs/'+saved['run']['id']+'/settle'
    # A result writer holds the Game lock. Settlement must wait and resolve the
    # newly committed scores, rather than a pre-lock identity-map value.
    with Session(engine) as writer:
        game = writer.scalar(select(Game).where(Game.id == UUID(saved['bets'][0]['game_id'])).with_for_update())
        game.home_score, game.away_score = 0, 21
        def settle():
            started.set()
            response = client.post(path)
            finished.set()
            return response
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(settle)
            assert started.wait(2)
            assert not finished.wait(.15)
            writer.commit()
            response = future.result(timeout=5)
    assert response.status_code == 200, response.text
    assert response.json()['bets'][0]['result'] == 'lost'
    assert response.json()['run']['total_profit'] == '-20.00'


def test_injected_commit_failure_and_restart_retry(api, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    client, engine, games = api
    saved, _, _ = create(client, games)
    finals(engine, saved)
    path = '/api/runs/'+saved['run']['id']+'/settle'
    original = Session.commit
    def fail(session):
        raise OperationalError(None, None, Exception('private database detail'))
    with monkeypatch.context() as patch:
        patch.setattr(Session, 'commit', fail)
        response = client.post(path)
        assert response.status_code == 503
        assert response.json() == {'detail':'Database unavailable'}
    assert Session.commit is original
    with TestClient(app) as restarted:
        settled = restarted.post(path).json()
    with TestClient(app) as restarted:
        assert restarted.post(path).json() == {**settled, 'settled_bet_ids': []}
        assert restarted.get('/api/runs/'+saved['run']['id']).json() == settled['run']
