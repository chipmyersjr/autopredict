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

The backend can start without Docker or a database using the same startup commands. Health and `/docs` work; readiness returns 503 until PostgreSQL is available. Database connections are lazy, released after checks, and disposed at application shutdown. No domain tables or migrations are created in this epic.

`ECONNREFUSED` on port 8000 means no server is listening: check the backend terminal and startup output. A 503 readiness response means the backend is reachable but its database check failed; check Docker Desktop, `docker compose ps`, and configuration.

## Tests

From `backend/`:

```bash
uv run pytest
```

Tests need no running database. They cover health, readiness success/failure, cleanup, and settings. The current upstream test client emits an httpx deprecation warning; tests pass.

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
