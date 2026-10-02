# AutoPredict

A prediction optimization platform, starting with a college football betting simulator. Product requirements live in `design/`; agent plans and completion tracking live in `progress/`.

## Prerequisites

Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) (Apple silicon version on your Mac) and open it before starting the database. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) for dependency management; Python 3.12 is downloaded automatically when needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal afterward. If uv is still not found, run `export PATH="$HOME/.local/bin:$PATH"` and add that line to `~/.zshrc`.

If docker or docker-credential-desktop is not found, run `export PATH="$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"` and add that line to `~/.zshrc`.

```bash
uv --version
docker --version
docker compose version
```

## Start the database

From the repository root, copy example settings on first setup (preserve an existing `.env`):

```bash
cp -n .env.example .env
docker compose up -d --wait db
docker compose ps
```

PostgreSQL 17 runs on `127.0.0.1:5432` with a health check and a persistent named volume. Credentials in the example are for local development. If port 5432 is occupied, change `POSTGRES_PORT` in root `.env` before starting the database.

The backend loads the same root `.env` regardless of working directory; shell environment variables override file settings. `POSTGRES_HOST` is the backend database host. Compose binds the database port to localhost. `DB_CONNECT_TIMEOUT` defaults to 3 seconds (allowed range 2–10); server-side statements have a 3-second timeout. Changing credentials in `.env` after volume initialization does not change existing PostgreSQL credentials.

## Start the backend

From the repository root, in a separate terminal:

```bash
cd backend
uv sync --locked
uv run fastapi dev
```

Leave that terminal running. FastAPI runs on port 8000 with hot reload. Stop it with Ctrl+C. If port 8000 is occupied, use `uv run fastapi dev --port 8001` and adjust request URLs.

If dependencies were already installed but uv is unavailable, run `.venv/bin/fastapi dev` from `backend/`.

## Apply database migrations

After starting PostgreSQL and syncing backend dependencies, run from `backend/`:

```bash
uv run alembic upgrade head
uv run alembic current
```

Alembic loads the same root `.env` and shell overrides as the application. Migration files live in root `migrations/`; configuration lives in `backend/alembic.ini`. The initial migration creates only games, markets, and selections (plus Alembic's revision table). It does not seed data or add read endpoints. Timestamps use timezone-aware PostgreSQL types; `updated_at` advances on SQLAlchemy ORM updates. Direct SQL writers must update that field themselves.

## Load and inspect demo games

From `backend/`, after applying migrations:

```bash
uv run python -m app.seed --anchor-date 2026-10-01
```

Omit `--anchor-date` to use the current UTC date. Five fictional matchups use real college team names and demo week 5: USC/UCLA, Oregon/Washington, Michigan/Ohio State, Alabama/Georgia, and Texas/Oklahoma. Kickoffs are at 19:00 UTC, one through five days after the anchor. The first four have active spread markets with two opposite team lines (including a zero pick'em line) and decimal odds `1.9091`; Texas/Oklahoma has no market. Scores are null. Notes and descriptions label the fixtures as demo data, separate from future provider imports.

The loader validates pairs and commits one transaction. Stable fixture IDs make repeat runs idempotent: existing games and their markets/selections are preserved, including edits. Changing the anchor does not reschedule existing fixtures. Seeding only occurs when this command is run.

With the backend running, open [games JSON](http://127.0.0.1:8000/api/games) or [interactive API docs](http://127.0.0.1:8000/docs). For the verification server started on October 1, use port **8001**: [demo games](http://127.0.0.1:8001/api/games) and [docs](http://127.0.0.1:8001/docs). If that server has stopped, start it from `backend/` with `uv run fastapi dev --port 8001`.

| Read endpoint | Response |
| --- | --- |
| `GET /api/games` | Array of stored games with nested markets and selections |
| `GET /api/games/{game_id}` | One game with the same nested shape |
| `GET /api/games/{game_id}/markets` | Array of the game's markets with selections |
| `GET /api/markets/{market_id}` | One market with selections |

```bash
curl http://127.0.0.1:8001/api/games
curl http://127.0.0.1:8001/api/games/db3173a4-944a-5c22-b40f-0ddda00e7b7f
curl http://127.0.0.1:8001/api/games/db3173a4-944a-5c22-b40f-0ddda00e7b7f/markets
curl http://127.0.0.1:8001/api/markets/750d75e2-a2e0-5317-938b-9d0ddc6a713c
```

Use a `market.id` from the games response for market detail. All responses expose the entity fields and timestamps shown in `/docs`. UUIDs are strings; timestamps are UTC ISO 8601. Exact lines/prices are decimal strings, such as `"-3.50"` and `"1.9091"`; a nullable line is JSON `null`. Game order is kickoff then ID; nested markets and selections order by ID. Stored statuses and inactive records remain visible. Empty games or a known game without markets return `[]`; unknown valid IDs return 404 (`Game not found` / `Market not found`), malformed IDs return 422, and database errors return 503 with `{"detail":"Database unavailable"}`. Reads make no provider calls. Current-week filtering and provider refresh belong to the separate ingress epic.

## Frontend API access

The backend allows GET requests from `http://127.0.0.1:5173` and `http://localhost:5173`. Set a JSON array in root `.env` and restart the backend to allow alternate Vite ports:

```dotenv
CORS_ORIGINS=["http://127.0.0.1:5173","http://localhost:5173","http://localhost:5174"]
```

Origins must be explicit HTTP(S) origins without paths, wildcards, or credentials. CORS does not enable browser credentials. One `/api/games` request supplies the Games page's spread data; preserve decimal precision, distinguish null from zero, and convert UTC kickoffs for display. The frontend Games page remains the initialization placeholder pending frontend implementation.

## Verify the API

Use a browser, Bruno GET request, or another terminal:

```bash
curl -i http://127.0.0.1:8000/api/health
curl -i http://127.0.0.1:8000/api/ready
```

| Endpoint | Expected response |
| --- | --- |
| `/api/health` | HTTP 200, `{"status":"ok"}`; no database access |
| `/api/ready` | HTTP 200, `{"status":"ready"}` when PostgreSQL is available; HTTP 503, `{"status":"unavailable"}` otherwise |
| `/docs` | Interactive API documentation |

The backend can start without Docker or a database using the same startup commands. Health and `/docs` work; readiness returns 503 until PostgreSQL is available. Database connections are lazy, released after checks, and disposed at application shutdown. Application startup never creates or migrates the domain schema; apply migrations explicitly.

`ECONNREFUSED` on port 8000 means no server is listening: check the backend terminal and startup output. A 503 readiness response means the backend is reachable but its database check failed; check Docker Desktop, `docker compose ps`, and configuration.

## Tests

From `backend/`:

```bash
uv run pytest
```

By default, tests need no running database; PostgreSQL integration tests are skipped. Unit checks cover health/readiness, sanitized data errors/session cleanup, fixture validation, CORS, and settings. The current upstream test client emits an httpx deprecation warning; tests pass.

To include PostgreSQL integration tests, start PostgreSQL and run from `backend/`:

```bash
RUN_POSTGRES_TESTS=1 uv run pytest
```

These tests use the configured PostgreSQL server and credentials to create randomly named disposable databases, validate schema/constraints and upgrade/downgrade/re-upgrade, seed idempotence/rollback, and nested API contracts/query counts, then drop only those databases. The configured role needs permission to create databases. They never migrate or downgrade the development database.

## Shutdown and restart

Stop FastAPI with Ctrl+C. From the repository root:

```bash
docker compose stop db
docker compose up -d --wait db
```

To remove containers and the network while keeping database data:

```bash
docker compose down
```

Ordinary stops, restarts, and `down` preserve the named volume. `docker compose down -v` deletes database volumes and their data.

## Frontend development

Install **Node.js 24 LTS for macOS ARM64** from [Node.js downloads](https://nodejs.org/en/download). npm is included. Open a new terminal and verify `node --version` and `npm --version`. The frontend records Node 24 in `.nvmrc` and `package.json`.

From the repository root:

```bash
cd frontend
npm ci
npm run dev
```

Leave the terminal running and open the URL printed by Vite, normally http://127.0.0.1:5173. The initial Games page displays **Hey its the game page**. This page works independently of FastAPI, PostgreSQL, and Docker. Stop the development server with Ctrl+C. If port 5173 is occupied, Vite prints the next available port; use that URL.

From `frontend/`, check TypeScript and create a production build:

```bash
npm run build
```

Build output goes to `frontend/dist/`. To check the built app locally, run `npm run preview` and open the printed URL (normally http://127.0.0.1:4173).
