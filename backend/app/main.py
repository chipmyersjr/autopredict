"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.database import check_database, create_database_engine
from app.settings import Settings
from app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_database_engine(Settings())
    app.state.database_engine = engine
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(title="AutoPredict API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=Settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
)
app.include_router(router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Report process health without accessing external services."""
    return {"status": "ok"}


@app.get("/api/ready", responses={503: {"description": "Database unavailable"}})
def ready(request: Request) -> JSONResponse:
    """Report database readiness without exposing connection details."""
    try:
        check_database(request.app.state.database_engine)
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(content={"status": "ready"})
