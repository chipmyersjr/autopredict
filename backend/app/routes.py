"""Database-only read endpoints for stored games and spread markets."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_session
from app.models import Game, Market
from app.schemas import GameResponse, MarketResponse

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
