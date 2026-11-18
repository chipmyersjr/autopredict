"""Pure spread resolution from immutable execution snapshots and stored results.

No database writes, provider access, or regrading occurs here. Callers apply a
resolution only to open Bets, in their settlement transaction.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext


class SettlementError(ValueError):
    """Invalid saved evidence or accounting outside the persisted precision."""


def numeric(value: Decimal, precision: int, scale: int) -> Decimal:
    """Reject non-Decimal, nonfinite, overprecise and overflowing values."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise SettlementError("Invalid settlement accounting")
    if value.copy_abs() >= Decimal(10) ** (precision - scale):
        raise SettlementError("Settlement accounting exceeds storage precision")
    with localcontext() as context:
        context.prec = max(40, len(value.as_tuple().digits) + scale + 1)
        if value != value.quantize(Decimal(1).scaleb(-scale)):
            raise SettlementError("Invalid settlement precision")
    return value


@dataclass(frozen=True)
class Resolution:
    result: str
    profit: Decimal
    settlement_game_status: str
    settlement_home_score: int | None
    settlement_away_score: int | None


def resolve_spread(*, side: str, home_team: str, away_team: str,
                   line: Decimal, price: Decimal, stake: Decimal,
                   game_status: str, home_score: int | None,
                   away_score: int | None) -> Resolution | None:
    """Return terminal evidence, or None while a game's result is pending.

    Team names are the saved Bet labels, never the current Game labels. A
    conflicting role/name interpretation is rejected rather than guessed.
    """
    numeric(line, 10, 2)
    numeric(price, 10, 4)
    numeric(stake, 12, 2)
    if price <= 1 or stake <= 0:
        raise SettlementError("Invalid execution money")
    if (not isinstance(home_team, str) or not home_team.strip()
            or not isinstance(away_team, str) or not away_team.strip()
            or home_team == away_team):
        raise SettlementError("Ambiguous execution participants")
    roles = set()
    if side == "home" or side == home_team:
        roles.add("home")
    if side == "away" or side == away_team:
        roles.add("away")
    if len(roles) != 1:
        raise SettlementError("Ambiguous execution side")
    if game_status not in {"scheduled", "in_progress", "completed", "canceled"}:
        raise SettlementError("Invalid stored game status")
    for score in (home_score, away_score):
        if score is not None and (type(score) is not int or not 0 <= score <= 2147483647):
            raise SettlementError("Invalid stored score")
    if game_status == "canceled":
        return Resolution("void", Decimal("0.00"), game_status, home_score, away_score)
    if game_status != "completed" or home_score is None or away_score is None:
        return None
    with localcontext() as context:
        context.prec = 40
        margin = Decimal(home_score - away_score)
        if roles == {"away"}:
            margin = -margin
        margin += line
        result = "won" if margin > 0 else "lost" if margin < 0 else "pushed"
        profit = (stake * (price - 1)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if result == "won" else -stake if result == "lost" else Decimal("0.00")
        numeric(profit, 12, 2)
    return Resolution(result, profit, game_status, home_score, away_score)
