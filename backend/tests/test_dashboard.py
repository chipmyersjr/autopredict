"""Exact dashboard oracles against disposable PostgreSQL history."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import Bet, Game, Run, User
from app.seed_user import LOCAL_USER_ID
from test_runs import api, body, post
from test_run_settlement import create, finals


def dashboard(client):
    response = client.get('/api/dashboard')
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_and_unsettled(api):
    client, engine, games = api
    empty = dashboard(client)
    assert empty['roi'] is None
    assert empty['recent_results'] == empty['performance'] == []
    assert all(value == 0 for key, value in empty.items() if key.endswith('count'))
    for field in ['starting_bankroll_total', 'current_bankroll_total',
                  'available_bankroll_total', 'committed_stake_total', 'realized_profit']:
        assert empty[field] == '0.00'
    create(client, games)
    opened = dashboard(client)
    assert opened['starting_bankroll_total'] == opened['current_bankroll_total'] == '100.00'
    assert opened['committed_stake_total'] == '40.00'
    assert opened['available_bankroll_total'] == '60.00'
    assert opened['roi'] == '0.0000'
    assert opened['bet_count'] == opened['open_bet_count'] == 4
    assert opened['performance'] == opened['recent_results'] == []


def test_partial_completed_ownership_and_weighted_roi(api):
    client, engine, games = api
    saved, _, _ = create(client, games)
    other = post(client, {**body(games), 'starting_bankroll': '900.00'}).json()
    foreign, _, _ = create(client, games)
    with Session(engine) as session:
        user = User(name='Unrelated', email='dashboard@example.local')
        session.add(user)
        session.flush()
        session.get(Run, UUID(foreign['run']['id'])).user_id = user.id
        session.commit()
    finals(engine, saved)
    path = '/api/runs/' + saved['run']['id'] + '/settle'
    assert client.post(path).status_code == 200
    partial = dashboard(client)
    expected = dict(run_count=2, active_run_count=2, completed_run_count=0,
                    starting_bankroll_total='1000.00', current_bankroll_total='999.50',
                    available_bankroll_total='949.50', committed_stake_total='50.00',
                    realized_profit='-0.50', roi='-0.0005', bet_count=8,
                    open_bet_count=5, win_count=1, loss_count=1, push_count=1, void_count=0)
    assert {key: partial[key] for key in expected} == expected
    assert len(partial['recent_results']) == 3
    with Session(engine) as session:
        for index, item in enumerate(saved['bets'][:3]):
            session.get(Bet, UUID(item['id'])).settled_at = datetime.fromisoformat(
                '2026-10-01T23:59:59+00:00' if index == 0 else '2026-10-02T00:00:00+00:00')
        session.commit()
    assert dashboard(client)['performance'] == [
        {'date': '2026-10-01', 'profit': '9.50', 'cumulative_profit': '9.50'},
        {'date': '2026-10-02', 'profit': '-10.00', 'cumulative_profit': '-0.50'}]
    with Session(engine) as session:
        session.get(Game, UUID(saved['bets'][-1]['game_id'])).status = 'canceled'
        session.commit()
    assert client.post(path).status_code == 200
    complete = dashboard(client)
    assert complete['completed_run_count'] == complete['active_run_count'] == 1
    assert complete['committed_stake_total'] == '40.00'
    assert complete['void_count'] == 1
    assert complete['realized_profit'] == '-0.50'
    # Reading never settles the other Run, even with final stored results.
    assert client.get('/api/runs/'+other['run']['id']).json()['total_profit'] is None


def test_utc_performance_ties_limit_and_zero_profit(api):
    client, engine, games = api
    runs = [create(client, games)[0] for _ in range(4)]
    with Session(engine) as session:
        for game in session.scalars(select(Game)):
            game.status = 'canceled'
        session.commit()
    for saved in runs:
        assert client.post('/api/runs/'+saved['run']['id']+'/settle').status_code == 200
    before = datetime.fromisoformat('2026-10-02T01:59:59+02:00')
    after = datetime.fromisoformat('2026-10-01T17:00:00-07:00')
    with Session(engine) as session:
        bets = session.scalars(select(Bet).order_by(Bet.id)).all()
        ids = [str(b.id) for b in bets]
        for index, bet in enumerate(bets):
            bet.settled_at = before if index < 4 else after
        session.commit()
    result = dashboard(client)
    assert result['recent_results'][0]['settled_at'] == '2026-10-02T00:00:00+00:00'
    assert [b['id'] for b in result['recent_results']] == ids[4:14]
    assert result['performance'] == [
        {'date': '2026-10-01', 'profit': '0.00', 'cumulative_profit': '0.00'},
        {'date': '2026-10-02', 'profit': '0.00', 'cumulative_profit': '0.00'}]
    assert result['roi'] == '0.0000'
    assert result['void_count'] == 16
    assert result['available_bankroll_total'] == '400.00'


def test_snapshot_consistency_and_bounded_queries(api):
    client, engine, games = api
    saved, _, _ = create(client, games)
    finals(engine, saved)
    assert client.post('/api/runs/'+saved['run']['id']+'/settle').status_code == 200
    statements = []
    changed = False

    def settle_between(conn, cursor, statement, parameters, context, many):
        nonlocal changed
        if not changed and statement.startswith('SELECT') and 'FROM runs' in statement:
            changed = True
            with Session(engine) as writer:
                writer.get(Game, UUID(saved['bets'][-1]['game_id'])).status = 'canceled'
                writer.commit()
            from app.runs import settle_run
            with Session(engine) as writer:
                settle_run(writer, UUID(saved['run']['id']))

    def record(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(engine, 'before_cursor_execute', record)
    event.listen(engine, 'after_cursor_execute', settle_between)
    try:
        snapshot = dashboard(client)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
        event.remove(engine, 'after_cursor_execute', settle_between)
    assert changed
    assert snapshot['active_run_count'] == 1
    assert snapshot['open_bet_count'] == 1
    assert snapshot['void_count'] == 0
    assert len(snapshot['recent_results']) == 3
    assert dashboard(client)['void_count'] == 1
    # Count dashboard statements alone on a subsequent request.
    statements.clear()
    event.listen(engine, 'before_cursor_execute', record)
    try:
        dashboard(client)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert len(statements) == 6  # READ ONLY + User + four bounded queries
    assert all(s.startswith('SELECT') or s == 'SET TRANSACTION READ ONLY' for s in statements)
