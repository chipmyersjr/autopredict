"""Stored-data eligibility and side-effect-free Random Strategy decisions."""
from datetime import datetime, timezone
from random import SystemRandom
from typing import Protocol, Sequence

from sqlalchemy import select
from app.models import Game, QuoteObservation, ProviderGameLink
from app.schemas import BetDecision, SkippedGame, QuoteProvenance


class ChoiceGenerator(Protocol):
    def choice(self, candidates: Sequence[BetDecision]) -> BetDecision: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_candidates(game: Game, now: datetime, session=None) -> tuple[list[BetDecision], SkippedGame | None]:
    """Use the server clock even when a source still labels a game scheduled.

    Imported projections must match a current persisted paired observation.
    Demo projections retain null provenance.
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
        sides = {s.side for s in pair}
        if sides not in ({game.home_team, game.away_team}, {"home", "away"}):
            continue
        if any(s.line is None or not s.line.is_finite() or not s.price.is_finite() or s.price <= 1 for s in pair):
            continue
        if pair[0].line != -pair[1].line:
            continue
        provenance = None
        if session is not None:
            quote = session.scalar(select(QuoteObservation).where(
                QuoteObservation.game_id == game.id, QuoteObservation.market_id == market.id,
                QuoteObservation.is_current))
            if quote is not None:
                if any((s.line, s.price) != (
                    (quote.home_line, quote.home_price) if s.side == (
                        "home" if sides == {"home", "away"} else game.home_team)
                    else (quote.away_line, quote.away_price)) for s in pair):
                    continue
                provenance = QuoteProvenance(observation_id=quote.id, bookmaker=quote.bookmaker,
                    source_timestamp=quote.source_timestamp, fetched_at=quote.fetched_at)
            elif session.scalar(select(ProviderGameLink.id).where(ProviderGameLink.game_id == game.id).limit(1)):
                continue
        candidates.extend(BetDecision(
            game_id=game.id, market_id=market.id, selection_id=s.id,
            side=s.side, line=s.line, price=s.price, quote_provenance=provenance,
        ) for s in pair)
    candidates.sort(key=lambda c: (c.market_id, c.selection_id))
    if not candidates:
        return [], SkippedGame(game_id=game.id, reason="spread_unavailable")
    return candidates, None


def random_decisions(candidate_groups: Sequence[Sequence[BetDecision]], rng: ChoiceGenerator | None = None) -> list[BetDecision]:
    generator = rng if rng is not None else SystemRandom()
    return [generator.choice(group) for group in candidate_groups if group]
