# Epic 0 — Initialize the backend

Area status: `not_started`

## Objective and design references

Stand up a minimal FastAPI application with a health endpoint and a reproducible local development setup. Prepare PostgreSQL connectivity for the first games-and-spreads slice without implementing domain models yet.

Governing design:
- [MVP proposal](../../../../design/1_mvp.html), sections 4 (data), 7 (stack and local development), 9 (vertical slices), and 11 (local setup criteria).
- [MVP ERD](../../../../design/2_mvp_erd.png), for future schema context only; no domain tables in this epic.

This loop is planning only. Implementation tasks remain unchecked until executed and validated.

## Implementation decisions

- Backend lives in `backend/`, using Python, FastAPI, Pydantic, and `uv` with a committed dependency lockfile. Record the supported Python version in project configuration and setup instructions.
- Run FastAPI on the host with hot reload; run PostgreSQL through root `docker-compose.yml`, following the design's `docker compose up db` workflow. A backend Docker image is unnecessary for this initial local setup.
- Use SQLAlchemy with a synchronous PostgreSQL driver and environment-based database configuration. Keep database access in a small dedicated module.
- Add root `.env.example` with local development settings and ignore real `.env` files. Explicitly configure loading the root `.env` when running from `backend/`.
- PostgreSQL is the database specified by the design. SQLite is not adopted by this plan. A health-only app can run without any database; the database setup can be completed as a separate task.
- SQLite could support an early prototype, but adopting it requires a subsequent CHIP-maintained design document. Switching later is manageable with SQLAlchemy and Alembic, but still requires checking types, constraints, migrations, and moving any existing data. SQLite has different typing and foreign-key behavior ([SQLite documentation](https://www.sqlite.org/quirks.html)) and migration limitations ([Alembic documentation](https://alembic.sqlalchemy.org/en/latest/batch.html)). Starting with PostgreSQL avoids that conversion work.
- Defer Alembic setup and the first schema migration to the games-and-spreads epic, where real domain tables become necessary. Do not create placeholder tables or use automatic table creation as a migration substitute.

## API contract

| Endpoint | Purpose | Success | Failure |
| --- | --- | --- | --- |
| `GET /api/health` | Process health; no database calls | HTTP 200, `{"status":"ok"}` | Unreachable if process is down |
| `GET /api/ready` | Database connectivity via `SELECT 1` | HTTP 200, `{"status":"ready"}` | HTTP 503, `{"status":"unavailable"}` if database is unreachable |

Database connections are lazy so database downtime does not prevent application startup or process health checks. Readiness uses a short bounded database connection timeout, cleans up the connection, and exposes no credentials or driver error details in its response. FastAPI's `/docs` remains available locally.

## Reviewable tasks

- [ ] BE-01 — Bootstrap the Python application
  - Status: `not_started`
  - Scope: Add `backend/pyproject.toml`, dependency lockfile, supported Python version, and minimal `backend/app/` package with an importable FastAPI application. Add necessary ignore rules for virtual environments, caches, and local secrets.
  - Dependencies: None.
  - Acceptance criteria: A fresh dependency sync succeeds; the server starts from `backend/`; `/docs` loads. No frontend or domain functionality is introduced.
  - Validation: Sync dependencies and start the development server; request `/docs`.
  - Completion notes: Pending.

- [ ] BE-02 — Add process health
  - Status: `not_started`
  - Scope: Implement `GET /api/health` with the contract above and a focused pytest test using FastAPI's test client.
  - Dependencies: BE-01.
  - Acceptance criteria: Endpoint returns the exact HTTP status and JSON contract without requiring a running database.
  - Validation: Run the endpoint test without PostgreSQL; smoke-check the running server with `curl`.
  - Completion notes: Pending.

- [ ] BE-03 — Provision local PostgreSQL
  - Status: `not_started`
  - Scope: Add a PostgreSQL Compose service with an explicit supported image version, named data volume, health check, configurable host port, and local development credentials from environment configuration. Add root `.env.example`.
  - Dependencies: None.
  - Acceptance criteria: `docker compose up -d db` starts a healthy database; data survives an ordinary container restart; example configuration contains no real secrets. No domain schema is created.
  - Validation: Validate Compose configuration, start the service, inspect health, execute `SELECT 1`, and confirm the named volume is mounted. Do not delete volumes during verification.
  - Completion notes: Pending.

- [ ] BE-04 — Wire database configuration and readiness
  - Status: `not_started`
  - Scope: Add validated settings, SQLAlchemy engine configuration, and `GET /api/ready`. Load root environment configuration consistently from the documented working directory; release engine resources at shutdown.
  - Dependencies: BE-01, BE-03.
  - Acceptance criteria: Readiness succeeds against local PostgreSQL and returns the failure contract within a bounded timeout when the database is unavailable. `/api/health` continues to succeed in that condition. Connections are released and errors do not expose secrets.
  - Validation: Focused tests for success and database-error handling, plus real PostgreSQL smoke checks for available and unavailable database configurations.
  - Completion notes: Pending.

- [ ] BE-05 — Document and verify the complete startup path
  - Status: `not_started`
  - Scope: Update root README with prerequisites, `.env` setup, database startup, backend dependency sync and launch, endpoint URLs, test commands, and shutdown instructions. Include how to run health-only without Docker and explain that readiness will fail until PostgreSQL is available.
  - Dependencies: BE-02, BE-04.
  - Acceptance criteria: Following the README yields a running backend, healthy database, passing health/readiness requests, and passing backend tests. Document that ordinary shutdown preserves database data.
  - Validation: Follow the documented commands from their stated directories, run `uv run pytest` from `backend/`, and record actual smoke-check results. Record any environment limitations rather than claiming unperformed checks passed.
  - Completion notes: Pending.

## Epic acceptance criteria

- Backend setup is documented and reproducible from the repository.
- Health endpoint works without PostgreSQL.
- Docker Compose starts PostgreSQL with persistent storage.
- Readiness distinguishes available and unavailable database connectivity.
- Relevant automated tests and local smoke checks pass.
- No games, strategies, bets, settlement, frontend implementation, or production deployment work is included.

## Loop log

### 2026-09-30 — Planning

- Completed task IDs: None; drafted the backend plan only.
- Validation: Read repository instructions and governing design; checked existing epic plan locations. No application or infrastructure checks performed.
- Blockers: None for the PostgreSQL plan. SQLite adoption would require a subsequent design document from CHIP.
- Next step: Implement BE-01, then BE-02; provision PostgreSQL in BE-03 before wiring readiness.
- Layout note: This pre-epic already uses sibling `backend/` and `frontend/` directories, whereas AGENTS.md specifies `front_end/`. Preserve the existing directory for this planning request; align the naming instruction before adding further frontend plans.
