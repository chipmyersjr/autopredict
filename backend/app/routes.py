"""Database-only read endpoints for stored games and spread markets."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_session
from app.models import Game, Market, Strategy
from app.schemas import GameResponse, MarketResponse
from app.schemas import StrategyCreate, StrategyResponse, DecisionRequest, DecisionResponse
from app.strategies import utc_now, resolve_candidates, random_decisions

router = APIRouter(prefix="/api", responses={503: {"description": "Database unavailable"}})
DatabaseSession = Annotated[Session, Depends(get_session)]
GAME_GRAPH = selectinload(Game.markets).selectinload(Market.selections)


def find_game(session: Session, game_id: UUID) -> Game:
    game = session.scalar(select(Game).where(Game.id == game_id).options(GAME_GRAPH))
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@router.get("/games", response_model=list[GameResponse], tags=["Games"])
def list_games(session: DatabaseSession):
    """Read all stored games, including demo/historical data, with markets and selections."""
    return session.scalars(select(Game).options(GAME_GRAPH).order_by(Game.start_time.desc(), Game.id)).all()


@router.get("/games/{game_id}", response_model=GameResponse, tags=["Games"], responses={404: {"description": "Game not found"}})
def game_detail(game_id: UUID, session: DatabaseSession):
    return find_game(session, game_id)


@router.get("/games/{game_id}/markets", response_model=list[MarketResponse], tags=["Markets"], responses={404: {"description": "Game not found"}})
def game_markets(game_id: UUID, session: DatabaseSession):
    return find_game(session, game_id).markets


@router.get("/markets/{market_id}", response_model=MarketResponse, tags=["Markets"], responses={404: {"description": "Market not found"}})
def market_detail(market_id: UUID, session: DatabaseSession):
    market = session.scalar(select(Market).where(Market.id == market_id).options(selectinload(Market.selections)))
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    return market


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
        candidates, skip = resolve_candidates(by_id[game_id], now)
        groups.append(candidates)
        if skip is not None:
            skips.append(skip)
    return DecisionResponse(
        strategy_id=strategy.id, generated_at=now, requested_game_ids=body.game_ids,
        decisions=random_decisions(groups), skipped_games=skips,
    )
