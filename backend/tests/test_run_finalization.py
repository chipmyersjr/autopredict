"""Atomic best-effort execution with controlled predictions and disposable DBs."""
import asyncio
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import Bet, Game, RunGame, Selection
from app.predictors import AgentDecision, Prediction
from app.run_worker import (LostClaim, begin_attempt, claim_next, finalize,
                            process_claim, release, save_attempt)
from app.seed import demo_games, seed_demo
from app.seed_strategy import AGENT_STRATEGY_ID, seed_agent_strategy
from test_runs import NOW, api, body, post


def predict_remaining(engine, claim):
    while (work := begin_attempt(engine, claim)) is not None:
        row_id, value, *_ = work
        save_attempt(engine, claim, row_id,
                     prediction=Prediction(selection_id=value.selections[0].selection_id))


@pytest.mark.parametrize('change', ['price', 'line', 'selection', 'teams', 'kickoff'])
def test_changed_inputs_retry_only_affected_game(api, change):
    client, engine, games = api
    key = uuid4()
    accepted = post(client, body(games[:2]), key).json()
    claim = claim_next(engine)
    predict_remaining(engine, claim)
    with Session(engine) as session, session.begin():
        game = session.get(Game, games[0].id)
        pair = game.markets[0].selections
        if change == 'price':
            pair[0].price = Decimal('2.0000')
        elif change == 'line':
            pair[0].line, pair[1].line = Decimal('-7'), Decimal('7')
        elif change == 'selection':
            original = pair[0]
            original.is_active = False
            game.markets[0].selections.append(Selection(
                side=original.side, line=original.line, price=original.price, is_active=True))
        elif change == 'teams':
            old = game.home_team
            game.home_team = 'Updated home alias'
            next(s for s in pair if s.side == old).side = game.home_team
        else:
            game.start_time += timedelta(hours=1)
    assert finalize(engine, claim) is False
    # No partial Bets are visible while a changed game is retried.
    assert client.get('/api/runs/'+accepted['run']['id']+'/bets').json() == []
    row_id, fresh, *_ = begin_attempt(engine, claim)
    assert fresh.game_id == games[0].id
    save_attempt(engine, claim, row_id,
                 prediction=Prediction(selection_id=fresh.selections[0].selection_id))
    assert finalize(engine, claim) is True
    saved = post(client, body(games[:2]), key).json()
    assert saved['run']['execution_status'] == 'completed' and len(saved['bets']) == 2
    assert saved['bets'][0]['home_team'] == fresh.home_team
    assert saved['bets'][0]['kickoff_at_placement'] == fresh.kickoff.isoformat()
    with Session(engine) as session:
        rows = session.scalars(select(RunGame).where(RunGame.run_id == claim.run_id)
                               .order_by(RunGame.position)).all()
        assert [row.attempts for row in rows] == [2, 1]
    with pytest.raises(LostClaim):
        finalize(engine, claim)
    assert post(client, body(games[:2]), key).json() == saved
    assert claim_next(engine) is None


def test_second_quote_change_skips_and_preserves_other_success(api):
    client, engine, games = api
    key = uuid4()
    accepted = post(client, body(games[:2]), key).json()
    claim = claim_next(engine)
    for price in ('2.0000', '3.0000'):
        predict_remaining(engine, claim)
        with Session(engine) as session, session.begin():
            session.get(Selection, games[0].markets[0].selections[0].id).price = Decimal(price)
        finished = finalize(engine, claim)
    assert finished is True
    saved = post(client, body(games[:2]), key).json()
    assert saved['skipped_games'] == [{'game_id': str(games[0].id), 'reason': 'quote_changed'}]
    assert [b['game_id'] for b in saved['bets']] == [str(games[1].id)]
    assert saved['run']['available_bankroll'] == '30.00'
    assert saved['run']['id'] == accepted['run']['id']


def test_finalization_rollback_retains_predictions_and_recovery(api, monkeypatch):
    from app.runs import DryRunAdapter
    client, engine, games = api
    key = uuid4()
    post(client, body(games[:2]), key)
    claim = claim_next(engine)
    predict_remaining(engine, claim)
    original = DryRunAdapter.record

    def fail(*args):
        original(*args)
        raise RuntimeError('failure after constructing Bets')

    with monkeypatch.context() as patch:
        patch.setattr(DryRunAdapter, 'record', fail)
        with pytest.raises(RuntimeError):
            finalize(engine, claim)
    with Session(engine) as session:
        assert session.scalars(select(Bet)).all() == []
        assert all(row.state == 'predicted' for row in session.scalars(select(RunGame)))
    assert finalize(engine, claim) is True
    saved = post(client, body(games[:2]), key).json()
    assert len(saved['bets']) == 2 and saved['run']['execution_status'] == 'completed'


def test_final_commit_failure_and_expired_writer_recovery(api):
    client, engine, games = api
    key = uuid4()
    accepted = post(client, body(games[:2]), key).json()
    claim = claim_next(engine)
    predict_remaining(engine, claim)

    def fail(session):
        # Flush actual INSERTs before simulating loss at the commit boundary.
        session.flush()
        raise RuntimeError('commit failed')

    event.listen(Session, 'before_commit', fail)
    try:
        with pytest.raises(RuntimeError):
            finalize(engine, claim)
    finally:
        event.remove(Session, 'before_commit', fail)
    assert client.get('/api/runs/'+accepted['run']['id']+'/bets').json() == []
    release(engine, claim)
    replacement = claim_next(engine)
    with pytest.raises(LostClaim):
        finalize(engine, claim)
    # No new prediction attempts are needed after a failed atomic commit.
    assert begin_attempt(engine, replacement) is None
    assert finalize(engine, replacement) is True
    saved = post(client, body(games[:2]), key).json()
    assert len(saved['bets']) == 2
    with Session(engine) as session:
        assert all(row.attempts == 1 for row in session.scalars(select(RunGame)))


def test_kickoff_crossing_all_skipped_has_no_financial_result(api, monkeypatch):
    client, engine, games = api
    key = uuid4()
    accepted = post(client, body(games[:2]), key).json()
    claim = claim_next(engine)
    predict_remaining(engine, claim)
    monkeypatch.setattr('app.run_worker.db_now', lambda session: NOW + timedelta(seconds=2))
    with Session(engine) as session, session.begin():
        for game in session.scalars(select(Game)):
            game.start_time = NOW
    assert finalize(engine, claim) is True
    saved = post(client, body(games[:2]), key).json()
    run = saved['run']
    assert run['id'] == accepted['run']['id'] and run['execution_status'] == 'failed'
    assert run['status'] == 'open' and saved['bets'] == []
    assert run['available_bankroll'] == run['current_bankroll'] == '40.00'
    assert all(run[field] is None for field in ('total_profit', 'roi', 'final_bankroll', 'end_time'))
    assert [g['reason'] for g in saved['skipped_games']] == ['kickoff_reached'] * 2
    assert client.post('/api/runs/'+run['id']+'/settle').status_code == 409


def test_fifty_agent_games_yield_forty_seven_bets_with_saved_reasoning(api):
    client, engine, _ = api
    seed_agent_strategy(engine)
    games = []
    for _ in range(50):
        game = demo_games(NOW.date())[0]
        game.id = uuid4()
        game.start_time = NOW + timedelta(days=1)
        for market in game.markets:
            market.id = uuid4()
            for selection in market.selections:
                selection.id = uuid4()
        games.append(game)
    seed_demo(engine, games)
    payload = {**body(games), 'strategy_id': str(AGENT_STRATEGY_ID), 'starting_bankroll': '500'}
    key = uuid4()
    accepted = post(client, payload, key)
    assert accepted.status_code == 201 and accepted.json()['bets'] == []
    calls = Counter()
    failed = {g.id for g in games[:3]}

    class Controlled:
        async def predict(self, value):
            calls[value.game_id] += 1
            if value.game_id in failed:
                # Inject invalid output; it must never fall back to Random.
                return AgentDecision(selection_id=uuid4(), reasoning='Invalid selection')
            return AgentDecision(selection_id=value.selections[0].selection_id,
                                 reasoning='Verified matchup evidence supports this side.')

    asyncio.run(process_claim(engine, claim_next(engine), lambda *_: Controlled()))
    saved = post(client, payload, key).json()
    assert saved['run']['execution_status'] == 'completed'
    assert len(saved['bets']) == 47 and len(saved['skipped_games']) == 3
    assert saved['run']['committed_stake'] == '470.00'
    assert saved['run']['available_bankroll'] == '30.00'
    assert all(b['reasoning'] == 'Verified matchup evidence supports this side.' for b in saved['bets'])
    assert all(g['reason'] == 'invalid_agent_decision' for g in saved['skipped_games'])
    assert all(calls[g.id] == (2 if g.id in failed else 1) for g in games)
    assert post(client, payload, key).json() == saved
    assert claim_next(engine) is None
