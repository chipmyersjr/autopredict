"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
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
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Idempotency-Key"],
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, error: RequestValidationError):
    if request.url.path == "/api/games/refresh" and request.method == "POST":
        from app.refresh import RefreshService
        result = RefreshService(None, None).result("configuration_error")
        result.body["message"] = "Refresh failed: invalid input; no parameters are accepted."
        return JSONResponse(status_code=422, content=result.body)
    from fastapi.exception_handlers import request_validation_exception_handler
    return await request_validation_exception_handler(request, error)


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
