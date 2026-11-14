"""Atomic theoretical execution and durable, user-scoped history."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.models import Bet, Game, Market, Run, RunGame, Selection, Strategy, User
from app.schemas import BetDecision, BetResponse, QuoteProvenance, RunCreate, RunCreationResponse, RunResponse, SkippedGame
from app.seed_user import LOCAL_USER_ID
from app.strategies import random_decisions, resolve_candidates, utc_now
from app.settlement import SettlementError, numeric, resolve_spread
from app.schemas import SettlementResponse, PendingGame

RUN_GRAPH = (selectinload(Run.games), selectinload(Run.bets))


def local_user(session):
    if session.get(User, LOCAL_USER_ID) is None:
        raise HTTPException(503, "Local simulation User is not configured; run python -m app.seed_user")
    return LOCAL_USER_ID


def read_run(session, run_id):
    owner = local_user(session)
    run = session.scalar(select(Run).where(Run.id == run_id, Run.user_id == owner).options(*RUN_GRAPH))
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


def run_response(run):
    committed = sum((b.stake for b in run.bets if b.status == "open"), Decimal("0.00"))
    terminal = [b for b in run.bets if b.status != "open"]
    current = run.starting_bankroll + (run.total_profit or Decimal("0.00"))
    return RunResponse.model_validate({
        **{field: getattr(run, field) for field in RunResponse.model_fields if hasattr(run, field)},
        "game_ids": [g.game_id for g in run.games], "bet_count": len(run.bets),
        "committed_stake": committed, "available_bankroll": current - committed,
        "current_bankroll": current,
        "settled_stake": sum((b.stake for b in terminal), Decimal("0.00")),
        "open_bet_count": len(run.bets) - len(terminal), "settled_bet_count": len(terminal),
        **{name: sum(b.status == status for b in terminal) for name, status in
           [("win_count", "won"), ("loss_count", "lost"), ("push_count", "pushed"), ("void_count", "void")]},
        "skipped_games": [SkippedGame(game_id=g.game_id, reason=g.skip_reason) for g in run.games if g.skip_reason],
    })


def bet_response(bet):
    provenance = None
    if bet.observation_id is not None:
        provenance = QuoteProvenance(observation_id=bet.observation_id, bookmaker=bet.bookmaker,
                                     source_timestamp=bet.source_timestamp, fetched_at=bet.fetched_at)
    return BetResponse.model_validate({**{f: getattr(bet, f) for f in BetResponse.model_fields if f != "quote_provenance"},
                                       "quote_provenance": provenance})


def ordered_bets(run):
    positions = {g.game_id: g.position for g in run.games}
    return [bet_response(b) for b in sorted(run.bets, key=lambda b: (positions[b.game_id], b.id))]


def result(run):
    response = run_response(run)
    return RunCreationResponse(run=response, bets=ordered_bets(run), skipped_games=response.skipped_games)


def settle_run(session: Session, run_id: UUID):
    """Lock Games before Run/Bets; terminal rows are the retry boundary."""
    owner = local_user(session)
    # Discover immutable references without taking a Run lock ahead of Games.
    exists = session.scalar(select(Run.id).where(Run.id == run_id, Run.user_id == owner))
    if exists is None:
        raise HTTPException(404, "Run not found")
    game_ids = select(Bet.game_id).where(Bet.run_id == run_id)
    games = session.scalars(select(Game).where(Game.id.in_(game_ids)).order_by(Game.id)
                           .with_for_update().execution_options(populate_existing=True)).all()
    run = session.scalar(select(Run).where(Run.id == run_id, Run.user_id == owner)
                         .with_for_update().execution_options(populate_existing=True))
    if run is None:
        raise HTTPException(404, "Run not found")
    bets = session.scalars(select(Bet).where(Bet.run_id == run_id).order_by(Bet.id)
                          .with_for_update().execution_options(populate_existing=True)).all()
    set_committed_value(run, "bets", bets)
    by_id = {game.id: game for game in games}
    newly_settled = set()
    now = utc_now()
    try:
        with localcontext() as context:
            context.prec = 40
            for bet in bets:
                if bet.status != "open":
                    continue
                game = by_id[bet.game_id]
                resolution = resolve_spread(
                    side=bet.side, home_team=bet.home_team, away_team=bet.away_team,
                    line=bet.line, price=bet.price, stake=bet.stake,
                    game_status=game.status, home_score=game.home_score, away_score=game.away_score)
                if resolution is None:
                    continue
                bet.status = bet.result = resolution.result
                bet.profit = resolution.profit
                bet.settlement_game_status = resolution.settlement_game_status
                bet.settlement_home_score = resolution.settlement_home_score
                bet.settlement_away_score = resolution.settlement_away_score
                bet.settled_at = now
                newly_settled.add(bet.id)
            if newly_settled:
                profit = sum((b.profit for b in bets if b.status != "open"), Decimal("0.00"))
                current = run.starting_bankroll + profit
                roi = (profit / run.starting_bankroll).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                numeric(profit, 12, 2)
                numeric(current, 12, 2)
                numeric(roi, 8, 4)
                run.total_profit, run.roi = profit, roi
                if all(b.status != "open" for b in bets):
                    run.status, run.final_bankroll, run.end_time = "completed", current, now
            session.flush()
            # Serialize before commit from the locked state, including updated_at.
            ordered = ordered_bets(run)
            pending = [PendingGame(game_id=g.game_id, reason=(
                "final_scores_missing" if by_id[g.game_id].status == "completed" else "game_not_final"))
                for g in run.games if any(b.game_id == g.game_id and b.status == "open" for b in bets)]
            response = SettlementResponse(run=run_response(run), bets=ordered,
                settled_bet_ids=[b.id for b in ordered if b.id in newly_settled], pending_games=pending)
            session.commit()
            return response
    except SettlementError:
        session.rollback()
        raise HTTPException(409, "Invalid settlement snapshot or accounting overflow") from None


class DryRunAdapter:
    """Records typed server decisions; never samples or requests prices."""
    def record(self, run: Run, decisions: list[BetDecision], games: dict[UUID, Game], stake: Decimal, placed_at):
        for decision in decisions:
            game = games[decision.game_id]
            provenance = decision.quote_provenance
            run.bets.append(Bet(
                game_id=game.id, market_id=decision.market_id, selection_id=decision.selection_id,
                side=decision.side, line=decision.line, price=decision.price, stake=stake,
                home_team=game.home_team, away_team=game.away_team,
                kickoff_at_placement=game.start_time, placed_at=placed_at, status="open",
                observation_id=provenance.observation_id if provenance else None,
                bookmaker=provenance.bookmaker if provenance else None,
                source_timestamp=provenance.source_timestamp if provenance else None,
                fetched_at=provenance.fetched_at if provenance else None,
            ))


def check_budget(count, stake, bankroll):
    if count == 0:
        raise HTTPException(409, "No eligible games")
    if count * stake > bankroll:
        raise HTTPException(422, "Insufficient starting bankroll for eligible games")


def existing_request(session, owner, key, payload):
    run = session.scalar(select(Run).where(Run.user_id == owner, Run.request_id == key).options(*RUN_GRAPH))
    if run is not None and run.request_payload != payload:
        raise HTTPException(409, "Idempotency-Key already used with different input")
    return run


def create_run(session: Session, body: RunCreate, key: UUID):
    owner = local_user(session)
    payload = body.model_dump(mode="json")
    prior = existing_request(session, owner, key, payload)
    if prior is not None:
        return result(prior), False
    # Claim request identity before sampling. A competing insert waits for commit;
    # rollback and read in a fresh transaction after the unique conflict.
    run = Run(user_id=owner, strategy_id=body.strategy_id, request_id=key, request_payload=payload,
              name=body.name, notes=body.notes, starting_bankroll=Decimal(body.starting_bankroll),
              stake_per_bet=Decimal(body.stake_per_bet), start_time=utc_now(), status="open")
    strategy = session.scalar(select(Strategy).where(Strategy.id == body.strategy_id).with_for_update())
    if strategy is None:
        raise HTTPException(404, "Strategy not found")
    # Strategy lock serializes competing creations; recheck replay after waiting.
    prior = existing_request(session, owner, key, payload)
    if prior is not None:
        return result(prior), False
    if not strategy.is_active:
        raise HTTPException(409, "Strategy inactive")
    session.add(run)
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        if getattr(error.orig, "diag", None) is None or error.orig.diag.constraint_name != "uq_runs_user_request":
            raise
        prior = existing_request(session, owner, key, payload)
        if prior is None:
            raise
        return result(prior), False
    games = session.scalars(select(Game).where(Game.id.in_(body.game_ids)).order_by(Game.id).with_for_update()).all()
    if len(games) != len(body.game_ids):
        raise HTTPException(404, "Game not found")
    markets = session.scalars(select(Market).where(Market.game_id.in_(body.game_ids)).order_by(Market.id).with_for_update()).all()
    selections = session.scalars(select(Selection).where(Selection.market_id.in_([m.id for m in markets])).order_by(Selection.id).with_for_update()).all()
    # Assemble the graph from locked rows without per-game lazy queries.
    for market in markets:
        set_committed_value(market, "selections", [s for s in selections if s.market_id == market.id])
    for game in games:
        set_committed_value(game, "markets", [m for m in markets if m.game_id == game.id])
    by_id = {g.id: g for g in games}
    now = utc_now()
    groups, skips = [], {}
    for game_id in body.game_ids:
        candidates, skip = resolve_candidates(by_id[game_id], now, session)
        groups.append(candidates)
        if skip:
            skips[game_id] = skip.reason
    check_budget(sum(bool(g) for g in groups), run.stake_per_bet, run.starting_bankroll)
    decisions = random_decisions(groups)
    placed_at = utc_now()
    retained = []
    for decision in decisions:
        _, skip = resolve_candidates(by_id[decision.game_id], placed_at, session)
        if skip:
            skips[decision.game_id] = skip.reason
        else:
            retained.append(decision)
    check_budget(len(retained), run.stake_per_bet, run.starting_bankroll)
    run.start_time = placed_at
    run.games = [RunGame(game_id=g, position=i, skip_reason=skips.get(g), included_at=placed_at)
                 for i, g in enumerate(body.game_ids)]
    DryRunAdapter().record(run, retained, by_id, run.stake_per_bet, placed_at)
    session.commit()
    return result(read_run(session, run.id)), True
