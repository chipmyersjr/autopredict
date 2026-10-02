"""Stored-data eligibility and side-effect-free Random Strategy decisions."""
from datetime import datetime, timezone
from random import SystemRandom
from typing import Protocol, Sequence

from app.models import Game
from app.schemas import BetDecision, SkippedGame


class ChoiceGenerator(Protocol):
    def choice(self, candidates: Sequence[BetDecision]) -> BetDecision: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_candidates(game: Game, now: datetime) -> tuple[list[BetDecision], SkippedGame | None]:
    """Use the server clock even when a source still labels a game scheduled.

    Ingress is not implemented yet: canonical active paired selections are the
    available stored snapshots. No provider provenance is invented here.
    """
    reason = None
    if game.status != "scheduled":
        reason = "game_not_scheduled"
    elif game.start_time is None:
        reason = "spread_unavailable"
    elif game.start_time <= now:
        reason = "kickoff_reached"
    if reason:
        return [], SkippedGame(game_id=game.id, reason=reason)
    candidates = []
    for market in game.markets:
        if market.type != "spread" or market.status != "active":
            continue
        pair = [s for s in market.selections if s.is_active]
        if len(pair) != 2 or game.home_team == game.away_team:
            continue
        if {s.side for s in pair} != {game.home_team, game.away_team}:
            continue
        if any(s.line is None or not s.line.is_finite() or not s.price.is_finite() or s.price <= 1 for s in pair):
            continue
        if pair[0].line != -pair[1].line:
            continue
        candidates.extend(BetDecision(
            game_id=game.id, market_id=market.id, selection_id=s.id,
            side=s.side, line=s.line, price=s.price,
        ) for s in pair)
    candidates.sort(key=lambda c: (c.market_id, c.selection_id))
    if not candidates:
        return [], SkippedGame(game_id=game.id, reason="spread_unavailable")
    return candidates, None


def random_decisions(candidate_groups: Sequence[Sequence[BetDecision]], rng: ChoiceGenerator | None = None) -> list[BetDecision]:
    generator = rng if rng is not None else SystemRandom()
    return [generator.choice(group) for group in candidate_groups if group]
