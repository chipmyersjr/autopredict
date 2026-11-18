"""Independent numeric oracles for saved spread execution accounting."""
from decimal import Decimal, localcontext

import pytest

from app.settlement import SettlementError, numeric, resolve_spread


def resolve(**changes):
    return resolve_spread(**{
        "side": "home", "home_team": "Saved Home", "away_team": "Saved Away",
        "line": Decimal("-3.50"), "price": Decimal("1.9500"), "stake": Decimal("10.00"),
        "game_status": "completed", "home_score": 24, "away_score": 20, **changes,
    })


@pytest.mark.parametrize("side,line,home,away,result,profit", [
    ("home", "-3.5", 24, 20, "won", "9.50"),
    ("Saved Home", "-3.5", 23, 20, "lost", "-10.00"),
    ("away", "3.5", 24, 20, "lost", "-10.00"),
    ("Saved Away", "3.5", 23, 20, "won", "9.50"),
    ("home", "-4", 24, 20, "pushed", "0.00"),
    ("away", "4", 24, 20, "pushed", "0.00"),
    ("home", "0", 0, 0, "pushed", "0.00"),
    ("away", "-2", 17, 20, "won", "9.50"),
    ("home", "2", 17, 20, "lost", "-10.00"),
    ("home", "0.5", 20, 20, "won", "9.50"),
])
def test_known_spreads(side, line, home, away, result, profit):
    evidence = resolve(side=side, line=Decimal(line), home_score=home, away_score=away)
    assert evidence.result == result
    assert evidence.profit == Decimal(profit)
    assert (evidence.settlement_game_status, evidence.settlement_home_score,
            evidence.settlement_away_score) == ("completed", home, away)


@pytest.mark.parametrize("price,profit", [("1.0004", "0.00"), ("1.0005", "0.01"),
                                         ("1.0006", "0.01"), ("1.9091", "9.09")])
def test_round_once_half_up(price, profit):
    assert resolve(price=Decimal(price)).profit == Decimal(profit)


def test_decimal_context_and_per_bet_rounding():
    with localcontext() as context:
        context.prec = 6
        assert resolve(price=Decimal("1.9091")).profit == Decimal("9.09")
    assert sum(resolve(price=Decimal("1.0005")).profit for _ in range(2)) == Decimal("0.02")


@pytest.mark.parametrize("status,home,away", [("scheduled", 24, 20), ("in_progress", 24, 20),
                                             ("completed", None, 20), ("completed", 24, None),
                                             ("completed", None, None)])
def test_pending(status, home, away):
    assert resolve(game_status=status, home_score=home, away_score=away) is None


def test_cancellation_and_saved_labels():
    evidence = resolve(game_status="canceled", home_score=None, away_score=None)
    assert evidence.result == "void" and evidence.profit == Decimal("0.00")
    assert evidence.settlement_home_score is evidence.settlement_away_score is None
    # No current Game/Selection is accepted: a renamed participant or refreshed
    # quote cannot influence resolution of these saved execution fields.
    assert resolve(side="Saved Home").profit == Decimal("9.50")
    assert resolve(game_status="canceled", home_score=7).settlement_home_score == 7


@pytest.mark.parametrize("changes", [
    {"side": "unknown"}, {"home_team": "Saved Away"}, {"home_team": ""},
    {"side": "away", "home_team": "away"}, {"home_score": -1},
    {"away_score": True}, {"home_score": 2.5}, {"game_status": "final"},
    {"price": Decimal("NaN")}, {"line": Decimal("Infinity")},
    {"stake": Decimal("0")}, {"stake": 10.0}, {"price": Decimal("1")},
    {"line": Decimal("1.001")}, {"price": Decimal("1.12345")},
    {"stake": Decimal("9999999999.99"), "price": Decimal("999999.9999")},
])
def test_invalid_snapshot_or_profit_overflow(changes):
    with pytest.raises(SettlementError):
        resolve(**changes)


def test_storage_boundaries_for_later_run_accounting():
    assert numeric(Decimal("9999999999.99"), 12, 2) == Decimal("9999999999.99")
    assert numeric(Decimal("-9999.9999"), 8, 4) == Decimal("-9999.9999")
    for value, precision, scale in [("10000000000", 12, 2), ("-10000", 8, 4)]:
        with pytest.raises(SettlementError):
            numeric(Decimal(value), precision, scale)
