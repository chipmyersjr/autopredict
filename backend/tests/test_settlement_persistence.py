"""Settlement evidence checks against generated disposable PostgreSQL only."""
from decimal import Decimal
from uuid import UUID

import pytest
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Bet
from test_runs import api, body, finished_post as post, legacy_execution_fixture
from test_strategies import NOW


def test_evidence_upgrade_cycle_preserves_saved_bets(api, migrated_database):
    client, engine, games = api
    _, config = migrated_database
    saved = post(client, body(games)).json()
    legacy_execution_fixture(engine)
    command.downgrade(config, "0004")
    assert "settlement_game_status" not in {c["name"] for c in inspect(engine).get_columns("bets")}
    command.upgrade(config, "head")
    command.check(config)
    assert client.get('/api/runs/' + saved['run']['id'] + '/bets').json() == saved['bets']
    with Session(engine) as session:
        bet = session.get(Bet, UUID(saved["bets"][0]["id"]))
        assert bet.settlement_home_score is bet.settlement_away_score is bet.settlement_game_status is None


@pytest.mark.parametrize("changes", [
    {"result": "won"}, {"profit": Decimal("0")}, {"settled_at": NOW},
    {"settlement_home_score": 0}, {"settlement_game_status": "completed"},
    {"status": "won"},
])
def test_open_bet_cannot_contain_outcome_evidence(api, changes):
    client, engine, games = api
    saved = post(client, body(games)).json()
    with Session(engine) as session:
        bet = session.get(Bet, UUID(saved["bets"][0]["id"]))
        for field, value in changes.items():
            setattr(bet, field, value)
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize("changes", [
    {"result": None}, {"result": "lost"}, {"profit": None}, {"profit": Decimal("NaN")},
    {"profit": Decimal("-1")}, {"settled_at": None},
    {"settlement_game_status": None}, {"settlement_game_status": "scheduled"},
    {"settlement_home_score": None}, {"settlement_away_score": None},
    {"settlement_home_score": -1},
])
def test_terminal_evidence_must_be_complete_and_consistent(api, changes):
    client, engine, games = api
    saved = post(client, body(games)).json()
    with Session(engine) as session:
        bet = session.get(Bet, UUID(saved["bets"][0]["id"]))
        values = dict(status="won", result="won", profit=Decimal("9.09"), settled_at=NOW,
                      settlement_game_status="completed", settlement_home_score=24, settlement_away_score=20)
        for field, value in {**values, **changes}.items():
            setattr(bet, field, value)
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize("result,profit,status,home,away", [
    ("won", "9.09", "completed", 24, 20),
    ("lost", "-10.00", "completed", 17, 20),
    ("pushed", "0.00", "completed", 20, 20),
    ("void", "0.00", "canceled", None, None),
    ("void", "0.00", "canceled", 7, None),
])
def test_valid_terminal_evidence_persists(api, result, profit, status, home, away):
    client, engine, games = api
    saved = post(client, body(games)).json()
    ident = UUID(saved["bets"][0]["id"])
    with Session(engine) as session:
        bet = session.get(Bet, ident)
        bet.status = bet.result = result
        bet.profit = Decimal(profit)
        bet.settled_at = NOW
        bet.settlement_game_status = status
        bet.settlement_home_score = home
        bet.settlement_away_score = away
        session.commit()
    with Session(engine) as session:
        bet = session.get(Bet, ident)
        assert (bet.status, bet.profit, bet.settled_at) == (result, Decimal(profit), NOW)
        assert (bet.settlement_game_status, bet.settlement_home_score, bet.settlement_away_score) == (status, home, away)
