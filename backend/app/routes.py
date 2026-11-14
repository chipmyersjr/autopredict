"""Database-only read endpoints for stored games and spread markets."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_session
from app.models import Game, Market, Strategy
from app.schemas import GameResponse, MarketResponse
from app.schemas import StrategyCreate, StrategyResponse, DecisionRequest, DecisionResponse
from app.strategies import utc_now, resolve_candidates, random_decisions
from app.ingress import current_week
from app.refresh import RefreshService
from app.settings import Settings
from app.schemas import RefreshRequest, RefreshResponse

from fastapi import Header, Response
from app.models import Run, Bet
from app.schemas import RunCreate, RunResponse, RunCreationResponse, BetResponse
from app.runs import create_run, read_run, run_response, ordered_bets, bet_response, local_user, RUN_GRAPH
from app.runs import settle_run
from app.schemas import SettlementResponse
from app.schemas import DashboardResponse
from app.dashboard import read_dashboard

router = APIRouter(prefix="/api", responses={503: {"description": "Database unavailable"}})
DatabaseSession = Annotated[Session, Depends(get_session)]
GAME_GRAPH = selectinload(Game.markets).selectinload(Market.selections)


@router.get("/dashboard", response_model=DashboardResponse, tags=["Dashboard"])
def dashboard(session: DatabaseSession):
    """Totals across independent simulations; never refresh or settle results."""
    return read_dashboard(session)


def find_game(session: Session, game_id: UUID) -> Game:
    game = session.scalar(select(Game).where(Game.id == game_id).options(GAME_GRAPH))
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@router.get("/games", response_model=list[GameResponse], tags=["Games"])
def list_games(session: DatabaseSession, window: Literal["current"] | None = None):
    """Read stored games only; window=current selects the server's Pacific week.

    Without window, include demo and historical games. Kickoff availability is
    derived from one server timestamp without changing provider-confirmed status.
    """
    now = utc_now()
    statement = select(Game).options(GAME_GRAPH).order_by(Game.start_time.desc(), Game.id)
    if window == "current":
        week = current_week(now)
        statement = statement.where(Game.start_time >= week.start, Game.start_time < week.end)
    return [game_view(game, now) for game in session.scalars(statement).all()]


def game_view(game, now=None):
    """Derive availability without writing stale source state back to storage."""
    view = GameResponse.model_validate(game)
    if game.status != "scheduled" or game.start_time <= (now if now is not None else utc_now()):
        for market in view.markets:
            for selection in market.selections:
                selection.is_active = False
    return view


@router.post("/games/refresh", response_model=RefreshResponse, tags=["Games"],
             responses={code: {"model": RefreshResponse, "description": description}
                        for code, description in [(429, "Preflight limit"), (409, "Refresh in progress"),
                                                  (503, "Database unavailable"), (422, "Invalid input")]})
async def refresh_games(request: Request, response: Response,
                        body: Annotated[RefreshRequest | None, Body()] = None):
    """Explicit refresh of the server's Pacific week; no caller-selected window.

    Finished full, partial, and provider failures return 200. data_changed tells
    callers to reload stored games even when success is false.
    """
    service = RefreshService(request.app.state.database_engine, Settings())
    if request.query_params:
        result = service.result("configuration_error")
        result.body["message"] = "Refresh failed: query parameters are not supported."
        response.status_code = 422
    else:
        result = await service.run()
        response.status_code = result.http_status
    return RefreshResponse.model_validate(result.body)


@router.get("/games/{game_id}", response_model=GameResponse, tags=["Games"], responses={404: {"description": "Game not found"}})
def game_detail(game_id: UUID, session: DatabaseSession):
    return game_view(find_game(session, game_id))


@router.get("/games/{game_id}/markets", response_model=list[MarketResponse], tags=["Markets"], responses={404: {"description": "Game not found"}})
def game_markets(game_id: UUID, session: DatabaseSession):
    return game_view(find_game(session, game_id)).markets


@router.get("/markets/{market_id}", response_model=MarketResponse, tags=["Markets"], responses={404: {"description": "Market not found"}})
def market_detail(market_id: UUID, session: DatabaseSession):
    market = session.scalar(select(Market).where(Market.id == market_id).options(selectinload(Market.selections)))
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    return next(m for m in game_view(find_game(session, market.game_id)).markets if m.id == market.id)


def find_strategy(session: Session, strategy_id: UUID) -> Strategy:
    strategy = session.get(Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@router.get("/strategies", response_model=list[StrategyResponse], tags=["Strategies"])
def list_strategies(session: DatabaseSession):
    return session.scalars(select(Strategy).order_by(Strategy.id)).all()


@router.post("/strategies", response_model=StrategyResponse, status_code=201, tags=["Strategies"])
def create_strategy(body: StrategyCreate, session: DatabaseSession):
    strategy = Strategy(**body.model_dump())
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


@router.get("/strategies/{strategy_id}", response_model=StrategyResponse, tags=["Strategies"], responses={404: {"description": "Strategy not found"}})
def strategy_detail(strategy_id: UUID, session: DatabaseSession):
    return find_strategy(session, strategy_id)


@router.post("/strategies/{strategy_id}/decisions", response_model=DecisionResponse, tags=["Strategies"], responses={404: {"description": "Strategy or game not found"}, 409: {"description": "Strategy inactive"}})
def preview_decisions(strategy_id: UUID, body: DecisionRequest, session: DatabaseSession):
    """Generate decisions from stored spreads; creates no bets or runs."""
    strategy = find_strategy(session, strategy_id)
    if not strategy.is_active:
        raise HTTPException(status_code=409, detail="Strategy inactive")
    games = session.scalars(select(Game).where(Game.id.in_(body.game_ids)).options(GAME_GRAPH)).all()
    by_id = {game.id: game for game in games}
    if any(game_id not in by_id for game_id in body.game_ids):
        raise HTTPException(status_code=404, detail="Game not found")
    now = utc_now()
    groups, skips = [], []
    for game_id in body.game_ids:
        candidates, skip = resolve_candidates(by_id[game_id], now, session)
        groups.append(candidates)
        if skip is not None:
            skips.append(skip)
    return DecisionResponse(
        strategy_id=strategy.id, generated_at=now, requested_game_ids=body.game_ids,
        decisions=random_decisions(groups), skipped_games=skips,
    )


@router.post("/runs", response_model=RunCreationResponse, status_code=201, tags=["Runs"], responses={200: {"model": RunCreationResponse, "description": "Original persisted result replayed"}, 404: {"description": "Strategy or game not found"}, 409: {"description": "Inactive strategy, no eligible games, or request key conflict"}})
def run_create(body: RunCreate, session: DatabaseSession, response: Response,
               idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")]):
    saved, created = create_run(session, body, idempotency_key)
    response.status_code = 201 if created else 200
    return saved


@router.get("/runs", response_model=list[RunResponse], tags=["Runs"])
def runs_list(session: DatabaseSession):
    owner = local_user(session)
    runs = session.scalars(select(Run).where(Run.user_id == owner).options(*RUN_GRAPH).order_by(Run.start_time.desc(), Run.id)).all()
    return [run_response(run) for run in runs]


@router.post("/runs/{run_id}/settle", response_model=SettlementResponse, tags=["Runs"],
             responses={404: {"description": "Run not found"},
                        409: {"description": "Invalid snapshot or accounting overflow"},
                        422: {"description": "Invalid input"}})
async def run_settle(run_id: UUID, request: Request, session: DatabaseSession):
    """Explicitly settle saved results; no request body or provider refresh."""
    if await request.body():
        raise HTTPException(422, "Settlement accepts no body")
    return await run_in_threadpool(settle_run, session, run_id)


@router.get("/runs/{run_id}", response_model=RunResponse, tags=["Runs"])
def run_detail(run_id: UUID, session: DatabaseSession):
    return run_response(read_run(session, run_id))


@router.get("/runs/{run_id}/bets", response_model=list[BetResponse], tags=["Bets"])
def run_bets(run_id: UUID, session: DatabaseSession):
    return ordered_bets(read_run(session, run_id))


@router.get("/bets/{bet_id}", response_model=BetResponse, tags=["Bets"])
def bet_detail(bet_id: UUID, session: DatabaseSession):
    owner = local_user(session)
    bet = session.scalar(select(Bet).join(Run).where(Bet.id == bet_id, Run.user_id == owner))
    if bet is None:
        raise HTTPException(404, "Bet not found")
    return bet_response(bet)
